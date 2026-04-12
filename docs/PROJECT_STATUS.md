# Kismet — Project Status

> Last updated: 2026-04-10

---

## Deployment Status

| Stack | Status | Notes |
|-------|--------|-------|
| **SharedStack** | Deployed | Cognito, API Gateway, EventBridge, S3, CloudFront, Kinesis, SNS |
| **KismetDomain1** | Deployed | Identity & Profiles — 4 Lambdas, 4 DynamoDB tables |
| **KismetDomain2** | Deployed | Discovery & Matching — 5 Lambdas, 5 DynamoDB tables |
| **KismetDomain3** | Blocked | API Gateway path variable conflict (Issue #83) |
| **KismetDomain4** | Deployed | Safety & Moderation — 4 Lambdas, 3 DynamoDB tables |
| **KismetDomain5** | Deployed | Notifications & Engagement — 4 Lambdas, 2 DynamoDB tables |
| **KismetDomain6** | Deployed | Analytics & Admin — 4 Lambdas, 2 DynamoDB tables |

**6 of 7 stacks live.** D3 blocked by API Gateway siblings having different path variable names under the same parent (e.g., `/messages/{matchId}` vs `/messages/{messageId}`). Tracked in Issue #83.

---

## Infrastructure

- **IaC**: AWS CDK (Python), fully migrated from SAM (template.yaml files deleted)
- **Reusable construct**: `KismetService` — single construct creates Lambda + DynamoDB + IAM + EventBridge rules + API Gateway routes for each service
- **Deploy command**: `cd infra && npx cdk deploy <StackName> --app "python3 app.py"`
- **Shared resources**: Cognito User Pool (`us-east-1_c20sP0XJb`), API Gateway (REST + WebSocket), EventBridge bus (`kismet-events`), S3 photos bucket, CloudFront distribution, Kinesis stream, SNS topic

---

## API Base URL

```
https://ugt4knycyj.execute-api.us-east-1.amazonaws.com/dev/
```

### Deployed Routes

| Domain | Routes |
|--------|--------|
| D1 Identity | `POST /auth/signup`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET/PUT/DELETE /profiles/{userId}`, `POST /profiles`, `POST /photos/upload`, `GET /users/{userId}/photos`, `DELETE /photos/{photoId}`, `PUT /photos/{photoId}/primary`, `POST /verify/send`, `POST /verify/confirm`, `GET /verify/status/{userId}` |
| D2 Discovery | `GET /discovery`, `GET /recommend`, `GET /bazi/top-matches`, `POST /swipe`, `GET /swipe/history`, `GET /matches`, `GET /matches/{matchId}` |
| D3 Messaging | *(not deployed yet)* `POST /messages`, `GET /messages/{matchId}`, `GET /messages/{matchId}/since/{timestamp}`, `POST /presence/heartbeat`, `GET /presence/{userId}`, `POST /presence/{matchId}/typing`, `POST /icebreaker/generate`, `GET /icebreaker/{matchId}` |
| D4 Moderation | `POST /reports`, `POST /moderate/text`, `POST /moderate/image`, `GET /ratelimit/status/{userId}` |
| D5 Notifications | `GET /notifications`, `GET /notifications/unread-count`, `GET/PUT /email/preferences` |
| D6 Analytics | `POST /analytics/log`, `GET /admin/stats`, `GET /health` |

---

## Testing

- **49 cross-domain integration tests** — all passing (merged in PR #81)
- Covers all EventBridge event chains across all 6 domains
- Tests file: `tests/test_cross_domain_integration.py`
- Each domain also has unit tests in `services/domain-N-*/*/tests/`

---

## Completed Milestones

| Date | Milestone |
|------|-----------|
| Apr 1–6 | API contracts finalized, Lambda scaffolding complete |
| Apr 7–8 | All 25 services built with unit tests |
| Apr 9 | CDK infrastructure complete, SharedStack deployed |
| Apr 10 | D2, D4, D5, D6 deployed; integration tests written (49 tests) |
| Apr 10 | D1 convention alignment (PR #80), photo route fix (PR #85) |
| Apr 10 | D1 deployed; 6/7 stacks live |

---

## Known Blockers

| Issue | Domain | Description | Owner |
|-------|--------|-------------|-------|
| #83 | D3 | API Gateway path variable conflict: `/messages/{matchId}` vs `/messages/{messageId}`, `/presence/{userId}` vs `/presence/{matchId}` | D3 team |

---

## Next Steps

1. **D3 deployment** — D3 team fixes path conflicts (Issue #83), then deploy KismetDomain3
2. **Frontend** — Next.js app (plan in `frontend/FRONTEND_PLAN.md`), deploy to Vercel
3. **Final demo** — Apr 17 presentation
