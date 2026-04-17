# Domain 5 — Notifications & Engagement

> Detailed design for push, email, event-bus, and scheduler services.
> Source of truth: [`infra/stacks/domain5_stack.py`](../../infra/stacks/domain5_stack.py) + [`services/domain-5-notifications/`](../../services/domain-5-notifications/)
> Last verified: Apr 16, 2026

---

## 1. Purpose

Domain 5 is the "engagement surface" of Kismet — it owns every piece of outbound communication (push, email), every timed job (digests, cleanups, health checks), and the cross-domain audit trail for events flowing through `kismet-events`. It runs four services, six Lambda functions, and four DynamoDB tables, backed by SNS platform endpoints, SES identities, and EventBridge Scheduler.

Upstream, D5 is almost entirely event-driven: it consumes lifecycle events from D1 (Identity), match events from D2 (Discovery), message events from D3 (Messaging), and moderation events from D4. Downstream it publishes only `scheduler.*` events (from the scheduler executor) and re-publishes historical events on admin replay. The catch-all logger receives **every** `kismet.*` event on the bus and is the cross-cutting audit layer for the whole platform.

---

## 2. Architecture

```
                    ┌─────────────────────────────────┐
                    │   Imported REST API + Cognito   │
                    └──┬──────┬──────┬──────┬─────────┘
                       │      │      │      │
              ┌────────▼──┐ ┌─▼──┐ ┌─▼───┐ ┌▼──────────┐
              │ Push Notif│ │Email│ │Event│ │Scheduler  │
              │           │ │     │ │Admin│ │Admin      │
              └──┬────┬───┘ └──┬──┘ └──┬──┘ └─────┬─────┘
                 │    │        │       │          │
             ┌───▼─┐ ┌▼───┐ ┌──▼─┐ ┌───▼─────┐ ┌──▼──────────┐
             │ SNS │ │DDB │ │SES │ │DDB      │ │EventBridge  │
             │     │ │×2  │ │    │ │event-log│ │Scheduler ×4 │
             └─────┘ └────┘ └────┘ └──▲──────┘ └──────┬──────┘
                                      │               │
                               ┌──────┴──────┐  ┌─────▼──────┐
                               │Catch-All Fn │  │Executor Fn │
                               │(every kismet│  │(built-in + │
                               │.* event)    │  │ custom jobs)│
                               └──────▲──────┘  └─────┬──────┘
                                      │               │
                                      └───── kismet-events (EventBridge)
                                              ▲
                           in:  user.created, user.deleted, user.reported,
                                match.created, message.sent
                           out: scheduler.weekly_digest,
                                scheduler.stale_match_cleanup,
                                scheduler.analytics_aggregation,
                                scheduler.health_check
```

See [`diagrams/domain5-architecture.drawio`](./diagrams/domain5-architecture.drawio).

---

## 3. Services

### 3.1 Push Notification Service

| | |
|---|---|
| **Entry** | `POST /notifications/register`, `GET /notifications`, `GET /notifications/unread-count`, `PUT /notifications/{notificationId}/read` (Cognito-authenticated) |
| **Tables** | `kismet-notifications`, `kismet-device-tokens` (both PK/SK single-table) |
| **Consumes events** | `match.created`, `message.sent` |
| **Publishes** | none |

**Responsibilities**
1. Device registration: register FCM/APNS/web-push tokens with SNS `CreatePlatformEndpoint`, persist the returned `EndpointArn` keyed by `USER#{userId}` / `DEVICE#{deviceToken}`
2. Fan-out on `match.created` — both matched users get an in-app notification row + a push to every registered device
3. Fan-out on `message.sent` — only the `recipientId` (pulled from the event detail) gets notified; a 50-char preview is attached
4. Serve in-app inbox (`GET /notifications`, paginated), mark-read, and O(1) unread-count lookups

**Key design choices**
- **Denormalized unread counter**: `UNREAD_COUNT` is a special SK on the user's partition updated via `ADD :1` / `ADD :-1`. Avoids a query-and-count on every `GET /unread-count`. Atomic DynamoDB `ADD` seeds the item on first write.
- **Notification SK layout**: `NOTIF#{epoch_ms:013d}-{uuid8}`. The zero-padded epoch prefix gives chronological `ScanIndexForward=False` sort without client-side sort; the uuid suffix keeps concurrent writes collision-safe.
- **Multi-platform SNS payload**: `MessageStructure="json"` with `default` / `GCM` / `APNS` branches in a single `Publish` call — one API call regardless of device mix.
- **Graceful degradation**: if `sns.create_platform_endpoint` fails, the row is still written with an empty `snsEndpointArn`. The inbox works; only the push channel is disabled for that device.

### 3.2 Email Service

| | |
|---|---|
| **Entry** | `GET /email/preferences`, `PUT /email/preferences` |
| **Table** | `kismet-email-preferences` (PK=`USER#{userId}`, SK=`PREFS`) |
| **Consumes events** | `user.created`, `match.created`, `user.reported`, `user.deleted`, `scheduler.weekly_digest`, `message.sent` |
| **Publishes** | none |

Single Lambda handler (`lambda_function.handler`) dispatches on `source`+`detail-type` for EventBridge invocations and on `httpMethod`+`path` for API Gateway. Every outbound email goes through one helper (`send_ses_email`) that wraps `ses:SendEmail` with inline HTML + plaintext fallbacks.

**Event handlers**

| Event | Action |
|-------|--------|
| `user.created` | Insert preferences row with `DEFAULT_PREFERENCES` (all `True`) and the user's email, under `ConditionExpression: attribute_not_exists(PK)` so replays don't overwrite opt-outs. Then send the "welcome" template. |
| `match.created` | For each userId in `detail.userIds`: read prefs, skip if `matchNotifications=False`, else render the "match_notification" template. |
| `message.sent` | Read recipient's prefs, skip if `messageNotifications=False`, else send "message_notification". |
| `user.reported` | Send "report_alert" template to `ADMIN_EMAIL` with the report/reporter/reportedUser/reason. No prefs check — admins don't opt out. |
| `user.deleted` | `delete_item` on the preferences row. Irreversible. |
| `scheduler.weekly_digest` | Paginated scan of the prefs table with `FilterExpression: weeklyDigest = True`, send the "weekly_digest" template to each. |

**Email preferences**
- Three boolean toggles: `matchNotifications`, `messageNotifications`, `weeklyDigest`. Defaulted to `True` for new users.
- `GET /email/preferences` returns defaults if no row exists yet (first-read before `user.created` has landed).
- `PUT /email/preferences` validates each field is `bool`, allowlists the three keys, and does a partial update — unlisted keys are preserved.
- The user's email address is **cached on the prefs row** at `user.created` time. This is deliberate: it avoids a cross-domain read to D1's profile table on every match/message email.

**SES sandbox constraints (critical)**
- In the current AWS account SES is in sandbox mode: **both** the `Source` identity and **every** `Destination` address must be pre-verified in the SES console or the send throws `MessageRejected: Email address is not verified`.
- Default `SENDER_EMAIL` in the stack is `noreply@kismet.app`, which is **not** verified. In the live demo environment the env var is overridden to `qinyuans0114@gmail.com`, which is verified. Any recipient used in a demo also has to be added to the verified-identity list first.
- `send_ses_email` catches and logs SES exceptions rather than raising — a failed send won't block a downstream event handler from completing, but it will silently drop the email. Check CloudWatch for the Email Service log group when a demo recipient claims "I never got it."

### 3.3 Event Bus Service

| | |
|---|---|
| **Entry (admin)** | `GET /events/rules`, `GET /events/history?source&detailType&limit`, `POST /events/replay { eventId }` |
| **Entry (event)** | EventBridge rule `kismet-catch-all-logger` — pattern `{source: [{prefix: "kismet."}]}` |
| **Table** | `kismet-event-log` (PK=`EVENT#{eventId}`, SK=`META`, GSI `source-timestamp-index`) |
| **Consumes events** | **every** `kismet.*` event on `kismet-events` |
| **Publishes** | re-publishes originals on `/events/replay` |

**What it actually does** — despite the "cross-domain event routing service" framing in the top-level Design Doc, the code is scoped more tightly:

1. **Catch-all logger** (`catch_all_handler`) — target of a single EventBridge rule matching `source: prefix "kismet."`. Every event that hits the bus gets stored: eventId, source, detail-type, full detail JSON, timestamp, `status: "delivered"`. No routing, no forwarding — just the audit log.
2. **Admin API** (`admin_api_handler`) — three endpoints for debugging:
   - `/events/rules` lists live EventBridge rules + their targets (via `events:ListRules` + `events:ListTargetsByRule`), so you can verify a new consumer was wired correctly.
   - `/events/history` queries the log. With `?source=` it uses the `source-timestamp-index` GSI for O(log n) by source; without, it falls back to a full `Scan` with a `Limit` cap at 100 (admin-only, low-traffic).
   - `/events/replay` re-publishes a historical event back onto `kismet-events` using the original source + detail-type + detail, and writes a new log entry with `status: "replayed"` and `originalEventId` pointing back.

Routing between producer and consumer is handled entirely by EventBridge rules defined in each domain's own CDK stack — Event Bus Service does **not** fan out, translate, or filter events. It is the observability + replay layer for the bus, not the routing layer.

### 3.4 Scheduler Service

| | |
|---|---|
| **Entry (admin)** | `GET /scheduler/jobs`, `POST /scheduler/jobs`, `DELETE /scheduler/jobs/{jobId}` |
| **Entry (schedule)** | EventBridge Scheduler → `job_executor_handler` Lambda |
| **Table** | `kismet-scheduler` (PK=`JOB#{jobId}`, SK=`META`) |
| **Consumes events** | none (scheduler invocations are direct Lambda calls, not bus events) |
| **Publishes** | `scheduler.weekly_digest`, `scheduler.stale_match_cleanup`, `scheduler.analytics_aggregation`, `scheduler.health_check` |

Two Lambdas share the same code bundle:

- **Job Executor** — invoked by EventBridge Scheduler with `{jobType, jobId?, params?}`. Looks up the job type in `JOB_EVENT_MAP` (the canonical registry of known job types) and emits the corresponding event onto `kismet-events`. If the invocation includes a `jobId` it updates `lastRunAt` on the DDB row; for built-in schedules `jobId` is `None` and the DDB write is skipped.
- **Admin API** — CRUD over both the DDB registry and the `scheduler:*` API:
  - `POST` creates an EventBridge Scheduler schedule (naming convention `kismet-{jobType}-{jobId}-{env}`), then writes the job row. Guards duplicates via a pre-scan on `jobType`+`schedule`.
  - `DELETE` removes the schedule (tolerating `ResourceNotFoundException` if it's already gone), then deletes the row.

**Built-in schedules** (created in the CDK stack, not via admin API — so they don't live in the DDB table):

| ID | Cron / Rate | Job type | Fan-out |
|----|-------------|----------|---------|
| `WeeklyDigest` | `cron(0 9 ? * SUN *)` | `weekly_digest` | Email Service sends to users with `weeklyDigest=True` |
| `StaleMatchCleanup` | `rate(1 day)` | `stale_match_cleanup` | (no consumer wired yet) |
| `AnalyticsAggregation` | `rate(1 hour)` | `analytics_aggregation` | D6 Activity Logger flush (when Kinesis enabled) |
| `HealthCheck` | `rate(5 minutes)` | `health_check` | D6 Health Monitor |

> **Note**: the task brief described the weekly digest as "Scheduler → Step Functions → Email." There are no Step Functions in the stack. The actual path is **EventBridge Scheduler (cron) → Executor Lambda → `put_events` onto kismet-events → Email Service catch-handler**. A Step Function would be overkill here — the work is one scan + one SES send per user and fits within a single Lambda's timeout for the current user base.

---

## 4. Data Layer

| Table | Primary key | GSI | Notes |
|-------|-------------|-----|-------|
| `kismet-notifications` | `USER#{userId}` / `NOTIF#{epoch_ms}-{uuid8}` or `UNREAD_COUNT` | — | in-app inbox + atomic unread counter; read paged newest-first |
| `kismet-device-tokens` | `USER#{userId}` / `DEVICE#{deviceToken}` | — | one row per registered device; stores `snsEndpointArn` |
| `kismet-email-preferences` | `USER#{userId}` / `PREFS` | — | three opt-in booleans + cached email for event handlers |
| `kismet-event-log` | `EVENT#{eventId}` / `META` | `source-timestamp-index` (source HK, timestamp RK) | every bus event, queryable by source |
| `kismet-scheduler` | `JOB#{jobId}` / `META` | — | custom (admin-created) jobs only; built-ins live in CFN |

All tables are `PAY_PER_REQUEST` with `RemovalPolicy.DESTROY` — acceptable for a demo environment, would flip to `RETAIN` before any real launch.

---

## 5. Event Flows

### 5.1 New user → welcome email + prefs row

```
D1 Profile Service
    │
    └─── user.created ──► EventBridge
                              │
                              ▼
                       Email Service
                       - conditional put on prefs row (idempotent)
                       - ses:SendEmail "welcome"
```

### 5.2 Match created → push + email to both users

```
D2 Match Service ── match.created ──► EventBridge
                                           │
                        ┌──────────────────┼─────────────────────┐
                        ▼                  ▼                     ▼
                Push Notif Service    Email Service         Catch-All Logger
                - for each userId:    - for each userId:    - put to event-log
                    create notif row      read prefs.match
                    ADD unread_count       skip if opted-out
                    SNS publish × N        ses:SendEmail
                    devices
```

### 5.3 Weekly digest

```
EventBridge Scheduler (cron SUN 09:00 UTC)
    │
    ▼
Scheduler Executor Lambda
    │
    └─── scheduler.weekly_digest ──► EventBridge
                                          │
                             ┌────────────┴────────────┐
                             ▼                         ▼
                       Email Service              Catch-All Logger
                       - paginated scan            - log event
                         where weeklyDigest=True
                       - ses:SendEmail × N
```

### 5.4 Account deletion

```
D1 Profile Service
    │
    └─── user.deleted ──► EventBridge
                              │
                              ▼
                       Email Service
                       - delete prefs row
    (Push Notif does NOT currently handle user.deleted — notification
     rows and device tokens are orphaned until TTL / manual cleanup.
     See §7 gotchas.)
```

---

## 6. Cross-Service Dependencies

| Caller | Reads / Writes | Why |
|--------|----------------|-----|
| Email Service | reads `kismet-email-preferences` (own); `email` attribute cached on row | avoid cross-domain read to D1 profile on every email |
| Push Notif | reads `kismet-device-tokens`, writes `kismet-notifications` | fan-out + inbox |
| Event Bus (catch-all) | writes `kismet-event-log` only | audit trail |
| Event Bus (admin) | reads `kismet-event-log`, reads EventBridge rules, puts to `kismet-events` on replay | debugging |
| Scheduler (executor) | puts to `kismet-events`, updates `kismet-scheduler.lastRunAt` | timed trigger |
| Scheduler (admin) | CRUD on `scheduler:*` + `kismet-scheduler`; `iam:PassRole` on `kismet-scheduler-execution-role` | custom-job registration |

No D5 service writes into another domain's table. All cross-domain signalling is via EventBridge.

---

## 7. Known Gotchas / Postmortem Highlights

1. **SES sandbox** — the #1 support request from demo rehearsals. Both sender and recipient must be verified in the AWS account running the demo. `SENDER_EMAIL` defaults to the unverified `noreply@kismet.app`; override via the Lambda env var to a verified identity (today: `qinyuans0114@gmail.com`). Sends fail with `MessageRejected: Email address is not verified` in CloudWatch.
2. **#120 — no ban notification email.** Email Service's consumer list does **not** include `profile.banned`. When a user is banned via D4 moderation, no email is sent to explain the action. Follow-up: add `profile.banned` to the CDK `consume_events` list and wire a handler that sends from a verified admin identity even if the user's own address isn't verified (relevant because banned users may not be on the verified list).
3. **Stale device tokens.** SNS raises `EndpointDisabled` for tokens that APNs/FCM has invalidated. `send_push_to_user` currently catches the exception and logs it, but does **not** delete the row from `kismet-device-tokens`. Over time this produces repeated publish attempts against dead endpoints. Follow-up: detect `EndpointDisabled` specifically and `delete_item` the offending `DEVICE#` row.
4. **`user.deleted` doesn't purge push state.** Email Service deletes the prefs row; Push Notif Service has no `user.deleted` handler. Notification rows and device-token rows for a deleted user are orphaned until we add a purge or a TTL attribute on the tables.
5. **Kinesis fallback.** The `analytics_aggregation` schedule fires every hour, but in the current AWS account Kinesis is disabled per Shared Stack config, so D6 Activity Logger silently drops the event. The scheduler run still succeeds — no alarm.
6. **"Cross-domain event routing service" is a misnomer.** The top-level Design Doc §3 describes Event Bus Service as doing routing; the code does audit logging + replay only. EventBridge rules in each domain's stack do the actual routing. This design doc reflects the code; the top-level doc should be corrected.
7. **`events:ListRules` IAM scope.** The admin Lambda's IAM policy grants `events:ListRules` scoped to `rule/kismet-events/*`. `ListRules` requires `EventBusName` to be supplied in the SDK call; if you call it bare it targets `default` and returns nothing — easy to misdiagnose as "no rules exist."
8. **Replay is idempotent-unsafe.** `POST /events/replay` re-emits the original event with a new EventBridge `id`. Every downstream consumer will re-run its handler. For `match.created` that means a duplicate notification row + duplicate email. Use with care; not safe to replay `user.created`.
9. **Unread-count drift.** The counter is updated separately from the notification row put. If the put succeeds and the counter `update_item` fails (ops error, throttle), the counter drifts low. No reconciliation job exists. Low-priority because DDB on-demand rarely throttles at demo scale.

---

## 8. Open Follow-ups

- **#120** — Ban notification email (consume `profile.banned`, use verified admin sender)
- Handle `EndpointDisabled` in Push Notif and delete the stale token row
- Add `user.deleted` handler to Push Notif to purge notifications + device tokens
- TTL attribute on `kismet-notifications` so read notifications age out automatically
- Wire a consumer for `scheduler.stale_match_cleanup` (currently fires to a black hole every day)
- Correct Event Bus Service description in the top-level Design Doc §3 to match the code
- Reconciliation job for `UNREAD_COUNT` drift (low priority)

---

## 9. References

- API contracts: [`docs/api-contracts/domain-5-*.md`](../api-contracts/)
- Event shapes: [`event-schema.json`](./event-schema.json)
- Shared infra: [`shared_stack.py`](../../infra/stacks/shared_stack.py)
- Reusable Lambda + DDB + route + IAM construct: [`kismet_constructs/kismet_service.py`](../../infra/kismet_constructs/kismet_service.py)
- Top-level architecture: [`Design_Doc.md`](./Design_Doc.md)
