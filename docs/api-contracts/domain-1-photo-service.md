# Photo Service — API Contract

**Owner:** KS
**Domain:** Identity & Profiles
**Base Paths:** `/photos`, `/users/{userId}/photos`
**AWS Services:** S3, Lambda, CloudFront

---

## Endpoints

### POST /photos/upload

Request a presigned S3 URL for direct photo upload from the client.

**Auth:** Required (JWT)

**Request:**

```json
{
  "contentType": "image/jpeg",
  "filename": "profile-pic.jpg"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `contentType` | string | Yes | MIME type (`image/jpeg`, `image/png`, `image/webp`) |
| `filename` | string | No | Original filename for reference |

**Response (200):**

```json
{
  "photoId": "photo-001",
  "uploadUrl": "https://kismet-photos-dev.s3.amazonaws.com/user-123/photo-001?X-Amz-Signature=...",
  "expiresIn": 300
}
```

**Side Effects:**
- Creates pending photo record in DynamoDB `kismet-photos` table
- After client uploads to S3, publishes EventBridge event `photo.uploaded`

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | Unsupported content type |
| 401 | `UNAUTHORIZED` | Not logged in |
| 413 | `FILE_TOO_LARGE` | Photo exceeds maximum size (10 MB) |
| 429 | `TOO_MANY_PHOTOS` | User has reached maximum photo limit (6) |

---

### GET /users/{userId}/photos

List all photos for a user. Returns CloudFront CDN URLs for optimized delivery.

**Auth:** Required (JWT)

**Request:**

```
GET /users/user-123/photos
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `userId` | string (path) | Yes | Target user ID |

**Response (200):**

```json
{
  "photos": [
    {
      "photoId": "photo-001",
      "url": "https://d1234abcd.cloudfront.net/user-123/photo-001.jpg",
      "isPrimary": true,
      "uploadedAt": "2026-04-01T12:00:00Z"
    },
    {
      "photoId": "photo-002",
      "url": "https://d1234abcd.cloudfront.net/user-123/photo-002.jpg",
      "isPrimary": false,
      "uploadedAt": "2026-04-01T12:05:00Z"
    }
  ],
  "count": 2
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 404 | `NOT_FOUND` | User does not exist |

---

### DELETE /photos/{photoId}

Delete a photo. Users can only delete their own photos.

**Auth:** Required (JWT)

**Request:**

```
DELETE /photos/photo-001
```

**Response (200):**

```json
{
  "message": "Photo deleted successfully"
}
```

**Side Effects:**
- Removes photo record from DynamoDB `kismet-photos` table
- Deletes object from S3 bucket `kismet-photos-dev`

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | Attempting to delete another user's photo |
| 404 | `NOT_FOUND` | Photo does not exist |

---

### PUT /photos/{photoId}/primary

Set a photo as the user's primary profile photo.

**Auth:** Required (JWT)

**Request:**

```
PUT /photos/photo-002/primary
```

**Response (200):**

```json
{
  "photoId": "photo-002",
  "isPrimary": true
}
```

**Side Effects:**
- Updates `isPrimary` flag in DynamoDB (unsets previous primary photo)

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | Attempting to modify another user's photo |
| 404 | `NOT_FOUND` | Photo does not exist |

---

## S3 Bucket

**Bucket:** `kismet-photos-dev`

| Property | Value |
|----------|-------|
| Key format | `{userId}/{photoId}.{ext}` |
| Max file size | 10 MB |
| Allowed types | `image/jpeg`, `image/png`, `image/webp` |
| CloudFront distribution | Serves optimized images via CDN |

---

## DynamoDB Table

**Table:** `kismet-photos`

| Attribute | Type | Key |
|-----------|------|-----|
| `PK` | String | Partition Key (`USER#{userId}`) |
| `SK` | String | Sort Key (`PHOTO#{photoId}`) |
| `photoId` | String | — |
| `s3Key` | String | — |
| `contentType` | String | — |
| `isPrimary` | Boolean | — |
| `status` | String | — (`pending`, `approved`, `rejected`) |
| `uploadedAt` | String (ISO 8601) | — |

---

## EventBridge Events

### Published: `photo.uploaded`

Published when a photo is successfully uploaded to S3 (triggered by S3 event notification).

```json
{
  "source": "kismet.photo-service",
  "detail-type": "photo.uploaded",
  "detail": {
    "photoId": "photo-001",
    "userId": "user-123",
    "s3Key": "user-123/photo-001.jpg",
    "s3Bucket": "kismet-photos-dev",
    "contentType": "image/jpeg",
    "cdnUrl": "https://d1234abcd.cloudfront.net/user-123/photo-001.jpg",
    "isPrimary": true,
    "timestamp": "2026-04-01T12:00:00Z"
  }
}
```

**Consumed by:** Image Moderation Service

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | Frontend (React) | HTTP via API Gateway |
| **Publishes to** | Image Moderation Service | EventBridge `photo.uploaded` |
| **Depends on** | Auth (Cognito) | JWT validation via API Gateway Authorizer |
| **Depends on** | S3, CloudFront | Photo storage and CDN delivery |
