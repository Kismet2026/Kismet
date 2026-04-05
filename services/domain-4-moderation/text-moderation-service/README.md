# Text Moderation Service

**Owner(s):** Yue  
**Domain:** Safety & Moderation (Domain 4)  
**Status:** 🟡 In progress

## Description

Detects toxic text via AWS Comprehend, persists moderation results to DynamoDB, publishes `content.flagged` on EventBridge when over threshold, and exposes an admin history API. **Week 1** delivers the API contract plus a deployable Lambda and DynamoDB table scaffold; **full behavior is implemented in Week 2+**.

## AWS Services Used

- **Lambda** — routes `/moderate/text` and `/moderate/text/history`, and (Week 2) consumes `message.sent` from EventBridge  
- **DynamoDB** — store moderation rows in `kismet-text-moderation` (table scaffold in `template.yaml`)  
- **Amazon Comprehend** — `DetectToxicContent` (**planned**; not wired in Week 1 template/IAM)  
- **EventBridge** — publish `content.flagged`; consume `message.sent` (**planned**; no rule on Lambda in Week 1 SAM)  
- **Cognito authorizer** — **planned** JWT enforcement for `GET /moderate/text/history` via shared API Gateway  

## Scaffold Status

- Week 1 skeleton is in place.
- All documented HTTP routes are wired in `lambda_function.py`.
- `template.yaml` defines the Lambda function and the `kismet-text-moderation` DynamoDB table (partition `contentId`, sort `sk` per contract).
- **HTTP:** each matched route returns **`501 NOT_IMPLEMENTED`** with body shaped as `{"error":{"code":"NOT_IMPLEMENTED","message":...}}` plus debug fields (`operation`, `path`, `requestId`, …) until Week 2.
- **EventBridge-shaped invocations** return **`200`** with a JSON body that includes `error.NOT_IMPLEMENTED` and metadata (Week 1 stub only; no real bus subscription in this template yet).

## API Endpoints

Canonical request/response and errors: **`docs/api-contracts/domain-4-text-moderation-service.md`**.

### POST /moderate/text

**Auth (contract):** Internal (EventBridge) or service-to-service — may differ from the global “JWT on all routes except auth signup/login” convention; confirm with PM/Integration.

**Request:**

```json
{
  "content": "some text to moderate",
  "contentId": "msg-123",
  "contentType": "message"
}
```

**Response (200 — Week 2 target):**

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

**Scaffold response (Week 1):** `501` + `NOT_IMPLEMENTED`.

---

### GET /moderate/text/history

**Auth (contract):** JWT, admin only.

**Request:**

```
GET /moderate/text/history?limit=20&cursor=xxx
```

**Response (200 — Week 2 target):**

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
    }
  ],
  "nextCursor": null,
  "count": 1
}
```

**Scaffold response (Week 1):** `501` + `NOT_IMPLEMENTED`.

## Dependencies

- **Depends on:** Shared API Gateway (optional `SharedApiId`), shared EventBridge bus `kismet-events` (Week 2), Cognito for admin routes, Comprehend in a supported Region (Week 2)  
- **Called by:** Message Service (via `message.sent` — Week 2), other services or internal calls to `POST /moderate/text` (e.g. bio moderation — confirm with Profile)  
- **Events published:** `content.flagged` (`source: kismet.moderation` per `docs/system-design/event-schema.json`)  
- **Events consumed:** `message.sent` (`source: kismet.message-service`)  

## Integration Notes

- **JWT vs contract:** Repo-wide API README says most endpoints require JWT except `/auth/signup` and `/auth/login`. This service’s contract marks `POST /moderate/text` as internal/S2S and `GET .../history` as admin JWT. Align authorizer rules on API Gateway before demo.
- **Week 1 SAM** does **not** attach an EventBridge rule to the Lambda and does **not** grant `comprehend:*` or `events:PutEvents`; add those when implementing Week 2.
- **History pagination** may require a GSI on the moderation table (not in Week 1 `template.yaml`); add when implementing `GET /moderate/text/history`.
- Event payload details for `message.sent` and `content.flagged`: **`docs/system-design/event-schema.json`**.

## Setup

```bash
cd services/domain-4-moderation/text-moderation-service
sam build
sam deploy --guided
```

- Omit `SharedApiId` (or leave default empty) for a stack-local API; pass the class **shared REST API id** when integrating with the main `api.kismet.app` gateway.
- Default table name parameter: `kismet-text-moderation-dev` (override via `TextModerationTableName`).

**Environment variables:** none required by the Week 1 scaffold handler. Week 2 logic typically adds names such as `TEXT_MODERATION_TABLE_NAME`, `EVENT_BUS_NAME`, `TOXICITY_THRESHOLD`, `ADMIN_GROUP_NAMES`, etc.

## Project layout

```
text-moderation-service/
├── lambda_function.py
├── template.yaml
├── requirements.txt
├── tests/
│   └── test_lambda_function.py
└── README.md
```
