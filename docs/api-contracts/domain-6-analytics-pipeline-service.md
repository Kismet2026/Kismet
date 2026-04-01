# Analytics Pipeline Service — API Contract

**Owner:** Jessica
**Domain:** Analytics & Admin
**Base Path:** `/analytics/query`
**AWS Services:** Kinesis Firehose, S3, Athena

---

## Endpoints

### POST /analytics/query

Run an Athena query on the analytics data lake.

**Auth:** Required (JWT, admin role)

**Request:**

```json
{
  "sql": "SELECT eventType, COUNT(*) as count FROM activity_events WHERE year='2026' AND month='04' GROUP BY eventType"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `sql` | string | Yes | Athena SQL query to execute |

**Response (200):**

```json
{
  "queryExecutionId": "qe-abc-123",
  "status": "QUEUED",
  "submittedAt": "2026-04-01T12:00:00Z"
}
```

**Side Effects:**
- Submits an Athena query execution against the S3 data lake

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | SQL query missing or invalid |
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | Not an admin |
| 500 | `ATHENA_ERROR` | Athena query submission failed |

---

### GET /analytics/query/{queryExecutionId}

Get results of an Athena query. May need polling if query is still running.

**Auth:** Required (JWT, admin role)

**Request:**

```
GET /analytics/query/qe-abc-123
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `queryExecutionId` | string (path) | Yes | Athena query execution ID |

**Response (200) — Query complete:**

```json
{
  "queryExecutionId": "qe-abc-123",
  "status": "SUCCEEDED",
  "results": [
    { "eventType": "swipe.created", "count": "1523" },
    { "eventType": "message.sent", "count": "892" },
    { "eventType": "match.created", "count": "234" }
  ],
  "submittedAt": "2026-04-01T12:00:00Z",
  "completedAt": "2026-04-01T12:00:05Z"
}
```

**Response (200) — Query still running:**

```json
{
  "queryExecutionId": "qe-abc-123",
  "status": "RUNNING",
  "submittedAt": "2026-04-01T12:00:00Z"
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | Not an admin |
| 404 | `NOT_FOUND` | Query execution ID not found |
| 500 | `ATHENA_ERROR` | Query execution failed |

---

### GET /analytics/dashboard

Pre-built dashboard metrics for quick admin overview.

**Auth:** Required (JWT, admin role)

**Request:**

```
GET /analytics/dashboard
```

**Response (200):**

```json
{
  "dau": 1250,
  "totalUsers": 8500,
  "matchesToday": 234,
  "messagesToday": 892,
  "generatedAt": "2026-04-01T12:00:00Z"
}
```

**Notes:**
- May cache dashboard metrics in DynamoDB for speed
- Metrics are refreshed periodically, `generatedAt` indicates freshness

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | Not an admin |

---

## Pipeline Architecture

```
Kinesis Data Stream (kismet-activity-stream)
  → Kinesis Firehose (delivery stream)
    → S3 (kismet-analytics-dev bucket)
      → Athena (SQL queries)
```

**S3 Path Structure:**

```
s3://kismet-analytics-dev/year=2026/month=04/day=01/events.json
```

Data is partitioned by year/month/day for efficient Athena queries.

---

## Storage

**Primary:** S3 + Athena (no DynamoDB)

- S3 bucket: `kismet-analytics-dev`
- Athena database: `kismet_analytics`
- Athena table: `activity_events`

**Optional:** DynamoDB cache for dashboard metrics (for speed)

---

## EventBridge Events

No events published or consumed. Reads from Kinesis Firehose automatically.

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Reads from** | Activity Logger Service | Kinesis Data Stream → Firehose → S3 |
| **Called by** | Admin Dashboard (React) | HTTP via API Gateway |
| **Depends on** | Auth (Cognito) | JWT validation via API Gateway Authorizer |
| **Uses** | AWS Athena | SQL queries on S3 data lake |
| **Uses** | AWS S3 | `kismet-analytics-dev` bucket |
