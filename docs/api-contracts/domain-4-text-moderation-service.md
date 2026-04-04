# Text Moderation Service — API Contract

**Owner:** Yue
**Domain:** Safety & Moderation
**Base Path:** `/moderate/text`
**AWS Services:** Comprehend, Lambda

---

## Endpoints

### POST /moderate/text

对文本内容进行毒性检测和审核。

**Auth:** Internal (EventBridge) or Service-to-Service

**Request:**

```json
{
  "content": "some text to moderate",
  "contentId": "msg-123",
  "contentType": "message"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `content` | string | Yes | 待审核的文本内容 |
| `contentId` | string | Yes | 内容的唯一 ID（消息 ID 或用户 ID） |
| `contentType` | string | Yes | `"message"` 或 `"bio"` |

**Response (200):**

```json
{
  "contentId": "msg-123",
  "contentType": "message",
  "flagged": true,
  "toxicityScore": 0.87,
  "categories": ["HATE_SPEECH", "INSULT"],
  "timestamp": "2026-04-01T12:00:00Z"
}
```

**Side Effects:**
- 调用 AWS Comprehend DetectToxicContent API 进行毒性分析
- 写入 DynamoDB `kismet-text-moderation` 表
- 如果 toxicityScore 超过阈值，发布 EventBridge 事件 `content.flagged`

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | content 为空，或 contentType 不是 message/bio |
| 500 | `COMPREHEND_ERROR` | AWS Comprehend 调用失败 |

---

### GET /moderate/text/history

获取最近的文本审核结果列表（管理员使用）。

**Auth:** Required (JWT, Admin only)

**Request:**

```
GET /moderate/text/history?limit=20&cursor=xxx
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
      "contentId": "msg-123",
      "contentType": "message",
      "flagged": true,
      "toxicityScore": 0.87,
      "categories": ["HATE_SPEECH", "INSULT"],
      "timestamp": "2026-04-01T12:00:00Z"
    },
    {
      "contentId": "bio-456",
      "contentType": "bio",
      "flagged": false,
      "toxicityScore": 0.05,
      "categories": [],
      "timestamp": "2026-04-01T11:55:00Z"
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
| 403 | `FORBIDDEN` | 非管理员用户 |

---

## DynamoDB Table

**Table:** `kismet-text-moderation`

| Attribute | Type | Key |
|-----------|------|-----|
| `contentId` | String | Partition Key (CONTENT#{contentId}) |
| `sk` | String | Sort Key (RESULT) |
| `contentType` | String | — |
| `flagged` | Boolean | — |
| `toxicityScore` | Number | — |
| `categories` | List | — |
| `timestamp` | String (ISO 8601) | — |

---

## EventBridge Events

### Consumed: `message.sent`

当消息发送时自动触发文本审核。

```json
{
  "source": "kismet.message-service",
  "detail-type": "message.sent",
  "detail": {
    "messageId": "msg-123",
    "matchId": "match-789",
    "senderId": "user-123",
    "recipientId": "user-456",
    "content": "message text",
    "messageType": "text",
    "timestamp": "2026-04-01T12:05:00Z"
  }
}
```

### Published: `content.flagged`

当 toxicityScore 超过阈值时发布。

```json
{
  "source": "kismet.moderation",
  "detail-type": "content.flagged",
  "detail": {
    "contentId": "msg-123",
    "contentType": "text",
    "userId": "user-123",
    "reason": "toxicity_detected",
    "score": 0.87,
    "timestamp": "2026-04-01T12:00:00Z"
  }
}
```

**Consumed by:** Admin Dashboard, Activity Logger

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | EventBridge (`message.sent`) | 自动触发审核 |
| **Publishes to** | Admin Dashboard | EventBridge `content.flagged` |
| **Depends on** | AWS Comprehend | DetectToxicContent API |
| **Depends on** | Auth (Cognito) | JWT validation（GET 端点，管理员权限） |
