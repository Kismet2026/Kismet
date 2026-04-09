# Scheduler Service

**Owner(s):** Xiaoyuan
**Domain:** Notifications & Engagement (Domain 5)
**Status:** 🟡 In progress

## Description

Manages timed jobs (weekly digest, stale match cleanup, analytics aggregation, health checks) using EventBridge Scheduler. Publishes events to the `kismet-events` bus so target services can react.

## AWS Services Used

- **Lambda** — Admin API handlers + job executor
- **EventBridge Scheduler** — Cron/rate-based schedule triggers
- **EventBridge** — Publishes job-trigger events to `kismet-events` bus
- **DynamoDB** — `kismet-scheduler` table stores job metadata

## Scheduled Jobs (Built-in)

| Job Type | Schedule | Target |
|----------|----------|--------|
| `weekly_digest` | Every Sunday 9am (`cron(0 9 ? * SUN *)`) | Email Service |
| `stale_match_cleanup` | Daily (`rate(1 day)`) | Match Service |
| `analytics_aggregation` | Hourly (`rate(1 hour)`) | Activity Logger |
| `health_check` | Every 5 min (`rate(5 minutes)`) | Health Monitor |

## API Endpoints

### GET /scheduler/jobs
List all scheduled jobs.

**Auth:** Admin only

### POST /scheduler/jobs
Create a new scheduled job.

**Auth:** Admin only

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

### DELETE /scheduler/jobs/{jobId}
Delete a scheduled job.

**Auth:** Admin only

## Dependencies

- **Depends on:** Auth (Cognito) for JWT validation
- **Called by:** Admin Dashboard (HTTP via API Gateway)
- **Triggers:** Email Service (weekly digest), Match Service (stale cleanup), Activity Logger (analytics), Health Monitor (health check)
- **Events published:** `scheduler.weekly_digest`, `scheduler.stale_match_cleanup`, `scheduler.analytics_aggregation`, `scheduler.health_check`

## Setup

```bash
# Deploy (via unified CDK from infra/)
cd infra/
pip install -r requirements.txt
cdk deploy KismetDomain5
```

## Testing

```bash
# Unit tests
cd services/domain-5-notifications/scheduler-service/
python -m pytest tests/ -v

# Manual: invoke executor directly
aws lambda invoke \
  --function-name kismet-scheduler-executor-dev \
  --payload '{"jobType": "health_check"}' \
  output.json
```
