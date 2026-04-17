# Domain 3 — Messaging

> Detailed design for the chat gateway, message persistence, presence, and AI icebreaker services.
> Source of truth: [`infra/stacks/domain3_stack.py`](../../infra/stacks/domain3_stack.py) + [`services/domain-3-messaging/`](../../services/domain-3-messaging/)
> Last verified: Apr 16, 2026

---

## 1. Purpose

Domain 3 is the "conversation surface" of Kismet — once two users match in D2, everything they send, see, and sense about each other in real time lives here. It owns four Lambda services backed by four DynamoDB tables, plus a **dedicated WebSocket API Gateway** that is *not* the shared REST API the rest of the system uses.

Upstream, D3 consumes `match.created` (from D2) to pre-generate icebreakers, and `user.deleted` / `profile.banned` (from D1) to purge conversation history. Downstream, D3 publishes `message.sent` which fans out to D4 (Text Moderation) and D5 (Push Notifications).

The real-time characteristics are the hard part of D3: WebSocket connection lifecycle, heartbeat TTLs, Bedrock cold starts, and client-side state reconciliation. All four have bitten us — see §7.

---

## 2. Architecture

See [`diagrams/domain3-architecture.drawio`](./diagrams/domain3-architecture.drawio).

```
                    ┌─────────────────────────────────┐       ┌─────────────────────────────┐
                    │   Imported REST API + Cognito   │       │   WebSocket API (D3-owned)  │
                    │   (from SharedStack)            │       │   kismet-chat-ws /dev       │
                    └───┬────────┬────────┬───────────┘       └──┬──────────┬─────────┬─────┘
                        │        │        │                      │$connect  │$default │$disc
                   ┌────▼──┐ ┌───▼──┐ ┌───▼──────┐          ┌────▼────┐ ┌───▼──────┐ ┌▼──────┐
                   │Message│ │Presnc│ │Icebreaker│          │ connect │ │send_msg  │ │discon │
                   └───┬───┘ └──┬───┘ └────┬─────┘          └────┬────┘ └────┬─────┘ └──┬────┘
                       │        │          │                    │            │          │
                       │        │          │  Bedrock           │            │invoke    │
                       │        │          ├──► Claude Haiku    │            │Message   │
                       │        │          │                    │            │Service   │
                       ▼        ▼          ▼                    ▼            ▼          ▼
             kismet-messages  kismet-      kismet-         kismet-connections (GSI: matchId-index)
             (GSI:            presence     icebreakers
              messageId-idx)  kismet-
                              typing

    EventBridge: kismet-events
      in:  match.created (→ Icebreaker), user.deleted + profile.banned (→ Message)
      out: message.sent
```

---

## 3. Services

### 3.1 Chat Gateway (WebSocket)

| | |
|---|---|
| **Entry** | `wss://<api-id>.execute-api.us-east-1.amazonaws.com/dev?userId={sub}&matchId={matchId}` |
| **Table** | `kismet-connections` (PK=`CONN#{connectionId}` / SK=`META`, GSI `matchId-index`) |
| **Consumes events** | none |
| **Publishes** | none (indirect — invokes Message Service which publishes `message.sent`) |

**Three Lambdas behind one WebSocket API** (`kismet-chat-ws`), each wired to a built-in WebSocket route:

| Route | Lambda | Handler file |
|-------|--------|--------------|
| `$connect` | `kismet-ws-connect` | `connect.py` |
| `$disconnect` | `kismet-ws-disconnect` | `disconnect.py` |
| `$default` | `kismet-ws-send-message` | `send_message.py` |

**Critical: this is a separate `apigwv2.WebSocketApi` resource owned by `Domain3Stack`, not the shared REST API from `SharedStack`.** Two different API Gateway IDs, two different URLs, two different auth models. REST uses the Cognito authorizer; the WebSocket API has no native authorizer and instead validates on `$connect` by reading `userId` and `matchId` from the query string and confirming participation via a `kismet-matches` lookup.

**Connection lifecycle**

1. `$connect` — `connect.py` pulls `userId` and `matchId` from `queryStringParameters`, does `matches_table.get_item(MATCH#{matchId}, META)`, rejects with 404 if no match or 403 if the user is not in `{userAId, userBId}`, then writes `CONN#{connectionId}` / `META` with a 24-hour `ttl` attribute. The TTL is a safety net for zombie connections the API Gateway forgets to signal.
2. `$default` — any frame the client sends (including `{"action":"sendMessage",...}`) hits `send_message.py`. It re-reads the connection row to recover `userId` + `matchId` (never trust the frame), invokes the Message Service Lambda via `lambda:Invoke` with a synthesized REST-shaped event, then queries `kismet-connections` by `matchId-index`, filters to the recipient's connections, and `post_to_connection`s the persisted message as `{"type":"newMessage", ...}`. Stale connection IDs surface as `GoneException`, which the handler catches and opportunistically deletes from the table.
3. `$disconnect` — `disconnect.py` unconditionally deletes `CONN#{connectionId}` / `META`.

**Only the recipient is pushed, not the sender.** The filter is `c["connectionId"] != connection_id and c.get("userId") == recipient_id`. This is deliberate — the sender already has an optimistic message in UI state, so echoing to them would guarantee a duplicate. (It did not, historically, prevent duplicates by itself — see §7.1.)

### 3.2 Message Service

| | |
|---|---|
| **Entry** | `POST /messages`, `POST /messages/read`, `GET /messages/match/{matchId}`, `DELETE /messages/{messageId}` (all Cognito-auth) |
| **Table** | `kismet-messages` (PK=`CONV#{matchId}` / SK=`MSG#{timestamp}#{messageId}`, GSI `messageId-index`) |
| **Consumes events** | `user.deleted`, `profile.banned` |
| **Publishes** | `message.sent` |

**Responsibilities**

1. Persist messages, enforce "sender must be a participant of the match" on every write, and publish `message.sent`.
2. Serve paginated history — `GET /messages/match/{matchId}` queries with `ScanIndexForward=False`, caps `limit` at 50, filters soft-deleted rows client-side, and base64-encodes `LastEvaluatedKey` as an opaque `nextCursor`.
3. Soft-delete via `DELETE /messages/{messageId}` — looks up the row through the `messageId-index` GSI (SK embeds the timestamp, so there's no way to build the key from just a messageId), verifies caller is the sender, and sets `deleted=True` + `deletedAt`.
4. **Purge on user lifecycle events** — when a `user.deleted` or `profile.banned` event arrives, walk every `USER#{userId}` / `MATCH#*` row in `kismet-matches` to enumerate the user's conversations, then paginate-and-batch-delete every `CONV#{matchId}` message. Paginating both outer and inner queries is required because batch_writer only takes 25 items per flush and a heavy talker can easily accrue >1000 messages.

**Message Service also has a WebSocket escape hatch.** The stack injects `WEBSOCKET_ENDPOINT` (the callback URL of the D3 WebSocket API) and `execute-api:ManageConnections` IAM so the service can push read-receipts directly to connected clients without going through Chat Gateway. As of Apr 16 the `POST /messages/read` handler is declared as a route in CDK but the handler body doesn't ship it yet — the plumbing exists, the behavior doesn't.

**Ban cascade (#119)** — the event filter matches `source == "kismet.profile-service"` AND `detail-type in ("user.deleted", "profile.banned")`. Both events route to the same `handle_user_deleted` path; the only difference is what upstream produced them (self-service deletion vs moderation ban). The stack's `consume_events` array lists both, which `KismetService` turns into two EventBridge rules with the same Lambda target.

### 3.3 Presence Service

| | |
|---|---|
| **Entry** | `POST /presence/heartbeat`, `GET /presence/user/{userId}`, `POST /presence/{matchId}/typing`, `GET /presence/{matchId}/typing` |
| **Tables** | `kismet-presence`, `kismet-typing` (both with DynamoDB TTL) |
| **Consumes events** | none |
| **Publishes** | none |

**Online/offline via TTL, not a background job.** The presence row is `USER#{userId}` / `STATUS` with `ttl = now + 60s`. The frontend heartbeats every ~30s; if three successive heartbeats miss, DynamoDB's TTL sweeper removes the row within ~10 min (usually much faster). `GET /presence/user/{userId}` simply `get_item`s — a missing row is treated as offline (returned as 404 today; see §7.4).

**Typing indicators via a 5-second TTL.** `POST /presence/{matchId}/typing` writes `MATCH#{matchId}#USER#{userId}` / `TYPING` with `ttl = now + 5s`. `GET` reads the *other* participant's typing row (computed from the match's `userAId`/`userBId`). If the row is present, they're typing; if it's gone, they stopped or TTL expired. No WebSocket fan-out — the frontend polls this endpoint while the composer is focused.

Both tables were created as raw `dynamodb.Table` resources instead of through `KismetService` because the shared construct doesn't expose `time_to_live_attribute`. The service's `tables=[]` kwarg is empty for that reason; IAM is granted manually on the next lines of the stack.

### 3.4 Icebreaker Service

| | |
|---|---|
| **Entry** | `POST /icebreaker/generate`, `GET /icebreaker/{matchId}` |
| **Table** | `kismet-icebreakers` (PK=`MATCH#{matchId}` / SK=`META`) |
| **Consumes events** | `match.created` |
| **Publishes** | none |

**Bedrock with a hardcoded-template fallback.** On `match.created`, the handler fires `_generate_and_cache` with empty user dicts, calling Claude Haiku (`anthropic.claude-3-haiku-20240307-v1:0`) via Bedrock Runtime to generate 3 openers. The prompt asks for a JSON array of strings, the response is `json.loads`-ed, and rows are written as `{id: "ice-001", text, source: "bedrock" | "template"}`. Any exception — quota, cold start, malformed JSON — falls through to three hardcoded strings in `FALLBACK_ICEBREAKERS`, tagged `source: "template"` so the frontend can badge them if it wants.

**Pre-generation beats on-demand.** The `match.created` handler writes the cache *before* either user opens the chat; by the time the frontend calls `GET /icebreaker/{matchId}` the row already exists. `POST /icebreaker/generate` is the on-demand fallback — it returns the cache if present, else regenerates. The GET route returns `suggestions: null` (not 404) when nothing's cached, so the frontend can render an empty state without special-casing errors.

**Note**: the EventBridge handler ignores the `userA` / `userB` body fields (it passes `{}` to `_call_bedrock`), so auto-generated openers are always generic until the user opens chat and triggers `POST /icebreaker/generate` with profile data — but by then the cached generic version returns first. This is effectively a bug; see §8.

---

## 4. Data Layer

| Table | Primary key | Size profile | Notes |
|-------|-------------|--------------|-------|
| `kismet-messages` | PK `CONV#{matchId}` / SK `MSG#{timestamp}#{messageId}` | unbounded, ~chat-volume | GSI `messageId-index` for DELETE; soft-delete via `deleted` flag |
| `kismet-connections` | PK `CONN#{connectionId}` / SK `META` | ~online-users, TTL 24h | GSI `matchId-index` to fan out sends |
| `kismet-presence` | PK `USER#{userId}` / SK `STATUS` | ~online-users, TTL 60s | missing row = offline |
| `kismet-typing` | PK `MATCH#{matchId}#USER#{userId}` / SK `TYPING` | ~actively-typing, TTL 5s | one row per typist |
| `kismet-icebreakers` | PK `MATCH#{matchId}` / SK `META` | ~total-matches | one row per match, pre-generated |

All tables are on-demand billing. `kismet-connections`, `kismet-presence`, and `kismet-typing` all use DynamoDB TTL on a `ttl` attribute (Unix epoch seconds). `kismet-messages` and `kismet-icebreakers` do not expire — history is permanent.

D3 also has cross-domain read access to `kismet-matches` (owned by D2) in every service for participant-of-match checks. No writes ever cross the domain boundary.

---

## 5. Event Flows

### 5.1 Sending a message (WebSocket path)

```
Client ─(WSS frame)─► $default ─► send_message.py
                                     │
                                     │  get_item CONN#{connId}  (recover userId/matchId)
                                     │  get_item MATCH#{matchId} (authz)
                                     │
                                     └─► lambda:Invoke MessageService (synthesized REST event)
                                                  │
                                                  │  put_item CONV#{matchId}/MSG#{ts}#{msgId}
                                                  │
                                                  └─► events:PutEvents message.sent
                                                              │
                                                              ├─► D4 Text Moderation
                                                              └─► D5 Push Notification
                                     │
                                     │  query matchId-index, filter by recipient userId
                                     └─► post_to_connection(recipient connectionId, {type:"newMessage",...})
```

### 5.2 Match created → icebreakers pre-generated

```
D2 Match Service ─ match.created ─► EventBridge
                                         │
                                         ├─► D3 Icebreaker (this domain)
                                         │      - _generate_and_cache(matchId)
                                         │      - bedrock.invoke_model (Claude Haiku)
                                         │      - put_item MATCH#{matchId}/META
                                         │
                                         ├─► D5 Push Notification
                                         └─► D6 Analytics
```

### 5.3 Ban or delete cascade

```
D1 Profile Service
    │  (user.deleted self-service OR profile.banned from moderation)
    └─── EventBridge ──► D3 Message Service
                           │
                           │  query kismet-matches USER#{userId}/MATCH#*
                           │  for each matchId:
                           │    paginate CONV#{matchId}
                           │    batch_writer.delete_item per message
                           │
                           └─► (no outbound event — D2 also consumes and handles the match row)
```

Presence, typing, connections, and icebreakers are *not* purged by this path. Rationale:
- `kismet-presence` / `kismet-typing` self-expire within 60s / 5s anyway.
- `kismet-connections` self-expires in 24h and the next `$connect` will fail authz after the match is deleted in D2.
- `kismet-icebreakers` is keyed by `matchId` — once D2 deletes the match row, the icebreaker cache is unreachable dead weight but doesn't leak PII. Cleanup is on the follow-up list (§8).

---

## 6. Cross-Service Dependencies

| Caller | Reads (other svc's table) | Why |
|--------|---------------------------|-----|
| Chat Gateway `connect` / `send_message` | `kismet-matches` | Participant-of-match authz |
| Message Service | `kismet-matches` | Participant check + enumerate user's matches on ban/delete |
| Presence Service | `kismet-matches` | Participant check for typing endpoints |
| Icebreaker Service | `kismet-matches` | Participant check for generate/get |
| Message Service | `kismet-connections` | Push read-receipts via `execute-api:ManageConnections` |
| Chat Gateway `send_message` | MessageService Lambda | `lambda:Invoke` for persistence |

Writes to `kismet-messages` only happen from Message Service. Chat Gateway never writes to the messages table directly — it invokes the service Lambda with a synthesized REST event. This keeps the event-publishing path single-sourced and avoids two writers competing on the same `CONV#{matchId}` partition.

---

## 7. Known Gotchas / Postmortem Highlights

### 7.1 Chat duplicate messages ([postmortem](../postmortem/chat-duplicate-messages-2026-04-14.md))

The sender saw every message 2-3 times. Three independent writers (optimistic insert with a `temp-*` id, the WebSocket echo with the real uuid, and a 5-second HTTP poll with the same uuid) each appended to React state; dedup by `messageId` failed because temp and server IDs never match. **Backend was not the fault** — Chat Gateway already excludes the sender's connection from the broadcast. Fix was client-side: WebSocket became a *notification* that triggers `fetchMessages()` (which fully replaces state), not a data channel. Optimistic `temp-*` rows live ~1s until the next fetch overwrites them. Takeaway: do not build a client-side CRDT when the server is the source of truth.

### 7.2 D3 route revert (#83 / [postmortem](../postmortem/d3-route-revert-2026-04-12.md))

PR #89 was branched off main *before* PR #86's route-conflict fix merged. On merge, the old `domain3_stack.py` (with `/messages/{matchId}` and `/presence/{userId}` — both colliding with other path variables at the REST API level) came back with it, breaking `cdk deploy KismetDomain3` twice into `ROLLBACK_COMPLETE`. All D3 endpoints were down for ~2 hours. Fix was PR #97 re-applying the new paths (`/messages/match/{matchId}`, `/presence/user/{userId}`), manual CloudFormation stack deletion, and redeploy. Process lesson: rebase before merging any PR that touches a CDK stack file; coordinate edits to `domain3_stack.py`.

### 7.3 iOS `Load failed` ([postmortem](../postmortem/ios-fetch-load-failed-2026-04-14.md))

iOS WebKit silently blocked cross-origin `fetch()` to API Gateway — CORS preflight succeeded, the actual request threw `TypeError: Load failed` at the network layer. The D3 chat page was the canary because it was the first route the user hit after login. Fix was a Next.js catch-all proxy at `/api/proxy/[...path]` making all browser requests same-origin (Vercel → API Gateway server-to-server). **WSS was not affected** and still connects directly to the D3 WebSocket API — WebSocket traffic works fine on iOS. So the chat page has a mixed transport model today: REST goes through the proxy, WebSocket is direct.

### 7.4 Presence 404 vs offline

`GET /presence/user/{userId}` returns 404 when no row exists for that user. Semantically this conflates "user has never heartbeated" with "user is currently offline (TTL expired)." The frontend treats 404 as offline, which is fine, but any future alerting on 404 rates will be misleading. Consider returning `200 {status: "offline"}` on miss.

### 7.5 WebSocket stage URL is not stable across deploys

The WebSocket API is created fresh each time `KismetDomain3` is recreated (as happened during the #83 incident), and `api_id` is generated by CloudFormation. Current URL is emitted as a CfnOutput (`ChatWebSocketUrl`). Frontend hardcodes this in `NEXT_PUBLIC_WS_URL` — any stack recreation requires a Vercel env var update and redeploy.

### 7.6 Icebreaker auto-generation ignores user profiles

The `match.created` branch calls `_generate_and_cache(matchId, user_a={}, user_b={})` with empty profiles, so the cached openers are always generic ("a college student ... a college student"). The `POST /icebreaker/generate` path does pass profile data from the body, but it short-circuits on the cache hit that EventBridge already wrote. Net effect: personalization never happens for auto-generated icebreakers.

---

## 8. Open Follow-ups

- **#119 ban-cascade** — extended Message Service to consume `profile.banned`; keep both event filters wired (user-initiated vs moderation-initiated). Mirror of D2's same change.
- **Icebreaker personalization** — the EventBridge handler should fetch profile data for `userAId` / `userBId` from D1 (or receive it in the event payload) before invoking Bedrock. Current auto-generation is effectively degraded to template mode.
- **Icebreaker cache on match delete** — no cleanup path; rows outlive their `matchId`. Low priority (no PII, just orphaned AI output) but worth a `match.deleted` consumer eventually.
- **Read receipts** — CDK declares `POST /messages/read` and the env + IAM for WebSocket push are wired, but the handler body isn't implemented. Stub route currently 404s at dispatch.
- **Presence offline semantics** — return `200 {status:"offline"}` instead of 404 so the frontend doesn't have to treat a missing row as an error.
- **WebSocket auth via query param** — `?userId=<sub>` is trust-on-first-read; a forged `userId` that matches an existing match participant would pass `$connect`. Long-term: pass a JWT and verify it in `$connect` like the REST side.
- **`cdk synth` in CI** — action item from the #83 postmortem; would have caught the route-conflict regression before merge.

---

## 9. References

- API contracts: [`docs/api-contracts/domain-3-*.md`](../api-contracts/)
- Event shapes: [`event-schema.json`](./event-schema.json)
- Shared infra: [`shared_stack.py`](../../infra/stacks/shared_stack.py)
- Reusable Lambda + DDB + route + IAM construct: [`kismet_constructs/kismet_service.py`](../../infra/kismet_constructs/kismet_service.py)
- Postmortems: [`chat-duplicate-messages-2026-04-14.md`](../postmortem/chat-duplicate-messages-2026-04-14.md), [`d3-route-revert-2026-04-12.md`](../postmortem/d3-route-revert-2026-04-12.md), [`ios-fetch-load-failed-2026-04-14.md`](../postmortem/ios-fetch-load-failed-2026-04-14.md)
- Sibling domain doc: [`Domain2_Design.md`](./Domain2_Design.md)
