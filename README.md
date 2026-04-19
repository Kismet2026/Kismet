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
| **Identity & Profiles** | Quinn Gao, KS | Auth, Profile, Photo |
| **Discovery & Matching** | Qinyuan Shen | Discovery, Swipe, Match, Recommendation, BaZi |
| **Messaging** | Parker, QX, Jiaxin | Chat Gateway, Message, Presence, Icebreaker |
| **Safety & Moderation** | Yue, Xinyuan Fan (Amber) | Text Moderation, Image Moderation, Report, Rate Limiter |
| **Notifications** | Nili, Xiaoyuan | Push Notification, Email, Event Bus, Scheduler |
| **Analytics & Admin** | Yuyi Zhang, Lingyun | Activity Logger, Analytics Pipeline, Admin Dashboard, Health Monitor |
| **Integration** | Qinyuan Shen | Cross-domain service orchestration |
| **PM / Frontend** | Qinyuan Shen | Architecture, frontend (AI-generated), coordination |

---

## Microservice Map

### Domain 1 — Identity & Profiles

| Service | Owner | AWS Services | Description |
|---------|-------|-------------|-------------|
| Auth Service | Quinn Gao | Cognito, Lambda | Sign up, login, JWT tokens |
| Profile Service | Quinn Gao | Lambda, DynamoDB | CRUD for user profiles |
| Photo Service | KS | S3, Lambda, CloudFront | Upload, resize, serve photos |

### Domain 2 — Discovery & Matching

| Service | Owner | AWS Services | Description |
|---------|-------|-------------|-------------|
| Discovery Service | Qinyuan Shen | Lambda, DynamoDB | Filter and browse candidates |
| Swipe Service | Qinyuan Shen | Lambda, DynamoDB | Record like/pass actions |
| Match Service | Qinyuan Shen | Lambda, DynamoDB, EventBridge | Detect mutual likes, ban cascade |
| Recommendation Service | Qinyuan Shen | Lambda, DynamoDB | Score and rank candidates |
| BaZi Service | Qinyuan Shen | Lambda | 八字 compatibility via external API |

### Domain 3 — Messaging

| Service | Owner | AWS Services | Description |
|---------|-------|-------------|-------------|
| Chat Gateway | Parker, Jiaxin | API Gateway WebSocket, Lambda | Real-time message routing |
| Message Service | Parker | Lambda, DynamoDB | Persist and retrieve chats |
| Presence Service | QX | DynamoDB, Lambda | Online/offline/typing status |
| Icebreaker Service | Jiaxin | Bedrock, Lambda | AI conversation starters |

### Domain 4 — Safety & Moderation

| Service | Owner | AWS Services | Description |
|---------|-------|-------------|-------------|
| Text Moderation | Yue | Comprehend, Lambda | Flag toxic content |
| Image Moderation | Yue | Rekognition, Lambda, S3 | Scan uploads; flag nudity/violence/weapons |
| Report Service | Xinyuan Fan (Amber) | Lambda, DynamoDB, SES, EventBridge | User reports → admin email + auto-ban at threshold |
| Rate Limiter | Xinyuan Fan (Amber) | API Gateway, ElastiCache (Redis) | Anti-spam protection |

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
| Activity Logger | Yuyi Zhang | Kinesis Data Streams, Lambda | Capture user events |
| Analytics Pipeline | Yuyi Zhang | Kinesis Firehose, S3, Athena | Queryable data lake |
| Admin Dashboard | Lingyun | Lambda, DynamoDB, Streamlit (SCC) | Stats, flagged content; Streamlit UI on Streamlit Community Cloud |
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
│   │   ├── SharedStack_Design.md     ← deep dive: shared foundation (Cognito/API GW/EventBus/S3/CDN)
│   │   ├── Domain1_Design.md         ← deep dive: Identity & Profiles
│   │   ├── Domain2_Design.md         ← deep dive: Discovery & Matching
│   │   ├── Domain3_Design.md         ← deep dive: Messaging
│   │   ├── Domain4_Design.md         ← deep dive: Safety & Moderation
│   │   ├── Domain5_Design.md         ← deep dive: Notifications & Engagement
│   │   ├── Domain6_Design.md         ← deep dive: Analytics & Admin
│   │   └── event-schema.json         ← canonical EventBridge event schemas
│   └── guides/
│       └── Service_Communication_Guide.md
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
│   │   └── photo-service/
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
├── tests/
│   └── test_cross_domain_integration.py  ← 49 integration tests
│
├── scripts/
│   ├── create-admin-user.sh         ← bootstrap the admin@kismet.com Cognito user
│   ├── verify-d6.sh                 ← one-shot D6 unit + integration + synth check
│   └── seed_profiles.py             ← populate demo profiles
│
└── frontend/                         ← user-facing app + admin dashboard
    ├── (Next.js, Vercel)            ← `src/app/` — dating app UI
    └── admin/                        ← Streamlit admin console, deployed on SCC
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

## Current Status (as of Apr 17)

**All 7 CDK stacks deployed. User frontend on Vercel, admin console on Streamlit Community Cloud.**

| Stack | Status |
|-------|--------|
| SharedStack | Deployed |
| Domain 1 — Identity | Deployed |
| Domain 2 — Discovery | Deployed |
| Domain 3 — Messaging | Deployed |
| Domain 4 — Moderation | Deployed |
| Domain 5 — Notifications | Deployed |
| Domain 6 — Analytics | Deployed |

**Live demo:** available on request (URL withheld to limit public exposure)
- 49 cross-domain integration tests passing
- End-to-end flow verified on mobile web: signup → profile → discover → swipe → match → chat

### Sprint 3 highlights (Apr 11–16)

- **Account lifecycle**: full cascade on `user.deleted` across all 6 domains (#111, #113)
- **Ban pipeline**: auto-ban at 2 distinct reports (#114) with cascade across matches, messages, and recommendation cache (#119)
- **Image moderation**: live end-to-end with AWS Rekognition — uploads go through D4 before landing in the discovery pool; inappropriate content surfaces a rejection dialog in the UI
- **Image normalization**: WebP/HEIC uploads auto-converted to JPEG client-side so Rekognition can always scan them
- **BaZi scoring**: bidirectional compatibility (你→ta and ta→你) visualized as a yin-yang dual-ring badge
- **Follow-up issues (all resolved before demo)**: ban notification email ([#120](https://github.com/Kismet2026/Kismet/issues/120) → [#133](https://github.com/Kismet2026/Kismet/pull/133)), ban-then-resignup loophole ([#121](https://github.com/Kismet2026/Kismet/issues/121) → [#124](https://github.com/Kismet2026/Kismet/pull/124)), API Gateway stage auto-redeploy ([#118](https://github.com/Kismet2026/Kismet/issues/118) → [#131](https://github.com/Kismet2026/Kismet/pull/131) + postmortem [#132](https://github.com/Kismet2026/Kismet/pull/132))

---

## Timeline

| Week | Milestone | Status |
|------|-----------|--------|
| Week 1 (Apr 1–6) | API contracts, Lambda scaffolding | ✅ |
| Week 2 (Apr 7–10) | Build, unit test, CDK deploy, integration tests | ✅ |
| Week 3 (Apr 11–16) | Frontend, D3 fix, moderation pipeline, demo prep | ✅ |
| **Apr 17** | Presentation & Demo | ▶ |

---

## Getting Started

1. Clone this repo
2. Navigate to your service folder under `services/`
3. Read your service's README for setup instructions
4. Deploy: `cd infra && npx cdk deploy <StackName> --app "python3 app.py"`

> **Heads up — `enableActivityStream` context flag.** If the target AWS account already has D6's activity pipeline deployed (Kinesis stream `kismet-activity-stream` + `kismet-activity-firehose`), **every `cdk deploy` on that account must include `-c enableActivityStream=true`**, even when deploying an unrelated stack. `cdk.json` ships with the flag set to `false` (to keep the stream opt-in and avoid the ~$11/month Kinesis cost on fresh environments), and without the CLI override CDK will try to drift-correct `KismetShared` back to the no-stream state on every deploy, fail because `KismetDomain6` still imports the ActivityStream ARN, and auto-rollback. No damage, but your real deploy never runs. Example: `cdk deploy KismetDomain2 -c enableActivityStream=true`.

### User frontend (Next.js, Vercel)

Local:

```bash
cd frontend
npm install
npm run dev     # http://localhost:3000
```

Required env vars (put them in `frontend/.env.local`):

```
NEXT_PUBLIC_API_BASE_URL=https://<api-id>.execute-api.<region>.amazonaws.com/dev
NEXT_PUBLIC_WS_URL=wss://<ws-api-id>.execute-api.<region>.amazonaws.com/dev
NEXT_PUBLIC_COGNITO_USER_POOL_ID=<KismetShared.UserPoolId>
NEXT_PUBLIC_COGNITO_CLIENT_ID=<KismetShared.UserPoolClientId>
```

All four values come from `cdk deploy KismetShared` outputs.

Deploy (Vercel):

1. Connect `Kismet2026/Kismet` in Vercel, set **Root Directory** to `frontend/`
2. Add the same four `NEXT_PUBLIC_*` vars in **Project Settings → Environment Variables**
3. Pushes to `main` auto-deploy to production; PRs get preview URLs

### Admin dashboard (Streamlit)

Local:

```bash
cd frontend/admin
pip install -r requirements.txt
API_BASE_URL="<your-api-gateway-base-url>" streamlit run app.py
```

Cloud (Streamlit Community Cloud):

1. New app → pick this repo, branch `main`, main file `frontend/admin/app.py`
2. Under **Advanced settings**, add secret `API_BASE_URL = "<api-gateway-base-url>"`
3. Python version is pinned via [`frontend/admin/runtime.txt`](frontend/admin/runtime.txt) to match CI (3.12)
4. First-time admin login requires `./scripts/create-admin-user.sh <UserPoolId>`
