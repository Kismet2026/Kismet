# Kismet — Product Requirements Document

> Cloud Computing Spring 2026 — Final Project
> Last updated: 2026-03-31

---

## 1. Overview & Vision

**Kismet** is a microservice-based dating application that differentiates itself through **BaZi (八字) compatibility matching** — an ancient Chinese astrological system that scores partner compatibility based on birth date and time.

The app is built entirely on AWS using a **serverless, event-driven architecture** comprising **25 microservices** across **6 domains**, powered by **18+ AWS services**.

**Goal:** Demonstrate cloud-native design at scale — microservice decomposition, event-driven communication, AI/ML integration, and real-time capabilities — in a working, end-to-end dating application.

---

## 2. Target Users

- **Primary:** College students
- **Demographics:** 18–25, tech-comfortable, open to personality-based matching
- **Key differentiator for users:** BaZi compatibility scores alongside traditional swipe-based discovery

---

## 3. Core Features

### 3.1 Identity & Profiles
- **Sign up / Login** — Cognito-based authentication with JWT tokens; email is auto-verified by Cognito
- **Profile management** — Create, read, update, delete user profiles
- **Photo upload** — Upload, auto-resize, and serve profile photos via CDN

### 3.2 Discovery & Matching
- **Discovery feed** — Browse and filter candidate profiles by preferences
- **Swipe** — Like or pass on candidate profiles
- **Mutual match detection** — When two users like each other, trigger a match event
- **Recommendation engine** — Score and rank candidates based on preferences, activity, and compatibility
- **BaZi compatibility** — Calculate compatibility scores via external BaZi API based on birth data

### 3.3 Messaging
- **Real-time chat** — WebSocket-based message routing for instant messaging between matches
- **Message persistence** — Store and retrieve full conversation history
- **Presence** — Online/offline/typing indicators via in-memory cache
- **AI icebreakers** — Bedrock-powered conversation starters to help users break the ice

### 3.4 Safety & Moderation
- **Text moderation** — Automated toxic content detection on messages using NLP
- **Image moderation** — Automated inappropriate photo detection on uploads
- **User reports** — Report system with admin alerts via email
- **Rate limiting** — Anti-spam protection at the API gateway level

### 3.5 Notifications & Engagement
- **Push notifications** — Alerts for new matches, messages, and engagement events
- **Email notifications** — Welcome emails, weekly digests, and transactional emails
- **Event bus** — Central cross-domain event routing backbone
- **Scheduled jobs** — Timed tasks (digest emails, cleanup, analytics aggregation)

### 3.6 Analytics & Admin
- **Activity logging** — Capture all user events into a real-time data stream
- **Analytics pipeline** — Stream events to a queryable data lake for analysis
- **Admin dashboard** — View platform stats, flagged content, and user reports
- **Health monitoring** — Service health alerts and CloudWatch-based observability

---

## 4. Architecture Overview

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

**Key architectural decisions:**
- **Serverless-first:** All compute runs on AWS Lambda — no servers to manage
- **Event-driven:** Domains communicate asynchronously via EventBridge, reducing coupling
- **Real-time:** WebSocket API Gateway for chat; DynamoDB TTL for presence; ElastiCache (Redis) for rate limiting
- **AI/ML native:** Rekognition (image moderation), Comprehend (text moderation), Bedrock (icebreakers)

---

## 5. Service Inventory

### Domain 1 — Identity & Profiles

| Service | Owner | AWS Services | Description |
|---------|-------|-------------|-------------|
| Auth Service | Quinn Gao | Cognito, Lambda | Sign up, login, JWT tokens |
| Profile Service | Quinn Gao | Lambda, DynamoDB | CRUD for user profiles |
| Photo Service | KS | S3, Lambda, CloudFront | Upload, resize, serve photos |

### Domain 2 — Discovery & Matching

| Service | Owner | AWS Services | Description |
|---------|-------|-------------|-------------|
| Discovery Service | Qinyuan | Lambda, DynamoDB | Filter and browse candidates |
| Swipe Service | Qinyuan | Lambda, DynamoDB | Record like/pass actions |
| Match Service | Qinyuan | Lambda, DynamoDB Streams, SNS | Detect mutual likes |
| Recommendation Service | Qinyuan | Lambda, DynamoDB | Score and rank candidates |
| BaZi Service | Qinyuan | Lambda | BaZi compatibility via external API |

### Domain 3 — Messaging

| Service | Owner | AWS Services | Description |
|---------|-------|-------------|-------------|
| Chat Gateway | Parker | API Gateway WebSocket, Lambda | Real-time message routing |
| Message Service | Parker | Lambda, DynamoDB | Persist and retrieve chats |
| Presence Service | QX | DynamoDB TTL, Lambda | Online/offline/typing status |
| Icebreaker Service | Jiaxin | Bedrock, Lambda | AI conversation starters |

### Domain 4 — Safety & Moderation

| Service | Owner | AWS Services | Description |
|---------|-------|-------------|-------------|
| Text Moderation | Yue | Comprehend, Lambda | Flag toxic content |
| Image Moderation | Yue | Rekognition, Lambda | Block inappropriate photos |
| Report Service | Xinyuan Fan (Amber) | Lambda, DynamoDB, SES | User reports with admin alerts |
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
| Activity Logger | Jessica | Kinesis Data Streams, Lambda | Capture user events |
| Analytics Pipeline | Jessica | Kinesis Firehose, S3, Athena | Queryable data lake |
| Admin Dashboard | Lingyun | Lambda, DynamoDB | Stats, flagged content |
| Health Monitor | Lingyun | CloudWatch, Lambda, SNS | Service health alerts |

---

## 6. User Flows

### 6.1 Sign Up
1. User enters email, password, and birth date/time
2. **Auth Service** creates Cognito account (email auto-verified by the user pool), returns JWT
3. **Event Bus** publishes `user.created` event
4. **Activity Logger** records the event; **Email Service** sends welcome email

### 6.2 Profile Creation
1. User fills in profile (name, bio, preferences)
2. **Profile Service** stores profile in DynamoDB
3. User uploads photos → **Photo Service** stores in S3, resizes via Lambda, serves via CloudFront
4. **Image Moderation** scans each photo via Rekognition → blocks inappropriate content
5. **Event Bus** publishes `profile.completed`

### 6.3 Discovery & Matching
1. User opens discovery feed
2. **Discovery Service** fetches candidates filtered by preferences
3. **Recommendation Service** scores/ranks candidates (including **BaZi Service** compatibility)
4. User swipes right (like) or left (pass) → **Swipe Service** records action
5. If mutual like detected → **Match Service** creates match, publishes `match.created`
6. **Push Notification** sends "It's a match!" alert to both users
7. **Email Service** sends match notification email

### 6.4 Messaging
1. Both matched users can now chat
2. **Chat Gateway** establishes WebSocket connection
3. Messages routed through **Chat Gateway** → persisted by **Message Service**
4. **Text Moderation** scans each message via Comprehend → flags toxic content
5. **Presence Service** tracks online/typing status via ElastiCache
6. **Icebreaker Service** can suggest AI-generated conversation starters via Bedrock
7. **Event Bus** publishes `message.sent` for downstream consumers

---

## 7. Cross-Domain Events (EventBridge)

| Event | Published By | Consumed By | Action |
|-------|-------------|-------------|--------|
| `user.created` | Auth Service | Activity Logger, Email Service | Log event, send welcome email |
| `profile.completed` | Profile Service | Recommendation Service, Activity Logger | Index for discovery, log event |
| `photo.uploaded` | Photo Service | Image Moderation | Scan for inappropriate content |
| `match.created` | Match Service | Push Notification, Email Service, Icebreaker, Activity Logger | Notify users, suggest icebreaker, log |
| `message.sent` | Message Service | Text Moderation, Activity Logger | Scan for toxicity, log event |
| `user.reported` | Report Service | Admin Dashboard, Email Service | Alert admins, send confirmation |
| `user.action` | Various | Activity Logger | Stream to Kinesis for analytics |

---

## 8. AWS Services Used (18+)

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

## 9. Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| **Compute** | 100% serverless (Lambda) — no EC2/ECS |
| **Scalability** | Auto-scales with Lambda concurrency; DynamoDB on-demand |
| **Latency** | Chat messages delivered < 500ms via WebSocket |
| **Content safety** | All photos scanned before display; all messages scanned in real-time |
| **Data durability** | DynamoDB for structured data; S3 for objects; Kinesis for streaming |
| **Observability** | CloudWatch metrics/alarms on all services; Health Monitor for alerts |
| **Cost** | Stay within AWS Academy / free-tier limits where possible |
| **Auth** | JWT-based, Cognito-managed, email auto-verified |

---

## 10. Team & Ownership

**12 team members** across 6 domains + integration + PM/frontend.

| Role | Members |
|------|---------|
| **PM / Architect / Frontend** | Qinyuan |
| **Domain 1 — Identity & Profiles** | Quinn Gao, KS |
| **Domain 2 — Discovery & Matching** | Qinyuan |
| **Domain 3 — Messaging** | Parker, QX, Jiaxin |
| **Domain 4 — Safety & Moderation** | Yue, KS, Xinyuan Fan (Amber) |
| **Domain 5 — Notifications** | Nili, Xiaoyuan |
| **Domain 6 — Analytics & Admin** | Jessica, Lingyun |
| **Integration Team** | QX, KS |

---

## 11. Timeline & Milestones

| Week | Dates | Milestone | Deliverables |
|------|-------|-----------|-------------|
| **Week 1** | Mar 31 — Apr 6 | API Contracts & Scaffolding | API contracts per service, Lambda skeletons, EventBridge event schema |
| **Week 2** | Apr 7 — Apr 13 | Build & Unit Test | Individual services implemented and unit tested |
| **Week 3** | Apr 14 — Apr 16 | Integration & Demo Prep | Cross-domain wiring, end-to-end testing, presentation slides |
| **Demo Day** | Apr 17 | Presentation & Live Demo | Working app, slide deck, live walkthrough |

---

## 12. Success Criteria

- [ ] All 25 microservices deployed and functional on AWS
- [ ] End-to-end user flow works: sign up → verify email → create profile → discover → swipe → match → chat
- [ ] BaZi compatibility scores displayed on candidate profiles
- [ ] Real-time messaging works via WebSocket
- [ ] Content moderation catches inappropriate text and images
- [ ] Push and email notifications fire on match/message events
- [ ] Admin dashboard shows platform stats and flagged content
- [ ] Analytics pipeline captures events and is queryable via Athena
- [ ] Health monitoring alerts on service failures
- [ ] Live demo runs without critical failures on Apr 17

---

## 13. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Team members unfamiliar with AWS | Delayed delivery | Setup guide provided; PM available for pairing |
| Cross-domain integration failures | Broken user flows | EventBridge contract defined in Week 1; integration team assigned |
| AWS service access issues (Bedrock, Rekognition) | Features blocked | Verify access in Week 1; have mock fallbacks |
| 3-week timeline is tight | Incomplete features | MVP-first approach; cut non-essential features early |
| WebSocket complexity | Chat doesn't work | Parker dedicated to chat; fallback to polling if needed |

---

*Generated from project docs — README.md, Kismet_Kickoff.md, Kismet_Setup_Guide.md*
