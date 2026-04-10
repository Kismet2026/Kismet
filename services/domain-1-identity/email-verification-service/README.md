# Email Verification Service

**Owner(s):** Zhiping
**Domain:** Identity & Profiles
**Status:** 🟡 In progress

## Description
Sends `.edu` verification codes, confirms submitted codes, and exposes the current email verification state.

## AWS Services Used
- Lambda — route `/verify/*` requests and host service logic
- SES — planned delivery of verification codes
- Cognito — planned lookup/update of `email_verified` state
- DynamoDB — planned TTL-backed storage for verification codes in `kismet-verifications`

## Scaffold Status
- Week 1 skeleton is in place.
- All documented routes are wired in `lambda_function.py`.
- `template.yaml` includes both the Lambda function and the `kismet-verifications` DynamoDB table scaffold.
- Each route currently returns `501 NOT_IMPLEMENTED` until Week 2 service logic is built.

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
- **Depends on:** Shared API Gateway/Cognito authorizer, Cognito user pool, SES sender identity, `kismet-verifications` table
- **Called by:** Frontend (React) via `/verify/*`
- **Events published:** None
- **Events consumed:** None documented in this scaffold

## Integration Notes
- `docs/api-contracts/domain-1-auth-service.md` says Auth publishes `user.created` for Email Verification Service, but the email verification API contract currently documents only HTTP routes. Confirm whether signup should auto-trigger verification emails in Week 2.
- `docs/api-contracts/domain-1-email-verification-service.md` defines a `kismet-verifications` DynamoDB table, but `docs/system-design/Infrastructure_Design.md` does not currently list that table in section 3.1.
- `infra/stacks/shared_stack.py` enables Cognito `auto_verify=email`, which conflicts with the manual verification flow described in the email verification API contract. Confirm the intended Cognito configuration before implementing business logic.

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
