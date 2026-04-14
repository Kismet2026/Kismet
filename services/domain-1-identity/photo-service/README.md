# Photo Service

**Owner(s):** Zhiping
**Domain:** Identity & Profiles
**Status:** 🟡 Ready for deploy

## Description
Manages profile photo upload, listing, deletion, and primary-photo selection workflows.
This rollout fronts the shared photos bucket with a dedicated CloudFront distribution so photo reads use stable public URLs without making S3 public.

## AWS Services Used
- Lambda — routes `/photos/*` and `/users/*/photos` requests and hosts service logic
- S3 — stores uploaded photo objects in the shared photos bucket
- CloudFront — serves stable public photo URLs via `PHOTOS_CDN_BASE_URL` after the shared/domain1 rollout is deployed
- DynamoDB — stores metadata in `kismet-photos`
- EventBridge — publishes `photo.uploaded`
- Cognito authorizer — enforces JWT auth through shared API Gateway

## Scaffold Status
- Service logic is implemented in `lambda_function.py`.
- This branch sources `PHOTOS_CDN_BASE_URL` from the shared photos CloudFront distribution in `SharedStack`.
- After deploying `KismetShared` and then `KismetDomain1`, `GET /users/{userId}/photos` and `photo.uploaded` will return CloudFront-backed photo URLs.

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

### GET /users/{userId}/photos
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
- **Depends on:** Shared API Gateway/Cognito authorizer, `kismet-photos` table, shared photos bucket, shared photos CloudFront distribution/base URL, `kismet-events` EventBridge bus
- **Called by:** Frontend (React) via photo-service routes
- **Events published:** `photo.uploaded`
- **Events consumed:** None

## Integration Notes
- `docs/api-contracts/domain-1-photo-service.md` lists Image Moderation Service as the consumer of `photo.uploaded`, while `docs/system-design/event-schema.json`, `docs/guides/Service_Communication_Guide.md`, and `docs/system-design/Infrastructure_Design.md` also list Activity Logger.
- `docs/api-contracts/domain-1-photo-service.md` uses bucket name `kismet-photos-dev`, while `infra/stacks/shared_stack.py` currently provisions `kismet-photos-{account}-dev`.
- This rollout adds a dedicated photos CloudFront distribution in shared infrastructure and injects its base URL into photo-service.
- Keep the S3 bucket private and treat CloudFront as the canonical delivery URL for photo reads and `photo.uploaded` events.

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
