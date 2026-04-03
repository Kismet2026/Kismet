# 💫 Kismet

A microservice dating app built on AWS — with BaZi (八字) compatibility matching.

> Cloud Computing Spring 2026 — Final Project

---

## Architecture

**25 microservices** across **6 domains**, powered by **18+ AWS services**.

```
                    ┌──────────────────────┐
                    │   Frontend (React)   │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │  API Gateway (REST   │
                    │    + WebSocket)      │
                    └──┬───────┬───────┬───┘
                       │       │       │
         ┌─────────────▼──┐ ┌─▼─────────┐ ┌▼──────────────┐
         │   Identity &   │ │ Discovery  │ │   Messaging   │
         │   Profiles     │ │ & Matching │ │               │
         │  (4 services)  │ │(5 services)│ │  (4 services) │
         └────────────────┘ └────────────┘ └───────────────┘
         ┌────────────────┐ ┌────────────┐ ┌───────────────┐
         │   Safety &     │ │Notifications│ │  Analytics &  │
         │  Moderation    │ │& Engagement│ │    Admin      │
         │  (4 services)  │ │(4 services)│ │  (4 services) │
         └───────┬────────┘ └─────┬──────┘ └──────┬────────┘
                 │                │                │
              ┌──▼────────────────▼────────────────▼──┐
              │    EventBridge (event-driven backbone) │
              └───────────────────────────────────────┘
```

---

## Team

| Domain | Members | Services |
|--------|---------|----------|
| **Identity & Profiles** | Quinn Gao, Zhiping | Auth, Profile, Photo, Email Verification |
| **Discovery & Matching** | Qinyuan, Hao | Discovery, Swipe, Match, Recommendation, BaZi |
| **Messaging** | Parker, QX, Jiaxin | Chat Gateway, Message, Presence, Icebreaker |
| **Safety & Moderation** | Yue, KS, Amber | Text Moderation, Image Moderation, Report, Rate Limiter |
| **Notifications** | Nili, Xiaoyuan | Push Notification, Email, Event Bus, Scheduler |
| **Analytics & Admin** | Jessica, Lingyun | Activity Logger, Analytics Pipeline, Admin Dashboard, Health Monitor |
| **Integration** | Zhiping, QX, KS | Cross-domain service orchestration |
| **PM / Frontend** | Qinyuan | Architecture, frontend (AI-generated), coordination |

---

## Microservice Map

### Domain 1 — Identity & Profiles

| Service | Owner | AWS Services | Description |
|---------|-------|-------------|-------------|
| Auth Service | Quinn Gao | Cognito, Lambda | Sign up, login, JWT tokens |
| Profile Service | Quinn Gao | Lambda, DynamoDB | CRUD for user profiles |
| Photo Service | Zhiping | S3, Lambda, CloudFront | Upload, resize, serve photos |
| Email Verification | Zhiping | SES, Lambda, Cognito | .edu email verification |

### Domain 2 — Discovery & Matching

| Service | Owner | AWS Services | Description |
|---------|-------|-------------|-------------|
| Discovery Service | Hao | Lambda, DynamoDB | Filter and browse candidates |
| Swipe Service | Hao | Lambda, DynamoDB | Record like/pass actions |
| Match Service | Hao | Lambda, DynamoDB Streams, SNS | Detect mutual likes |
| Recommendation Service | Qinyuan | Lambda, DynamoDB | Score and rank candidates |
| BaZi Service | Qinyuan | Lambda | 八字 compatibility via external API |

### Domain 3 — Messaging

| Service | Owner | AWS Services | Description |
|---------|-------|-------------|-------------|
| Chat Gateway | Parker | API Gateway WebSocket, Lambda | Real-time message routing |
| Message Service | Parker | Lambda, DynamoDB | Persist and retrieve chats |
| Presence Service | QX | ElastiCache, Lambda | Online/offline/typing status |
| Icebreaker Service | Jiaxin | Bedrock, Lambda | AI conversation starters |

### Domain 4 — Safety & Moderation

| Service | Owner | AWS Services | Description |
|---------|-------|-------------|-------------|
| Text Moderation | Yue | Comprehend, Lambda | Flag toxic content |
| Image Moderation | KS | Rekognition, Lambda | Block inappropriate photos |
| Report Service | Amber | Lambda, DynamoDB, SES | User reports → admin alerts |
| Rate Limiter | Amber | API Gateway, DynamoDB | Anti-spam protection |

### Domain 5 — Notifications & Engagement

| Service | Owner | AWS Services | Description |
|---------|-------|-------------|-------------|
| Push Notification | Nili | SNS, Lambda | New match/message alerts |
| Email Service | Nili | SES, Lambda | Welcome emails, digests |
| Event Bus | Xiaoyuan | EventBridge, Lambda | Cross-domain event routing |
| Scheduler | Xiaoyuan | EventBridge Scheduler, Step Functions | Timed jobs |

### Domain 6 — Analytics & Admin

| Service | Owner | AWS Services | Description |
|---------|-------|-------------|-------------|
| Activity Logger | Jessica | Kinesis Data Streams, Lambda | Capture user events |
| Analytics Pipeline | Jessica | Kinesis Firehose, S3, Athena | Queryable data lake |
| Admin Dashboard | Lingyun | Lambda, DynamoDB | Stats, flagged content |
| Health Monitor | Lingyun | CloudWatch, Lambda, SNS | Service health alerts |

---

## AWS Services Used (18+)

| Category | Services |
|----------|----------|
| Compute | Lambda |
| API | API Gateway (REST + WebSocket) |
| Auth | Cognito |
| Database | DynamoDB, DynamoDB Streams |
| Storage | S3 |
| CDN | CloudFront |
| Caching | ElastiCache (Redis) |
| AI/ML | Rekognition, Comprehend, Bedrock |
| Messaging | SNS, SES |
| Event-Driven | EventBridge, EventBridge Scheduler |
| Orchestration | Step Functions |
| Streaming | Kinesis Data Streams, Kinesis Firehose |
| Analytics | Athena |
| Monitoring | CloudWatch |

---

## Project Structure

```
kismet/
├── README.md
├── docs/
│   ├── architecture.md
│   ├── api-contracts/          ← one file per service
│   └── onboarding.md
├── frontend/
├── services/
│   ├── domain-1-identity/
│   │   ├── auth-service/
│   │   ├── profile-service/
│   │   ├── photo-service/
│   │   └── email-verification-service/
│   ├── domain-2-discovery/
│   │   ├── discovery-service/
│   │   ├── swipe-service/
│   │   ├── match-service/
│   │   ├── recommendation-service/
│   │   └── bazi-service/
│   ├── domain-3-messaging/
│   │   ├── chat-gateway/
│   │   ├── message-service/
│   │   ├── presence-service/
│   │   └── icebreaker-service/
│   ├── domain-4-moderation/
│   │   ├── text-moderation-service/
│   │   ├── image-moderation-service/
│   │   ├── report-service/
│   │   └── rate-limiter-service/
│   ├── domain-5-notifications/
│   │   ├── push-notification-service/
│   │   ├── email-service/
│   │   ├── event-bus-service/
│   │   └── scheduler-service/
│   └── domain-6-analytics/
│       ├── activity-logger-service/
│       ├── analytics-pipeline-service/
│       ├── admin-dashboard-service/
│       └── health-monitor-service/
└── infra/
```

---

## Git Workflow

- `main` — stable, deployable
- `dev` — integration branch
- `domain-N/service-name` — feature branches

**PR flow:** your branch → `dev` (1 review from domain partner) → `main` (PM merges)

---

## Timeline

| Week | Milestone |
|------|-----------|
| **Week 1** (now → Apr 6) | API contracts, Lambda scaffolding |
| **Week 2** (Apr 7–13) | Build & unit test services |
| **Week 3** (Apr 14–16) | Integration, demo prep, slides |
| **Apr 17** | 🎤 Presentation & Demo |

---

## Getting Started

1. Clone this repo
2. Navigate to your service folder under `services/`
3. Read your service's README for setup instructions
4. Define your API contract in `docs/api-contracts/`
5. Post daily standups in Discord `#standup`

## Standup Format

```
[Name] — [Date]
✅ Done:
🔄 Doing:
🚧 Blocked:
```
