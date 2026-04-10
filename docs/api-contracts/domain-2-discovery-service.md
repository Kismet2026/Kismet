# Discovery Service — API Contract

**Owner:** Qinyuan
**Domain:** Discovery & Matching
**Base Path:** `/discovery`
**AWS Services:** Lambda, DynamoDB, External BaZi API

---

## Endpoints

### GET /discovery

获取候选用户列表（经过筛选和分页）。每个候选人包含基本资料和八字兼容评分。
自动过滤已 swipe 过的用户。

**Auth:** Required (JWT)

**Request:**

```
GET /discovery?age_min=20&age_max=30&gender=female&limit=20&cursor=xxx
```

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `age_min` | number | No | 0 | 最小年龄筛选 |
| `age_max` | number | No | 200 | 最大年龄筛选 |
| `gender` | string | No | null | 性别筛选：`"male"`, `"female"`, `"non-binary"` |
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
      "location": [42.36, -71.06],
      "city": "Boston",
      "avatarUrl": "https://cdn.kismet.com/avatars/user-456.jpg",
      "bio": "Love hiking and coffee",
      "baziScore": 92
    },
    {
      "userId": "user-789",
      "displayName": "Bob",
      "age": 28,
      "gender": "male",
      "location": [40.71, -74.01],
      "city": "New York",
      "avatarUrl": "https://cdn.kismet.com/avatars/user-789.jpg",
      "bio": "Software engineer, dog lover",
      "baziScore": null
    }
  ],
  "nextCursor": "eyJ0aW1lc3Rhb...",
  "count": 2
}
```

**`baziScore` 说明：**
- `92` — 八字兼容评分（0–100，来自外部八字 API）
- `null` — 候选人生日不在 top 200 最佳匹配中，或用户/候选人缺少出生日期

**过滤逻辑：**
1. 排除自己
2. 排除已 swipe 过的用户（查 `kismet-swipes` 表）
3. 按 age_min/age_max 过滤
4. 按 gender 过滤

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | 未登录 |

---

## DynamoDB Table

**Table:** `kismet-discovery` (single-table design)

| PK Pattern | SK | Purpose |
|---|---|---|
| `PROFILE#{userId}` | `META` | 候选人资料（从 profile.completed 事件索引） |
| `BAZI#{birthDate}` | `SCORES` | 八字评分缓存（永久，按生日去重） |

**Profile record fields:**

| Field | Type | Description |
|-------|------|-------------|
| `userId` | String | 用户 ID |
| `displayName` | String | 显示名 |
| `gender` | String | 性别 |
| `preferredGender` | String | 偏好匹配性别 |
| `age` | Number | 从 birthDate 计算 |
| `birthDate` | String | YYYY-MM-DD |
| `location` | List [lat, lng] | 坐标 |
| `city` | String | 城市 |
| `avatarUrl` | String | 头像 URL |
| `bio` | String | 自我介绍 |

**BaZi cache record:**

| Field | Type | Description |
|-------|------|-------------|
| `birthDate` | String | YYYY-MM-DD |
| `scores` | Map {date: score} | 最佳匹配日期 → 分数（最多 200 条） |
| `cachedAt` | String | 缓存时间 |

---

## EventBridge Events

### Consumed: `profile.completed`

新用户完成资料后触发。Discovery 做两件事：
1. 将用户索引为候选人（`PROFILE#{userId}`）
2. 预热八字缓存（`BAZI#{birthDate}`，如未缓存则调外部 API）

```json
{
  "source": "kismet.profile-service",
  "detail-type": "profile.completed",
  "detail": {
    "userId": "user-456",
    "name": "Alice",
    "gender": "female",
    "preferred_gender": "male",
    "birthDate": "1999-05-15",
    "birthTime": "14:30",
    "location_coordinates": [42.36, -71.06],
    "city": "Boston",
    "avatarUrl": "https://photos.example.com/alice.jpg",
    "createdAt": "2026-04-01T12:00:00Z"
  }
}
```

**注意：** `age` 由 Discovery 从 `birthDate` 计算，事件中不需要传 age 字段。

---

## BaZi Score Caching Strategy

```
注册时：profile.completed → 索引 profile + _ensure_bazi_cache(birthDate)
  → cache miss → 调外部 API → 写入 BAZI#{birthDate} | SCORES
  → cache hit  → 跳过（同生日的人共享缓存）

查询时：GET /discovery → 读 BAZI#{userBirthDate} | SCORES
  → cache hit  → 直接用（零外部调用）
  → cache miss → 调外部 API → 写入缓存 → 返回
```

- 缓存按 birthDate 去重，不按 userId — 同生日用户共享一条缓存
- 缓存永不过期（生日不变，八字算法不变）
- 外部 API 故障时，baziScore 返回 null，不影响发现功能

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | Frontend (React) | HTTP via API Gateway |
| **Reads from** | `kismet-swipes` table | DynamoDB Query — 过滤已 swipe 用户 |
| **Depends on** | External BaZi API | HTTP POST — 获取八字评分（有缓存） |
| **Depends on** | Auth (Cognito) | JWT validation via API Gateway Authorizer |
| **Consumes from** | Profile Service (D1) | EventBridge `profile.completed` |
