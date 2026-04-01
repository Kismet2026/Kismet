# Recommendation Service — API Contract

**Owner:** Qinyuan
**Domain:** Discovery & Matching
**Base Path:** `/recommend`
**AWS Services:** Lambda, DynamoDB

---

## Endpoints

### GET /recommend

获取当前用户的推荐候选人列表（已评分和排序）。

**Auth:** Required (JWT)

**Request:**

```
GET /recommend?limit=20
```

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `limit` | number | No | 20 | 返回数量 (max 50) |

**Response (200):**

```json
{
  "items": [
    {
      "userId": "user-456",
      "displayName": "Alice",
      "age": 25,
      "gender": "female",
      "location": "Boston",
      "avatarUrl": "https://cdn.kismet.com/avatars/user-456.jpg",
      "score": 92,
      "scoreBreakdown": {
        "locationProximity": 25,
        "sharedInterests": 20,
        "baziCompatibility": 35,
        "activityRecency": 12
      }
    },
    {
      "userId": "user-789",
      "displayName": "Bob",
      "age": 28,
      "gender": "male",
      "location": "Cambridge",
      "avatarUrl": "https://cdn.kismet.com/avatars/user-789.jpg",
      "score": 78,
      "scoreBreakdown": {
        "locationProximity": 22,
        "sharedInterests": 15,
        "baziCompatibility": 28,
        "activityRecency": 13
      }
    }
  ],
  "count": 2
}
```

**Scoring Factors:**
- `locationProximity` — 地理位置接近程度
- `sharedInterests` — 共同兴趣匹配度
- `baziCompatibility` — 八字合婚评分
- `activityRecency` — 用户活跃度

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | 未登录 |

---

### POST /recommend/refresh

强制重新计算当前用户的推荐列表。

**Auth:** Required (JWT)

**Request:**

```
POST /recommend/refresh
```

（无请求体）

**Response (200):**

```json
{
  "status": "refreshed",
  "candidateCount": 45,
  "refreshedAt": "2026-04-01T12:00:00Z"
}
```

**Side Effects:**
- 重新调用 BaZi Service 和 Profile Service 计算评分
- 更新 DynamoDB `kismet-recommendations` 表中的缓存

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | 未登录 |
| 429 | `TOO_MANY_REQUESTS` | 刷新频率过高（限制每 5 分钟一次） |

---

## DynamoDB Table

**Table:** `kismet-recommendations`

| Attribute | Type | Key |
|-----------|------|-----|
| `PK` | String (`USER#{userId}`) | Partition Key |
| `SK` | String (`SCORE#{score}#{candidateId}`) | Sort Key |
| `candidateUserId` | String | — |
| `score` | Number | — |
| `scoreBreakdown` | Map | — |
| `calculatedAt` | String (ISO 8601) | — |

---

## EventBridge Events

### Consumed: `profile.completed`

新用户完成资料后，将其加入推荐池并为现有用户重新计算推荐。

```json
{
  "source": "kismet.profile-service",
  "detail-type": "profile.completed",
  "detail": {
    "userId": "user-456",
    "displayName": "Alice",
    "age": 25,
    "gender": "female",
    "location": "Boston"
  }
}
```

### Consumed: `swipe.created`

用户划动后更新推荐列表（移除已划过的候选人，调整排序）。

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

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | Discovery Service | HTTP 调用获取评分排序 |
| **Called by** | Frontend (React) | HTTP via API Gateway |
| **Depends on** | BaZi Service | HTTP 调用获取八字合婚评分 |
| **Depends on** | Profile Service | HTTP 调用获取用户资料 |
| **Depends on** | Auth (Cognito) | JWT validation via API Gateway Authorizer |
| **Consumes from** | Profile Service | EventBridge `profile.completed` |
| **Consumes from** | Swipe Service | EventBridge `swipe.created` |
