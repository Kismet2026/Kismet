# Text Moderation Service

**Owner(s):** Yue  
**Domain:** Safety & Moderation (Domain 4)  
**Status:** In progress

## Description

Single Lambda module (`lambda_function.py`): **Comprehend** toxicity, **DynamoDB** results, **EventBridge** `content.flagged`, **`message.sent`** consumer, **GET** admin history. Same behavior as before; code is inlined in one file (similar layout to other teams’ one-file Lambdas: config/clients at top, EventBridge block, HTTP block, helpers).

## API contract

`docs/api-contracts/domain-4-text-moderation-service.md`  
Events: `docs/system-design/event-schema.json`

**Behavior not spelled out in the contract doc**

- POST accepts optional **`userId`**; stored on the moderation row when sent.
- **`content`** is limited to **4500 UTF-8 bytes**; longer body → `400` `VALIDATION_ERROR`.
- GET history: bad **`cursor`** → `400` `VALIDATION_ERROR`; DynamoDB read failure → `500` `INTERNAL_ERROR`.

## AWS (see `template.yaml`)

DynamoDB + GSI `gsi1`, Comprehend, PutEvents, API routes, EventBridge rule on `message.sent`.

## Setup

```bash
cd services/domain-4-moderation/text-moderation-service
sam build
sam deploy --guided
```

## Tests

**pytest** + **moto** (DynamoDB, EventBridge in-process; Comprehend is monkeypatched).

```bash
cd services/domain-4-moderation/text-moderation-service
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

## Layout

```
text-moderation-service/
├── lambda_function.py
├── template.yaml
├── requirements.txt          # Lambda runtime (boto3 provided by AWS)
├── requirements-dev.txt      # pytest + moto for local tests
├── tests/
│   └── test_text_moderation.py
└── README.md
```
