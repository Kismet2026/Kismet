# Profile Service

**Owner(s):** Quinn Gao
**Domain:** Identity & Profiles
**Status:** 🟡 In progress

## Description
Stores and manages user profile data for create, read, update, and delete profile workflows.

## AWS Services Used
- Lambda — route `/profiles/*` requests and host profile CRUD logic
- DynamoDB — store profile records in `kismet-profiles`
- EventBridge — planned publication of `profile.completed`
- Cognito authorizer — planned JWT enforcement through shared API Gateway

## Scaffold Status
- Week 1 skeleton is in place.
- All documented routes are wired in `lambda_function.py`.
- `template.yaml` includes both the Lambda function and the `kismet-profiles` DynamoDB table scaffold.
- Each route currently returns `501 NOT_IMPLEMENTED` until Week 2 service logic is built.

## API Endpoints

### POST /profiles
**Request:**
```json
{
  "name": "Alice",
  "bio": "Astronomy major who loves stargazing",
  "gender": "female",
  "interestedIn": "male",
  "birthDate": "1999-05-15",
  "birthTime": "14:30",
  "location": {
    "latitude": 42.3601,
    "longitude": -71.0589
  },
  "interests": ["astronomy", "hiking", "coffee"]
}
```
**Response:**
```json
{
  "userId": "user-123",
  "name": "Alice",
  "createdAt": "2026-04-01T12:00:00Z"
}
```

### GET /profiles/{userId}
**Request:**
```json
{}
```
**Response:**
```json
{
  "userId": "user-123",
  "name": "Alice",
  "bio": "Astronomy major who loves stargazing",
  "updatedAt": "2026-04-01T12:00:00Z"
}
```

### PUT /profiles/{userId}
**Request:**
```json
{
  "bio": "Updated bio text",
  "interests": ["astronomy", "yoga"]
}
```
**Response:**
```json
{
  "userId": "user-123",
  "bio": "Updated bio text",
  "updatedAt": "2026-04-01T13:00:00Z"
}
```

### DELETE /profiles/{userId}
**Request:**
```json
{}
```
**Response:**
```json
{
  "message": "Profile deleted successfully"
}
```

## Dependencies
- **Depends on:** Shared API Gateway/Cognito authorizer, `kismet-profiles` table, `kismet-events` EventBridge bus
- **Called by:** Frontend (React), plus downstream services that fetch profile data via `/profiles/{userId}`
- **Events published:** `profile.completed`
- **Events consumed:** None

## Integration Notes
- `docs/api-contracts/domain-1-profile-service.md` lists Discovery Service and Astrology Service as `profile.completed` consumers.
- `docs/event-schema.json`, `docs/PRD.md`, and `docs/Infrastructure_Design.md` currently list Recommendation Service and Activity Logger instead.
- `docs/Infrastructure_Design.md` section 3.1 also lists `kismet-users` under Profile Service, while the profile API contract defines `kismet-profiles`.
- Confirm the final event consumers and table name before deployment wiring in Week 2.

## Setup
```bash
cd services/domain-1-identity/profile-service
sam build
sam deploy --guided
```

Environment variables expected by the scaffold:
- `PROFILES_TABLE_NAME`
- `EVENT_BUS_NAME`

## Testing
```bash
cd services/domain-1-identity/profile-service
python -m unittest discover -s tests -v
```
