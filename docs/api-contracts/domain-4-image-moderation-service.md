# Image Moderation Service — API Contract

**Owner:** KS
**Domain:** Safety & Moderation
**Base Path:** `/moderate/image`
**AWS Services:** Rekognition, Lambda

---

## Endpoints

### POST /moderate/image

对上传的图片进行内容审核。

**Auth:** Internal (EventBridge) or Service-to-Service

**Request:**

```json
{
  "s3Key": "uploads/user-123/photo-001.jpg",
  "photoId": "photo-001",
  "userId": "user-123"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `s3Key` | string | Yes | S3 中图片的 key |
| `photoId` | string | Yes | 照片唯一 ID |
| `userId` | string | Yes | 上传照片的用户 ID |

**Response (200):**

```json
{
  "photoId": "photo-001",
  "userId": "user-123",
  "flagged": true,
  "labels": [
    {
      "name": "Explicit Nudity",
      "confidence": 95.6
    },
    {
      "name": "Violence",
      "confidence": 12.3
    }
  ],
  "confidence": 95.6,
  "timestamp": "2026-04-01T12:00:00Z"
}
```

**Side Effects:**
- 调用 AWS Rekognition DetectModerationLabels API 进行图片审核
- 写入 DynamoDB `kismet-image-moderation` 表
- 如果检测到不当内容（flagged = true），发布 EventBridge 事件 `content.flagged`
- 如果 flagged，更新照片记录将其标记为 blocked

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | s3Key、photoId 或 userId 缺失 |
| 404 | `IMAGE_NOT_FOUND` | S3 中找不到指定图片 |
| 500 | `REKOGNITION_ERROR` | AWS Rekognition 调用失败 |

---

### GET /moderate/image/history

获取最近的图片审核结果列表（管理员使用）。

**Auth:** Required (JWT, Admin only)

**Request:**

```
GET /moderate/image/history?limit=20&cursor=xxx
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
      "photoId": "photo-001",
      "userId": "user-123",
      "flagged": true,
      "labels": [
        {
          "name": "Explicit Nudity",
          "confidence": 95.6
        }
      ],
      "confidence": 95.6,
      "timestamp": "2026-04-01T12:00:00Z"
    },
    {
      "photoId": "photo-002",
      "userId": "user-456",
      "flagged": false,
      "labels": [],
      "confidence": 0.0,
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

**Table:** `kismet-image-moderation`

| Attribute | Type | Key |
|-----------|------|-----|
| `photoId` | String | Partition Key (PHOTO#{photoId}) |
| `sk` | String | Sort Key (RESULT) |
| `userId` | String | — |
| `s3Key` | String | — |
| `flagged` | Boolean | — |
| `labels` | List | — |
| `confidence` | Number | — |
| `timestamp` | String (ISO 8601) | — |

---

## EventBridge Events

### Consumed: `photo.uploaded`

当用户上传照片时自动触发图片审核。

```json
{
  "source": "kismet.photo-service",
  "detail-type": "photo.uploaded",
  "detail": {
    "photoId": "photo-001",
    "userId": "user-123",
    "s3Key": "uploads/user-123/photo-001.jpg"
  }
}
```

### Published: `content.flagged`

当检测到不当内容时发布。

```json
{
  "source": "kismet.image-moderation-service",
  "detail-type": "content.flagged",
  "detail": {
    "photoId": "photo-001",
    "userId": "user-123",
    "labels": ["Explicit Nudity"],
    "confidence": 95.6,
    "timestamp": "2026-04-01T12:00:00Z"
  }
}
```

**Consumed by:** Admin Dashboard

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | EventBridge (photo.uploaded) | 自动触发审核 |
| **Publishes to** | Admin Dashboard | EventBridge `content.flagged` |
| **Depends on** | AWS Rekognition | DetectModerationLabels API |
| **Depends on** | Photo Service | 更新照片记录为 blocked |
| **Depends on** | Auth (Cognito) | JWT validation（GET 端点，管理员权限） |
