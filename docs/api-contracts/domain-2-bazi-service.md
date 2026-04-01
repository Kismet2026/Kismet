# BaZi Service — API Contract

**Owner:** Qinyuan
**Domain:** Discovery & Matching
**Base Path:** `/bazi`
**AWS Services:** Lambda (external API call)

---

## Endpoints

### POST /bazi/compatibility

计算两位用户的八字合婚评分和分析。

**Auth:** Required (JWT)

**Request:**

```json
{
  "userABirthDate": "1998-03-15",
  "userABirthTime": "14:30",
  "userBBirthDate": "1997-08-22",
  "userBBirthTime": "09:00"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `userABirthDate` | string (YYYY-MM-DD) | Yes | 用户 A 出生日期 |
| `userABirthTime` | string (HH:mm) | Yes | 用户 A 出生时辰 |
| `userBBirthDate` | string (YYYY-MM-DD) | Yes | 用户 B 出生日期 |
| `userBBirthTime` | string (HH:mm) | Yes | 用户 B 出生时辰 |

**Response (200):**

```json
{
  "compatibilityScore": 85,
  "analysis": "天作之合，五行互补，感情运势极佳。金水相生，木火通明，双方性格互补，婚姻和谐美满。",
  "userAElements": {
    "year": "土",
    "month": "木",
    "day": "金",
    "hour": "水"
  },
  "userBElements": {
    "year": "火",
    "month": "金",
    "day": "水",
    "hour": "土"
  }
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | 日期或时间格式不正确 |
| 401 | `UNAUTHORIZED` | 未登录 |
| 502 | `EXTERNAL_API_ERROR` | 外部八字 API 调用失败 |

---

### GET /bazi/profile/{userId}

获取指定用户的八字命盘（基于其出生数据）。

**Auth:** Required (JWT)

**Request:**

```
GET /bazi/profile/user-456
```

**Response (200):**

```json
{
  "userId": "user-456",
  "birthDate": "1998-03-15",
  "birthTime": "14:30",
  "baziChart": {
    "yearPillar": { "heavenlyStem": "戊", "earthlyBranch": "寅", "element": "土" },
    "monthPillar": { "heavenlyStem": "乙", "earthlyBranch": "卯", "element": "木" },
    "dayPillar": { "heavenlyStem": "庚", "earthlyBranch": "申", "element": "金" },
    "hourPillar": { "heavenlyStem": "癸", "earthlyBranch": "未", "element": "水" }
  },
  "fiveElements": {
    "metal": 2,
    "wood": 2,
    "water": 1,
    "fire": 0,
    "earth": 3
  },
  "summary": "日主庚金，生于卯月，土多金旺，缺火。性格刚毅果断，重情重义。"
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | 未登录 |
| 404 | `NOT_FOUND` | 用户不存在或未填写出生信息 |
| 502 | `EXTERNAL_API_ERROR` | 外部八字 API 调用失败 |

---

## Storage

无专属 DynamoDB 表（无状态服务，调用外部八字 API）。可选：使用 DynamoDB 缓存计算结果以提升性能。

**Optional Cache Table:** `kismet-bazi-cache`

| Attribute | Type | Key |
|-----------|------|-----|
| `PK` | String (`BAZI#{userId}` or `COMPAT#{userAId}#{userBId}`) | Partition Key |
| `result` | Map | — |
| `ttl` | Number (epoch) | — |

---

## EventBridge Events

无事件发布或消费。该服务为同步调用的无状态服务。

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | Recommendation Service | HTTP 同步调用获取合婚评分 |
| **Called by** | Frontend (React) | HTTP via API Gateway |
| **Depends on** | External BaZi API | HTTP 调用外部八字计算服务 |
| **Depends on** | Auth (Cognito) | JWT validation via API Gateway Authorizer |
