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
| **Identity & Profiles** | Quinn Gao, KS | Auth, Profile, Photo, Email Verification |
| **Discovery & Matching** | Qinyuan | Discovery, Swipe, Match, Recommendation, BaZi |
| **Messaging** | Parker, QX, Jiaxin | Chat Gateway, Message, Presence, Icebreaker |
| **Safety & Moderation** | Yue, Amber | Text Moderation, Image Moderation, Report, Rate Limiter |
| **Notifications** | Nili, Xiaoyuan | Push Notification, Email, Event Bus, Scheduler |
| **Analytics & Admin** | Jessica, Lingyun | Activity Logger, Analytics Pipeline, Admin Dashboard, Health Monitor |
| **Integration** | QX, KS | Cross-domain service orchestration |
| **PM / Frontend** | Qinyuan | Architecture, frontend (AI-generated), coordination |

---

## Microservice Map

### Domain 1 — Identity & Profiles

| Service | Owner | AWS Services | Description |
|---------|-------|-------------|-------------|
| Auth Service | Quinn Gao | Cognito, Lambda | Sign up, login, JWT tokens |
| Profile Service | Quinn Gao | Lambda, DynamoDB | CRUD for user profiles |
| Photo Service | KS | S3, Lambda, CloudFront | Upload, resize, serve photos |
| Email Verification | KS | SES, Lambda, Cognito | .edu email verification |

### Domain 2 — Discovery & Matching

| Service | Owner | AWS Services | Description |
|---------|-------|-------------|-------------|
| Discovery Service | Qinyuan | Lambda, DynamoDB | Filter and browse candidates |
| Swipe Service | Qinyuan | Lambda, DynamoDB | Record like/pass actions |
| Match Service | Qinyuan | Lambda, DynamoDB Streams, SNS | Detect mutual likes |
| Recommendation Service | Qinyuan | Lambda, DynamoDB | Score and rank candidates |
| BaZi Service | Qinyuan | Lambda | 八字 compatibility via external API |

### Domain 3 — Messaging

| Service | Owner | AWS Services | Description |
|---------|-------|-------------|-------------|
| Chat Gateway | Parker | API Gateway WebSocket, Lambda | Real-time message routing |
| Message Service | Parker | Lambda, DynamoDB | Persist and retrieve chats |
| Presence Service | QX | DynamoDB, Lambda | Online/offline/typing status |
| Icebreaker Service | Jiaxin | Bedrock, Lambda | AI conversation starters |

### Domain 4 — Safety & Moderation

| Service | Owner | AWS Services | Description |
|---------|-------|-------------|-------------|
| Text Moderation | Yue | Comprehend, Lambda | Flag toxic content |
| Image Moderation | Yue | Rekognition, Lambda | Block inappropriate photos |
| Report Service | Amber | Lambda, DynamoDB, SES | User reports → admin alerts |
| Rate Limiter | Amber | API Gateway, ElastiCache (Redis) | Anti-spam protection |

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
| Caching / Rate Limiting | ElastiCache (Redis) |
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
├── PRD.md
│
├── docs/
│   ├── api-contracts/                ← one API contract per service (25 files)
│   ├── system-design/
│   │   ├── Design_Doc.md             ← high-level architecture & decisions
│   │   ├── Infrastructure_Design.md  ← AWS resource details
│   │   ├── CDK_Migration_Plan.md     ← CDK migration guide
│   │   └── event-schema.json         ← canonical EventBridge event schemas
│   └── guides/
│       ├── Kismet_Setup_Guide.md     ← dev environment setup
│       ├── Service_Communication_Guide.md
│       └── SERVICE_README_TEMPLATE.md
│
├── infra/                            ← AWS CDK (Python)
│   ├── app.py                        ← CDK entry point
│   ├── cdk.json
│   ├── requirements.txt
│   ├── kismet_constructs/
│   │   └── kismet_service.py         ← reusable KismetService construct
│   └── stacks/
│       ├── shared_stack.py           ← Cognito, API GW, EventBridge, S3, Kinesis, SNS
│       ├── domain1_stack.py          ← Identity & Profiles
│       ├── domain2_stack.py          ← Discovery & Matching
│       ├── domain3_stack.py          ← Messaging
│       ├── domain4_stack.py          ← Safety & Moderation
│       ├── domain5_stack.py          ← Notifications & Engagement
│       └── domain6_stack.py          ← Analytics & Admin
│
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
│
└── frontend/                         ← React app (AI-generated)
```

Each service follows the same structure:
```
service-name/
├── lambda_function.py      ← handler function: handler(event, context)
├── requirements.txt
├── tests/
│   └── test_lambda_function.py
└── README.md
```


---

## Git Workflow

- `main` — stable, deployable (branch protection enabled)
- `domain-N/service-name` — feature branches

**PR flow:** feature branch → PR to `main` → 1 review required → merge

> `main` has branch protection: direct push disabled, at least 1 approving review required.

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
