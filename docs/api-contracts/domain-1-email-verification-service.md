# Email Verification Service — API Contract

> Legacy contract only. This SES-based `/verify/*` flow is not part of the deployed architecture anymore.
>
> The current production flow is Cognito-native:
> - `POST /auth/signup` creates the user and triggers the email code
> - `POST /auth/confirm` confirms the code
>
> PR #90 removed the custom verification service from the Domain 1 CDK stack, and PR #99 added the replacement `POST /auth/confirm` endpoint in auth-service.

**Owner:** KS
**Domain:** Identity & Profiles
**Base Path:** `/verify`
**AWS Services:** SES, Lambda, Cognito

**Status:** Legacy / not deployed

---

## Historical Endpoints

### POST /verify/send

Send a verification code to a .edu email address.

**Auth:** Not required

**Request:**

```json
{
  "email": "student@university.edu"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `email` | string | Yes | Must be a valid .edu email address |

**Response (200):**

```json
{
  "message": "Verification code sent",
  "email": "student@university.edu",
  "expiresIn": 600
}
```

**Side Effects:**
- Sends verification email via AWS SES
- Writes verification code to DynamoDB `kismet-verifications` table with TTL

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | Missing or invalid email |
| 400 | `INVALID_EMAIL` | Email is not a .edu address |
| 429 | `RATE_LIMIT` | Too many verification requests (max 3 per hour) |

---

### POST /verify/confirm

Confirm a verification code and mark the email as verified in Cognito.

**Auth:** Not required

**Request:**

```json
{
  "email": "student@university.edu",
  "code": "123456"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `email` | string | Yes | The .edu email address to verify |
| `code` | string | Yes | 6-digit verification code |

**Response (200):**

```json
{
  "message": "Email verified successfully",
  "email": "student@university.edu",
  "verified": true
}
```

**Side Effects:**
- Updates Cognito user attribute `email_verified` to `true`
- Deletes verification record from DynamoDB

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | Missing email or code |
| 400 | `INVALID_CODE` | Code is incorrect |
| 410 | `CODE_EXPIRED` | Verification code has expired |

---

### GET /verify/status

Check the current email verification status for the logged-in user.

**Auth:** Required (JWT)

**Request:**

```
GET /verify/status
```

**Response (200):**

```json
{
  "email": "student@university.edu",
  "verified": true,
  "verifiedAt": "2026-04-01T12:05:00Z"
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |

---

## Historical DynamoDB Table

**Table:** `kismet-verifications`

| Attribute | Type | Key |
|-----------|------|-----|
| `PK` | String | Partition Key (`EMAIL#{email}`) |
| `SK` | String | Sort Key (`LATEST`) |
| `code` | String | — |
| `createdAt` | String (ISO 8601) | — |
| `ttl` | Number | — (TTL attribute, auto-expires records) |
| `attempts` | Number | — (tracks failed verification attempts) |

---

## EventBridge Events

No events published by this service.

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | Frontend (React) | HTTP via API Gateway |
| **Depends on** | Auth (Cognito) | JWT validation for `/verify/status`; updates `email_verified` attribute |
| **Depends on** | SES | Sends verification emails |
