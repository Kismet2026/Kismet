# Auth Service — API Contract

**Owner:** Quinn Gao
**Domain:** Identity & Profiles
**Base Path:** `/auth`
**AWS Services:** Cognito, Lambda

---

## Endpoints

### POST /auth/signup

Register a new user account in Cognito.

**Auth:** Not required

**Request:**

```json
{
  "email": "student@university.edu",
  "password": "SecureP@ss123",
  "birthDate": "1999-05-15",
  "birthTime": "14:30"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `email` | string | Yes | Email address used as the Cognito username |
| `password` | string | Yes | Password validated by Cognito |
| `birthDate` | string | No | Optional ISO 8601 date (YYYY-MM-DD) stored in `kismet-users` |
| `birthTime` | string | No | 24-hour time format (HH:mm), used for astrology features |

**Response (201):**

```json
{
  "userId": "user-123",
  "email": "student@university.edu",
  "createdAt": "2026-04-01T12:00:00Z"
}
```

**Side Effects:**
- Creates user record in Cognito user pool
- Writes to DynamoDB `kismet-users` table
- Publishes EventBridge event `user.created`
- Triggers Cognito to send an email confirmation code; the client must then call `POST /auth/confirm`

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | Missing required fields or Cognito rejected a parameter |
| 409 | `CONFLICT` | Email already registered |
| 429 | `RATE_LIMITED` | Cognito rate-limited the request |

---

### POST /auth/confirm

Confirm the Cognito signup code sent during `POST /auth/signup`.

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
| `email` | string | Yes | Email address used during signup |
| `code` | string | Yes | Cognito confirmation code from email |

**Response (200):**

```json
{
  "message": "Email confirmed successfully"
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | Missing email/code or invalid confirmation code |
| 404 | `NOT_FOUND` | No Cognito user exists for that email |
| 410 | `EXPIRED` | Confirmation code expired |
| 429 | `RATE_LIMITED` | Cognito rate-limited the request |

---

### POST /auth/login

Authenticate a user and return JWT tokens.

**Auth:** Not required

**Request:**

```json
{
  "email": "student@university.edu",
  "password": "SecureP@ss123"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `email` | string | Yes | Registered email address |
| `password` | string | Yes | User password |

**Response (200):**

```json
{
  "accessToken": "eyJhbGciOiJSUzI1NiIs...",
  "refreshToken": "eyJjdHkiOiJKV1Qi...",
  "idToken": "eyJhbGciOiJSUzI1NiIs...",
  "expiresIn": 3600
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | Missing email or password |
| 401 | `UNAUTHORIZED` | Email or password incorrect |
| 403 | `FORBIDDEN` | Account email has not been confirmed yet |

---

### POST /auth/refresh

Refresh an expired access token using a valid refresh token.

**Auth:** Not required

**Request:**

```json
{
  "refreshToken": "eyJjdHkiOiJKV1Qi..."
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `refreshToken` | string | Yes | Valid refresh token from login |

**Response (200):**

```json
{
  "accessToken": "eyJhbGciOiJSUzI1NiIs...",
  "expiresIn": 3600
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | Missing refreshToken |
| 401 | `UNAUTHORIZED` | Refresh token is invalid or revoked |

---

### POST /auth/logout

Invalidate the current session by revoking the refresh token.

**Auth:** Not required

**Request:**

```json
{
  "refreshToken": "eyJjdHkiOiJKV1Qi..."
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `refreshToken` | string | Yes | Refresh token to invalidate |

**Response (200):**

```json
{
  "message": "Successfully logged out"
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | Missing refreshToken |
| 401 | `UNAUTHORIZED` | Refresh token is invalid or already revoked |

---

## DynamoDB Table

**Table:** `kismet-users`

| Attribute | Type | Key |
|-----------|------|-----|
| `PK` | String | Partition Key (`USER#{userId}`) |
| `SK` | String | Sort Key (`METADATA`) |
| `email` | String | — |
| `birthDate` | String (ISO 8601) | — |
| `birthTime` | String | — |
| `createdAt` | String (ISO 8601) | — |

## EventBridge Events

### Published: `user.created`

Published when a new user successfully signs up.

```json
{
  "source": "kismet.auth-service",
  "detail-type": "user.created",
  "detail": {
    "userId": "user-123",
    "email": "student@university.edu",
    "timestamp": "2026-04-01T12:00:00Z"
  }
}
```

**Consumed by:** Downstream subscribers on the shared `kismet-events` bus

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | Frontend (React) | HTTP via API Gateway |
| **Publishes to** | Shared event bus subscribers | EventBridge `user.created` |
| **Depends on** | Cognito | User pool for authentication |
