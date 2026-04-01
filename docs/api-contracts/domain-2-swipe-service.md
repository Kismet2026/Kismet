# Swipe Service — API Contract

**Owner:** Hao
**Domain:** Discovery & Matching
**Base Path:** `/swipe`
**AWS Services:** Lambda, DynamoDB

---

## Endpoints

### POST /swipe

记录用户的 like 或 pass 操作。

**Auth:** Required (JWT)

**Request:**

```json
{
  "targetUserId": "user-456",
  "action": "like"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `targetUserId` | string | Yes | 被划的用户 ID |
| `action` | string | Yes | `"like"` 或 `"pass"` |

**Response (200):**

```json
{
  "swipeId": "swipe-001",
  "action": "like",
  "targetUserId": "user-456",
  "timestamp": "2026-04-01T12:00:00Z"
}
```

**Side Effects:**
- 写入 DynamoDB `kismet-swipes` 表
- 发布 EventBridge 事件 `swipe.created`（仅 action = like 时）

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | action 不是 like/pass，或 targetUserId 缺失 |
| 401 | `UNAUTHORIZED` | 未登录 |
| 409 | `CONFLICT` | 已经对该用户操作过 |

---

### GET /swipe/history

获取当前用户的划动历史。

**Auth:** Required (JWT)

**Request:**

```
GET /swipe/history?action=like&limit=20&cursor=xxx
```

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `action` | string | No | all | 过滤：`"like"` 或 `"pass"` |
| `limit` | number | No | 20 | 每页数量 (max 50) |
| `cursor` | string | No | null | 分页游标 |

**Response (200):**

```json
{
  "items": [
    {
      "swipeId": "swipe-001",
      "targetUserId": "user-456",
      "action": "like",
      "timestamp": "2026-04-01T12:00:00Z"
    },
    {
      "swipeId": "swipe-002",
      "targetUserId": "user-789",
      "action": "pass",
      "timestamp": "2026-04-01T11:55:00Z"
    }
  ],
  "nextCursor": "eyJ0aW1lc3Rhb...",
  "count": 2
}
```

---

## DynamoDB Table

**Table:** `kismet-swipes`

| Attribute | Type | Key |
|-----------|------|-----|
| `userId` | String | Partition Key |
| `targetUserId` | String | Sort Key |
| `action` | String | — |
| `swipeId` | String | — |
| `timestamp` | String (ISO 8601) | — |

**GSI:** `action-index` — 按 action 过滤查询

---

## EventBridge Events

### Published: `swipe.created`

仅当 action = `"like"` 时发布。

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

**Consumed by:** Match Service, Activity Logger

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | Frontend (React) | HTTP via API Gateway |
| **Publishes to** | Match Service, Activity Logger | EventBridge `swipe.created` |
| **Depends on** | Auth (Cognito) | JWT validation via API Gateway Authorizer |
