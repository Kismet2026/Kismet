# Profile Service — API Contract

**Owner:** Quinn Gao
**Domain:** Identity & Profiles
**Base Path:** `/profiles`
**AWS Services:** Lambda, DynamoDB

---

## Endpoints

### POST /profiles

Create a new user profile. Users can only create a profile for themselves.

**Auth:** Required (JWT)

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

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Display name |
| `bio` | string | No | Short bio (max 500 characters) |
| `gender` | string | Yes | `"male"`, `"female"`, or `"non-binary"` |
| `interestedIn` | string | Yes | `"male"`, `"female"`, `"non-binary"`, or `"everyone"` |
| `birthDate` | string | Yes | ISO 8601 date format (YYYY-MM-DD) |
| `birthTime` | string | No | 24-hour time format (HH:mm) |
| `location` | object | Yes | `{ latitude, longitude }` |
| `interests` | string[] | No | List of interest tags (max 10) |

**Response (201):**

```json
{
  "userId": "user-123",
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
  "interests": ["astronomy", "hiking", "coffee"],
  "createdAt": "2026-04-01T12:00:00Z"
}
```

**Side Effects:**
- Writes to DynamoDB `kismet-profiles` table
- Publishes EventBridge event `profile.completed` (first creation only)

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | Missing required fields or invalid format |
| 401 | `UNAUTHORIZED` | Not logged in |
| 409 | `CONFLICT` | Profile already exists for this user |

---

### GET /profiles/{userId}

Retrieve a user's profile by user ID.

**Auth:** Required (JWT)

**Request:**

```
GET /profiles/user-123
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `userId` | string (path) | Yes | Target user ID |

**Response (200):**

```json
{
  "userId": "user-123",
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
  "interests": ["astronomy", "hiking", "coffee"],
  "createdAt": "2026-04-01T12:00:00Z",
  "updatedAt": "2026-04-01T12:00:00Z"
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 404 | `NOT_FOUND` | Profile does not exist |

---

### PUT /profiles/{userId}

Update an existing profile. Supports partial updates. Users can only update their own profile.

**Auth:** Required (JWT)

**Request:**

```json
{
  "bio": "Updated bio text",
  "interests": ["astronomy", "yoga"]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | No | Display name |
| `bio` | string | No | Short bio (max 500 characters) |
| `gender` | string | No | `"male"`, `"female"`, or `"non-binary"` |
| `interestedIn` | string | No | `"male"`, `"female"`, `"non-binary"`, or `"everyone"` |
| `location` | object | No | `{ latitude, longitude }` |
| `interests` | string[] | No | List of interest tags (max 10) |

**Response (200):**

```json
{
  "userId": "user-123",
  "name": "Alice",
  "bio": "Updated bio text",
  "gender": "female",
  "interestedIn": "male",
  "birthDate": "1999-05-15",
  "birthTime": "14:30",
  "location": {
    "latitude": 42.3601,
    "longitude": -71.0589
  },
  "interests": ["astronomy", "yoga"],
  "createdAt": "2026-04-01T12:00:00Z",
  "updatedAt": "2026-04-01T13:00:00Z"
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | Invalid field format |
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | Attempting to update another user's profile |
| 404 | `NOT_FOUND` | Profile does not exist |

---

### DELETE /profiles/{userId}

Delete a user's profile. Users can only delete their own profile.

**Auth:** Required (JWT)

**Request:**

```
DELETE /profiles/user-123
```

**Response (200):**

```json
{
  "message": "Profile deleted successfully"
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | Attempting to delete another user's profile |
| 404 | `NOT_FOUND` | Profile does not exist |

---

## DynamoDB Table

**Table:** `kismet-profiles`

| Attribute | Type | Key |
|-----------|------|-----|
| `PK` | String | Partition Key (`USER#{userId}`) |
| `SK` | String | Sort Key (`PROFILE`) |
| `name` | String | — |
| `bio` | String | — |
| `gender` | String | — |
| `interestedIn` | String | — |
| `birthDate` | String (ISO 8601) | — |
| `birthTime` | String | — |
| `location` | Map | — |
| `interests` | List | — |
| `createdAt` | String (ISO 8601) | — |
| `updatedAt` | String (ISO 8601) | — |

---

## EventBridge Events

### Published: `profile.completed`

Published when a user creates their profile for the first time.

```json
{
  "source": "kismet.profile-service",
  "detail-type": "profile.completed",
  "detail": {
    "userId": "user-123",
    "name": "Alice",
    "gender": "female",
    "interestedIn": "male",
    "birthDate": "1999-05-15",
    "birthTime": "14:30",
    "createdAt": "2026-04-01T12:00:00Z"
  }
}
```

**Consumed by:** Discovery Service, Astrology Service

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | Frontend (React) | HTTP via API Gateway |
| **Publishes to** | Discovery Service, Astrology Service | EventBridge `profile.completed` |
| **Depends on** | Auth (Cognito) | JWT validation via API Gateway Authorizer |
