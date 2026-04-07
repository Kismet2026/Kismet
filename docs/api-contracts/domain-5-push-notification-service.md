# Push Notification Service — API Contract

**Owner:** Ni Li
**Domain:** Notifications & Engagement
**Base Path:** `/notifications`
**AWS Services:** SNS, Lambda

---

## Endpoints

### POST /notifications/register

Register a device for push notifications.

**Auth:** Required (JWT)

**Request:**

```json
{
  "deviceToken": "abc123def456...",
  "platform": "ios"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `deviceToken` | string | Yes | Device push token from OS |
| `platform` | string | Yes | `"ios"`, `"android"`, or `"web"` |

**Response (200):**

```json
{
  "deviceToken": "abc123def456...",
  "platform": "ios",
  "registeredAt": "2026-04-01T12:00:00Z"
}
```

**Side Effects:**
- Writes to DynamoDB `kismet-device-tokens` table
- Registers device endpoint with SNS Platform Application

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | Missing deviceToken or invalid platform value |
| 401 | `UNAUTHORIZED` | Not logged in |
| 409 | `CONFLICT` | Device token already registered for this user |

---

### GET /notifications

List current user's recent notifications (paginated).

**Auth:** Required (JWT)

**Request:**

```
GET /notifications?limit=20&cursor=xxx
```

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `limit` | number | No | 20 | Items per page (max 50) |
| `cursor` | string | No | null | Pagination cursor |

**Response (200):**

```json
{
  "items": [
    {
      "notificationId": "notif-001",
      "type": "match",
      "title": "You have a new match!",
      "body": "You matched with someone new.",
      "read": false,
      "timestamp": "2026-04-01T12:00:00Z"
    },
    {
      "notificationId": "notif-002",
      "type": "message",
      "title": "New message from Alex",
      "body": "Hey! How are you?",
      "read": true,
      "timestamp": "2026-04-01T11:55:00Z"
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

---

### PUT /notifications/{notificationId}/read

Mark a notification as read.

**Auth:** Required (JWT)

**Request:**

```
PUT /notifications/notif-001/read
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `notificationId` | string (path) | Yes | The notification ID to mark as read |

**Response (200):**

```json
{
  "notificationId": "notif-001",
  "read": true,
  "updatedAt": "2026-04-01T12:05:00Z"
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 404 | `NOT_FOUND` | Notification does not exist or does not belong to user |

---

### GET /notifications/unread-count

Get the count of unread notifications for the current user.

**Auth:** Required (JWT)

**Request:**

```
GET /notifications/unread-count
```

**Response (200):**

```json
{
  "unreadCount": 5
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |

---

## DynamoDB Tables

### Table: `kismet-notifications`

| Attribute | Type | Key |
|-----------|------|-----|
| `PK` | String (`USER#{userId}`) | Partition Key |
| `SK` | String (`NOTIF#{epoch_ms}-{uuid8}`) | Sort Key |
| `notificationId` | String | — |
| `type` | String | — |
| `title` | String | — |
| `body` | String | — |
| `read` | Boolean | — |
| `timestamp` | String (ISO 8601) | — |

### Table: `kismet-device-tokens`

| Attribute | Type | Key |
|-----------|------|-----|
| `PK` | String (`USER#{userId}`) | Partition Key |
| `SK` | String (`DEVICE#{deviceToken}`) | Sort Key |
| `platform` | String | — |
| `snsEndpointArn` | String | — |
| `registeredAt` | String (ISO 8601) | — |

---

## EventBridge Events

### Consumed: `match.created`

Triggers a push notification: "You have a new match!"

```json
{
  "source": "kismet.match-service",
  "detail-type": "match.created",
  "detail": {
    "matchId": "match-001",
    "userIds": ["user-123", "user-456"],
    "timestamp": "2026-04-01T12:00:00Z"
  }
}
```

### Consumed: `message.sent`

Triggers a push notification: "New message from {senderName}"

```json
{
  "source": "kismet.message-service",
  "detail-type": "message.sent",
  "detail": {
    "messageId": "msg-001",
    "matchId": "match-789",
    "senderId": "user-123",
    "recipientId": "user-456",
    "content": "Hey! Nice to meet you",
    "messageType": "text",
    "timestamp": "2026-04-01T12:00:00Z"
  }
}
```

---

## SNS Configuration

- SNS Platform Application for APNs (iOS)
- SNS Platform Application for FCM (Android)
- SNS Platform Application for Web Push
- Each device registration creates an SNS platform endpoint for push delivery

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | Frontend (React) | HTTP via API Gateway |
| **Consumes from** | Match Service | EventBridge `match.created` |
| **Consumes from** | Message Service | EventBridge `message.sent` |
| **Depends on** | Auth (Cognito) | JWT validation via API Gateway Authorizer |
| **Uses** | SNS | Push notification delivery |
