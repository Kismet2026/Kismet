# Rate Limiter Service — API Contract

**Owner:** Xinyuan Fan (Amber)
**Domain:** Safety & Moderation
**Base Path:** N/A (middleware, not directly called)
**AWS Services:** API Gateway, ElastiCache (Redis)

---

## Overview

Rate Limiter 不是传统的 REST 服务，而是一个速率限制层。通过 API Gateway Usage Plans + API Keys 实现基础限流，通过 ElastiCache (Redis) + TTL 实现用户级别的精细限流。

### Rate Limits

| Action | Limit | Window |
|--------|-------|--------|
| Swipes | 100 | per day |
| Messages | 50 | per hour |
| Reports | 5 | per day |

### Approach

- **基础限流：** API Gateway Usage Plans + API Keys，对所有 API 进行全局限流
- **用户级限流：** ElastiCache 记录每个用户的操作计数，使用 EX/PX 自动过期
- **应用方式：** 作为 Lambda middleware 或 API Gateway Authorizer 在请求处理前检查限流

---

## Endpoints (Internal / Admin)

### GET /ratelimit/status/{userId}

查询指定用户的当前速率限制状态。

**Auth:** Internal / Admin

**Request:**

```
GET /ratelimit/status/user-123
```

**Response (200):**

```json
{
  "userId": "user-123",
  "limits": {
    "swipes": {
      "used": 45,
      "limit": 100,
      "remaining": 55,
      "resetsAt": "2026-04-02T00:00:00Z"
    },
    "messages": {
      "used": 12,
      "limit": 50,
      "remaining": 38,
      "resetsAt": "2026-04-01T13:00:00Z"
    },
    "reports": {
      "used": 1,
      "limit": 5,
      "remaining": 4,
      "resetsAt": "2026-04-02T00:00:00Z"
    }
  }
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | 未登录 |
| 403 | `FORBIDDEN` | 非管理员用户 |
| 404 | `NOT_FOUND` | 该用户无限流记录 |

---

### POST /ratelimit/reset/{userId}

重置指定用户的速率限制计数器（管理员使用）。

**Auth:** Required (JWT, Admin only)

**Request:**

```
POST /ratelimit/reset/user-123
```

**Response (200):**

```json
{
  "userId": "user-123",
  "message": "Rate limit counters have been reset.",
  "resetAt": "2026-04-01T14:00:00Z"
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | 未登录 |
| 403 | `FORBIDDEN` | 非管理员用户 |

---

## ElastiCache (Redis) Schema

**Key Format:** `ratelimit:{userId}:{action}:{windowTimestamp}`

| Component | Example | Description |
|-----------|---------|-------------|
| `{userId}` | `user-123` | 用户 ID |
| `{action}` | `swipes` | 操作类型 (`swipes`, `messages`, `reports`) |
| `{windowTimestamp}` | `1711929600000` | 时间窗口的起始 Unix 时间戳 |

**Value Type:** String (integer)

**TTL:** 记录在时间窗口结束后自动使用 Redis 过期机制删除。

---

## EventBridge Events

无事件发布或消费。

---

## Rate Limit Response (when limit exceeded)

当用户超过速率限制时，API Gateway 或 Lambda middleware 返回：

```json
{
  "statusCode": 429,
  "error": "RATE_LIMIT_EXCEEDED",
  "message": "You have exceeded the limit of 100 swipes per day.",
  "retryAfter": "2026-04-02T00:00:00Z"
}
```

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | API Gateway / Lambda middleware | 在请求处理前检查限流 |
| **Called by** | Admin Dashboard | HTTP via API Gateway（查看和重置限流） |
| **Depends on** | Auth (Cognito) | JWT validation（管理员端点） |