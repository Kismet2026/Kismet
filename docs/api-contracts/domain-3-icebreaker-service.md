# Icebreaker Service — API Contract

**Owner:** Jiaxin
**Domain:** Messaging
**Base Path:** `/icebreaker`
**AWS Services:** Bedrock, Lambda, DynamoDB

---

## Endpoints

### POST /icebreaker/generate

Generate AI-powered conversation starters based on both users' profiles and BaZi compatibility. Returns 3 suggestions. If Bedrock is unavailable, falls back to a hardcoded template list.

**Auth:** Required (JWT)

**Request:**

```json
{
  "matchId": "match-123"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `matchId` | string | Yes | The match to generate icebreakers for |

**Response (200):**

```json
{
  "matchId": "match-123",
  "suggestions": [
    {
      "id": "ice-001",
      "text": "I see we're both Wood elements — do you feel most energized in spring too?",
      "source": "bedrock"
    },
    {
      "id": "ice-002",
      "text": "Your profile says you love hiking! What's the best trail you've been on?",
      "source": "bedrock"
    },
    {
      "id": "ice-003",
      "text": "Our BaZi compatibility is really high — have you explored your chart before?",
      "source": "bedrock"
    }
  ],
  "generatedAt": "2026-04-01T12:00:00Z"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `source` | string | `"bedrock"` if AI-generated, `"template"` if from fallback list |

**Side Effects:**
- Calls Profile Service to get both users' profiles
- Calls BaZi Service to get compatibility data
- Calls Bedrock (Claude or Titan) for text generation
- Caches result in DynamoDB `kismet-icebreakers`

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | matchId is missing |
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | User is not a participant of this match |
| 404 | `NOT_FOUND` | matchId does not exist |

---

### GET /icebreaker/{matchId}

Get previously generated icebreakers for a match. Returns cached results from DynamoDB.

**Auth:** Required (JWT)

**Request:**

```
GET /icebreaker/match-123
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `matchId` | string (path) | Yes | The match to get icebreakers for |

**Response (200):**

```json
{
  "matchId": "match-123",
  "suggestions": [
    {
      "id": "ice-001",
      "text": "I see we're both Wood elements — do you feel most energized in spring too?",
      "source": "bedrock"
    },
    {
      "id": "ice-002",
      "text": "Your profile says you love hiking! What's the best trail you've been on?",
      "source": "bedrock"
    },
    {
      "id": "ice-003",
      "text": "Our BaZi compatibility is really high — have you explored your chart before?",
      "source": "bedrock"
    }
  ],
  "generatedAt": "2026-04-01T12:00:00Z"
}
```

Returns `null` for `suggestions` if no icebreakers have been generated yet.

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | User is not a participant of this match |
| 404 | `NOT_FOUND` | matchId does not exist |

---

## DynamoDB Table

**Table:** `kismet-icebreakers`

| Attribute | Type | Key |
|-----------|------|-----|
| `MATCH#{matchId}` | String | Partition Key |
| `META` | String | Sort Key |
| `suggestions` | List | — |
| `source` | String | — |
| `generatedAt` | String (ISO 8601) | — |

---

## Bedrock Configuration

**Model:** Claude (primary) or Titan (fallback) for text generation

**Fallback behavior:** If Bedrock is unavailable (timeout, error, quota exceeded), return icebreakers from a hardcoded template list. Templates are generic conversation starters that do not require profile or BaZi data. The `source` field will be set to `"template"` to indicate fallback was used.

---

## EventBridge Events

### Consumed: `match.created`

Auto-generates icebreakers when a new match is created, so suggestions are ready before either user opens the chat.

```json
{
  "source": "kismet.match-service",
  "detail-type": "match.created",
  "detail": {
    "matchId": "match-123",
    "userIds": ["user-123", "user-456"],
    "timestamp": "2026-04-01T12:00:00Z"
  }
}
```

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | Frontend (React) | HTTP via API Gateway |
| **Triggered by** | Match Service | EventBridge `match.created` |
| **Depends on** | Profile Service | HTTP — fetch both users' profiles |
| **Depends on** | BaZi Service | HTTP — fetch compatibility data |
| **Depends on** | Bedrock | AWS SDK — text generation |
| **Depends on** | Auth (Cognito) | JWT validation via API Gateway Authorizer |
