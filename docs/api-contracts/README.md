# API Contracts

本目录包含 Kismet 所有 25 个微服务的 API Contract（接口定义）。

## 什么是 API Contract？

就是每个 HTTP 端点的"合同"——请求格式、响应格式、状态码、错误处理。
前端和其他 service 按照这份合同来调用你的接口。

## 文件命名

每个 service 一个文件，按 domain 编号：

```
api-contracts/
├── README.md                          ← 你在这里
├── domain-1-auth-service.md
├── domain-1-profile-service.md
├── domain-1-photo-service.md
├── domain-2-discovery-service.md
├── domain-2-swipe-service.md
├── domain-2-match-service.md
├── domain-2-recommendation-service.md
├── domain-2-bazi-service.md
├── domain-3-chat-gateway.md
├── domain-3-message-service.md
├── domain-3-presence-service.md
├── domain-3-icebreaker-service.md
├── domain-4-text-moderation-service.md
├── domain-4-image-moderation-service.md
├── domain-4-report-service.md
├── domain-4-rate-limiter-service.md
├── domain-5-push-notification-service.md
├── domain-5-email-service.md
├── domain-5-event-bus-service.md
├── domain-5-scheduler-service.md
├── domain-6-activity-logger-service.md
├── domain-6-analytics-pipeline-service.md
├── domain-6-admin-dashboard-service.md
└── domain-6-health-monitor-service.md
```

## 公共约定

### Base URL

```
https://xxxxxxxxxx.execute-api.us-east-1.amazonaws.com/dev
```

### 认证

除了 `/auth/signup` 和 `/auth/login`，所有端点都需要 JWT：

```
Authorization: Bearer <jwt_token>
```

### 错误响应格式

所有 service 统一使用以下错误格式：

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid email format"
  }
}
```

常见错误码：

| HTTP Status | code | 含义 |
|-------------|------|------|
| 400 | `VALIDATION_ERROR` | 请求参数不合法 |
| 401 | `UNAUTHORIZED` | 缺少或无效的 JWT |
| 403 | `FORBIDDEN` | 没有权限访问该资源 |
| 404 | `NOT_FOUND` | 资源不存在 |
| 409 | `CONFLICT` | 资源已存在（如重复注册） |
| 429 | `RATE_LIMITED` | 请求过于频繁 |
| 500 | `INTERNAL_ERROR` | 服务器内部错误 |

### 分页

返回列表的端点统一使用游标分页：

```json
// Request
GET /discovery?limit=20&cursor=eyJ1c2VySWQiOi...

// Response
{
  "items": [...],
  "nextCursor": "eyJ1c2VySWQiOi...",   // null 表示没有更多
  "count": 20
}
```

### 时间格式

所有时间字段使用 ISO 8601：`2026-04-01T12:00:00Z`

---

## Week 1 任务

每个 domain 的同学需要：

1. 照着下面的模板和示例，为你负责的 service 写 API Contract
2. 提交 PR 到 `dev` 分支
3. 在 Discord 你的 domain channel 里通知 partner review

**截止日期：Apr 6 (Sunday)**
