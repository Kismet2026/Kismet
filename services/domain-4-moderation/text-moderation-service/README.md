# Text Moderation Service

**Owner(s):** Yue  
**Domain:** Safety & Moderation (Domain 4)  
**Status:** Implemented

## Description

Single Lambda module (`lambda_function.py`): **Comprehend** toxicity, **DynamoDB** moderation results, EventBridge consumer for **`message.sent`**, publisher for **`content.flagged`**, plus HTTP endpoints for moderation and admin history.

## API contract

`docs/api-contracts/domain-4-text-moderation-service.md`  
Events: `docs/system-design/event-schema.json`

**Behavior not spelled out in the contract doc**

- POST accepts optional **`userId`**; stored on the moderation row when sent.
- **`content`** is limited to **4500 UTF-8 bytes**; longer body → `400` `VALIDATION_ERROR`.
- GET history: bad **`cursor`** → `400` `VALIDATION_ERROR`; DynamoDB read failure → `500` `INTERNAL_ERROR`.

## Runtime behavior

- Consumes `message.sent` (`source: kismet.message-service`)
- Publishes `content.flagged` (`source: kismet.moderation`) when toxic score exceeds threshold
- Persists moderation rows into `kismet-text-moderation` with GSI `gsi1` for history queries
- Enforces admin-only access on `GET /moderate/text/history` via Cognito groups

## AWS (see `template.yaml`)

- DynamoDB table + GSI `gsi1`
- Comprehend `DetectToxicContent`
- EventBridge rule on `message.sent`
- `events:PutEvents` permission for `content.flagged`
- API Gateway routes

## Setup

```bash
cd services/domain-4-moderation/text-moderation-service
sam build
sam deploy --guided
```

## Tests

Uses **pytest** + **moto** (DynamoDB/EventBridge mocked in-process; Comprehend client monkeypatched in tests).

```bash
cd services/domain-4-moderation/text-moderation-service
python -m pip install pytest moto boto3 botocore
python -m pytest tests/test_text_moderation.py -q
```

## Layout

```
text-moderation-service/
├── lambda_function.py
├── template.yaml
├── requirements.txt          # Lambda runtime dependencies
├── tests/
│   └── test_text_moderation.py
└── README.md
```
