# Email Verification Service

**Owner(s):** Zhiping
**Domain:** Identity & Profiles
**Status:** ⚪ Legacy / not deployed

## Description
Historical scaffold for a custom SES-based verification flow. It is no longer part of the deployed Domain 1 stack.

The deployed flow is now Cognito-native:
- `POST /auth/signup` sends the confirmation code
- `POST /auth/confirm` confirms the code

## AWS Services Used
- Lambda — historical `/verify/*` handlers kept in repo as reference
- SES — historical delivery mechanism for custom verification emails
- Cognito — historical lookup/update of `email_verified` state
- DynamoDB — historical TTL-backed storage for verification codes in `kismet-verifications`

## Scaffold Status
- The code remains in the repo as a legacy scaffold and test fixture.
- The service is not wired into `infra/stacks/domain1_stack.py`.
- The live API does not expose `/verify/*` routes.

## API Endpoints

### POST /verify/send
**Request:**
```json
{
  "email": "student@university.edu"
}
```
**Response:**
```json
{
  "message": "Verification code sent",
  "email": "student@university.edu",
  "expiresIn": 600
}
```

### POST /verify/confirm
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
  "message": "Email verified successfully",
  "email": "student@university.edu",
  "verified": true
}
```

### GET /verify/status
**Request:**
```json
{}
```
**Response:**
```json
{
  "email": "student@university.edu",
  "verified": true,
  "verifiedAt": "2026-04-01T12:05:00Z"
}
```

## Dependencies
- **Depends on:** Historical shared API Gateway/Cognito authorizer, Cognito user pool, SES sender identity, `kismet-verifications` table
- **Called by:** No deployed clients
- **Events published:** None
- **Events consumed:** None documented in this scaffold

## Integration Notes
- This service was superseded because the custom SES flow conflicted with Cognito's native signup confirmation.
- Prefer `services/domain-1-identity/auth-service` and `docs/api-contracts/domain-1-auth-service.md` for the current verification behavior.

## Setup
```bash
cd services/domain-1-identity/email-verification-service
sam build
sam deploy --guided
```

Environment variables expected by the scaffold:
- `COGNITO_USER_POOL_ID`
- `VERIFICATIONS_TABLE_NAME`
- `SES_SOURCE_EMAIL`

## Testing
```bash
cd services/domain-1-identity/email-verification-service
python -m unittest discover -s tests -v
```
