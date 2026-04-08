# Discovery Service — API Contract

**Owner:** Qinyuan
**Domain:** Discovery & Matching
**Base Path:** `/discovery`
**AWS Services:** Lambda, DynamoDB

---

## Endpoints

### GET /discovery

获取候选用户列表（经过筛选和分页）。每个候选人包含基本资料和八字评分（如有）。

**Auth:** Required (JWT)

**Request:**

```
GET /discovery?age_min=20&age_max=30&gender=female&location=Boston&limit=20&cursor=xxx
```

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `age_min` | number | No | null | 最小年龄筛选 |
| `age_max` | number | No | null | 最大年龄筛选 |
| `gender` | string | No | null | 性别筛选：`"male"`, `"female"`, `"other"` |
| `location` | string | No | null | 地点筛选 |
| `limit` | number | No | 20 | 每页数量 (max 50) |
| `cursor` | string | No | null | 分页游标 |

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
      "bio": "Love hiking and coffee",
      "baziScore": 85
    },
    {
      "userId": "user-789",
      "displayName": "Bob",
      "age": 28,
      "gender": "male",
      "location": "Boston",
      "avatarUrl": "https://cdn.kismet.com/avatars/user-789.jpg",
      "bio": "Software engineer, dog lover",
      "baziScore": null
    }
  ],
  "nextCursor": "eyJ0aW1lc3Rhb...",
  "count": 2
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | 参数格式不正确（如 age_min > age_max） |
| 401 | `UNAUTHORIZED` | 未登录 |

---

## DynamoDB Table

**Table:** `kismet-discovery`

| Attribute | Type | Key |
|-----------|------|-----|
| `PK` | String (`USER#{userId}`) | Partition Key |
| `SK` | String (`CANDIDATE#{score}`) | Sort Key |
| `candidateUserId` | String | — |
| `displayName` | String | — |
| `age` | Number | — |
| `gender` | String | — |
| `location` | String | — |
| `avatarUrl` | String | — |
| `baziScore` | Number | — |
| `cachedAt` | String (ISO 8601) | — |

---

## EventBridge Events

### Consumed: `profile.completed`

当新用户完成资料填写后，将其索引到候选人列表中。

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

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | Frontend (React) | HTTP via API Gateway |
| **Depends on** | Profile Service | HTTP 调用获取完整用户资料 |
| **Depends on** | Recommendation Service | HTTP 调用获取评分排序 |
| **Depends on** | Auth (Cognito) | JWT validation via API Gateway Authorizer |
| **Consumes from** | Profile Service | EventBridge `profile.completed` |
