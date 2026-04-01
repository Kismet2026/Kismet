# Health Monitor Service — API Contract

**Owner:** Lingyun Xiao
**Domain:** Domain 6 — Analytics & Admin
**AWS Services:** CloudWatch, Lambda, SNS
**Status:** 🟡 In Progress

## Description

Monitors the health of all 25 microservices by polling CloudWatch metrics every 5 minutes. Sends SNS alert when any service exceeds error or latency thresholds.

## Trigger

This service is **not triggered by API Gateway**. It runs on a schedule:

```
EventBridge Scheduler → Lambda (every 5 minutes)
```

---

## Health Check Logic

For each Lambda function across all 25 services, the monitor checks two CloudWatch metrics over the past 5 minutes:

| Metric           | Threshold | Action         |
| ---------------- | --------- | -------------- |
| `Errors` rate    | > 5%      | Send SNS alert |
| `Duration` (p99) | > 5000ms  | Send SNS alert |

---

## SNS Alert Format

When a threshold is exceeded, the following message is published to the `kismet-health-alerts` SNS topic:

```json
{
  "alertId": "alert_abc123",
  "service": "bazi-service",
  "lambdaFunction": "kismet-bazi-service-prod",
  "metric": "ErrorRate",
  "value": 12.5,
  "threshold": 5.0,
  "status": "ALARM",
  "detectedAt": "2026-03-31T10:05:00Z"
}
```

SNS subscribers (email) will receive this alert automatically.

---

## Services Monitored

| Lambda Function Name                 | Service                    |
| ------------------------------------ | -------------------------- |
| `kismet-auth-service-prod`           | auth-service               |
| `kismet-profile-service-prod`        | profile-service            |
| `kismet-photo-service-prod`          | photo-service              |
| `kismet-email-verification-prod`     | email-verification-service |
| `kismet-discovery-service-prod`      | discovery-service          |
| `kismet-swipe-service-prod`          | swipe-service              |
| `kismet-match-service-prod`          | match-service              |
| `kismet-recommendation-service-prod` | recommendation-service     |
| `kismet-bazi-service-prod`           | bazi-service               |
| `kismet-chat-gateway-prod`           | chat-gateway               |
| `kismet-message-service-prod`        | message-service            |
| `kismet-presence-service-prod`       | presence-service           |
| `kismet-icebreaker-service-prod`     | icebreaker-service         |
| `kismet-text-moderation-prod`        | text-moderation-service    |
| `kismet-image-moderation-prod`       | image-moderation-service   |
| `kismet-report-service-prod`         | report-service             |
| `kismet-rate-limiter-prod`           | rate-limiter-service       |
| `kismet-push-notification-prod`      | push-notification-service  |
| `kismet-email-service-prod`          | email-service              |
| `kismet-event-bus-prod`              | event-bus-service          |
| `kismet-scheduler-service-prod`      | scheduler-service          |
| `kismet-activity-logger-prod`        | activity-logger-service    |
| `kismet-analytics-pipeline-prod`     | analytics-pipeline-service |
| `kismet-admin-dashboard-prod`        | admin-dashboard-service    |
| `kismet-health-monitor-prod`         | health-monitor-service     |

> **Note:** Lambda function names must be confirmed with each service owner before deployment.

---

## Admin Query Endpoint (Optional)

A read-only endpoint to fetch current health status of all services.

### GET /admin/health

**Response:**

```json
{
  "checkedAt": "2026-03-31T10:05:00Z",
  "services": [
    {
      "service": "auth-service",
      "lambdaFunction": "kismet-auth-service-prod",
      "status": "OK",
      "errorRate": 0.0,
      "p99Duration": 45
    },
    {
      "service": "bazi-service",
      "lambdaFunction": "kismet-bazi-service-prod",
      "status": "ALARM",
      "errorRate": 12.5,
      "p99Duration": 3200
    }
  ]
}
```

---

## Dependencies

- **Depends on:** CloudWatch (reads metrics for all Lambda functions), SNS (publishes alerts)
- **Called by:** EventBridge Scheduler (every 5 minutes)
- **Events published:** None (uses SNS directly)
- **Events consumed:** None
