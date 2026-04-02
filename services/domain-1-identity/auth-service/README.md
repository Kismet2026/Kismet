# Auth Service

**Owner(s):** Quinn Gao
**Domain:** Identity & Profiles
**Status:** 🟡 In progress

## Description
Handles account sign-up, login, token refresh, and logout for Kismet users.

## AWS Services Used
- Lambda — route `/auth/*` requests and host service logic
- Cognito — primary identity store and JWT/token management
- DynamoDB — planned persistence for auth-side user metadata in `kismet-users`
- EventBridge — planned publication of `user.created`

## Scaffold Status
- Week 1 skeleton is in place.
- All documented routes are wired in `lambda_function.py`.
- Each route currently returns `501 NOT_IMPLEMENTED` until Week 2 service logic is built.

## API Endpoints

### POST /auth/signup
**Request:**
```json
{
  "email": "student@university.edu",
  "password": "SecureP@ss123",
  "birthDate": "1999-05-15",
  "birthTime": "14:30"
}
```
**Response:**
```json
{
  "userId": "user-123",
  "email": "student@university.edu",
  "createdAt": "2026-04-01T12:00:00Z"
}
```

### POST /auth/login
**Request:**
```json
{
  "email": "student@university.edu",
  "password": "SecureP@ss123"
}
```
**Response:**
```json
{
  "accessToken": "eyJhbGciOiJSUzI1NiIs...",
  "refreshToken": "eyJjdHkiOiJKV1Qi...",
  "idToken": "eyJhbGciOiJSUzI1NiIs...",
  "expiresIn": 3600
}
```

### POST /auth/refresh
**Request:**
```json
{
  "refreshToken": "eyJjdHkiOiJKV1Qi..."
}
```
**Response:**
```json
{
  "accessToken": "eyJhbGciOiJSUzI1NiIs...",
  "expiresIn": 3600
}
```

### POST /auth/logout
**Request:**
```json
{
  "refreshToken": "eyJjdHkiOiJKV1Qi..."
}
```
**Response:**
```json
{
  "message": "Successfully logged out"
}
```

## Dependencies
- **Depends on:** Shared API Gateway, Cognito user pool/app client, `kismet-users` table, `kismet-events` EventBridge bus
- **Called by:** Frontend (React) via `/auth/*`
- **Events published:** `user.created`
- **Events consumed:** None

## Integration Notes
- `docs/api-contracts/domain-1-auth-service.md` says `user.created` is consumed by Profile Service and Email Verification Service.
- `docs/event-schema.json` and `docs/Infrastructure_Design.md` currently list Email Service and Activity Logger instead.
- Confirm the downstream consumers before implementing event publication in Week 2.

## Setup
```bash
cd services/domain-1-identity/auth-service
sam build
sam deploy --guided
```

Environment variables expected by the scaffold:
- `COGNITO_USER_POOL_ID`
- `COGNITO_APP_CLIENT_ID`
- `USERS_TABLE_NAME`
- `EVENT_BUS_NAME`

## Testing
```bash
cd services/domain-1-identity/auth-service
python -m unittest discover -s tests -v
```
