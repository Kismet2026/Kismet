# Event Bus Service

**Owner(s):** Xiaoyuan
**Domain:** Notifications & Engagement (Domain 5)
**Status:** 🟡 In progress

## Description

Central EventBridge routing hub that logs all cross-domain events for debugging and provides admin endpoints for querying event history and replaying failed events.

## AWS Services Used

- **Lambda** — Catch-all event logger + admin API handlers
- **EventBridge** — `kismet-events` bus; catch-all rule routes all events to the logger
- **DynamoDB** — `kismet-event-log` table stores every event for debugging/replay

## API Endpoints

### GET /events/rules
List all active EventBridge rules on the kismet-events bus.

**Auth:** Admin only

### GET /events/history
Query recent events from the event log.

**Auth:** Admin only

**Query params:** `source`, `detailType`, `limit` (max 100, default 20)

### POST /events/replay
Re-publish a failed event by its eventId.

**Auth:** Admin only

**Request:**
```json
{
  "eventId": "evt-003"
}
```

## Dependencies

- **Depends on:** Auth (Cognito) for JWT validation
- **Called by:** Admin Dashboard (HTTP via API Gateway)
- **Receives from:** All Kismet services (EventBridge events on `kismet-events` bus)
- **Routes to:** Push Notification, Email, Activity Logger, etc. (EventBridge rules)

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
cd services/domain-5-notifications/event-bus-service/
python -m pytest tests/ -v

# Manual: publish a test event
aws events put-events --entries '[{
  "Source": "kismet.match-service",
  "DetailType": "match.created",
  "Detail": "{\"matchId\":\"test-001\",\"userIds\":[\"u1\",\"u2\"],\"timestamp\":\"2026-04-01T12:00:00Z\"}",
  "EventBusName": "kismet-events"
}]'
```
