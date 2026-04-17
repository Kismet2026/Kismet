# Domain 2 — Discovery & Matching

> Detailed design for the discovery, swipe, match, recommendation, and BaZi services.
> Source of truth: [`infra/stacks/domain2_stack.py`](../../infra/stacks/domain2_stack.py) + [`services/domain-2-discovery/`](../../services/domain-2-discovery/)
> Last verified: Apr 16, 2026

---

## 1. Purpose

Domain 2 is the "dating surface" of Kismet — it decides **who a user sees, in what order, and what happens when two users like each other**. It owns five Lambda services backed by four DynamoDB tables, all driven by the same REST API (inherited from `SharedStack`) and the `kismet-events` EventBridge bus.

Upstream, D2 consumes user lifecycle events from D1 (Identity) and moderation events from D4 (Moderation). Downstream, D2 publishes `swipe.created` and `match.created` which fan out to D3 (Messaging icebreakers), D5 (Notifications), and D6 (Analytics).

---

## 2. Architecture

See [`diagrams/domain2-architecture.drawio`](./diagrams/domain2-architecture.drawio).

```
                    ┌─────────────────────────────────┐
                    │   Imported REST API + Cognito   │
                    └───┬───┬───┬───┬───┬─────────────┘
                        │   │   │   │   │
              ┌─────────▼─┐ │   │   │ ┌─▼──────────┐
              │ Discovery │ │   │   │ │   BaZi     │──► external BaZi API
              └─────┬─────┘ │   │   │ └────────────┘
                    │     ┌─▼─┐ │ ┌─▼──────────┐
                    │     │Swi│ │ │Recommend   │
                    │     │pe │ │ └──────┬─────┘
                    │     └─┬─┘ │        │
                    │       │  ┌▼───────▼┐
                    │       │  │  Match  │
                    │       │  └─────────┘
            ┌───────▼───────▼──────────┐
            │ kismet-discovery (GSI    │
            │ BaZi cache) / kismet-    │
            │ swipes / kismet-matches /│
            │ kismet-recommendations   │
            └──────────────────────────┘

    EventBridge: kismet-events
      in:  profile.completed, profile.updated, profile.banned, user.deleted
      out: swipe.created, match.created
```

---

## 3. Services

### 3.1 Discovery Service

| | |
|---|---|
| **Entry** | `GET /discovery?limit&age_min&age_max&gender&cursor` (Cognito-authenticated) |
| **Table** | `kismet-discovery` (PK/SK single-table) |
| **Consumes events** | `profile.completed`, `profile.updated`, `profile.banned`, `user.deleted` |
| **Publishes** | none |

**Responsibilities**
1. Maintain the **discovery pool**: one row per active user, denormalized from D1's `profile.completed` / `profile.updated` events — avoids cross-domain reads on every request
2. Serve filtered candidate lists with age / gender filters and cursor pagination
3. Attach the caller's **BaZi forward score** (caller → candidate) to every row
4. **BaZi cache**: store Rekognition API responses at `BAZI#{birthDate}` / `SCORES` so repeat calls are free

**Key design choices**
- **Scan, not Query**, because filters span multiple non-key attributes (age, gender, city). The DynamoDB `Limit` parameter caps *rows scanned*, not rows returned — we explicitly do **not** pass `Limit` after a past incident where 200+ BaZi cache rows filled the scan page before any PROFILE rows surfaced (see postmortems).
- **Partial-cache protection**: earlier iterations had a reverse-write pattern that contaminated forward scores. Cache entries now skip anything with `partialCache: True` and re-call the API.

### 3.2 Swipe Service

| | |
|---|---|
| **Entry** | `POST /swipe { targetUserId, action }`, `GET /swipe/history` |
| **Table** | `kismet-swipes` (PK=`userId`, SK=`targetUserId`) |
| **Consumes events** | `user.deleted` (purge) |
| **Publishes** | `swipe.created` (like only — pass doesn't fan out) |

Flat hash+range keyed on `userId` + `targetUserId` so:
- Writes are single-row puts
- `GET /swipe/history` is a Query
- Anyone can cheaply check "has user A swiped user B?" (used by Match Service to verify mutual likes)

Rationale for **not** publishing `pass` events: pass is a no-op for every downstream consumer. EventBridge volume stays low.

### 3.3 Match Service

| | |
|---|---|
| **Entry** | `GET /matches`, `GET /matches/{matchId}`, `DELETE /matches/{matchId}` |
| **Table** | `kismet-matches` (single-table, 3 access patterns) |
| **Consumes events** | `swipe.created` (mutual-like detection), `user.deleted`, `profile.banned` |
| **Publishes** | `match.created` |

**Access patterns** in `kismet-matches`:

| Purpose | PK | SK |
|---------|----|----|
| Dedup: one match per pair | `PAIR#{userA}#{userB}` (sorted) | `META` |
| Detail lookup by matchId | `MATCH#{matchId}` | `META` |
| "My matches" list, sorted recent-first | `USER#{userId}` | `MATCH#{timestamp}#{matchId}` |

**Atomic match creation** — when a `swipe.created` event arrives:
1. Read reverse swipe (`swipe_table.get_item(target, swiper)`) — this is a single-key read on Swipe's table (scoped IAM)
2. If not a like, exit
3. If mutual, `dynamodb_client.transact_write_items` creates all 4 rows in one transaction with `ConditionExpression: attribute_not_exists(PK)` on the PAIR row — prevents duplicate matches under concurrent mutual swipes

**Ban cascade** — on `user.deleted` or `profile.banned`, query the USER-index rows for the banned user, then delete META + PAIR + both USER-index copies for each match. Other counter-party no longer sees the banned user in their list.

### 3.4 Recommendation Service

| | |
|---|---|
| **Entry** | `GET /recommend?limit`, `POST /recommend/refresh` |
| **Table** | `kismet-recommendations` (PK=`USER#{userId}`, SK=`SCORE#{totalScore:04d}#{candidateId}`) |
| **Consumes events** | `profile.completed` (marker), `swipe.created` (cache invalidation), `user.deleted`, `profile.banned` |
| **Publishes** | none |

**Composite scoring** weights (0-70 total, room for growth):

| Component | Weight | Signal |
|-----------|--------|--------|
| BaZi compatibility | 0-40 | external API forward score × 40 / 100 |
| Profile completeness | 0-20 | has avatar (+8), bio (+7), city (+5) |
| Activity recency | 10 (constant) | placeholder until login tracking ships |

**Bidirectional BaZi** — the UI shows both directions (yin-yang badge):

- `baziScore`: candidate → user (read from Discovery's cache at `BAZI#{candidateBirthDate}` → `scores[userBirthDate]`) via batched `BatchGetItem`
- `reverseBaziScore`: user → candidate (user's own cache)

The SK encoding `SCORE#{totalScore:04d}` pads to 4 digits so DynamoDB's lexicographic sort on `ScanIndexForward: False` returns highest-score-first without client-side sort.

**Cache invalidation** — on `swipe.created`, delete the row at `USER#{swiperId}` / `SCORE#*#{targetId}`. The next `GET /recommend` call recomputes lazily (scan + sort + batch put).

### 3.5 BaZi Service

| | |
|---|---|
| **Entry** | `POST /bazi/top-matches { birthDate, limit }` |
| **Table** | none (stateless) |
| **Consumes events** | none |
| **Publishes** | none |

Thin wrapper over the external BaZi API (`match-date-nu.vercel.app/api/match`). Exists as its own service mostly for access-control boundary — the external API key stays in a single Lambda's environment, not leaked to frontend.

The actual BaZi cache lives in Discovery's table (`BAZI#{birthDate}` / `SCORES`), populated lazily when Discovery calls out on a cache miss. BaZi Service's role is narrower: a direct proxy for services that want the raw top-N list without Discovery's opinion.

---

## 4. Data Layer

| Table | Primary key | Size profile | Notes |
|-------|-------------|--------------|-------|
| `kismet-discovery` | PK `PROFILE#{userId}` or `BAZI#{birthDate}` / SK `META` or `SCORES` | ~N users + ~N distinct birthDates | single-table discovery pool + BaZi cache |
| `kismet-swipes` | `userId` / `targetUserId` | ~N² worst-case | one row per swipe; swiper query + direct-key reverse lookup |
| `kismet-matches` | three PK patterns (see §3.3) | ~N² / 4 worst-case mutual | 4 rows per match (dedup + detail + 2 user-index) |
| `kismet-recommendations` | `USER#{userId}` / `SCORE#{score:04d}#{candidateId}` | ~N × cache fanout | lazy, invalidated on swipe |

All tables use on-demand billing. No global secondary indexes except the implicit sort on SK.

---

## 5. Event Flows

### 5.1 New user enters the pool

```
D1 Profile Service
    │  (user completes onboarding)
    └─── profile.completed ──► EventBridge
                                    │
                  ┌─────────────────┼─────────────────┐
                  ▼                 ▼                 ▼
          Discovery              Recommendation       (D5 email, D6 log)
          - insert PROFILE row   - write SYSTEM marker
          - pre-warm BaZi cache    so next GET refreshes
```

### 5.2 Mutual like → match

```
Swipe Service ── POST /swipe (like) ──► kismet-swipes put
       │
       └─── swipe.created ──► EventBridge
                                 │
                  ┌──────────────┼─────────────────┐
                  ▼              ▼                 ▼
          Match Service    Recommendation     D6 Activity Logger
          - get reverse    - delete cached
            swipe row        row for that pair
          - if mutual:
              transact_write 4 rows
              publish match.created ───► D3 Icebreaker, D5 Push/Email
```

### 5.3 Ban cascade

```
D4 Report Service
       │  (2nd distinct report auto-fires, or admin resolve=ban)
       └─── user.banned ──► EventBridge
                               │
                               ▼
                        D1 Profile Service
                          - set status=banned
                          - publish profile.banned
                               │
                               └─► EventBridge
                                       │
                  ┌────────────┬───────┴──────┬────────────────┐
                  ▼            ▼              ▼                ▼
            Discovery      Match          Recommendation    D3 Message
            delete pool    purge matches  clear cache       purge threads
            row
```

### 5.4 Account deletion

Same fan-out as §5.3 but triggered by `user.deleted` (from user's own `DELETE /profiles/me` rather than moderation). Also includes D1 Photo (S3 + table), D5 Email (preferences), and Cognito admin-delete.

---

## 6. Cross-Service Dependencies

Domain 2 services share a lot of read-only access to each other's tables. Summarized so IAM stays least-privilege:

| Caller | Reads (other svc's table) | Why |
|--------|--------------------------|-----|
| Discovery | `kismet-swipes` | Exclude already-swiped candidates |
| Match | `kismet-swipes` | Check reverse swipe for mutual-like detection |
| Recommendation | `kismet-discovery`, `kismet-swipes` | Score candidate pool + exclude swiped |

Writes always go through the owning service — no cross-service writes.

---

## 7. Known Gotchas / Postmortem Highlights

1. **DynamoDB `Limit` on Scan does not cap returned rows.** The Discovery scan got "empty page" bugs when BAZI# cache rows dominated the first scanned segment. Fixed by dropping `Limit` and post-filtering. Applies anywhere we mix entity types in one table.
2. **Rekognition rejects WebP/HEIC.** D4 image moderation needs JPEG/PNG. Frontend normalizes client-side via `<canvas>` in `frontend/src/lib/imageUtils.ts` — D2's only involvement is that rejected photos never become part of the discovery pool because Photo Service sets `status=rejected` before Discovery consumes `profile.completed`.
3. **API Gateway stage doesn't auto-redeploy on imported-API route changes.** When Domain 2 adds a new route, `cdk deploy KismetDomain2` creates the Resource but the `dev` stage has to be re-published manually. Tracked in #118.
4. **Match-service's `user.deleted` handler pre-dates `profile.banned`.** Originally only wired through #113; extended to also consume `profile.banned` in #119. Keep both wired — one is user-initiated, the other is moderation-initiated.
5. **BaZi reverse write was a trap.** Writing candidate's score-for-user into the user's forward cache corrupted subsequent forward scans. Removed in favor of batch `BatchGetItem` from each candidate's BaZi cache.

---

## 8. Open Follow-ups

- **#118** — CDK: imported API Gateway stage auto-redeploy
- **#120** — Ban notification email (affects which consumer list `profile.banned` fans to)
- **#121** — Banned-user re-registration loophole (affects whether a banned user can re-enter the discovery pool with the same email)
- Activity recency scoring is still a constant. Blocked on D6 presence/login timestamps landing in a queryable form.
- Geo-filter / distance ranking — Discovery stores `location_coordinates` but doesn't use them. Low priority for the demo.

---

## 9. References

- API contracts: [`docs/api-contracts/domain-2-*.md`](../api-contracts/)
- Event shapes: [`event-schema.json`](./event-schema.json)
- Shared infra: [`shared_stack.py`](../../infra/stacks/shared_stack.py)
- Reusable Lambda + DDB + route + IAM construct: [`kismet_constructs/kismet_service.py`](../../infra/kismet_constructs/kismet_service.py)
- Cross-domain integration tests: [`tests/test_cross_domain_integration.py`](../../tests/test_cross_domain_integration.py)
