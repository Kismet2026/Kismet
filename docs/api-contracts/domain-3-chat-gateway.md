# Chat Gateway — API Contract

**Owner:** Parker
**Domain:** Messaging
**Base Path:** `/chat`
**AWS Services:** API Gateway, Lambda

---

## Approach

This service supports **two approaches** for real-time chat. HTTP Polling is the primary approach; WebSocket is an optional upgrade if the team has capacity.

---

## Primary: HTTP Polling Endpoints

### POST /chat/{matchId}/send

Send a message in a conversation.

**Auth:** Required (JWT)

**Request:**

```json
{
  "content": "Hey, nice to meet you!",
  "messageType": "text"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `matchId` | string (path) | Yes | The match/conversation ID |
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
- Delegates persistence to Message Service
- Message Service publishes EventBridge event `message.sent`

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | content is empty or messageType is invalid |
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | User is not a participant of this match |
| 404 | `NOT_FOUND` | matchId does not exist |

---

### GET /chat/{matchId}/messages

Poll for new messages since a given timestamp. Frontend should call this on an interval (e.g., every 3-5 seconds).

**Auth:** Required (JWT)

**Request:**

```
GET /chat/{matchId}/messages?since=2026-04-01T12:00:00Z&limit=50
```

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `matchId` | string (path) | Yes | — | The match/conversation ID |
| `since` | string (ISO 8601) | No | null | Only return messages after this timestamp |
| `limit` | number | No | 50 | Max messages to return (max 50) |

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
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | User is not a participant of this match |
| 404 | `NOT_FOUND` | matchId does not exist |

---

### GET /chat/{matchId}/status

Get conversation status including unread count and last message preview.

**Auth:** Required (JWT)

**Request:**

```
GET /chat/{matchId}/status
```

**Response (200):**

```json
{
  "matchId": "match-123",
  "unreadCount": 3,
  "lastMessage": {
    "messageId": "msg-002",
    "senderId": "user-456",
    "content": "Hi! How are you?",
    "timestamp": "2026-04-01T12:01:00Z"
  }
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | User is not a participant of this match |
| 404 | `NOT_FOUND` | matchId does not exist |

---

## Optional Upgrade: WebSocket

If the team has capacity, WebSocket can replace polling for lower latency.

### WSS Connection

**Auth:** Required (JWT passed as query param `token`)

```
wss://api.kismet.com/chat?matchId=match-123&token=<jwt>
```

**$connect route:**
- Validates JWT
- Stores connection in DynamoDB `kismet-connections`
- Associates connection with matchId and userId

**sendMessage action:**

```json
{
  "action": "sendMessage",
  "matchId": "match-123",
  "content": "Hello!",
  "messageType": "text"
}
```

Routes to Message Service for persistence, then broadcasts to other participant's connection.

**$disconnect route:**
- Removes connection from `kismet-connections`
- Cleans up presence state

### Connection DynamoDB Table

**Table:** `kismet-connections`

| Attribute | Type | Key |
|-----------|------|-----|
| `CONN#{connectionId}` | String | Partition Key |
| `META` | String | Sort Key |
| `userId` | String | — |
| `matchId` | String | — |
| `connectedAt` | String (ISO 8601) | — |

**GSI:** `match-index` — query all connections for a given matchId

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | Frontend (React) | HTTP via API Gateway (polling) or WebSocket |
| **Delegates to** | Message Service | Internal invocation for message persistence |
| **Depends on** | Auth (Cognito) | JWT validation via API Gateway Authorizer |
