# Presence Service — API Contract

**Owner:** QX
**Domain:** Messaging
**Base Path:** `/presence`
**AWS Services:** Lambda, DynamoDB (with TTL)

---

## Endpoints

### POST /presence/heartbeat

Update the current user's online status. The frontend should call this every 30 seconds to keep the user marked as "online". If no heartbeat is received within 60 seconds, the DynamoDB TTL automatically expires the record and the user appears offline.

**Auth:** Required (JWT)

**Request:**

```
POST /presence/heartbeat
```

No request body required. The userId is extracted from the JWT.

**Response (200):**

```json
{
  "userId": "user-123",
  "status": "online",
  "expiresAt": "2026-04-01T12:01:00Z"
}
```

**Side Effects:**
- Upserts record in DynamoDB `kismet-presence` with TTL set to now + 60s

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |

---

### GET /presence/{userId}

Get a user's presence status.

**Auth:** Required (JWT)

**Request:**

```
GET /presence/user-456
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `userId` | string (path) | Yes | The user to check presence for |

**Response (200):**

```json
{
  "userId": "user-456",
  "status": "online",
  "lastSeen": "2026-04-01T12:00:30Z"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"online"` or `"offline"` |
| `lastSeen` | string (ISO 8601) | Last heartbeat timestamp. Present for both online and offline users. |

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 404 | `NOT_FOUND` | userId does not exist |

---

### POST /presence/{matchId}/typing

Signal that the current user is typing in a conversation. The typing indicator auto-expires after 5 seconds via DynamoDB TTL.

**Auth:** Required (JWT)

**Request:**

```
POST /presence/match-123/typing
```

No request body required. The userId is extracted from the JWT.

**Response (200):**

```json
{
  "matchId": "match-123",
  "userId": "user-123",
  "typing": true,
  "expiresAt": "2026-04-01T12:00:05Z"
}
```

**Side Effects:**
- Upserts record in DynamoDB `kismet-typing` with TTL set to now + 5s

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | User is not a participant of this match |

---

### GET /presence/{matchId}/typing

Check if the other user in a conversation is currently typing.

**Auth:** Required (JWT)

**Request:**

```
GET /presence/match-123/typing
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `matchId` | string (path) | Yes | The match/conversation ID |

**Response (200):**

```json
{
  "matchId": "match-123",
  "typingUsers": [
    {
      "userId": "user-456",
      "since": "2026-04-01T12:00:02Z"
    }
  ]
}
```

If no one is typing, `typingUsers` is an empty array.

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | User is not a participant of this match |

---

## DynamoDB Tables

### Table: `kismet-presence`

| Attribute | Type | Key |
|-----------|------|-----|
| `USER#{userId}` | String | Partition Key |
| `STATUS` | String | Sort Key |
| `status` | String | — |
| `lastSeen` | String (ISO 8601) | — |
| `ttl` | Number (Unix epoch) | — (TTL attribute, auto-expires after 60s) |

### Table: `kismet-typing`

| Attribute | Type | Key |
|-----------|------|-----|
| `MATCH#{matchId}#USER#{userId}` | String | Partition Key |
| `TYPING` | String | Sort Key |
| `since` | String (ISO 8601) | — |
| `ttl` | Number (Unix epoch) | — (TTL attribute, auto-expires after 5s) |

---

## EventBridge Events

No events published. This service is called directly by the frontend.

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | Frontend (React) | HTTP via API Gateway |
| **Depends on** | Auth (Cognito) | JWT validation via API Gateway Authorizer |
