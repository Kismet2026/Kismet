# Match Service — API Contract

**Owner:** Hao
**Domain:** Discovery & Matching
**Base Path:** `/matches`
**AWS Services:** Lambda, DynamoDB Streams, SNS

---

## Endpoints

### GET /matches

获取当前用户的所有匹配列表（分页）。

**Auth:** Required (JWT)

**Request:**

```
GET /matches?limit=20&cursor=xxx
```

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `limit` | number | No | 20 | 每页数量 (max 50) |
| `cursor` | string | No | null | 分页游标 |

**Response (200):**

```json
{
  "items": [
    {
      "matchId": "match-001",
      "userId": "user-456",
      "displayName": "Alice",
      "avatarUrl": "https://cdn.kismet.com/avatars/user-456.jpg",
      "baziScore": 85,
      "matchedAt": "2026-04-01T12:00:00Z"
    },
    {
      "matchId": "match-002",
      "userId": "user-789",
      "displayName": "Bob",
      "avatarUrl": "https://cdn.kismet.com/avatars/user-789.jpg",
      "baziScore": 72,
      "matchedAt": "2026-03-30T08:30:00Z"
    }
  ],
  "nextCursor": "eyJ0aW1lc3Rhb...",
  "count": 2
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | 未登录 |

---

### GET /matches/{matchId}

获取匹配详情，包含双方用户资料和八字评分。

**Auth:** Required (JWT)

**Request:**

```
GET /matches/match-001
```

**Response (200):**

```json
{
  "matchId": "match-001",
  "userA": {
    "userId": "user-123",
    "displayName": "CurrentUser",
    "avatarUrl": "https://cdn.kismet.com/avatars/user-123.jpg",
    "age": 26,
    "bio": "Music lover"
  },
  "userB": {
    "userId": "user-456",
    "displayName": "Alice",
    "avatarUrl": "https://cdn.kismet.com/avatars/user-456.jpg",
    "age": 25,
    "bio": "Love hiking and coffee"
  },
  "baziScore": 85,
  "baziAnalysis": "天作之合，五行互补，感情运势极佳。",
  "matchedAt": "2026-04-01T12:00:00Z"
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | 未登录 |
| 403 | `FORBIDDEN` | 该匹配不属于当前用户 |
| 404 | `NOT_FOUND` | matchId 不存在 |

---

### DELETE /matches/{matchId}

取消匹配（解除配对）。

**Auth:** Required (JWT)

**Request:**

```
DELETE /matches/match-001
```

**Response (200):**

```json
{
  "matchId": "match-001",
  "status": "unmatched",
  "unmatchedAt": "2026-04-01T14:00:00Z"
}
```

**Side Effects:**
- 从 DynamoDB `kismet-matches` 表中标记匹配为已取消
- 发布 EventBridge 事件 `match.unmatched`

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | 未登录 |
| 403 | `FORBIDDEN` | 该匹配不属于当前用户 |
| 404 | `NOT_FOUND` | matchId 不存在 |

---

## DynamoDB Table

**Table:** `kismet-matches`

| Attribute | Type | Key |
|-----------|------|-----|
| `PK` | String (`MATCH#{matchId}`) | Partition Key |
| `SK` | String (`META`) | Sort Key |
| `matchId` | String | — |
| `userAId` | String | — |
| `userBId` | String | — |
| `baziScore` | Number | — |
| `status` | String | — |
| `matchedAt` | String (ISO 8601) | — |

**GSI:** `userId-index` — 按 userId 查询该用户的所有匹配

---

## EventBridge Events

### Consumed: `swipe.created`

监听 like 事件，检查是否双向 like，如果是则创建匹配。

```json
{
  "source": "kismet.swipe-service",
  "detail-type": "swipe.created",
  "detail": {
    "swipeId": "swipe-001",
    "userId": "user-123",
    "targetUserId": "user-456",
    "action": "like",
    "timestamp": "2026-04-01T12:00:00Z"
  }
}
```

**Triggered by:** DynamoDB Stream on `kismet-swipes` 或 EventBridge `swipe.created`

### Published: `match.created`

当双向 like 产生匹配时发布。

```json
{
  "source": "kismet.match-service",
  "detail-type": "match.created",
  "detail": {
    "matchId": "match-001",
    "userAId": "user-123",
    "userBId": "user-456",
    "baziScore": 85,
    "matchedAt": "2026-04-01T12:00:00Z"
  }
}
```

**Consumed by:** Notification Service, Chat Service

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | Frontend (React) | HTTP via API Gateway |
| **Consumes from** | Swipe Service | EventBridge `swipe.created` / DynamoDB Stream |
| **Publishes to** | Notification Service, Chat Service | EventBridge `match.created` |
| **Depends on** | Auth (Cognito) | JWT validation via API Gateway Authorizer |
