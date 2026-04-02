# Email Service — API Contract

**Owner:** Ni Li
**Domain:** Notifications & Engagement
**Base Path:** `/email`
**AWS Services:** SES, Lambda

---

## Endpoints

### POST /email/send

Send a templated email to a user. Internal use only (called by EventBridge rules).

**Auth:** Internal only (not exposed to frontend; invoked by EventBridge/Lambda)

**Request:**

```json
{
  "templateName": "match_notification",
  "recipientUserId": "user-456",
  "templateData": {
    "matchName": "Alex",
    "matchProfileUrl": "https://kismet.app/profile/user-123"
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `templateName` | string | Yes | One of: `welcome`, `match_notification`, `message_notification`, `weekly_digest` |
| `recipientUserId` | string | Yes | User ID of the email recipient |
| `templateData` | object | Yes | Key-value pairs for template variable substitution |

**Response (200):**

```json
{
  "emailId": "email-001",
  "templateName": "match_notification",
  "recipientUserId": "user-456",
  "status": "sent",
  "sentAt": "2026-04-01T12:00:00Z"
}
```

**Side Effects:**
- Sends email via SES using the specified template
- Respects user's email preferences (checks `kismet-email-preferences` before sending)

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | Invalid templateName or missing required templateData fields |
| 404 | `USER_NOT_FOUND` | recipientUserId does not exist |
| 422 | `EMAIL_OPTED_OUT` | User has opted out of this email type |

---

### GET /email/preferences

Get the current user's email notification preferences.

**Auth:** Required (JWT)

**Request:**

```
GET /email/preferences
```

**Response (200):**

```json
{
  "userId": "user-123",
  "matchNotifications": true,
  "messageNotifications": true,
  "weeklyDigest": true,
  "updatedAt": "2026-04-01T10:00:00Z"
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |

---

### PUT /email/preferences

Update the current user's email notification preferences.

**Auth:** Required (JWT)

**Request:**

```json
{
  "matchNotifications": true,
  "messageNotifications": false,
  "weeklyDigest": true
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `matchNotifications` | boolean | No | Receive email on new matches |
| `messageNotifications` | boolean | No | Receive email on new messages |
| `weeklyDigest` | boolean | No | Receive weekly digest email |

**Response (200):**

```json
{
  "userId": "user-123",
  "matchNotifications": true,
  "messageNotifications": false,
  "weeklyDigest": true,
  "updatedAt": "2026-04-01T12:00:00Z"
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | Invalid field values (not boolean) |
| 401 | `UNAUTHORIZED` | Not logged in |

---

## Email Templates

| Template Name | Trigger | Description |
|---------------|---------|-------------|
| `welcome` | `user.created` event | Welcome email for new users |
| `match_notification` | `match.created` event | Notification that user has a new match |
| `message_notification` | `message.sent` event | Notification that user received a new message |
| `weekly_digest` | Scheduler (Sunday 9am) | Weekly summary of activity and suggestions |
| `report_alert` | `user.reported` event | Admin alert when a user is reported |

---

## DynamoDB Table

### Table: `kismet-email-preferences`

| Attribute | Type | Key |
|-----------|------|-----|
| `PK` | String (`USER#{userId}`) | Partition Key |
| `SK` | String (`PREFS`) | Sort Key |
| `matchNotifications` | Boolean | — |
| `messageNotifications` | Boolean | — |
| `weeklyDigest` | Boolean | — |
| `updatedAt` | String (ISO 8601) | — |

---

## EventBridge Events

### Consumed: `user.created`

Triggers sending the welcome email to new users.

```json
{
  "source": "kismet.auth-service",
  "detail-type": "user.created",
  "detail": {
    "userId": "user-123",
    "email": "user@example.com",
    "timestamp": "2026-04-01T12:00:00Z"
  }
}
```

### Consumed: `match.created`

Triggers sending a match notification email (if user has matchNotifications enabled).

```json
{
  "source": "kismet.match-service",
  "detail-type": "match.created",
  "detail": {
    "matchId": "match-001",
    "userIds": ["user-123", "user-456"],
    "timestamp": "2026-04-01T12:00:00Z"
  }
}
```

### Consumed: `user.reported`

Triggers sending an alert email to admin when a user is reported.

```json
{
  "source": "kismet.report-service",
  "detail-type": "user.reported",
  "detail": {
    "reportId": "report-001",
    "reporterId": "user-123",
    "reportedUserId": "user-456",
    "reason": "harassment",
    "timestamp": "2026-04-01T14:00:00Z"
  }
}
```

---

## SES Configuration

- Requires verified sender domain or email address (e.g., `noreply@kismet.app`)
- Uses SES email templates for consistent formatting
- Handles bounce and complaint notifications via SNS

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | EventBridge rules | Lambda invocation on events |
| **Called by** | Scheduler Service | Weekly digest trigger |
| **Called by** | Frontend (React) | HTTP via API Gateway (preferences only) |
| **Consumes from** | Auth Service | EventBridge `user.created` |
| **Consumes from** | Match Service | EventBridge `match.created` |
| **Consumes from** | Report Service | EventBridge `user.reported` |
| **Depends on** | Auth (Cognito) | JWT validation via API Gateway Authorizer |
| **Uses** | SES | Email delivery |
