# Kismet — Infrastructure Design

> Last updated: 2026-03-31

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Route 53 (DNS)                          │
└──────────────┬──────────────────────────────┬───────────────────┘
               │                              │
    ┌──────────▼──────────┐       ┌───────────▼──────────┐
    │   CloudFront CDN    │       │   API Gateway (REST) │
    │  (React frontend    │       │   api.kismet.app     │
    │   + photo serving)  │       └──────────┬───────────┘
    └─────────────────────┘                  │
                                  ┌──────────▼──────────────┐
                                  │    Cognito Authorizer   │
                                  │    (JWT verification)   │
                                  └──────────┬──────────────┘
                                             │
               ┌─────────────┬───────────────┼───────────────┬─────────────┐
               │             │               │               │             │
          ┌────▼────┐   ┌────▼────┐    ┌─────▼────┐   ┌─────▼────┐  ┌────▼────┐
          │Domain 1 │   │Domain 2 │    │ Domain 3 │   │ Domain 4 │  │Domain 5 │
          │ 4 Fns   │   │ 5 Fns   │    │  4 Fns   │   │  4 Fns   │  │ 4 Fns   │
          └────┬────┘   └────┬────┘    └────┬─────┘   └────┬─────┘  └────┬────┘
               │             │              │              │              │
     ┌─────────▼─────────────▼──────────────▼──────────────▼──────────────▼──────┐
     │                     EventBridge Bus (kismet-events)                       │
     └──────────────────────────────────┬───────────────────────────────────────┘
                                        │
                                  ┌─────▼─────┐
                                  │ Domain 6  │
                                  │ 4 Fns     │
                                  └───────────┘
```

---

## 2. Shared Resources (Deployed Once by PM)

These are global resources shared across all 25 services. PM deploys them once; service owners reference the exported ARNs.

### 2.1 Authentication — Cognito

| Resource | Details |
|----------|---------|
| **User Pool** | `kismet-user-pool` — email/password sign-up, .edu verification |
| **App Client** | `kismet-web-client` — used by React frontend |
| **Authorizer** | Attached to API Gateway — validates JWT on every request |

All services trust the same Cognito-issued JWT. No service manages its own auth.

### 2.2 API Gateway — Single REST API

One API Gateway for all services. Routes are organized by path prefix:

```
api.kismet.app/
├── /auth/*            → Auth Service Lambda
├── /profiles/*        → Profile Service Lambda
├── /photos/*          → Photo Service Lambda
├── /verify/*          → Email Verification Lambda
├── /discovery/*       → Discovery Service Lambda
├── /swipe/*           → Swipe Service Lambda
├── /matches/*         → Match Service Lambda
├── /recommend/*       → Recommendation Service Lambda
├── /bazi/*            → BaZi Service Lambda
├── /chat/*            → Chat / Message Service Lambda (see §4)
├── /messages/*        → Message Service Lambda
├── /presence/*        → Presence Service Lambda
├── /icebreaker/*      → Icebreaker Service Lambda
├── /moderate/text/*   → Text Moderation Lambda
├── /moderate/image/*  → Image Moderation Lambda
├── /reports/*         → Report Service Lambda
├── /notifications/*   → Push Notification Lambda
├── /email/*           → Email Service Lambda
├── /events/*          → Event Bus Lambda
├── /scheduler/*       → Scheduler Lambda
├── /analytics/*       → Activity Logger / Analytics Lambda
├── /admin/*           → Admin Dashboard Lambda
└── /health/*          → Health Monitor Lambda
```

**Why one API Gateway:**
- Frontend only needs one base URL
- Shared Cognito authorizer
- Centralized rate limiting and throttling
- Easier CORS configuration

### 2.3 EventBridge — Event Bus

| Resource | Details |
|----------|---------|
| **Bus Name** | `kismet-events` |
| **Purpose** | All cross-domain async communication |

Rules are managed per-service (each service creates its own EventBridge rule to filter events it cares about).

### 2.4 S3 Buckets

| Bucket | Purpose | Access |
|--------|---------|--------|
| `kismet-photos-{env}` | User profile photos | Photo Service writes; CloudFront reads |
| `kismet-analytics-{env}` | Analytics data lake | Kinesis Firehose writes; Athena queries |
| `kismet-frontend-{env}` | React static assets | CloudFront serves |

### 2.5 CloudFront

| Distribution | Origin | Purpose |
|-------------|--------|---------|
| Frontend | `kismet-frontend` S3 bucket | Serve React app |
| Photos | `kismet-photos` S3 bucket | Serve user photos with caching |

### 2.6 ElastiCache (Redis)

| Resource | Purpose |
|----------|---------|
| **ElastiCache Cluster** | `kismet-redis` — Rate Limiter per-user sliding window counters |

**Rate Limiting — ElastiCache (Redis) + API Gateway Throttling:**
- Key format: `ratelimit:{userId}:{action}:{windowTimestamp}`
- Redis `INCR` + `EX`/`PX` 实现滑动窗口自动过期
- 结合 API Gateway Usage Plans（基础防护）

> **Note:** ElastiCache 需要 VPC + NAT Gateway。Presence Service 仍使用 DynamoDB TTL。

### 2.7 Kinesis (Analytics Pipeline)

| Resource | Purpose |
|----------|---------|
| **Kinesis Data Stream** | `kismet-activity-stream` — Activity Logger writes user events |
| **Kinesis Firehose** | Reads from Data Stream → batches → writes to S3 analytics bucket |
| **Athena** | Queries the S3 data lake on demand |

---

## 3. Per-Service Resources

Each service owns and manages:

| Resource | Convention | Example |
|----------|-----------|---------|
| **Lambda Function** | `kismet-{service-name}` | `kismet-auth-service` |
| **DynamoDB Table** | `kismet-{entity}` | `kismet-users`, `kismet-swipes` |
| **IAM Role** | `kismet-{service-name}-role` | `kismet-auth-service-role` |
| **CloudWatch Logs** | Auto-created | `/aws/lambda/kismet-auth-service` |
| **EventBridge Rule** | `kismet-{service}-on-{event}` | `kismet-notification-on-match-created` |

### 3.1 DynamoDB Table Design

Each service has its own table(s). **Services never read/write another service's table.**

| Table | Service | PK | SK | Streams |
|-------|---------|----|----|---------|
| `kismet-users` | Profile | `USER#{userId}` | `PROFILE` / `SETTINGS` | No |
| `kismet-photos` | Photo | `USER#{userId}` | `PHOTO#{photoId}` | No |
| `kismet-swipes` | Swipe | `USER#{userId}` | `TARGET#{targetId}` | Yes → Match detection |
| `kismet-matches` | Match | `MATCH#{matchId}` | `USER#{userId}` | No |
| `kismet-messages` | Message | `CONV#{matchId}` | `MSG#{timestamp}` | No |
| `kismet-connections` | Chat Gateway | `CONN#{connId}` | `META` | No |
| `kismet-reports` | Report | `REPORT#{reportId}` | `META` | No |
| `kismet-discovery` | Discovery | `USER#{userId}` | `CANDIDATE#{score}` | No |
| `kismet-admin` | Admin Dashboard | `STAT#{type}` | `DATE#{date}` | No |

### 3.2 IAM — Least Privilege

Every Lambda gets its own IAM role with **only** the permissions it needs:

```
Auth Lambda        → cognito:AdminCreateUser, cognito:AdminInitiateAuth
                   → dynamodb:PutItem, GetItem (kismet-users only)

Photo Lambda       → s3:PutObject, s3:GetObject (kismet-photos bucket only)
                   → dynamodb:PutItem, Query (kismet-photos table only)

Match Lambda       → dynamodb:Query (kismet-swipes, kismet-matches)
                   → events:PutEvents (kismet-events bus)
                   → sns:Publish

Text Moderation    → comprehend:DetectToxicContent
                   → events:PutEvents

Image Moderation   → rekognition:DetectModerationLabels

Icebreaker Lambda  → bedrock:InvokeModel

Activity Logger    → kinesis:PutRecord (kismet-activity-stream)

Analytics Pipeline → (Firehose role) s3:PutObject (kismet-analytics bucket)
```

---

## 4. Service Communication Patterns

Services communicate in exactly two ways. For a detailed Chinese-language explanation with examples, see the [Service Communication Guide (微服务通信指南)](./Service_Communication_Guide.md).

### 4.1 Synchronous — HTTP via API Gateway

```
Frontend ──HTTP Request──→ API Gateway ──→ Lambda ──→ Response ──→ Frontend
```

Used when the caller **needs the result immediately** (e.g., loading the discovery feed, fetching chat history, login).

Service-to-service sync calls also go through the API Gateway (e.g., Recommendation Service calls `GET /profiles/{userId}` to get profile data for scoring).

### 4.2 Asynchronous — Events via EventBridge

```
Lambda A ──publish event──→ EventBridge ──→ Lambda B (independent)
                                        ──→ Lambda C (independent)
                                        ──→ Lambda D (independent)
```

Used when subsequent actions **don't need to block the current request** (e.g., sending notifications, content moderation, logging).

Key events:

| Event | Publisher | Consumers |
|-------|-----------|-----------|
| `swipe.created` | Swipe Service | Match Service, Activity Logger |
| `match.created` | Match Service | Push Notification, Email, Icebreaker, Activity Logger |
| `message.sent` | Message Service | Text Moderation, Activity Logger |
| `photo.uploaded` | Photo Service | Image Moderation, Activity Logger |
| `user.created` | Auth Service | Email Service, Activity Logger |
| `user.reported` | Report Service | Admin Dashboard, Email Service, Activity Logger |
| `profile.completed` | Profile Service | Recommendation Service, Activity Logger |

### 4.3 Why Not Multithreading?

Lambda uses a **one-instance-per-request** model. Each invocation runs in its own isolated container — no shared memory, no thread locks, no race conditions. AWS handles concurrency automatically by spinning up more instances as traffic increases.

Data consistency is handled at the database layer using DynamoDB conditional writes, not application-level locking.

---

## 5. Messaging — WebSocket vs. Polling

Real-time chat has two possible implementations. Choose based on team capacity.

### Option A: WebSocket (Preferred)

```
React App ←──WSS──→ API Gateway WebSocket ←→ Chat Gateway Lambda
                                                    │
                                            ┌───────▼───────┐
                                            │ Message Service│
                                            │  (DynamoDB)    │
                                            └────────────────┘
```

| Component | Details |
|-----------|---------|
| **API Gateway WebSocket** | Separate from the REST API; manages persistent connections |
| **Connection Table** | DynamoDB `kismet-connections` — maps connectionId → userId |
| **Routes** | `$connect`, `$disconnect`, `sendMessage`, `typing` |
| **Push to client** | Lambda calls `ApiGatewayManagementApi.postToConnection()` |

**Pros:** True real-time, low latency, typing indicators work naturally
**Cons:** More complex; connection management adds code; harder to debug

### Option B: HTTP Polling (Fallback)

```
React App ──GET /messages?since={ts}──→ API Gateway REST ──→ Message Lambda ──→ DynamoDB
            (poll every 3-5 seconds)
```

| Component | Details |
|-----------|---------|
| **Endpoint** | `GET /messages/{matchId}?since={timestamp}` |
| **Poll interval** | 3–5 seconds from frontend |
| **New message detection** | Compare timestamp; return only new messages |
| **Typing indicator** | `POST /presence/{matchId}/typing` + poll `GET /presence/{matchId}` |

**Pros:** Simple REST, same API Gateway, easy to debug, no connection state
**Cons:** 3–5s delay, more API calls, typing indicators feel laggy

### Option C: Hybrid (Recommended Compromise)

Start with **Option B (polling)** to get messaging working end-to-end in Week 2. If time permits in Week 3, upgrade to **Option A (WebSocket)** for the demo.

This way:
- Message Service and DynamoDB schema are the same either way
- Only the Chat Gateway layer changes
- No risk of being blocked on WebSocket complexity

**Implementation plan:**

| Week | Chat Implementation |
|------|-------------------|
| Week 1 | Define message API contract (works for both options) |
| Week 2 | Build with HTTP polling — messages work, typing via polling |
| Week 3 (if time) | Add WebSocket Gateway in front — swap transport layer, same backend |

---

## 6. Simplification Options

If the team hits blockers, here are drop-in simplifications:

### ElastiCache (Redis) for Rate Limiter

Rate Limiter 使用 ElastiCache (Redis) 实现用户级精细限流。需要配置 VPC + NAT Gateway。

### Kinesis → Direct S3 Write

If Kinesis setup is too complex:

```
Activity Logger Lambda → direct s3:PutObject to kismet-analytics bucket
                         (one JSON file per event batch)
```

Athena can still query it. You lose real-time streaming but keep the analytics pipeline.

### Bedrock → Hardcoded Icebreakers

If Bedrock access is delayed:

```python
ICEBREAKERS = [
    "I see you're into {interest}. What got you started?",
    "Your BaZi compatibility is {score}%! What's your take on astrology?",
    "If you could travel anywhere tomorrow, where would you go?",
]
```

Swap in Bedrock when access is granted — the API contract stays the same.

---

## 7. Deployment Strategy

### 7.1 Tool: AWS SAM

Each service has its own `template.yaml`. Shared infra has a separate template.

```
infra/
└── shared/
    └── template.yaml              # Cognito, EventBridge, API Gateway, S3, CloudFront

services/domain-X/service-name/
├── template.yaml                  # Lambda + DynamoDB + IAM for this service
├── lambda_function.py             # Handler code
├── requirements.txt               # Dependencies
└── tests/
```

### 7.2 Deployment Order

```
Step 1:  infra/shared/template.yaml     ← PM deploys once
         (creates Cognito, EventBridge, API Gateway, S3 buckets)
         Exports: UserPoolId, ApiGatewayId, EventBusArn, PhotosBucketArn

Step 2:  Each service template.yaml      ← Each owner deploys their own
         (imports shared resource ARNs via CloudFormation exports)

Step 3:  Frontend build + deploy to S3   ← PM deploys
         (React build → S3 → CloudFront invalidation)
```

### 7.3 Environments

For a 3-week project, **one environment is fine** (no staging/prod split):

| Resource naming | Example |
|----------------|---------|
| `kismet-{resource}-dev` | `kismet-photos-dev`, `kismet-users-dev` |

### 7.4 Deploy Commands (per service)

```bash
cd services/domain-2-discovery/swipe-service/

# Build
sam build

# Deploy (first time — guided)
sam deploy --guided

# Deploy (subsequent — uses saved config)
sam deploy
```

---

## 8. Cost Considerations

All resources should stay within AWS free tier or Academy credits:

| Resource | Free Tier |
|----------|-----------|
| Lambda | 1M requests/month, 400K GB-seconds |
| DynamoDB | 25 GB storage, 25 WCU/RCU |
| S3 | 5 GB storage |
| API Gateway | 1M REST calls/month |
| Cognito | 50K MAU |
| EventBridge | Free for AWS events |
| CloudWatch | 10 custom metrics, 5 GB logs |
| SNS | 1M publishes |
| SES | 62K emails/month (from EC2) |

**Watch out for:**
- **ElastiCache** — NOT free tier (~$32/month). Required for Rate Limiter.
- **Bedrock** — Pay per token. Use sparingly or mock for development.
- **Kinesis** — $0.015/shard/hour. Consider the direct-S3 alternative.
- **NAT Gateway** — $0.045/hour if using VPC. Avoid if possible.

---

## 9. Infra File Structure (Final)

```
infra/
├── app.py                         # CDK entry point
├── kismet_constructs/
│   └── kismet_service.py          # Reusable KismetService construct
├── stacks/
│   ├── shared_stack.py            # Cognito, API GW, EventBridge, S3, Kinesis, SNS
│   ├── domain1_stack.py           # Identity & Profiles services
│   ├── domain2_stack.py           # Discovery & Matching services
│   ├── domain3_stack.py           # Messaging services
│   ├── domain4_stack.py           # Safety & Moderation services
│   ├── domain5_stack.py           # Notifications & Engagement services
│   └── domain6_stack.py           # Analytics & Admin services
│
services/domain-X/service-name/
│   ├── lambda_function.py
│   ├── requirements.txt
│   ├── tests/
│   └── README.md
```

---

## 10. Summary Decision Table

| Decision | Choice | Rationale |
|----------|--------|-----------|
| IaC Tool | **AWS CDK (Python)** | Migrated from SAM; reusable KismetService construct |
| API Gateway | **One REST + optional WebSocket** | Single entry point; shared auth |
| Messaging | **HTTP polling → upgrade to WebSocket if time** | De-risks Week 2; same backend |
| Rate Limiting | **ElastiCache (Redis)** + API Gateway Usage Plans | Redis for per-user sliding window; API GW for global throttle |
| Analytics | **Kinesis** (default) / Direct S3 (fallback) | Kinesis is a course requirement |
| Icebreakers | **Bedrock** (default) / Hardcoded (fallback) | Depends on Bedrock access timing |
| Environments | **Single `dev` env** | 3-week project, no prod needed |
| Deployment | **Each owner deploys their own service** | Parallel development; PM deploys shared |

---

*This document should be read alongside the [PRD](./PRD.md), [Setup Guide](./Kismet_Setup_Guide.md), and [Service Communication Guide (微服务通信指南)](./Service_Communication_Guide.md).*
