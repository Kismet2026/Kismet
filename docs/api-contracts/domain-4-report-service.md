# Report Service — API Contract

**Owner:** Amber
**Domain:** Safety & Moderation
**Base Path:** `/reports`
**AWS Services:** Lambda, DynamoDB, SES

---

## Endpoints

### POST /reports

用户举报另一个用户。

**Auth:** Required (JWT, any authenticated user)

**Request:**

```json
{
  "reportedUserId": "user-456",
  "reason": "harassment",
  "description": "This user sent threatening messages."
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `reportedUserId` | string | Yes | 被举报用户的 ID |
| `reason` | string | Yes | `"harassment"` \| `"inappropriate_content"` \| `"spam"` \| `"fake_profile"` \| `"other"` |
| `description` | string | No | 举报的详细描述 |

**Response (201):**

```json
{
  "reportId": "report-001",
  "reporterId": "user-123",
  "reportedUserId": "user-456",
  "reason": "harassment",
  "description": "This user sent threatening messages.",
  "status": "PENDING",
  "createdAt": "2026-04-01T12:00:00Z"
}
```

**Side Effects:**
- 写入 DynamoDB `kismet-reports` 表
- 发布 EventBridge 事件 `user.reported`

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | reason 不在允许值列表中，或 reportedUserId 缺失 |
| 401 | `UNAUTHORIZED` | 未登录 |
| 409 | `CONFLICT` | 对同一用户已有未处理的举报 |

---

### GET /reports

获取所有举报列表（管理员使用，支持分页）。

**Auth:** Required (JWT, Admin only)

**Request:**

```
GET /reports?limit=20&cursor=xxx
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
      "reportId": "report-001",
      "reporterId": "user-123",
      "reportedUserId": "user-456",
      "reason": "harassment",
      "status": "PENDING",
      "createdAt": "2026-04-01T12:00:00Z"
    },
    {
      "reportId": "report-002",
      "reporterId": "user-789",
      "reportedUserId": "user-321",
      "reason": "spam",
      "status": "RESOLVED",
      "createdAt": "2026-04-01T11:55:00Z"
    }
  ],
  "nextCursor": "eyJ0aW1lc3Rhb...",
  "count": 2
}
```

---

### GET /reports/{reportId}

获取单个举报的详细信息（管理员使用）。

**Auth:** Required (JWT, Admin only)

**Request:**

```
GET /reports/report-001
```

**Response (200):**

```json
{
  "reportId": "report-001",
  "reporterId": "user-123",
  "reportedUserId": "user-456",
  "reason": "harassment",
  "description": "This user sent threatening messages.",
  "status": "PENDING",
  "resolution": null,
  "createdAt": "2026-04-01T12:00:00Z",
  "resolvedAt": null
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | 未登录 |
| 403 | `FORBIDDEN` | 非管理员用户 |
| 404 | `NOT_FOUND` | reportId 不存在 |

---

### PUT /reports/{reportId}/resolve

管理员处理举报（警告、封禁或驳回）。

**Auth:** Required (JWT, Admin only)

**Request:**

```json
{
  "resolution": "warning"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `resolution` | string | Yes | `"warning"` \| `"ban"` \| `"dismiss"` |

**Response (200):**

```json
{
  "reportId": "report-001",
  "reportedUserId": "user-456",
  "reason": "harassment",
  "status": "RESOLVED",
  "resolution": "warning",
  "resolvedAt": "2026-04-01T14:00:00Z"
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | resolution 不在允许值列表中 |
| 401 | `UNAUTHORIZED` | 未登录 |
| 403 | `FORBIDDEN` | 非管理员用户 |
| 404 | `NOT_FOUND` | reportId 不存在 |
| 409 | `CONFLICT` | 该举报已处理 |

---

## DynamoDB Table

**Table:** `kismet-reports`

| Attribute | Type | Key |
|-----------|------|-----|
| `reportId` | String | Partition Key (REPORT#{reportId}) |
| `sk` | String | Sort Key (META) |
| `reporterId` | String | — |
| `reportedUserId` | String | — |
| `reason` | String | — |
| `description` | String | — |
| `status` | String | — | "PENDING", "RESOLVED", "DISMISSED" |
| `resolution` | String | — | "warning" \| "ban" \| null |
| `createdAt` | String (ISO 8601) | — |
| `resolvedAt` | String (ISO 8601) | — |

**GSIs:** 
1. `reportedUserId-index` — 按 reportedUserId 查询该用户的所有举报 (PK: `reportedUserId`, SK: `createdAt`)
2. `status-index` — 按 status 查询和过滤举报列表 (PK: `status`, SK: `createdAt`)

---

## EventBridge Events

### Published: `user.reported`

当用户提交举报时发布。

```json
{
  "source": "kismet.report-service",
  "detail-type": "user.reported",
  "detail": {
    "reportId": "report-001",
    "reporterId": "user-123",
    "reportedUserId": "user-456",
    "reason": "harassment",
    "timestamp": "2026-04-01T12:00:00Z"
  }
}
```

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | Frontend (React) | HTTP via API Gateway |
| **Publishes to** | EventBridge | `user.reported` |
| **Depends on** | Auth (Cognito) | JWT validation via API Gateway Authorizer |
| **Depends on** | AWS SES | 发送举报处理通知邮件 |
