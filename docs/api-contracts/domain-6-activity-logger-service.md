# Activity Logger Service — API Contract

**Owner:** Jessica
**Domain:** Analytics & Admin
**Base Path:** `/analytics/log`
**AWS Services:** Kinesis Data Streams, Lambda

---

## Endpoints

### POST /analytics/log

Log a user activity event to Kinesis stream (internal use, triggered by EventBridge).

**Auth:** Internal only (EventBridge trigger, no external access)

**Request:**

```json
{
  "eventType": "swipe.created",
  "eventData": {
    "swipeId": "swipe-001",
    "targetUserId": "user-456",
    "action": "like"
  },
  "userId": "user-123"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `eventType` | string | Yes | Event type name (e.g. `"swipe.created"`, `"message.sent"`) |
| `eventData` | object | Yes | Event payload (varies by event type) |
| `userId` | string | Yes | User who triggered the event |

**Response (200):**

```json
{
  "logId": "log-001",
  "eventType": "swipe.created",
  "userId": "user-123",
  "timestamp": "2026-04-01T12:00:00Z",
  "status": "accepted"
}
```

**Side Effects:**
- Writes JSON record to Kinesis Data Stream `kismet-activity-stream`
- Writes to DynamoDB `kismet-activity-log` table for recent event cache
- Simplification fallback: if Kinesis is too complex, write directly to S3 as JSON files

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | eventType, eventData, or userId missing |
| 500 | `INTERNAL_ERROR` | Kinesis write failure |

---

### GET /analytics/log/recent

Query recent activity events (admin only).

**Auth:** Required (JWT, admin role)

**Request:**

```
GET /analytics/log/recent?userId=user-123&eventType=swipe.created&limit=50
```

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `userId` | string | No | null | Filter by user ID |
| `eventType` | string | No | null | Filter by event type |
| `limit` | number | No | 50 | Number of events to return (max 100) |

**Response (200):**

```json
{
  "items": [
    {
      "logId": "log-001",
      "eventType": "swipe.created",
      "userId": "user-123",
      "eventData": {
        "swipeId": "swipe-001",
        "targetUserId": "user-456",
        "action": "like"
      },
      "timestamp": "2026-04-01T12:00:00Z"
    },
    {
      "logId": "log-002",
      "eventType": "message.sent",
      "userId": "user-123",
      "eventData": {
        "messageId": "msg-001",
        "matchId": "match-789"
      },
      "timestamp": "2026-04-01T11:55:00Z"
    }
  ],
  "count": 2
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | Not an admin |

---

## Kinesis Data Stream

**Stream:** `kismet-activity-stream`

Writes events as JSON records:

```json
{
  "logId": "log-001",
  "eventType": "swipe.created",
  "userId": "user-123",
  "eventData": { ... },
  "timestamp": "2026-04-01T12:00:00Z"
}
```

---

## DynamoDB Table

**Table:** `kismet-activity-log`

| Attribute | Type | Key |
|-----------|------|-----|
| `PK` | String (`USER#{userId}`) | Partition Key |
| `SK` | String (`EVENT#{timestamp}#{eventId}`) | Sort Key |
| `eventType` | String | — |
| `eventData` | Map | — |
| `logId` | String | — |
| `timestamp` | String (ISO 8601) | — |

---

## EventBridge Events

### Consumed: ALL events (catch-all subscriber)

Subscribes to all event types on the EventBridge bus. Logs every event to Kinesis.

Example event types consumed:
- `swipe.created`
- `match.created`
- `message.sent`
- `user.created`
- `content.flagged`
- `user.reported`
- (all other events)

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | EventBridge | Catch-all event subscription triggers Lambda |
| **Writes to** | Kinesis Data Streams | `kismet-activity-stream` |
| **Writes to** | DynamoDB | `kismet-activity-log` table |
| **Read by** | Analytics Pipeline Service | Reads from Kinesis stream |
| **Depends on** | Auth (Cognito) | JWT validation for admin GET endpoint |
