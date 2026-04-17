# Domain 6 — Analytics & Admin

> Detailed design for the activity-log, analytics pipeline, admin dashboard, and health-monitor services.
> Source of truth: [`infra/stacks/domain6_stack.py`](../../infra/stacks/domain6_stack.py) + [`services/domain-6-analytics/`](../../services/domain-6-analytics/)
> Last verified: Apr 16, 2026

---

## 1. Purpose

Domain 6 is Kismet's **observability and operator surface**. Nothing in the user-facing product calls D6 directly — instead, it's the fan-in sink for every interesting event that happens elsewhere, plus the back-office console for operators to see what's going on and act on it.

It owns four Lambda services backed by three DynamoDB tables, one S3 bucket, one Athena database, and one SNS topic. Upstream, it consumes virtually every domain event on the `kismet-events` bus — D1's user/profile lifecycle, D2's swipes and matches, D3's messages, D4's moderation events. Downstream, it publishes **nothing** back to EventBridge; its outputs are HTTP responses (admin console, health probes) and SNS alerts.

---

## 2. Architecture

See [`diagrams/domain6-architecture.drawio`](./diagrams/domain6-architecture.drawio).

```
     ┌───────────────────────────── kismet-events (EventBridge) ───────────────────────────┐
     │                                                                                     │
     │  user.created, profile.completed, swipe.created, match.created, message.sent,       │
     │  photo.uploaded, content.flagged, user.reported                                     │
     │                                                                                     │
     └───────┬─────────────────────────────────────────────────────────┬───────────────────┘
             │                                                         │
             ▼                                                         ▼
      ┌──────────────┐                                          ┌──────────────┐
      │  Activity    │                                          │    Admin     │
      │  Logger      │──► kismet-activity-log (DDB)             │  Dashboard   │──► kismet-flagged-content
      │              │──► (Kinesis put_record — disabled,       │              │──► kismet-admin-stats
      │              │     failure is swallowed, see §3.1)      │              │──► kismet-profiles (x-domain)
      └──────────────┘                                          └──────┬───────┘
             │                                                         │
             ▼ (intended; currently inert)                              │ REST /admin/*
       ┌───────────┐        ┌──────────────┐         ┌──────────┐      │
       │  Kinesis  │──────► │   Firehose   │────────►│    S3    │      ▼
       │  Stream   │        │              │         │ analytics│  ┌──────────────┐
       └───────────┘        └──────────────┘         └────┬─────┘  │   Admin UI   │
                                                          │        └──────────────┘
                                                          ▼
                                                     ┌─────────┐
                                                     │ Athena  │◄── Analytics Pipeline
                                                     └─────────┘    (POST /analytics/query,
                                                                     GET  /analytics/dashboard)

      ┌───────────────┐   CloudWatch GetMetricData   ┌──────────────────┐
      │ Health Monitor│─────────────────────────────►│ AWS/Lambda       │
      │               │──► SNS: kismet-health-alerts │   metrics (per   │
      │               │──► kismet-health-history     │   kismet-* fn)   │
      └───────────────┘                              └──────────────────┘

    EventBridge: kismet-events
      in (Activity Logger):  user.created, profile.completed, swipe.created, match.created,
                             message.sent, photo.uploaded, content.flagged, user.reported
      in (Admin Dashboard):  content.flagged, user.reported
      out: (none — D6 is a sink)
```

---

## 3. Services

### 3.1 Activity Logger Service

| | |
|---|---|
| **Entry** | `POST /analytics/log` (no auth — trusted intra-VPC ingest), `GET /analytics/log/recent?userId&eventType&limit` (auth) |
| **Table** | `kismet-activity-log` (PK=`USER#{userId}`, SK=`EVENT#{timestamp}#{logId}`) |
| **Consumes events** | `swipe.created`, `match.created`, `message.sent`, `user.created`, `profile.completed`, `photo.uploaded`, `content.flagged`, `user.reported` |
| **Publishes** | none |

**Responsibilities**
1. Fan-in sink for cross-domain events — every interesting thing that happens in D1-D5 lands here
2. Per-user activity timeline (query by `USER#{userId}`, sorted newest-first via `ScanIndexForward: False`)
3. Originally designed to feed a Kinesis Data Stream for real-time analytics; **currently writes directly to DynamoDB** (see Kinesis caveat below)

**Key design choices**
- **Per-user partitioning**: `PK=USER#{userId}` means one user's timeline is a single DDB partition, efficient for the recent-activity read. The trade-off is that cross-user analytical queries require a full scan (which is what Analytics Pipeline / Athena is for, on the S3 side).
- **`_extract_user_id` normalizes heterogeneous event shapes**: `match.created` carries `userIds[]` (we pick index 0 and write a *second* row for `userIds[1]` so both users' timelines see the match); `message.sent` uses `senderId`; `user.reported` uses `reporterId`; everything else falls back to `detail.userId`. See `lambda_function.py:48-57`.
- **Unauthenticated `POST /analytics/log`**: intentionally open because it's the manual/legacy ingestion path for events that don't flow through EventBridge yet. Not public-exposed — meant to be called by other Lambdas inside the account.

**Kinesis fallback (current reality).** `SharedStack.activity_stream = None` in the current AWS account because Kinesis is not yet provisioned (see `shared_stack.py:127-136`). The CDK stack correspondingly has the Kinesis import commented out (`domain6_stack.py:30-35`) and does **not** pass `KINESIS_STREAM_NAME` into the Lambda env. The Lambda code still calls `kinesis.put_record(...)` on every event, wrapped in a bare `try/except` that swallows the failure and logs it (`lambda_function.py:195-203`). The net effect:

1. Every event still lands in `kismet-activity-log` via `_write_to_dynamodb` — **DDB is effectively the current system of record for activity**.
2. Every event also triggers a failing Kinesis call, logging a line per invocation. Noisy but harmless.
3. Analytics Pipeline's S3/Athena path is therefore **empty** until Kinesis + Firehose are re-enabled — see §3.2.

### 3.2 Analytics Pipeline Service

| | |
|---|---|
| **Entry** | `POST /analytics/query { sql }`, `GET /analytics/query/{queryId}`, `GET /analytics/dashboard` (all auth) |
| **Table** | none (Athena over S3) |
| **Consumes events** | none |
| **Publishes** | none |

**Intended pipeline**: Kinesis Data Stream (`kismet-activity-stream`) → Firehose → S3 (`kismet-analytics-{account}-dev`, prefix `events/`) → Athena external table `kismet_analytics.activity_events`.

**Current pipeline**: Kinesis is disabled (see §3.1). Firehose is not provisioned. The S3 bucket exists and is empty. Athena queries succeed but return zero rows.

**Athena catalog bootstrap** — `_ensure_catalog()` lazily (once per cold start, guarded by the module-level `_catalog_ready` flag) runs:

```sql
CREATE DATABASE IF NOT EXISTS kismet_analytics;
CREATE EXTERNAL TABLE IF NOT EXISTS kismet_analytics.activity_events (
  logId STRING, eventType STRING, userId STRING,
  eventData STRING, source STRING, `timestamp` STRING
)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
WITH SERDEPROPERTIES ('ignore.malformed.json' = 'true')
LOCATION 's3://kismet-analytics-{account}-dev/events/';
```

Note: **no partitioning** defined on the external table. If the pipeline is re-enabled with any meaningful volume, partitioning by date (`events/year=YYYY/month=MM/day=DD/…`) will be needed to keep scan cost bounded — an open follow-up.

**Query lifecycle**:
- `POST /analytics/query` calls `athena:StartQueryExecution` and returns a `queryExecutionId` immediately (async).
- `GET /analytics/query/{queryId}` polls `GetQueryExecution` + `GetQueryResults` when state is `SUCCEEDED`.
- `GET /analytics/dashboard` runs a **synchronous** canned query with up to 25 s of 1 s polling (`_run_query_sync`) — DAU, totalUsers, matchesToday, messagesToday. Returns zeros on any Athena failure so the console doesn't break.

**IAM scope**: Athena, S3 read/write on the analytics bucket only, Glue catalog read/write. No DDB access.

### 3.3 Admin Dashboard Service

| | |
|---|---|
| **Entry** | 6 routes under `/admin/*` — see table below, all auth |
| **Tables** | `kismet-admin-stats` (stat counters), `kismet-flagged-content` (moderation queue), reads/writes `kismet-profiles` (D1-owned, cross-domain) |
| **Consumes events** | `content.flagged`, `user.reported` |
| **Publishes** | none |

| Route | Purpose |
|-------|---------|
| `GET /admin/stats` | Batch-read 5 counters (totalUsers, activeUsers, matchesToday, messagesToday, flaggedContentCount) from `kismet-admin-stats` at `STAT#{name}`/`LATEST` |
| `GET /admin/flagged-content` | Scan `kismet-flagged-content`, optional `?type=text|image`, cursor pagination |
| `PUT /admin/flagged-content/{contentId}/resolve` | Action = `approve` / `remove` / `ban_user`; `ban_user` cascades into `kismet-profiles` |
| `GET /admin/users` | Scan `kismet-profiles` filtered to `SK=PROFILE`, optional `search` (substring on `name`) |
| `PUT /admin/users/{userId}/ban` | Admin-initiated ban — sets `status=banned`, `bannedBy`, `bannedAt` on D1's profile row |
| `PUT /admin/users/{userId}/unban` | Reverse the above |

**Cross-domain write** — this is the only D6 service that writes outside its own tables. `domain6_stack.py:186-196` explicitly grants `GetItem/UpdateItem/Scan` on `kismet-profiles` for ban/unban/search. The ban does **not** publish `profile.banned` itself; it updates the `status` field directly. D1's Profile Service is expected to be the one publishing that event — if the admin ban path doesn't go through D1, **downstream consumers of `profile.banned` (Discovery, Match, Message) will miss the admin-initiated ban**. Tracked as a gotcha in §7.

**Admin-only authentication — demo-only**. Every `/admin/*` route is declared `auth: True` in CDK, which wires the shared Cognito authorizer. **The Lambda itself does no role check** — `_get_admin_id` reads `claims.sub` but never inspects a group or `custom:role` claim. So any authenticated user can call every `/admin/*` endpoint. The API contract (`domain-6-admin-dashboard-service.md`) documents `403 FORBIDDEN — Not an admin`, but that response path is not implemented. For production this needs either:
- API Gateway authorizer changes to require a Cognito group (e.g. `admins`), or
- An in-Lambda check on `claims['cognito:groups']` or `claims['custom:role']`.

For the course demo the model is "whoever knows the admin UI URL is an admin". Explicit and documented, not accidental.

**Event handlers**:
- `content.flagged` (from D4 Image Moderation / Text Moderation) → writes a row to `kismet-flagged-content` with `status=pending` and increments `flaggedContentCount`.
- `user.reported` (from D4 Report Service) → increments `reportCount` on the reported user's profile row. Does **not** auto-ban — that's D4's 2-distinct-reports policy.

**Missing integrations (known):**
- Does **not** consume `profile.banned`. When D4/D1 auto-ban from a 2nd distinct report, the admin dashboard has no record of it — the user just silently appears with `status=banned` on the next `/admin/users` scan. Auto-bans should ideally publish into the flagged-content queue for audit visibility.
- The `?status=PENDING` report filter added in #114 is **not wired** into `GET /admin/flagged-content`. The handler always scans all rows regardless of status. Low-effort fix.

### 3.4 Health Monitor Service

| | |
|---|---|
| **Entry** | `GET /health` (public, no auth), `GET /health/{serviceName}`, `GET /health/alarms`, `POST /health/check` (auth) |
| **Table** | `kismet-health-history` (PK=`SERVICE#_all`, SK=`CHECK#{timestamp}`) |
| **Consumes events** | none |
| **Publishes** | SNS only (`kismet-health-alerts`) |

**Monitored services** — hardcoded in `KNOWN_SERVICES`:

```
auth-service, profile-service, swipe-service, match-service,
message-service, chat-gateway
```

Conspicuous absence: D4 moderation services, D5 notification services, and the D6 services themselves. The list reflects the "core user path" — if these six are healthy, a user can sign in, browse, swipe, match, and chat. Expanding it is just editing the constant.

**Metric derivation** — for each service, `cloudwatch:GetMetricData` pulls a 5-minute window of `AWS/Lambda` metrics: `Errors` (Sum), `Invocations` (Sum), `Duration` (Average + p99), `Throttles` (Sum). Status classification:

| Status | Condition |
|--------|-----------|
| `unhealthy` | `errorRate > 0.05` |
| `degraded` | `avgDuration > 300 ms` |
| `healthy` | otherwise |

Overall status is the **worst** of the per-service statuses (`_rollup_status`).

**Two read paths, one write path**:
- `GET /health` and `GET /health/{serviceName}` are **pure reads** — compute-on-demand from CloudWatch, no DDB write. Public `/health` is safe because it returns only statuses and average latency, not raw invocation counts.
- `POST /health/check` is the **canonical sampler**: same rollup, plus it writes a history row to `kismet-health-history` and — if overall status is not `healthy` — publishes to the `kismet-health-alerts` SNS topic. Intended to be hit on a schedule (EventBridge rule or external cron; not currently wired in CDK).
- `GET /health/alarms` calls `cloudwatch:DescribeAlarms(StateValue=ALARM)` and returns anything currently firing, stripping the `-error-rate` naming suffix to surface the service name.

**SNS alert shape**:

```json
{
  "alarmName": "kismet-system-health",
  "serviceName": "_all",
  "state": "DEGRADED" | "UNHEALTHY",
  "reason": "Degraded/unhealthy services: swipe-service, match-service",
  "timestamp": "2026-04-16T..."
}
```

No actual CloudWatch Alarms are defined in `domain6_stack.py` — alarm discovery is read-only. If the team wants real alarms (with auto-SNS on threshold breach), those need to be added as `cloudwatch.Alarm` constructs in whichever stack owns the metric.

---

## 4. Data Layer

| Table | Primary key | Size profile | Notes |
|-------|-------------|--------------|-------|
| `kismet-activity-log` | PK `USER#{userId}` / SK `EVENT#{timestamp}#{logId}` | 1 row per event per user (2 per match) | Grows linearly with activity; TTL not set — future follow-up |
| `kismet-admin-stats` | PK `STAT#{statName}` / SK `LATEST` | ~5 rows, one per tracked counter | Atomic `ADD :delta` updates; stored as numbers |
| `kismet-flagged-content` | PK `CONTENT#{contentId}` / SK `META` | Bounded by moderation volume | Confidence stored as `Decimal` to avoid float drift |
| `kismet-health-history` | PK `SERVICE#_all` / SK `CHECK#{timestamp}` | 1 row per `POST /health/check` | All checks stored under one partition — fine at current sample rate (minutes), would need per-service PK at high frequency |
| `kismet-profiles` *(D1-owned, cross-domain)* | PK `USER#{userId}` / SK `PROFILE` | — | Admin Dashboard reads and writes `status`/`bannedBy`/`bannedAt`/`reportCount` |

All tables use on-demand billing. No GSIs.

**S3**: `kismet-analytics-{account}-dev` — analytics data (`events/` prefix) + Athena query results (`athena-results/` prefix). `auto_delete_objects=True` and `RemovalPolicy.DESTROY` — demo-safe, not production.

---

## 5. Event Flows

### 5.1 Swipe → Activity Log

```
D2 Swipe Service ── swipe.created ──► EventBridge
                                          │
                                          ▼
                                 Activity Logger
                                 - put 1 row at USER#{swiperId}
                                 - (Kinesis put fails silently)
```

### 5.2 Match → Both Users' Timelines

```
D2 Match Service ── match.created {userIds: [A, B]} ──► EventBridge
                                                           │
                                                           ▼
                                                 Activity Logger
                                                 - put row at USER#A (index 0)
                                                 - put row at USER#B (index 1)
```

See `lambda_function.py:85-93` — `match.created` is the one event that fans to two DDB rows so both participants' activity feeds reflect it.

### 5.3 Content Flagged → Admin Queue

```
D4 Image/Text Moderation ── content.flagged ──► EventBridge
                                                   │
                                     ┌─────────────┴─────────────┐
                                     ▼                           ▼
                            Activity Logger              Admin Dashboard
                            - timeline row               - put CONTENT# row
                                                         - flaggedContentCount++

Admin opens dashboard ──► GET /admin/flagged-content
Admin clicks "Ban"    ──► PUT /admin/flagged-content/{id}/resolve {action: "ban_user"}
                            - update CONTENT# status=resolved
                            - update kismet-profiles status=banned   ⚠ no event published
                            - flaggedContentCount--
```

The ⚠ note on the last step: downstream domains only learn about the ban if D1 or D4 publishes `profile.banned` elsewhere. D6's direct profile write is a shortcut that bypasses the event system — acceptable for demo, a gotcha for production.

### 5.4 Health Check Cycle

```
(scheduled trigger — currently manual or via console)
          │
          ▼
   POST /health/check
          │
          ├──► CloudWatch GetMetricData × 6 services × 5 metrics
          ├──► kismet-health-history put_item
          └──► if !healthy: SNS publish to kismet-health-alerts
```

---

## 6. Cross-Service Dependencies

| Caller | Reads/writes | Why |
|--------|--------------|-----|
| Activity Logger | writes `kismet-activity-log` only | Pure sink |
| Analytics Pipeline | reads/writes `kismet-analytics-*` S3, Athena, Glue | No DDB |
| Admin Dashboard | writes `kismet-profiles` (D1-owned) | Ban / unban path |
| Admin Dashboard | reads `kismet-profiles` | User list and search |
| Health Monitor | reads CloudWatch metrics for every `kismet-*` Lambda | Cross-cutting |

Nobody else writes D6's tables — the fan-in is one-way via EventBridge.

---

## 7. Known Gotchas / Postmortem Highlights

1. **Kinesis is disabled on the current AWS account.** `SharedStack.activity_stream = None` (`shared_stack.py:127-136`). The Activity Logger Lambda still issues `kinesis.put_record` on every invocation, wrapped in try/except — one noisy log line per event, no correctness impact. The Analytics Pipeline's S3/Athena path is consequently empty and the `/analytics/dashboard` endpoint returns zeros. DynamoDB (`kismet-activity-log`) is the de-facto system of record until the stream comes back.
2. **Admin auth is demo-only.** `auth: True` on `/admin/*` only means "valid Cognito JWT required". The Lambda does not check group membership or `custom:role`. Any signed-in user can ban other users. Documented in `domain-6-admin-dashboard-service.md` as `403 FORBIDDEN`, but that branch does not exist in code. Fix = authorizer-level group check OR in-Lambda claim inspection.
3. **Admin ban doesn't fan out.** `PUT /admin/users/{id}/ban` and the `ban_user` resolve action update `kismet-profiles.status` directly but do **not** publish `profile.banned`. Other domains (D2 Discovery, Match, D3 Message) rely on that event to purge state — they won't see an admin ban unless D1 Profile Service re-publishes the event itself. Course-correct is either publishing from the admin path or routing the write through D1.
4. **Admin Dashboard doesn't consume `profile.banned`.** Auto-bans from D4's "2 distinct reports" policy silently flip a profile's status; the admin console has no audit row for them. Adding `profile.banned` to `consume_events` and writing an entry into `kismet-flagged-content` (or a dedicated audit table) would close this loop.
5. **`?status=PENDING` filter from #114 isn't wired.** The report-queue filter landed in D4 but `GET /admin/flagged-content` still scans all rows. Trivial follow-up.
6. **No partitioning on the Athena external table.** `activity_events` is flat at `events/` with no date partitions. Fine at current (zero) volume; a ticking time bomb once the Kinesis/Firehose path is active. Firehose should be configured with dynamic partitioning or at minimum year/month/day prefixing.
7. **`kismet-health-history` single-partition.** All health checks write `PK=SERVICE#_all`, which is fine at a per-minute sample rate but would hot-spot at higher frequencies. Splitting to `PK=SERVICE#{name}` keeps per-service history queryable and distributes writes.
8. **`KNOWN_SERVICES` is hardcoded.** Health Monitor only watches six services; D4/D5/D6 Lambdas are invisible to `/health`. Editing the list is a one-line change but there's no convention forcing it to stay in sync with CDK.
9. **No CloudWatch Alarms are provisioned.** `/health/alarms` reads alarms but the stack doesn't create any. Real proactive alerting requires adding `cloudwatch.Alarm` constructs alongside the metrics they watch.

---

## 8. Open Follow-ups

- Re-enable Kinesis + Firehose once AWS account limits allow; re-wire `KINESIS_STREAM_NAME` env var and verify S3 partitioning.
- Admin role check — either Cognito group `admins` enforced at the authorizer, or explicit claim check in the Lambda.
- Publish `profile.banned` from admin ban paths (or route through D1).
- Consume `profile.banned` in Admin Dashboard for auto-ban audit trail.
- Wire `?status=pending` filter on `GET /admin/flagged-content` (#114 follow-on).
- Add date partitioning to the Athena external table.
- Schedule `POST /health/check` via EventBridge rule (every 1-5 min).
- Provision real `cloudwatch.Alarm`s for the 6 core services → SNS → PagerDuty/email.
- TTL on `kismet-activity-log` to bound storage cost.
- Expand `KNOWN_SERVICES` in Health Monitor to cover D4/D5/D6.

---

## 9. References

- API contracts: [`docs/api-contracts/domain-6-*.md`](../api-contracts/)
- Event shapes: [`event-schema.json`](./event-schema.json)
- Shared infra: [`shared_stack.py`](../../infra/stacks/shared_stack.py) (Kinesis disabled at line 136, analytics bucket at 119, SNS topic at 140)
- Reusable Lambda + DDB + route + IAM construct: [`kismet_constructs/kismet_service.py`](../../infra/kismet_constructs/kismet_service.py)
- Cross-domain integration tests: [`tests/test_cross_domain_integration.py`](../../tests/test_cross_domain_integration.py)
