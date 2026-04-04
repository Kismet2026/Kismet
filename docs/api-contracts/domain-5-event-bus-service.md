# Event Bus Service — API Contract

**Owner:** Xiaoyuan
**Domain:** Notifications & Engagement
**Base Path:** `/events`
**AWS Services:** EventBridge, Lambda

---

## Endpoints

### GET /events/rules

List all active EventBridge rules on the kismet-events bus.

**Auth:** Required (JWT, Admin only)

**Request:**

```
GET /events/rules
```

**Response (200):**

```json
{
  "rules": [
    {
      "ruleName": "match-created-to-notification",
      "eventPattern": {
        "source": ["kismet.match-service"],
        "detail-type": ["match.created"]
      },
      "targets": ["push-notification-service", "email-service"],
      "state": "ENABLED"
    },
    {
      "ruleName": "catch-all-logger",
      "eventPattern": {
        "source": [{ "prefix": "kismet." }]
      },
      "targets": ["event-log-lambda"],
      "state": "ENABLED"
    }
  ],
  "count": 2
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | Not an admin user |

---

### GET /events/history

Query recent events from the event log for debugging.

**Auth:** Required (JWT, Admin only)

**Request:**

```
GET /events/history?source=kismet.match-service&detailType=match.created&limit=20
```

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `source` | string | No | all | Filter by event source |
| `detailType` | string | No | all | Filter by detail-type |
| `limit` | number | No | 20 | Max results (max 100) |

**Response (200):**

```json
{
  "items": [
    {
      "eventId": "evt-001",
      "source": "kismet.match-service",
      "detailType": "match.created",
      "detail": {
        "matchId": "match-001",
        "userIds": ["user-123", "user-456"]
      },
      "timestamp": "2026-04-01T12:00:00Z",
      "status": "delivered"
    },
    {
      "eventId": "evt-002",
      "source": "kismet.swipe-service",
      "detailType": "swipe.created",
      "detail": {
        "swipeId": "swipe-001",
        "userId": "user-123",
        "targetUserId": "user-456",
        "action": "like"
      },
      "timestamp": "2026-04-01T11:55:00Z",
      "status": "delivered"
    }
  ],
  "count": 2
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | Not an admin user |

---

### POST /events/replay

Replay a failed event by re-publishing it to the EventBridge bus.

**Auth:** Required (JWT, Admin only)

**Request:**

```json
{
  "eventId": "evt-003"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `eventId` | string | Yes | ID of the event to replay from the event log |

**Response (200):**

```json
{
  "eventId": "evt-003",
  "replayedAt": "2026-04-01T12:10:00Z",
  "status": "replayed"
}
```

**Side Effects:**
- Re-publishes the event to the `kismet-events` EventBridge bus
- The replayed event is logged as a new entry in `kismet-event-log`

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | Missing eventId |
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | Not an admin user |
| 404 | `NOT_FOUND` | Event not found in event log |

---

## DynamoDB Table

### Table: `kismet-event-log`

| Attribute | Type | Key |
|-----------|------|-----|
| `PK` | String (`EVENT#{eventId}`) | Partition Key |
| `SK` | String (`META`) | Sort Key |
| `source` | String | — |
| `detailType` | String | — |
| `detail` | Map | — |
| `timestamp` | String (ISO 8601) | — |
| `status` | String | — |

---

## EventBridge Configuration

- **Bus Name:** `kismet-events`
- **Catch-All Rule:** A rule that matches all events with source prefix `kismet.` and logs them to DynamoDB `kismet-event-log` via a Lambda function
- All services in the Kismet platform publish events to this bus
- Rules route events to the appropriate consumer services (Push Notification, Email, Activity Logger, etc.)

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | Admin Dashboard | HTTP via API Gateway |
| **Receives from** | All Kismet services | EventBridge events on `kismet-events` bus |
| **Routes to** | Push Notification, Email, Activity Logger, etc. | EventBridge rules |
| **Depends on** | Auth (Cognito) | JWT validation via API Gateway Authorizer |
