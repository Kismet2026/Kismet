# Admin Dashboard Service — API Contract

**Owner:** Lingyun
**Domain:** Analytics & Admin
**Base Path:** `/admin`
**AWS Services:** Lambda, DynamoDB

---

## Endpoints

### GET /admin/stats

Platform overview with aggregated statistics.

**Auth:** Required (JWT, admin role)

**Request:**

```
GET /admin/stats
```

**Response (200):**

```json
{
  "totalUsers": 8500,
  "activeUsers": 1250,
  "matchesToday": 234,
  "messagesToday": 892,
  "flaggedContentCount": 15,
  "generatedAt": "2026-04-01T12:00:00Z"
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | Not an admin |

---

### GET /admin/flagged-content

List flagged content from moderation.

**Auth:** Required (JWT, admin role)

**Request:**

```
GET /admin/flagged-content?type=text&limit=20&cursor=xxx
```

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | string | No | all | Filter: `"text"` or `"image"` |
| `limit` | number | No | 20 | Number of items to return (max 50) |
| `cursor` | string | No | null | Pagination cursor |

**Response (200):**

```json
{
  "items": [
    {
      "contentId": "flag-001",
      "type": "text",
      "content": "Inappropriate message content...",
      "userId": "user-456",
      "reason": "hate_speech",
      "confidence": 0.92,
      "flaggedAt": "2026-04-01T11:30:00Z",
      "status": "pending"
    },
    {
      "contentId": "flag-002",
      "type": "image",
      "imageUrl": "https://cdn.kismet.com/photos/flagged/img-002.jpg",
      "userId": "user-789",
      "reason": "explicit_content",
      "confidence": 0.88,
      "flaggedAt": "2026-04-01T11:25:00Z",
      "status": "pending"
    }
  ],
  "nextCursor": "eyJjb250ZW50SWQ...",
  "count": 2
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | Invalid type parameter |
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | Not an admin |

---

### PUT /admin/flagged-content/{contentId}/resolve

Resolve a flagged content item.

**Auth:** Required (JWT, admin role)

**Request:**

```json
{
  "action": "remove"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `action` | string | Yes | `"approve"`, `"remove"`, or `"ban_user"` |

**Response (200):**

```json
{
  "contentId": "flag-001",
  "action": "remove",
  "resolvedBy": "admin-001",
  "resolvedAt": "2026-04-01T12:05:00Z",
  "status": "resolved"
}
```

**Side Effects:**
- Updates flagged content status in DynamoDB
- If action is `"remove"`: deletes the content from the originating service
- If action is `"ban_user"`: bans the user who posted the content

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | Invalid action value |
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | Not an admin |
| 404 | `NOT_FOUND` | Content ID not found |

---

### GET /admin/users

Search and list users.

**Auth:** Required (JWT, admin role)

**Request:**

```
GET /admin/users?search=john&limit=20&cursor=xxx
```

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `search` | string | No | null | Search by name or email |
| `limit` | number | No | 20 | Number of users to return (max 50) |
| `cursor` | string | No | null | Pagination cursor |

**Response (200):**

```json
{
  "items": [
    {
      "userId": "user-123",
      "displayName": "John Doe",
      "email": "john@example.com",
      "status": "active",
      "createdAt": "2026-03-15T10:00:00Z",
      "reportCount": 0
    },
    {
      "userId": "user-456",
      "displayName": "Johnny Smith",
      "email": "johnny@example.com",
      "status": "banned",
      "createdAt": "2026-03-20T14:00:00Z",
      "reportCount": 5
    }
  ],
  "nextCursor": "eyJ1c2VySWQ...",
  "count": 2
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | Not an admin |

---

### PUT /admin/users/{userId}/ban

Ban a user.

**Auth:** Required (JWT, admin role)

**Request:**

```
PUT /admin/users/user-456/ban
```

**Response (200):**

```json
{
  "userId": "user-456",
  "status": "banned",
  "bannedBy": "admin-001",
  "bannedAt": "2026-04-01T12:10:00Z"
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | Not an admin |
| 404 | `NOT_FOUND` | User not found |
| 409 | `CONFLICT` | User is already banned |

---

### PUT /admin/users/{userId}/unban

Unban a user.

**Auth:** Required (JWT, admin role)

**Request:**

```
PUT /admin/users/user-456/unban
```

**Response (200):**

```json
{
  "userId": "user-456",
  "status": "active",
  "unbannedBy": "admin-001",
  "unbannedAt": "2026-04-01T12:15:00Z"
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | Not an admin |
| 404 | `NOT_FOUND` | User not found |
| 409 | `CONFLICT` | User is not banned |

---

## DynamoDB Tables

### Table: `kismet-admin-stats`

| Attribute | Type | Key |
|-----------|------|-----|
| `PK` | String (`STAT#{type}`) | Partition Key |
| `SK` | String (`DATE#{date}`) | Sort Key |
| `value` | Number | — |
| `updatedAt` | String (ISO 8601) | — |

### Table: `kismet-flagged-content`

| Attribute | Type | Key |
|-----------|------|-----|
| `PK` | String (`CONTENT#{contentId}`) | Partition Key |
| `SK` | String (`META`) | Sort Key |
| `type` | String | — |
| `content` | String | — |
| `userId` | String | — |
| `reason` | String | — |
| `confidence` | Number | — |
| `status` | String | — |
| `flaggedAt` | String (ISO 8601) | — |
| `resolvedAt` | String (ISO 8601) | — |
| `resolvedBy` | String | — |

---

## EventBridge Events

### Consumed: `content.flagged`

Adds flagged content to the flagged content queue in DynamoDB.

```json
{
  "source": "kismet.moderation",
  "detail-type": "content.flagged",
  "detail": {
    "contentId": "msg-001",
    "contentType": "text",
    "userId": "user-456",
    "reason": "toxicity_detected",
    "score": 0.92,
    "timestamp": "2026-04-01T11:30:00Z"
  }
}
```

### Consumed: `user.reported`

Increments the report count for the reported user.

```json
{
  "source": "kismet.report-service",
  "detail-type": "user.reported",
  "detail": {
    "reportId": "report-001",
    "reportedUserId": "user-456",
    "reporterId": "user-123",
    "reason": "harassment",
    "timestamp": "2026-04-01T11:35:00Z"
  }
}
```

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | Admin Dashboard (React) | HTTP via API Gateway |
| **Consumes from** | Text/Image Moderation Service | EventBridge `content.flagged` |
| **Consumes from** | Report Service | EventBridge `user.reported` |
| **Depends on** | Auth (Cognito) | JWT validation via API Gateway Authorizer (admin role check) |
