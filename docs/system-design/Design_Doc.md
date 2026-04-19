# Kismet — Overall System Design

> Last updated: 2026-04-03

---

## 1. What Is Kismet

A microservice-based dating app, differentiated by **BaZi (八字) compatibility scoring** — an ancient Chinese astrological system that ranks partner compatibility based on birth date and time.

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
| Auth Service | Cognito, Lambda | Sign up, login, JWT tokens (Cognito auto-verifies email) |
| Profile Service | Lambda, DynamoDB | CRUD user profiles |
| Photo Service | S3, Lambda, CloudFront | Upload, resize, serve profile photos |

### Domain 2 — Discovery & Matching

| Service | AWS | Responsibility |
|---------|-----|----------------|
| Discovery Service | Lambda, DynamoDB | Maintain discovery pool; serve filtered candidate list; cache BaZi scores |
| Swipe Service | Lambda, DynamoDB | Record like/pass actions; publish `swipe.created` on like |
| Match Service | Lambda, DynamoDB, EventBridge | Detect mutual likes atomically (TransactWrite); emit `match.created`; purge on `user.deleted` / `profile.banned` |
| Recommendation Service | Lambda, DynamoDB | Compute and cache ranked candidates; bidirectional BaZi scoring |
| BaZi Service | Lambda | Compatibility score via external BaZi API (stateless; cache lives in Discovery table) |

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
| Rate Limiter | API Gateway, ElastiCache (Redis) | Anti-spam throttling |

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

Deployed once by PM (`SharedStack`); all domain stacks import these resources. See [`infra/stacks/shared_stack.py`](../../infra/stacks/shared_stack.py).

| Resource | Name | Purpose |
|----------|------|---------|
| Cognito User Pool | `kismet-user-pool` | Auth, email verification, JWT issuance |
| Cognito App Client | `kismet-web-client` | Frontend client with USER_PASSWORD + SRP auth flows |
| API Gateway (REST) | `kismet-api` | Single REST entry point (stage `dev`) + Cognito authorizer |
| EventBridge Bus | `kismet-events` | All async cross-domain events |
| S3 Bucket | `kismet-photos-{account}-dev` | Profile photos (PUT: Photo Service presigned, GET: CloudFront) |
| CloudFront Distribution | (auto-generated domain) | CDN for photo GET (cache-optimized, gzip) |
| S3 Bucket | `kismet-analytics-{account}-dev` | Analytics data lake (write: Firehose, query: Athena) |
| Kinesis Data Stream | `kismet-activity-stream` | Activity Logger → Analytics Pipeline ⚠️ *deferred on current AWS account — see `SharedStack.activity_stream = None`* |
| SNS Topic | `kismet-health-alerts` | Health Monitor alerts |

Domain-3 chat uses a separate **API Gateway WebSocket API** (`kismet-chat-websocket`) owned by Domain 3 — not shared.

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

See [`event-schema.json`](./event-schema.json) for full detail schemas.

| Event | Source | Consumers | Key fields |
|-------|--------|-----------|------------|
| `user.created` | auth-service | Email Service, Activity Logger | `userId`, `email`, `timestamp` |
| `profile.completed` | profile-service | Discovery, Recommendation, Activity Logger | `userId`, `birthDate`, `gender`, `preferred_gender`, `location_coordinates`, `avatarUrl`, `bio`, `timestamp` |
| `profile.updated` | profile-service | Discovery, Activity Logger | same shape as `profile.completed` |
| `photo.uploaded` | photo-service | Image Moderation, Activity Logger | `photoId`, `userId`, `s3Key`, `s3Bucket`, `contentType`, `isPrimary` |
| `swipe.created` | swipe-service | Match, Recommendation (cache invalidation), Activity Logger | `userId`, `targetUserId`, `action`, `timestamp` |
| `match.created` | match-service | Push Notification, Email, Icebreaker, Activity Logger | `matchId`, `userIds[]`, `timestamp` |
| `message.sent` | message-service | Text Moderation, Push Notification, Activity Logger | `messageId`, `matchId`, `senderId`, `recipientId`, `content` |
| `content.flagged` | moderation | Admin Dashboard, Activity Logger | `contentId`, `contentType`, `userId`, `reason`, `score` |
| `user.reported` | report-service | Admin Dashboard, Email Service, Activity Logger | `reportId`, `reporterId`, `reportedUserId`, `reason` |
| `user.banned` | report-service | Profile Service *(re-publishes as `profile.banned`)* | `userId`, `reportId`, `reason`, `autoBanned?`, `threshold?` |
| `profile.banned` | profile-service | Discovery, Match, Recommendation, Message, Email (planned #120) | `userId`, `reason`, `reportId`, `timestamp` |
| `user.deleted` | profile-service | Photo, Discovery, Swipe, Match, Recommendation, Message, Email | `userId`, `timestamp` |

---

## 7. Data Layer

**Each service owns its own DynamoDB table. No cross-service table access.**

Key tables:

| Table | Owner | PK | SK | Notes |
|-------|-------|----|----|-------|
| `kismet-profiles` | Profile | `USER#{userId}` | `PROFILE` | canonical user doc; `status` field: `active \| banned` |
| `kismet-photos` | Photo | `USER#{userId}` | `PHOTO#{photoId}` | `status`: `pending \| active \| rejected` |
| `kismet-discovery` | Discovery | `PROFILE#{userId}` \| `BAZI#{birthDate}` | `META` \| `SCORES` | denormalized discovery pool + BaZi cache |
| `kismet-swipes` | Swipe | `userId` | `targetUserId` | flat hash+range, one row per swipe |
| `kismet-matches` | Match | `MATCH#{matchId}` \| `PAIR#{a}#{b}` \| `USER#{userId}` | `META` \| `MATCH#{ts}#{matchId}` | single-table with 3 access patterns |
| `kismet-recommendations` | Recommendation | `USER#{userId}` | `SCORE#{score}#{candidateId}` | computed score cache |
| `kismet-messages` | Message | `CONV#{matchId}` | `MSG#{timestamp}` | |
| `kismet-reports` | Report | `pk` = `REPORT#{reportId}` | `sk` = `META` | GSI on `reportedUserId` for auto-ban count |
| `kismet-image-moderation-dev` | Image Moderation | `photoId` = `PHOTO#{id}` | `sk` = `RESULT` | Rekognition scan history + GSI for admin |
| `kismet-text-moderation-dev` | Text Moderation | `contentId` | `sk` | Comprehend scan history |
| `kismet-flagged-content` | Admin Dashboard | `CONTENT#{contentId}` | `META` | |
| `kismet-admin-stats` | Admin Dashboard | `STAT#{type}` | `DATE#{date}` | |
| `kismet-activity-log` | Activity Logger | `USER#{userId}` | `EVENT#{timestamp}` | |
| `kismet-presence` | Presence | `USER#{userId}` | `STATUS` | DynamoDB TTL → auto-offline |

**DynamoDB TTL** is used for Presence Service: status expires after 60s (user marked offline if no heartbeat).

**ElastiCache (Redis)** is used for Rate Limiter: per-user sliding window counters with automatic expiration via Redis TTL.

---

## 8. Key User Flows

### Sign Up
1. User submits email + password + birth date
2. Auth Service → Cognito creates account, auto-verifies the email attribute, returns JWT
3. `user.created` published → Email Service sends welcome email, Activity Logger records

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
| Rate Limiting | ElastiCache (Redis) + API Gateway | Redis for per-user limits; Presence still uses DynamoDB TTL |
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
| Auth | JWT (Cognito), email auto-verified |
| Cost | Within AWS Academy / free tier where possible |

---

*Source documents: [PRD](./PRD.md) · [Infrastructure Design](./Infrastructure_Design.md) · [Service Communication Guide](./Service_Communication_Guide.md) · [Event Schema](./event-schema.json)*
