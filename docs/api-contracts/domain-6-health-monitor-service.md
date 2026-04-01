# Health Monitor Service — API Contract

**Owner:** Lingyun
**Domain:** Analytics & Admin
**Base Path:** `/health`
**AWS Services:** CloudWatch, Lambda, SNS

---

## Endpoints

### GET /health

Overall system health status. Checks all services.

**Auth:** Not required (public, used for uptime monitoring)

**Request:**

```
GET /health
```

**Response (200):**

```json
{
  "status": "healthy",
  "services": {
    "auth-service": { "status": "healthy", "latency": 45 },
    "profile-service": { "status": "healthy", "latency": 62 },
    "swipe-service": { "status": "healthy", "latency": 38 },
    "match-service": { "status": "healthy", "latency": 55 },
    "message-service": { "status": "degraded", "latency": 320 },
    "chat-gateway": { "status": "healthy", "latency": 41 }
  },
  "checkedAt": "2026-04-01T12:00:00Z"
}
```

**Notes:**
- `status` is `"healthy"`, `"degraded"`, or `"unhealthy"`
- Overall status is `"degraded"` if any service is degraded, `"unhealthy"` if any is unhealthy

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 500 | `INTERNAL_ERROR` | Health check system itself failed |

---

### GET /health/{serviceName}

Individual service health with detailed metrics.

**Auth:** Required (JWT, admin role)

**Request:**

```
GET /health/swipe-service
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `serviceName` | string (path) | Yes | Name of the service to check |

**Response (200):**

```json
{
  "serviceName": "swipe-service",
  "status": "healthy",
  "metrics": {
    "errors": 2,
    "errorRate": 0.01,
    "avgDuration": 38,
    "p99Duration": 120,
    "invocations": 1523,
    "throttles": 0
  },
  "period": "last_5_minutes",
  "checkedAt": "2026-04-01T12:00:00Z"
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | Not an admin |
| 404 | `NOT_FOUND` | Service name not recognized |

---

### GET /health/alarms

List active CloudWatch alarms.

**Auth:** Required (JWT, admin role)

**Request:**

```
GET /health/alarms
```

**Response (200):**

```json
{
  "alarms": [
    {
      "alarmName": "swipe-service-error-rate",
      "serviceName": "swipe-service",
      "state": "ALARM",
      "reason": "Error rate exceeded 5% threshold",
      "stateChangedAt": "2026-04-01T11:45:00Z"
    }
  ],
  "activeCount": 1,
  "checkedAt": "2026-04-01T12:00:00Z"
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | Not an admin |

---

### POST /health/check

Trigger a manual health check of all services.

**Auth:** Required (JWT, admin role)

**Request:**

```
POST /health/check
```

**Response (200):**

```json
{
  "status": "healthy",
  "services": {
    "auth-service": { "status": "healthy", "latency": 45 },
    "profile-service": { "status": "healthy", "latency": 62 },
    "swipe-service": { "status": "healthy", "latency": 38 },
    "match-service": { "status": "healthy", "latency": 55 },
    "message-service": { "status": "healthy", "latency": 78 },
    "chat-gateway": { "status": "healthy", "latency": 41 }
  },
  "checkedAt": "2026-04-01T12:05:00Z"
}
```

**Side Effects:**
- Runs a fresh health check against all services
- Writes results to DynamoDB `kismet-health-history` table
- Triggers SNS alert if any service is unhealthy

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | Not an admin |
| 500 | `INTERNAL_ERROR` | Health check execution failed |

---

## CloudWatch Configuration

**Metrics monitored per Lambda function:**
- `Errors` — number of failed invocations
- `Duration` — execution time (avg, p99)
- `Invocations` — total invocation count
- `Throttles` — throttled invocations

**CloudWatch Alarms:**
- One alarm per service for error rate > 5%
- Alarm naming convention: `{serviceName}-error-rate`
- Evaluation period: 5 minutes

---

## SNS Topic

**Topic:** `kismet-health-alerts`

Sends alerts when CloudWatch alarms trigger. Payload:

```json
{
  "alarmName": "swipe-service-error-rate",
  "serviceName": "swipe-service",
  "state": "ALARM",
  "reason": "Error rate exceeded 5% threshold",
  "timestamp": "2026-04-01T11:45:00Z"
}
```

---

## DynamoDB Table

**Table:** `kismet-health-history`

| Attribute | Type | Key |
|-----------|------|-----|
| `PK` | String (`SERVICE#{serviceName}`) | Partition Key |
| `SK` | String (`CHECK#{timestamp}`) | Sort Key |
| `status` | String | — |
| `metrics` | Map | — |
| `checkedAt` | String (ISO 8601) | — |

---

## EventBridge Events

No events published or consumed. Runs on schedule (every 5 minutes via Scheduler Service) and on-demand via POST /health/check.

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | Uptime monitors (external) | HTTP via API Gateway (GET /health, public) |
| **Called by** | Admin Dashboard (React) | HTTP via API Gateway (admin endpoints) |
| **Called by** | Scheduler Service | Invokes health check every 5 minutes |
| **Reads from** | CloudWatch | Lambda metrics for all services |
| **Publishes to** | SNS | `kismet-health-alerts` topic |
| **Depends on** | Auth (Cognito) | JWT validation for admin endpoints |
