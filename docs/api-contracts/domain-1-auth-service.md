# Auth Service — API Contract

**Owner:** Quinn Gao
**Domain:** Identity & Profiles
**Base Path:** `/auth`
**AWS Services:** Cognito, Lambda

---

## Endpoints

### POST /auth/signup

Register a new user account. Requires a valid .edu email address.

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
| `email` | string | Yes | Must be a valid .edu email address |
| `password` | string | Yes | Minimum 8 characters, must include uppercase, lowercase, number |
| `birthDate` | string | Yes | ISO 8601 date format (YYYY-MM-DD) |
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

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | Missing required fields or invalid format |
| 400 | `INVALID_EMAIL` | Email is not a .edu address |
| 409 | `CONFLICT` | Email already registered |

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
| `email` | string | Yes | Registered .edu email address |
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
| 401 | `INVALID_CREDENTIALS` | Email or password incorrect |
| 403 | `ACCOUNT_DISABLED` | Account has been disabled |

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
| 401 | `TOKEN_EXPIRED` | Refresh token has expired |
| 401 | `TOKEN_INVALID` | Refresh token is invalid or revoked |

---

### POST /auth/logout

Invalidate the current session by revoking the refresh token.

**Auth:** Required (JWT)

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
| 401 | `UNAUTHORIZED` | Not logged in |

---

## DynamoDB Table

**Table:** `kismet-users`

| Attribute | Type | Key |
|-----------|------|-----|
| `PK` | String | Partition Key (`USER#{userId}`) |
| `SK` | String | Sort Key (`AUTH`) |
| `email` | String | — |
| `birthDate` | String (ISO 8601) | — |
| `birthTime` | String | — |
| `createdAt` | String (ISO 8601) | — |

**GSI:** `email-index` — Look up user by email

---

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
    "birthDate": "1999-05-15",
    "birthTime": "14:30",
    "createdAt": "2026-04-01T12:00:00Z"
  }
}
```

**Consumed by:** Profile Service, Email Verification Service

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | Frontend (React) | HTTP via API Gateway |
| **Publishes to** | Profile Service, Email Verification Service | EventBridge `user.created` |
| **Depends on** | Cognito | User pool for authentication |
