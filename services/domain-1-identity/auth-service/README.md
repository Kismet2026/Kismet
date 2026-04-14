# Auth Service

**Owner(s):** Quinn Gao
**Domain:** Identity & Profiles
**Status:** 🟢 Deployed

## Description
Handles Cognito-backed sign-up, email confirmation, login, token refresh, and logout for Kismet users.

## AWS Services Used
- Lambda — routes `/auth/*` requests and hosts service logic
- Cognito — identity store, email confirmation, and JWT/token management
- DynamoDB — persists auth-side user metadata in `kismet-users`
- EventBridge — publishes `user.created`

## Scaffold Status
- Service logic is implemented in `lambda_function.py`.
- Cognito sends the verification code during signup, and clients confirm with `POST /auth/confirm`.
- Unit tests cover success paths plus common Cognito error handling.

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

### POST /auth/confirm
**Request:**
```json
{
  "email": "student@university.edu",
  "code": "123456"
}
```
**Response:**
```json
{
  "message": "Email confirmed successfully"
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
- Legacy `/verify/*` docs describe the removed SES-based verification flow and are kept only as historical reference.
- The deployed signup flow is Cognito-native: `POST /auth/signup` sends the code and `POST /auth/confirm` completes verification.

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
