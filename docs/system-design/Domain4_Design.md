# Domain 4 — Safety & Moderation

> Detailed design for the text-moderation, image-moderation, report, and rate-limiter services.
> Source of truth: [`infra/stacks/domain4_stack.py`](../../infra/stacks/domain4_stack.py) + [`services/domain-4-moderation/`](../../services/domain-4-moderation/)
> Last verified: Apr 16, 2026

---

## 1. Purpose

Domain 4 is the **safety net** of Kismet — it decides what user-generated content is allowed on the platform, and it is the only domain that can cause a user to be removed against their will. It owns four Lambda services: two ML-backed content scanners (text, image), one user-facing report pipeline with admin resolution, and one Redis-backed per-user rate limiter.

Upstream, D4 consumes two data events: `message.sent` (from D3 Message Service) and `photo.uploaded` (from D1 Photo Service). Downstream, D4 publishes `content.flagged`, `user.reported`, and — critically — `user.banned`, which D1 Profile Service turns into a `profile.banned` fan-out that D2 (Discovery/Match/Recommendation) and D3 (Message) consume to purge the banned user's footprint.

Report Service and Image Moderation are the only services in the codebase that can cause *destructive* state changes for other users (match deletion, photo rejection, account ban). That concentration is deliberate — everything dangerous lives behind one review surface.

---

## 2. Architecture

```
                    ┌─────────────────────────────────┐
                    │   Imported REST API + Cognito   │
                    └───┬─────┬─────┬─────┬───────────┘
                        │     │     │     │
              ┌─────────▼─┐ ┌─▼───┐ ┌▼────┐ ┌▼──────────┐
              │  Text     │ │Img  │ │Rep  │ │ RateLimit │
              │ Moderate  │ │Mod  │ │ort  │ │  (VPC)    │
              └────┬──────┘ └──┬──┘ └──┬──┘ └─────┬─────┘
                   │           │      │           │
            ┌──────▼───┐ ┌─────▼──┐ ┌─▼─────┐  ┌──▼──────┐
            │ Comprehend│ │Rekogn. │ │ SES   │  │ Redis   │
            │ DetectTox.│ │DetectM.│ │ admin │  │ Elasti- │
            └──────┬────┘ └─────┬──┘ └───────┘  │ Cache   │
                   │            │               └─────────┘
            ┌──────▼────┐ ┌─────▼─────────┐ ┌───────────┐
            │ text-mod  │ │ image-mod    │ │  reports  │
            │ table +GSI│ │ table +GSI   │ │ +2 GSIs   │
            └───────────┘ └──────┬───────┘ └───────────┘
                                 │ (UpdateItem status=rejected)
                           ┌─────▼──────┐
                           │ kismet-    │
                           │ photos (D1)│
                           └────────────┘

    EventBridge: kismet-events
      in:  message.sent, photo.uploaded
      out: content.flagged, user.reported, user.banned
```

See [`diagrams/domain4-architecture.drawio`](./diagrams/domain4-architecture.drawio).

---

## 3. Services

### 3.1 Text Moderation Service

| | |
|---|---|
| **Entry** | `POST /moderate/text`, `GET /moderate/text/history` (admin-only), EventBridge `message.sent` |
| **Table** | `kismet-text-moderation-dev` (PK=`contentId`, SK=`sk`; GSI `gsi1` on `gsi1pk`/`gsi1sk:N`) |
| **Consumes** | `message.sent` |
| **Publishes** | `content.flagged` |

**Responsibilities**
1. Classify arbitrary text (message body or bio) with AWS Comprehend `DetectToxicContent`.
2. Persist the full result — toxicity score, category labels, timestamp — to the moderation table for admin audit.
3. On a flag, emit `content.flagged` so D5 / admin surfaces know.

**Key design choices**
- Two tunable thresholds, independent: `TOXICITY_THRESHOLD` (default 0.65) controls the flag decision; `CATEGORY_SCORE_FLOOR` (default 0.35) controls which category labels are recorded alongside the score. Scores always come back 0.0–1.0 from Comprehend.
- History pagination uses a `gsi1pk = "TEXT_MODERATION_HISTORY"` GSI with `gsi1sk = int(time.time() * 1000)` so admin list is descending by time without a sort-client-side step.
- For `message` type, `content.flagged` needs a `userId` — the event consumer extracts `senderId` from the `message.sent` detail. If it's missing, the service **logs and skips** rather than publishing an anonymous flag event (the comment in `run_moderation` is explicit: "check message-service senderId"). For `bio` type, `userId` falls back to `contentId` itself.
- Content is capped at `CONTENT_MAX_BYTES = 4500` — under Comprehend's 5 KB per-segment limit.

### 3.2 Image Moderation Service

| | |
|---|---|
| **Entry** | `POST /moderate/image`, `GET /moderate/image/history` (admin-only), EventBridge `photo.uploaded` |
| **Table** | `kismet-image-moderation-dev` (PK=`photoId`, SK=`sk`; GSI `gsi1` on `gsi1pk`/`gsi1sk:N`) |
| **Consumes** | `photo.uploaded` |
| **Publishes** | `content.flagged` |
| **Cross-writes** | `kismet-photos` (sets `status=rejected`) |

**Responsibilities**
1. Run AWS Rekognition `DetectModerationLabels` against the S3 object at `detail.s3Bucket` / `detail.s3Key`.
2. Flag if `max(label.Confidence) >= MODERATION_FLAG_CONFIDENCE` (default **60**, tunable via env).
3. On a flag: emit `content.flagged` **and** `UpdateItem` on `kismet-photos` (PK=`USER#{userId}`, SK=`PHOTO#{photoId}`) setting `status = "rejected"`.

**Key design choices**
- **Bucket resolution precedence** — `detail.s3Bucket` from the event wins over `PHOTO_S3_BUCKET` env, by design (event-schema contract). A mismatch is logged, not rejected, so environment drift doesn't block moderation.
- **Two Rekognition confidence knobs**: `REKOGNITION_MIN_CONFIDENCE` (default **5**) is passed to the API so the raw label list stays broad; `MODERATION_FLAG_CONFIDENCE` (default **60**) is applied locally to decide `flagged`. This lets us record low-confidence labels for admin review without auto-flagging everything.
- **Reason slug**: the top label name (e.g. "Explicit Nudity") is normalized to `explicit_nudity` for the `content.flagged` `reason` field, so downstream consumers can filter without brittle string matching.
- **Photo row cross-write is best-effort**: if the `UpdateItem` on `kismet-photos` fails, we log but do not re-raise — the moderation record is already persisted and the flag event is already published. Re-running moderation on a re-uploaded photo re-issues the update.

### 3.3 Report Service

| | |
|---|---|
| **Entry** | `POST /reports`, `GET /reports?status=&limit=&cursor=` (admin), `GET /reports/{reportId}` (admin), `PUT /reports/{reportId}/resolve` (admin) |
| **Table** | `kismet-reports` (PK=`pk`, SK=`sk`; GSI `reportedUserId-index`, GSI `status-index`) |
| **Consumes** | none |
| **Publishes** | `user.reported`, `user.banned` |
| **External** | SES admin alert on new reports |

**Responsibilities**
1. Let any authenticated user file a report on another user with a bounded reason enum (`harassment`, `inappropriate_content`, `spam`, `fake_profile`, `other`).
2. Dedupe: one PENDING report per (reporter, reportedUser) pair — a second POST while the first is unresolved returns `409`.
3. **Auto-ban at threshold** (added in PR #114): after every successful POST, query the `reportedUserId-index` GSI and count PENDING reports for the reported user. If `count >= AUTO_BAN_THRESHOLD` (default **2**), mark all PENDING reports for that user as `RESOLVED` with `resolution = "ban"` and fire `user.banned`.
4. Let admins resolve individual reports with `warning | ban | dismiss`. A `ban` resolution also fires `user.banned`.
5. SES-email an admin alert on every new report (non-blocking — failures are logged).

**Key design choices**
- **GSI for the auto-ban count**, not a scan. `_count_pending_reports_for_user` paginates via `Key('reportedUserId').eq(...)` with a `FilterExpression` on status and `Select='COUNT'`. Cost stays O(reports against *this* user), not O(all reports).
- **`GET /reports?status=PENDING`** (added in #114) uses a scan with a filter expression. There is a `status` GSI declared in CDK but the handler doesn't query it yet — follow-up opportunity once volume justifies.
- **Conditional resolve**: `PUT /resolve` uses `ConditionExpression: attribute_exists(pk) AND #status = :PENDING` so a double-resolve under two admin tabs returns `409 CONFLICT`.
- **`user.reported` vs `user.banned`**: every report emits `user.reported` (for activity logging / analytics). Only a ban path (auto or admin-resolved) emits `user.banned`. Consumers treat them as different severity tiers — `user.reported` is informational; `user.banned` triggers destructive cleanup in D1/D2/D3.
- Report list responses strip `description`, `resolution`, `resolvedAt` from the summary view; the detail GET returns the full row.

### 3.4 Rate Limiter Service

| | |
|---|---|
| **Entry** | `GET /ratelimit/status/{userId}` (admin), `POST /ratelimit/reset/{userId}` (admin) |
| **Storage** | ElastiCache Redis `cache.t3.micro`, single node, in VPC PRIVATE_ISOLATED subnet |
| **Consumes** | none |
| **Publishes** | none |

**Responsibilities**
1. Expose a `check_rate_limit(user_id, action)` function importable by other Lambdas — sliding-window counters in Redis.
2. Admin endpoints to inspect and reset counters.

**Limit table** (hard-coded in `LIMITS`):

| Action | Limit | Window |
|--------|-------|--------|
| `swipes` | 100 | 24 h (calendar UTC day) |
| `messages` | 50 | 1 h (calendar UTC hour) |
| `reports` | 5 | 24 h (calendar UTC day) |

**Key design choices**
- **Calendar-aligned windows, not true sliding**: `get_window_info` snaps to the start of the current UTC day or hour so all users share a reset boundary. This avoids sophisticated sorted-set algorithms and keeps each check to a single `INCR`.
- **Key shape**: `ratelimit:{userId}:{action}:{windowStartEpochMs}`. TTL set to `windowSeconds + 60` on first increment. Old windows age out naturally.
- **Fail-open**: if Redis is unreachable, `check_rate_limit` returns `{"allowed": True}`. Rate-limiting is a best-effort guardrail, not a correctness boundary — outages never block users.
- **VPC-attached**: the Lambda is in the same VPC/SG as the Redis cluster. Other domains that want rate limiting would currently have to duplicate the VPC attachment or call a (not-yet-built) internal HTTP endpoint. See Open Follow-ups.

---

## 4. Data Layer

| Table / Store | Primary key | GSIs | Notes |
|---------------|-------------|------|-------|
| `kismet-text-moderation-dev` | `contentId` / `sk="RESULT"` | `gsi1`: `gsi1pk="TEXT_MODERATION_HISTORY"` / `gsi1sk:N` (millis) | one row per moderated text; GSI drives descending admin history |
| `kismet-image-moderation-dev` | `photoId` / `sk="RESULT"` | `gsi1`: `gsi1pk="IMAGE_MODERATION_HISTORY"` / `gsi1sk:N` | same pattern; admin review via GSI |
| `kismet-reports` | `pk="REPORT#{reportId}"` / `sk="META"` | `reportedUserId-index` (PK `reportedUserId` / SK `createdAt`), `status-index` (PK `status` / SK `createdAt`) | auto-ban counting uses `reportedUserId-index`; `status-index` declared but not yet queried |
| ElastiCache Redis | `ratelimit:{userId}:{action}:{windowStart}` | n/a | single-node t3.micro, VPC-isolated |
| `kismet-photos` (**read/write, owned by D1**) | `PK=USER#{userId}` / `SK=PHOTO#{photoId}` | n/a for this write | image-mod sets `status=rejected` only |

All DynamoDB tables use on-demand billing. Nothing in D4 requires transactional writes today; the auto-ban loop issues per-item updates and accepts best-effort consistency (see Gotchas).

---

## 5. Event Flows

### 5.1 Message moderation

```
D3 Message Service ── POST /messages ──► kismet-messages put
       │
       └─── message.sent ──► EventBridge
                                 │
                                 ▼
                          Text Moderation
                          - Comprehend DetectToxicContent
                          - persist row
                          - if score >= 0.65:
                              content.flagged ──► D5 / admin / D6
```

### 5.2 Photo moderation

```
D1 Photo Service ── S3 put + POST /photos ──► kismet-photos put (status=pending)
       │
       └─── photo.uploaded (s3Bucket, s3Key, photoId, userId) ──► EventBridge
                                 │
                                 ▼
                          Image Moderation
                          - Rekognition DetectModerationLabels
                          - persist row
                          - if maxConfidence >= 60:
                              content.flagged            ──► D5 / admin / D6
                              UpdateItem kismet-photos   status=rejected
```

### 5.3 Report → auto-ban → cascade

```
User ── POST /reports ──► Report Service
                              - put PENDING row
                              - query reportedUserId-index (COUNT)
                              - SES admin alert (best-effort)
                              - user.reported ──► D6 Activity Logger
                              │
                              │ if pendingCount >= AUTO_BAN_THRESHOLD (2):
                              ├─ UpdateItem all PENDING → RESOLVED, resolution="ban"
                              └─ user.banned ──► EventBridge
                                                     │
                                                     ▼
                                              D1 Profile Service
                                              - set profile.status = banned
                                              - publish profile.banned
                                                     │
                                                     └─► EventBridge
                                                             │
                            ┌────────────────┬───────────────┼───────────────┐
                            ▼                ▼               ▼               ▼
                        D2 Discovery     D2 Match      D2 Recommend      D3 Message
                        purge pool row   purge match   clear cache       purge threads
                                         rows (PR #119)                   (PR #119)
```

### 5.4 Admin resolve path

```
Admin UI ── PUT /reports/{id}/resolve { resolution } ──► Report Service
                                                             │
                                ┌────────────────────────────┤
                                ▼                            ▼
                       resolution ∈ { warning, dismiss } resolution == "ban"
                       - update single row                - update single row
                         to RESOLVED/DISMISSED              to RESOLVED
                                                          - user.banned ──► cascade (§5.3)
```

---

## 6. Cross-Service Dependencies

| Caller | Target | Access | Why |
|--------|--------|--------|-----|
| Image Moderation | `shared.photos_bucket` | `s3:GetObject`, `s3:HeadObject` | Rekognition S3Object input; also used for HEAD checks |
| Image Moderation | `kismet-photos` (D1 table) | `dynamodb:UpdateItem` (scoped ARN + `/index/*`) | set `status=rejected` on flag |
| Text Moderation | AWS Comprehend | `comprehend:DetectToxicContent` | ML call |
| Report Service | SES | `ses:SendEmail` | admin notification |
| Report Service → D1 | via `user.banned` event | event-driven, no IAM grant | D1 Profile consumes, fans out |
| Rate Limiter | ElastiCache Redis (VPC) | TCP 6379 via SG | counter store |

D4 does not read from any other domain's DynamoDB table — all cross-domain effects flow through events. The one exception is the Image Moderation `UpdateItem` on `kismet-photos`, which was a deliberate decision (see Gotchas §7.3): adding a round-trip through a new `photo.rejected` event just to flip one attribute felt like overkill.

---

## 7. Known Gotchas / Postmortem Highlights

1. **Handler name mismatch was silent (PR #115).** Both `text-moderation-service` and `image-moderation-service` originally defined `def lambda_handler(...)` while CDK wired `handler="lambda_function.handler"`. CloudFormation reported deploy success; every invocation failed with `Runtime.HandlerNotFound`. Fixed by renaming both to `def handler(...)` — matches the rest of the codebase. Worth a lint rule.
2. **Rekognition only accepts JPEG / PNG.** WebP and HEIC (iPhone default) are rejected. The fix lives in the frontend: `frontend/src/lib/imageUtils.ts` re-encodes every upload to JPEG via a `<canvas>` before hitting S3. Document this as a D4 *input constraint* — if another upload path ever skips the canvas step (e.g., an admin import tool), moderation will 400 on those objects.
3. **Rekognition S3 eventual consistency.** Freshly-uploaded S3 objects sometimes aren't visible to Rekognition for a few hundred ms, producing `InvalidS3ObjectException`. Today the handler raises `IMAGE_NOT_FOUND` on that code and relies on EventBridge's built-in retry window to bail us out. Tracked as a follow-up to add in-process 0.5s/1s/2s backoff — the EventBridge retry is 60 s, which is fine but noisy in logs. *(See Open Follow-ups.)*
4. **`kismet-photos` cross-write creates a direction-of-authority question.** Image Moderation writes `status=rejected` on a table owned by D1 Photo. We accepted this because (a) moderation is the only external writer of `status=rejected`, (b) the IAM policy is narrowly scoped to the one table + its indexes, and (c) publishing a `photo.rejected` event just for D1 to loop back and update its own row doubles the latency. If another consumer ever needs the signal, revisit.
5. **API Gateway stage auto-redeploy (#118).** Adding the `/reports` routes in a D4 deploy created the Resource but the `dev` stage had stale route definitions for about 10 minutes. Same class of bug as D2. No permanent fix yet.
6. **Auto-ban is not atomic.** `_auto_ban_user` issues N `UpdateItem` calls in a loop, then a single `put_events`. If the Lambda dies mid-loop, some reports are marked RESOLVED but the `user.banned` event never fires — the ban effectively stalls. In practice N is small (threshold is 2) and the next report re-trips the threshold. A transactional resolve + event-outbox pattern is the right fix if this ever matters at scale.
7. **Rate Limiter is admin-only today.** There is no public caller yet; the `check_rate_limit` function exists but no service imports it. Shipping the limits as a real middleware is blocked on the VPC-attachment question (every caller Lambda would need VPC config, which adds cold-start latency).

---

## 8. Open Follow-ups

- **#118** — CDK: imported API Gateway stage auto-redeploy. Affects D4 route deploys.
- **#120** — Ban notification email. Banned users currently have no idea why they got banned; they just find themselves gone from matches and unable to send messages. Add a `user.banned` consumer in D5 that emails the affected user the resolution/reason.
- **#121** — Banned users can `DELETE /profiles/me` and re-register with the same email. `user.banned` doesn't block Cognito sign-up; D1 auth service doesn't consult a banlist. Simplest fix: a Dynamo banlist keyed on email hash, checked during sign-up.
- **In-process Rekognition retry** (0.5s / 1s / 2s backoff on `InvalidS3ObjectException`) — planned but not yet in source. Would cut the noisy-logs case from §7.3 without waiting for EventBridge.
- **Use `status-index` GSI** in `GET /reports?status=`. Currently implemented as a scan + FilterExpression; the GSI is declared in CDK but unused.
- **Rate Limiter as shared middleware.** Either extract `check_rate_limit` into a Lambda Layer, or replace the Redis-direct pattern with an internal `POST /ratelimit/check` endpoint callable without VPC attachment. Blocked on how many callers actually need it.
- **Admin UI for reports / moderation history** — the `GET /moderate/{text,image}/history` and `GET /reports?status=PENDING` endpoints exist but no frontend consumes them yet.

---

## 9. References

- API contracts: [`docs/api-contracts/domain-4-text-moderation-service.md`](../api-contracts/domain-4-text-moderation-service.md), [`domain-4-image-moderation-service.md`](../api-contracts/domain-4-image-moderation-service.md), [`domain-4-report-service.md`](../api-contracts/domain-4-report-service.md), [`domain-4-rate-limiter-service.md`](../api-contracts/domain-4-rate-limiter-service.md)
- Event shapes: [`event-schema.json`](./event-schema.json) — `message.sent`, `photo.uploaded`, `content.flagged`, `user.reported`, `user.banned`
- Shared infra: [`shared_stack.py`](../../infra/stacks/shared_stack.py) (REST API, Cognito authorizer, `kismet-photos` bucket, event bus)
- Reusable Lambda + DDB + route + IAM construct: [`kismet_constructs/kismet_service.py`](../../infra/kismet_constructs/kismet_service.py)
- Cross-domain integration tests: [`tests/test_cross_domain_integration.py`](../../tests/test_cross_domain_integration.py)
- Related PRs: #114 (auto-ban + `?status=` filter), #115 (handler name fix), #118 (stage redeploy), #119 (D2/D3 `profile.banned` purge), #120 (ban email — open), #121 (re-register loophole — open)
