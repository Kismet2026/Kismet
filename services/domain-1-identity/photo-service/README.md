# Photo Service

**Owner(s):** Zhiping
**Domain:** Identity & Profiles
**Status:** 🟡 In progress

## Description
Manages profile photo upload, listing, deletion, and primary-photo selection workflows.

## AWS Services Used
- Lambda — route `/photos/*` requests and host service logic
- S3 — planned storage for uploaded photo objects
- CloudFront — planned CDN delivery for profile photo URLs
- DynamoDB — planned metadata storage in `kismet-photos`
- EventBridge — planned publication of `photo.uploaded`
- Cognito authorizer — planned JWT enforcement through shared API Gateway

## Scaffold Status
- Week 1 skeleton is in place.
- All documented HTTP routes are wired in `lambda_function.py`.
- `template.yaml` includes the Lambda function and the `kismet-photos` DynamoDB table scaffold, plus parameters for the shared photos bucket and CDN base URL.
- Each route currently returns `501 NOT_IMPLEMENTED` until Week 2 service logic is built.

## API Endpoints

### POST /photos/upload
**Request:**
```json
{
  "contentType": "image/jpeg",
  "filename": "profile-pic.jpg"
}
```
**Response:**
```json
{
  "photoId": "photo-001",
  "uploadUrl": "https://kismet-photos-dev.s3.amazonaws.com/user-123/photo-001?X-Amz-Signature=...",
  "expiresIn": 300
}
```

### GET /photos/{userId}
**Request:**
```json
{}
```
**Response:**
```json
{
  "photos": [
    {
      "photoId": "photo-001",
      "url": "https://d1234abcd.cloudfront.net/user-123/photo-001.jpg",
      "isPrimary": true,
      "uploadedAt": "2026-04-01T12:00:00Z"
    }
  ],
  "count": 1
}
```

### DELETE /photos/{photoId}
**Request:**
```json
{}
```
**Response:**
```json
{
  "message": "Photo deleted successfully"
}
```

### PUT /photos/{photoId}/primary
**Request:**
```json
{}
```
**Response:**
```json
{
  "photoId": "photo-002",
  "isPrimary": true
}
```

## Dependencies
- **Depends on:** Shared API Gateway/Cognito authorizer, `kismet-photos` table, shared photos bucket, CloudFront distribution/base URL, `kismet-events` EventBridge bus
- **Called by:** Frontend (React) via `/photos/*`
- **Events published:** `photo.uploaded`
- **Events consumed:** None

## Integration Notes
- `docs/api-contracts/domain-1-photo-service.md` lists Image Moderation Service as the consumer of `photo.uploaded`, while `docs/system-design/event-schema.json`, `docs/guides/Service_Communication_Guide.md`, and `docs/system-design/Infrastructure_Design.md` also list Activity Logger.
- `docs/api-contracts/domain-1-photo-service.md` uses bucket name `kismet-photos-dev`, while `infra/stacks/shared_stack.py` currently provisions `kismet-photos-{account}-dev`.
- `docs/system-design/Infrastructure_Design.md` documents a dedicated CloudFront photos distribution, but the current shared infrastructure code only provisions the S3 bucket. Confirm where the CDN distribution will live before Week 2 implementation.

## Setup
```bash
cd services/domain-1-identity/photo-service
sam build
sam deploy --guided
```

Environment variables expected by the scaffold:
- `PHOTOS_TABLE_NAME`
- `PHOTOS_BUCKET_NAME`
- `PHOTOS_CDN_BASE_URL`
- `EVENT_BUS_NAME`

## Testing
```bash
cd services/domain-1-identity/photo-service
python -m unittest discover -s tests -v
```
