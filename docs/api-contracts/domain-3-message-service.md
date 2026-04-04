# Message Service — API Contract

**Owner:** Parker
**Domain:** Messaging
**Base Path:** `/messages`
**AWS Services:** Lambda, DynamoDB

---

## Endpoints

### POST /messages

Persist a new message in a conversation.

**Auth:** Required (JWT) — validates sender is a participant of the match.

**Request:**

```json
{
  "matchId": "match-123",
  "content": "Hey, nice to meet you!",
  "messageType": "text"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `matchId` | string | Yes | The match/conversation ID |
| `content` | string | Yes | Message content |
| `messageType` | string | Yes | `"text"` |

**Response (200):**

```json
{
  "messageId": "msg-001",
  "matchId": "match-123",
  "senderId": "user-123",
  "content": "Hey, nice to meet you!",
  "messageType": "text",
  "timestamp": "2026-04-01T12:00:00Z"
}
```

**Side Effects:**
- Writes to DynamoDB `kismet-messages` table
- Publishes EventBridge event `message.sent`

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | content is empty or messageType is invalid |
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | Sender is not a participant of this match |
| 404 | `NOT_FOUND` | matchId does not exist |

---

### GET /messages/{matchId}

Get conversation history, paginated, newest first.

**Auth:** Required (JWT)

**Request:**

```
GET /messages/{matchId}?limit=50&cursor=xxx
```

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `matchId` | string (path) | Yes | — | The match/conversation ID |
| `limit` | number | No | 50 | Messages per page (max 50) |
| `cursor` | string | No | null | Pagination cursor for next page |

**Response (200):**

```json
{
  "items": [
    {
      "messageId": "msg-002",
      "matchId": "match-123",
      "senderId": "user-456",
      "content": "Hi! How are you?",
      "messageType": "text",
      "timestamp": "2026-04-01T12:01:00Z"
    },
    {
      "messageId": "msg-001",
      "matchId": "match-123",
      "senderId": "user-123",
      "content": "Hey, nice to meet you!",
      "messageType": "text",
      "timestamp": "2026-04-01T12:00:00Z"
    }
  ],
  "nextCursor": "eyJ0aW1lc3Rhb...",
  "count": 2
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | User is not a participant of this match |
| 404 | `NOT_FOUND` | matchId does not exist |

---

### GET /messages/{matchId}/since/{timestamp}

Get all messages after a given timestamp. Used by the polling approach in Chat Gateway.

**Auth:** Required (JWT)

**Request:**

```
GET /messages/match-123/since/2026-04-01T12:00:00Z
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `matchId` | string (path) | Yes | The match/conversation ID |
| `timestamp` | string (path, ISO 8601) | Yes | Return messages after this time |

**Response (200):**

```json
{
  "items": [
    {
      "messageId": "msg-002",
      "matchId": "match-123",
      "senderId": "user-456",
      "content": "Hi! How are you?",
      "messageType": "text",
      "timestamp": "2026-04-01T12:01:00Z"
    }
  ],
  "count": 1
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | timestamp is not valid ISO 8601 |
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | User is not a participant of this match |
| 404 | `NOT_FOUND` | matchId does not exist |

---

### DELETE /messages/{messageId}

Soft delete a message. The message is marked as deleted but not removed from the database.

**Auth:** Required (JWT) — only the sender can delete their own message.

**Request:**

```
DELETE /messages/msg-001
```

**Response (200):**

```json
{
  "messageId": "msg-001",
  "deleted": true,
  "deletedAt": "2026-04-01T13:00:00Z"
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | User is not the sender of this message |
| 404 | `NOT_FOUND` | messageId does not exist |

---

## DynamoDB Table

**Table:** `kismet-messages`

| Attribute | Type | Key |
|-----------|------|-----|
| `CONV#{matchId}` | String | Partition Key |
| `MSG#{timestamp}#{messageId}` | String | Sort Key |
| `messageId` | String | — |
| `senderId` | String | — |
| `content` | String | — |
| `messageType` | String | — |
| `timestamp` | String (ISO 8601) | — |
| `deleted` | Boolean | — |
| `deletedAt` | String (ISO 8601) | — |

---

## EventBridge Events

### Published: `message.sent`

Published when a new message is persisted.

```json
{
  "source": "kismet.message-service",
  "detail-type": "message.sent",
  "detail": {
    "messageId": "msg-001",
    "matchId": "match-123",
    "senderId": "user-123",
    "recipientId": "user-456",
    "content": "Hey, nice to meet you!",
    "messageType": "text",
    "timestamp": "2026-04-01T12:00:00Z"
  }
}
```

**Consumed by:** Text Moderation, Activity Logger

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | Chat Gateway | Internal invocation |
| **Publishes to** | Notification Service, Activity Logger | EventBridge `message.sent` |
| **Depends on** | Auth (Cognito) | JWT validation via API Gateway Authorizer |
