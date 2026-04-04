# Kismet — Overall System Design

> Last updated: 2026-04-03

---

## 1. What Is Kismet

A microservice-based dating app for college students (.edu verified), differentiated by **BaZi (八字) compatibility scoring** — an ancient Chinese astrological system that ranks partner compatibility based on birth date and time.

Built entirely on AWS using a serverless, event-driven architecture: **25 microservices** across **6 domains**, deployed as AWS Lambda functions.

---

## 2. High-Level Architecture

```
                    ┌─────────────────┐
                    │ React Frontend  │
                    └────────┬────────┘
                             │ HTTPS
                    ┌────────▼────────┐
                    │   API Gateway   │  ← single entry point for all REST calls
                    │  + WebSocket    │  ← separate WS endpoint for real-time chat
                    └────────┬────────┘
                             │ JWT verified by Cognito Authorizer
          ┌──────────────────┼──────────────────────┐
          │                  │                      │
   ┌──────▼──────┐   ┌───────▼──────┐   ┌──────────▼──────┐
   │  Domain 1   │   │  Domain 2    │   │    Domain 3      │
   │  Domain 4   │   │  Domain 5    │   │    Domain 6      │
   └──────┬──────┘   └───────┬──────┘   └──────────┬───────┘
          │                  │                      │
          └──────────────────▼──────────────────────┘
                    ┌─────────────────┐
                    │   EventBridge   │  ← async backbone: all cross-domain events
                    │ (kismet-events) │
                    └─────────────────┘
```

**Core principles:**
- **Serverless** — all compute on Lambda, no servers to manage
- **Event-driven** — domains are decoupled; communicate via EventBridge, not direct calls
- **Single API Gateway** — one base URL for the frontend, shared Cognito authorizer
- **Each service owns its data** — services never read another service's DynamoDB table directly

---

## 3. Service Inventory

### Domain 1 — Identity & Profiles

| Service | AWS | Responsibility |
|---------|-----|----------------|
| Auth Service | Cognito, Lambda | Sign up, login, JWT tokens |
| Profile Service | Lambda, DynamoDB | CRUD user profiles |
| Photo Service | S3, Lambda, CloudFront | Upload, resize, serve profile photos |
| Email Verification | SES, Lambda | .edu email verification |

### Domain 2 — Discovery & Matching

| Service | AWS | Responsibility |
|---------|-----|----------------|
| Discovery Service | Lambda, DynamoDB | Filter and browse candidate profiles |
| Swipe Service | Lambda, DynamoDB | Record like / pass actions |
| Match Service | Lambda, DynamoDB Streams | Detect mutual likes, emit `match.created` |
| Recommendation Service | Lambda, DynamoDB | Score and rank candidates |
| BaZi Service | Lambda | Compatibility score via external BaZi API |

### Domain 3 — Messaging

| Service | AWS | Responsibility |
|---------|-----|----------------|
| Chat Gateway | API Gateway WebSocket, Lambda | Real-time message routing |
| Message Service | Lambda, DynamoDB | Persist and retrieve messages |
| Presence Service | Lambda, DynamoDB TTL | Online / offline / typing indicators |
| Icebreaker Service | Bedrock, Lambda | AI-generated conversation starters |

### Domain 4 — Safety & Moderation

| Service | AWS | Responsibility |
|---------|-----|----------------|
| Text Moderation | Comprehend, Lambda | Detect toxic messages |
| Image Moderation | Rekognition, Lambda | Block inappropriate photos |
| Report Service | Lambda, DynamoDB, SES | User reports with admin email alerts |
| Rate Limiter | API Gateway, DynamoDB TTL | Anti-spam throttling |

### Domain 5 — Notifications & Engagement

| Service | AWS | Responsibility |
|---------|-----|----------------|
| Push Notification | SNS, Lambda | Match / message push alerts |
| Email Service | SES, Lambda | Welcome, digest, transactional emails |
| Event Bus | EventBridge, Lambda | Cross-domain event routing |
| Scheduler | EventBridge Scheduler, Step Functions | Timed jobs (digests, cleanup) |

### Domain 6 — Analytics & Admin

| Service | AWS | Responsibility |
|---------|-----|----------------|
| Activity Logger | Kinesis Data Streams, Lambda | Capture every user event |
| Analytics Pipeline | Kinesis Firehose, S3, Athena | Stream → data lake → SQL queries |
| Admin Dashboard | Lambda, DynamoDB | Platform stats, flagged content, user bans |
| Health Monitor | CloudWatch, Lambda, SNS | Service health checks and alerts |

---

## 4. Shared Infrastructure

Deployed once by PM; all services reference these resources.

| Resource | Name | Purpose |
|----------|------|---------|
| Cognito User Pool | `kismet-user-pool` | Auth, .edu verification, JWT issuance |
| API Gateway | `kismet-api` | Single REST entry point + Cognito authorizer |
| EventBridge Bus | `kismet-events` | All async cross-domain events |
| S3 | `kismet-photos-dev` | Profile photos (write: Photo Service, read: CloudFront) |
| S3 | `kismet-analytics-dev` | Analytics data lake (write: Firehose, query: Athena) |
| Kinesis Data Stream | `kismet-activity-stream` | Activity Logger → Analytics Pipeline |
| SNS Topic | `kismet-health-alerts` | Health Monitor alerts |

---

## 5. Communication Patterns

### Synchronous — HTTP via API Gateway

Used when the caller needs the result immediately.

```
Frontend → API Gateway → Lambda → response → Frontend
```

Examples: login, load discovery feed, fetch chat history.

Service-to-service sync calls also go through API Gateway (e.g. Recommendation Service calls `GET /profiles/{userId}`).

### Asynchronous — Events via EventBridge

Used when the downstream action doesn't need to block the current request.

```
Lambda A → publish event → EventBridge → Lambda B  (independent)
                                       → Lambda C  (independent)
                                       → Lambda D  (independent)
```

Examples: send push notification after a match, scan message for toxicity, log activity.

**Rule of thumb:**
- Frontend needs the result now → HTTP
- Background processing → EventBridge

---

## 6. Event Schema

All events share this envelope format:

```json
{
  "source": "kismet.{service-name}",
  "detail-type": "{event.type}",
  "detail": { ... }
}
```

### Key events

| Event | Source | Consumers | Key fields |
|-------|--------|-----------|------------|
| `user.created` | auth-service | Email Service, Activity Logger | `userId`, `email`, `timestamp` |
| `profile.completed` | profile-service | Recommendation Service, Activity Logger | `userId`, `timestamp` |
| `photo.uploaded` | photo-service | Image Moderation, Activity Logger | `photoId`, `userId`, `s3Key` |
| `swipe.created` | swipe-service | Match Service, Activity Logger | `userId`, `targetUserId`, `action` |
| `match.created` | match-service | Push Notification, Email, Icebreaker, Activity Logger | `matchId`, `userIds[]`, `timestamp` |
| `message.sent` | message-service | Text Moderation, Activity Logger | `messageId`, `matchId`, `senderId`, `content` |
| `content.flagged` | moderation | Admin Dashboard, Activity Logger | `contentId`, `contentType`, `userId`, `reason`, `score` |
| `user.reported` | report-service | Admin Dashboard, Email Service, Activity Logger | `reportId`, `reporterId`, `reportedUserId`, `reason` |

---

## 7. Data Layer

**Each service owns its own DynamoDB table. No cross-service table access.**

Key tables:

| Table | Owner | PK | SK |
|-------|-------|----|----|
| `kismet-users` | Profile | `USER#{userId}` | `PROFILE` |
| `kismet-swipes` | Swipe | `USER#{userId}` | `TARGET#{targetId}` |
| `kismet-matches` | Match | `MATCH#{matchId}` | `USER#{userId}` |
| `kismet-messages` | Message | `CONV#{matchId}` | `MSG#{timestamp}` |
| `kismet-reports` | Report | `REPORT#{reportId}` | `META` |
| `kismet-flagged-content` | Admin Dashboard | `CONTENT#{contentId}` | `META` |
| `kismet-admin-stats` | Admin Dashboard | `STAT#{type}` | `DATE#{date}` |
| `kismet-activity-log` | Activity Logger | `USER#{userId}` | `EVENT#{timestamp}` |
| `kismet-presence` | Presence | `USER#{userId}` | `STATUS` |

**DynamoDB TTL** is used in two places as a replacement for Redis/ElastiCache:
- Presence: status expires after 60s (user marked offline if no heartbeat)
- Rate Limiter: sliding window keys expire automatically

---

## 8. Key User Flows

### Sign Up
1. User submits email (.edu) + password + birth date
2. Auth Service → Cognito creates account → returns JWT
3. Email Verification Service → SES sends verification email
4. On verification → `user.created` published → Email Service sends welcome email, Activity Logger records

### Discovery & Matching
1. Frontend calls `GET /discovery` → Discovery + Recommendation + BaZi Services return ranked candidates
2. User swipes right → Swipe Service writes to DynamoDB, publishes `swipe.created`
3. Match Service detects mutual like → creates match, publishes `match.created`
4. Push Notification + Email Service notify both users; Icebreaker generates conversation starter

### Messaging
1. Chat Gateway establishes WebSocket connection
2. Message routed through Chat Gateway → persisted by Message Service → `message.sent` published
3. Text Moderation scans asynchronously; flags toxic content via `content.flagged`
4. Presence Service tracks online/typing status via DynamoDB TTL + heartbeat

---

## 9. Infrastructure & Deployment

**IaC: AWS CDK (Python)** — migrating from SAM per PR #40.

Core pattern: a reusable `KismetService` construct wraps Lambda + DynamoDB + API route + IAM + EventBridge rule. Each of the 25 services is one construct instantiation.

Stack structure:
```
SharedStack     → Cognito, API Gateway, EventBridge, S3, Kinesis, SNS
Domain1Stack    → 4 KismetService constructs
Domain2Stack    → 5 KismetService constructs
...
Domain6Stack    → 4 KismetService constructs
```

Deployment order: SharedStack first, then all domain stacks (can deploy in parallel).

---

## 10. Key Design Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Caching | DynamoDB TTL (no Redis) | ElastiCache requires VPC + NAT Gateway; cost and complexity not worth it |
| Chat transport | HTTP polling first, WebSocket if time permits | De-risks Week 2; same Message Service backend either way |
| Analytics ingestion | Kinesis Data Stream → Firehose → S3 → Athena | Course requirement; fallback: direct S3 write |
| AI icebreakers | Bedrock (fallback: hardcoded templates) | Bedrock access may be delayed |
| Environments | Single `dev` environment | 3-week timeline; no prod needed |
| Auth | Cognito, shared across all services | No service manages its own auth |
| IAM | Least privilege per Lambda | Each function only gets permissions it needs |

---

## 11. Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Compute | 100% serverless (Lambda only) |
| Chat latency | < 500ms via WebSocket |
| Scalability | Lambda auto-scales; DynamoDB on-demand |
| Content safety | All photos scanned before display; all messages scanned post-send |
| Auth | JWT (Cognito), .edu verified |
| Cost | Within AWS Academy / free tier where possible |

---

*Source documents: [PRD](./PRD.md) · [Infrastructure Design](./Infrastructure_Design.md) · [Service Communication Guide](./Service_Communication_Guide.md) · [Event Schema](./event-schema.json)*
