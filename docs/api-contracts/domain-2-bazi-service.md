# BaZi Service — API Contract

**Owner:** Qinyuan
**Domain:** Discovery & Matching
**Base Path:** `/bazi`
**AWS Services:** Lambda (proxies to external BaZi API)

---

## Endpoints

### POST /bazi/top-matches

给定一个出生日期，返回八字最佳匹配的日期列表（按分数降序）。调用外部八字 API。

**Auth:** Required (JWT)

**Request:**

```json
{
  "birthDate": "1995-11-21",
  "limit": 50
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `birthDate` | string (YYYY-MM-DD) | Yes | 用户出生日期 |
| `limit` | number | No | 返回数量上限（默认 50，最大 200） |

**Response (200):**

```json
{
  "birthDate": "1995-11-21",
  "matches": [
    { "ranking": 1, "birthdate": "1991-06-20", "score": 99 },
    { "ranking": 2, "birthdate": "1998-07-13", "score": 99 },
    { "ranking": 3, "birthdate": "1999-05-09", "score": 99 }
  ],
  "hasMore": true
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | 缺少 birthDate 字段 |
| 401 | `UNAUTHORIZED` | 未登录 |
| 502 | `UPSTREAM_ERROR` | 外部八字 API 调用失败 |

---

## Planned Endpoints

### POST /bazi/compatibility (待外部 API 支持)

1v1 配对评分——传两个生日，返回兼容性分数。等外部 API 加入 1v1 endpoint 后实现。

---

## Storage

无 DynamoDB 表。无状态服务，直接代理外部 API。

---

## EventBridge Events

无事件发布或消费。该服务为同步调用的无状态服务。

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BAZI_API_URL` | `https://match-date-nu.vercel.app/api/match` | 外部八字 API 地址 |
| `BAZI_API_KEY` | `ABC` | 外部八字 API Key |

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | Recommendation Service | HTTP 同步调用获取匹配日期 |
| **Called by** | Frontend (React) | HTTP via API Gateway |
| **Depends on** | External BaZi API | HTTP POST to Vercel-hosted service |
| **Depends on** | Auth (Cognito) | JWT validation via API Gateway Authorizer |
