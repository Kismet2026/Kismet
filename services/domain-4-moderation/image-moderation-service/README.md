# Image Moderation Service

**Owner(s):** Yue 
**Domain:** Safety & Moderation (Domain 4)  
**Status:** In progress

## Description

Single Lambda module (`lambda_function.py`): **Rekognition** `DetectModerationLabels` on S3 objects, **DynamoDB** audit/history, **EventBridge** `content.flagged` (`contentType: image`), consumer for **`photo.uploaded`**, **POST** `/moderate/image`, **GET** `/moderate/image/history` (admin).

The API contract describes marking photos as “blocked”; the implementation updates the photo-service DynamoDB row to **`status: rejected`**, which matches `docs/api-contracts/domain-1-photo-service.md` (`pending` / `approved` / `rejected`). This only runs when **`PHOTOS_TABLE_NAME`** is set and the Lambda role can `UpdateItem` on that table.

## API contract

`docs/api-contracts/domain-4-image-moderation-service.md`

## AWS (see `template.yaml`)

- DynamoDB table `kismet-image-moderation-*` + GSI `gsi1` for history  
- Rekognition + `s3:GetObject` / `s3:HeadObject` on the photo bucket  
- `events:PutEvents` on the shared event bus  
- API routes + EventBridge rule on `photo.uploaded` (`kismet.photo-service`)

### Environment variables

| Variable | Purpose |
|----------|---------|
| `IMAGE_MODERATION_TABLE_NAME` | DynamoDB table for moderation rows |
| `PHOTO_S3_BUCKET` | S3 bucket passed to Rekognition `S3Object` |
| `EVENT_BUS_NAME` | Target bus for `content.flagged` |
| `MODERATION_FLAG_CONFIDENCE` | Flag if max Rekognition label confidence ≥ this (0–100, default `60`) |
| `REKOGNITION_MIN_CONFIDENCE` | `MinConfidence` on the Rekognition call (default `5`) |
| `ADMIN_GROUP_NAMES` | Comma-separated Cognito groups for history GET |
| `PHOTOS_TABLE_NAME` | Optional; if set, flagged images update `kismet-photos` row to `status=rejected` |

If `PHOTOS_TABLE_NAME` is enabled, attach **`dynamodb:UpdateItem`** on that table to the Lambda role (not included when the table lives in another stack).

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
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

## Layout

```
image-moderation-service/
├── lambda_function.py
├── template.yaml
├── requirements.txt          # Lambda runtime (boto3 provided by AWS)
├── requirements-dev.txt      # pytest + moto for local tests
├── tests/
│   └── test_image_moderation.py
└── README.md
```
