# Image Moderation Service

**Owner(s):** Yue 
**Domain:** Safety & Moderation (Domain 4)  
**Status:** Implemented

## Description

Single Lambda module (`lambda_function.py`): **Rekognition** moderation on S3 objects, **DynamoDB** audit/history, EventBridge consumer for **`photo.uploaded`**, publisher for **`content.flagged`** (`contentType: image`), and HTTP endpoints for moderation plus admin history.

The API contract describes marking photos as “blocked”; implementation updates the photo-service row to **`status: rejected`** (`pending` / `approved` / `rejected` in Domain 1 contract). This requires **`PHOTOS_TABLE_NAME`** and IAM `dynamodb:UpdateItem` on that table.

## API contract

`docs/api-contracts/domain-4-image-moderation-service.md`

## AWS (see `template.yaml`)

- DynamoDB table `kismet-image-moderation` + GSI `gsi1` for history  
- Rekognition + `s3:GetObject` / `s3:HeadObject` on the photo bucket  
- `events:PutEvents` on the shared event bus  
- API routes + EventBridge rule on `photo.uploaded` (`kismet.photo-service`)

### Environment variables

| Variable | Purpose |
|----------|---------|
| `IMAGE_MODERATION_TABLE_NAME` | DynamoDB table for moderation rows |
| `PHOTO_S3_BUCKET` | Default S3 bucket for HTTP path (used when event does not provide override) |
| `EVENT_BUS_NAME` | Target bus for `content.flagged` |
| `MODERATION_FLAG_CONFIDENCE` | Flag if max Rekognition label confidence ≥ this (0–100, default `60`) |
| `REKOGNITION_MIN_CONFIDENCE` | `MinConfidence` on the Rekognition call (default `5`) |
| `ADMIN_GROUP_NAMES` | Comma-separated Cognito groups for history GET |
| `PHOTOS_TABLE_NAME` | Photo table used to update flagged photos to `status=rejected` |

`photo.uploaded` event handling reads `detail.s3Bucket` (from `event-schema.json`) and prioritizes that value for Rekognition.

## Setup

```bash
cd services/domain-4-moderation/image-moderation-service
sam build
sam deploy --guided
```

Set stack parameter **`PhotoS3BucketName`** to the same bucket the photo service uses.

## Tests

Uses **pytest** and **moto** (DynamoDB, S3, EventBridge mocked in-process; Rekognition `detect_moderation_labels` is monkeypatched).

```bash
cd services/domain-4-moderation/image-moderation-service
python -m pip install pytest moto boto3 botocore
python -m pytest tests/test_image_moderation.py -q
```

## Layout

```
image-moderation-service/
├── lambda_function.py
├── template.yaml
├── requirements.txt          # Lambda runtime dependencies
├── tests/
│   └── test_image_moderation.py
└── README.md
```
