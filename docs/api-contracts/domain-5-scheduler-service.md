# Scheduler Service — API Contract

**Owner:** Xiaoyuan
**Domain:** Notifications & Engagement
**Base Path:** `/scheduler`
**AWS Services:** EventBridge Scheduler, Step Functions, Lambda

---

## Endpoints

### GET /scheduler/jobs

List all scheduled jobs.

**Auth:** Required (JWT, Admin only)

**Request:**

```
GET /scheduler/jobs
```

**Response (200):**

```json
{
  "jobs": [
    {
      "jobId": "job-001",
      "jobType": "weekly_digest",
      "schedule": "cron(0 9 ? * SUN *)",
      "description": "Send weekly digest email every Sunday at 9am",
      "state": "ENABLED",
      "lastRunAt": "2026-03-29T09:00:00Z",
      "nextRunAt": "2026-04-05T09:00:00Z"
    },
    {
      "jobId": "job-002",
      "jobType": "stale_match_cleanup",
      "schedule": "rate(1 day)",
      "description": "Archive matches with no messages after 30 days",
      "state": "ENABLED",
      "lastRunAt": "2026-04-01T00:00:00Z",
      "nextRunAt": "2026-04-02T00:00:00Z"
    },
    {
      "jobId": "job-003",
      "jobType": "analytics_aggregation",
      "schedule": "rate(1 hour)",
      "description": "Trigger Activity Logger to flush analytics data",
      "state": "ENABLED",
      "lastRunAt": "2026-04-01T11:00:00Z",
      "nextRunAt": "2026-04-01T12:00:00Z"
    },
    {
      "jobId": "job-004",
      "jobType": "health_check",
      "schedule": "rate(5 minutes)",
      "description": "Trigger Health Monitor to check all services",
      "state": "ENABLED",
      "lastRunAt": "2026-04-01T11:55:00Z",
      "nextRunAt": "2026-04-01T12:00:00Z"
    }
  ],
  "count": 4
}
```

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | Not an admin user |

---

### POST /scheduler/jobs

Create a new scheduled job.

**Auth:** Required (JWT, Admin only)

**Request:**

```json
{
  "jobType": "weekly_digest",
  "schedule": "cron(0 9 ? * SUN *)",
  "params": {
    "templateName": "weekly_digest",
    "targetService": "email-service"
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `jobType` | string | Yes | Type of job: `weekly_digest`, `stale_match_cleanup`, `analytics_aggregation`, `health_check` |
| `schedule` | string | Yes | EventBridge Scheduler expression (cron or rate) |
| `params` | object | No | Additional parameters for the job |

**Response (201):**

```json
{
  "jobId": "job-005",
  "jobType": "weekly_digest",
  "schedule": "cron(0 9 ? * SUN *)",
  "params": {
    "templateName": "weekly_digest",
    "targetService": "email-service"
  },
  "state": "ENABLED",
  "createdAt": "2026-04-01T12:00:00Z",
  "nextRunAt": "2026-04-05T09:00:00Z"
}
```

**Side Effects:**
- Creates an EventBridge Scheduler schedule
- For multi-step jobs, creates a Step Functions state machine
- Writes job metadata to DynamoDB `kismet-scheduler`

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `VALIDATION_ERROR` | Invalid jobType or schedule expression |
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | Not an admin user |
| 409 | `CONFLICT` | A job with the same jobType and schedule already exists |

---

### DELETE /scheduler/jobs/{jobId}

Delete a scheduled job.

**Auth:** Required (JWT, Admin only)

**Request:**

```
DELETE /scheduler/jobs/job-005
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `jobId` | string (path) | Yes | The job ID to delete |

**Response (200):**

```json
{
  "jobId": "job-005",
  "deleted": true,
  "deletedAt": "2026-04-01T12:30:00Z"
}
```

**Side Effects:**
- Deletes the EventBridge Scheduler schedule
- Deletes associated Step Functions state machine (if any)
- Removes job metadata from DynamoDB `kismet-scheduler`

**Errors:**

| Status | Code | Condition |
|--------|------|-----------|
| 401 | `UNAUTHORIZED` | Not logged in |
| 403 | `FORBIDDEN` | Not an admin user |
| 404 | `NOT_FOUND` | Job does not exist |

---

## Scheduled Jobs

| Job Type | Schedule | Description | Target |
|----------|----------|-------------|--------|
| `weekly_digest` | Every Sunday 9am (`cron(0 9 ? * SUN *)`) | Send weekly digest email to all users | Email Service |
| `stale_match_cleanup` | Daily (`rate(1 day)`) | Archive matches with no messages after 30 days | Match Service |
| `analytics_aggregation` | Hourly (`rate(1 hour)`) | Trigger Activity Logger to flush buffered analytics | Activity Logger |
| `health_check` | Every 5 minutes (`rate(5 minutes)`) | Trigger Health Monitor to check all services | Health Monitor |

---

## DynamoDB Table

### Table: `kismet-scheduler`

| Attribute | Type | Key |
|-----------|------|-----|
| `PK` | String (`JOB#{jobId}`) | Partition Key |
| `SK` | String (`META`) | Sort Key |
| `jobType` | String | — |
| `schedule` | String | — |
| `description` | String | — |
| `params` | Map | — |
| `state` | String | — |
| `lastRunAt` | String (ISO 8601) | — |
| `nextRunAt` | String (ISO 8601) | — |
| `createdAt` | String (ISO 8601) | — |

---

## Architecture

- **EventBridge Scheduler** handles all cron and rate-based triggers
- **Step Functions** orchestrates multi-step workflows (e.g., weekly digest: query users -> batch emails -> send via SES)
- **Lambda** functions serve as the glue between Scheduler triggers and target services

---

## Dependencies

| Direction | Service | How |
|-----------|---------|-----|
| **Called by** | Admin Dashboard | HTTP via API Gateway |
| **Triggers** | Email Service | Weekly digest job |
| **Triggers** | Match Service | Stale match cleanup job |
| **Triggers** | Activity Logger | Analytics aggregation job |
| **Triggers** | Health Monitor | Health check job |
| **Depends on** | Auth (Cognito) | JWT validation via API Gateway Authorizer |
