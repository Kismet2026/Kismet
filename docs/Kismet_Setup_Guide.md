# Kismet — Project Setup Guide

## GitHub Repository Structure

```
kismet/
├── README.md                    # Project overview + architecture diagram
├── docs/
│   ├── architecture.md          # System design document
│   ├── api-contracts/           # API specs per service (JSON examples)
│   │   ├── auth-service.md
│   │   ├── profile-service.md
│   │   ├── photo-service.md
│   │   └── ...                  # One file per microservice
│   └── onboarding.md            # How to set up local dev, AWS credentials
│
├── frontend/                    # AI-generated HTML/JS/React app
│   └── README.md
│
├── services/
│   ├── domain-1-identity/
│   │   ├── auth-service/
│   │   │   ├── lambda_function.py   # (or index.js)
│   │   │   ├── requirements.txt     # (or package.json)
│   │   │   ├── template.yaml        # SAM / CloudFormation
│   │   │   ├── tests/
│   │   │   └── README.md            # Owner, endpoints, AWS services used
│   │   ├── profile-service/
│   │   ├── photo-service/
│   │   └── verification-service/
│   │
│   ├── domain-2-discovery/
│   │   ├── discovery-service/
│   │   ├── swipe-service/
│   │   ├── match-service/
│   │   └── recommendation-service/
│   │
│   ├── domain-3-messaging/
│   │   ├── chat-gateway/
│   │   ├── message-service/
│   │   ├── presence-service/
│   │   └── icebreaker-service/
│   │
│   ├── domain-4-moderation/
│   │   ├── text-moderation-service/
│   │   ├── image-moderation-service/
│   │   ├── report-service/
│   │   └── rate-limiter-service/
│   │
│   ├── domain-5-notifications/
│   │   ├── push-notification-service/
│   │   ├── email-service/
│   │   ├── event-bus-service/
│   │   └── scheduler-service/
│   │
│   └── domain-6-analytics/
│       ├── activity-logger-service/
│       ├── analytics-pipeline-service/
│       ├── admin-dashboard-service/
│       └── health-monitor-service/
│
└── infra/                       # Shared infrastructure (VPC, IAM roles, etc.)
    ├── shared-resources.yaml
    └── README.md
```

## Microservice README Template

Each service folder should have a README.md following this template:

```markdown
# [Service Name]

**Owner(s):** [Name 1], [Name 2]
**Domain:** [Domain name]
**Status:** 🔴 Not started / 🟡 In progress / 🟢 Complete / 🔵 Integrated

## Description
One-sentence description of what this service does.

## AWS Services Used
- Lambda (compute)
- DynamoDB (storage)
- etc.

## API Endpoints

### POST /endpoint-name
**Request:**
\```json
{
  "field": "value"
}
\```
**Response:**
\```json
{
  "field": "value"
}
\```

## Dependencies
- Depends on: [list services this calls]
- Called by: [list services that call this]
- Events published: [list EventBridge events emitted]
- Events consumed: [list EventBridge events listened to]

## Setup
How to deploy this service to AWS.

## Testing
How to test locally and in the cloud.
```

---

## Discord Channel Structure

```
CLOUDMATCH SERVER
├── 📋 GENERAL
│   ├── #announcements          (PM posts updates, deadlines, decisions)
│   ├── #standup                (daily async check-ins)
│   ├── #random                 (off-topic)
│   └── #help                   (cross-domain questions)
│
├── 🔐 DOMAIN 1 — IDENTITY
│   └── #identity-profiles
│
├── 🔍 DOMAIN 2 — DISCOVERY
│   └── #discovery-matching
│
├── 💬 DOMAIN 3 — MESSAGING
│   └── #messaging
│
├── 🛡️ DOMAIN 4 — MODERATION
│   └── #safety-moderation
│
├── 🔔 DOMAIN 5 — NOTIFICATIONS
│   └── #notifications
│
├── 📊 DOMAIN 6 — ANALYTICS
│   └── #analytics-admin
│
├── 🎨 FRONTEND
│   └── #frontend
│
└── 🔗 INTEGRATION
    └── #integration            (cross-domain issues, API contract changes)
```

### Daily Standup Template (post in #standup)

```
**[Name] — [Date]**
✅ Done: [what you finished]
🔄 Doing: [what you're working on today]
🚧 Blocked: [anything blocking you, tag relevant people]
```

---

## GitHub Projects Board

Create a project board with these columns:

| Column | Description |
|--------|-------------|
| **Backlog** | All tasks not yet started |
| **Week 1: API Contracts** | Defining endpoints, request/response formats |
| **Week 2: Build & Test** | Individual service development |
| **Week 3: Integrate & Demo** | Cross-domain wiring, demo prep |
| **Done** | Completed and merged |

### Label System

| Label | Meaning |
|-------|---------|
| `domain-1-identity` | Identity & Profiles domain |
| `domain-2-discovery` | Discovery & Matching domain |
| `domain-3-messaging` | Messaging domain |
| `domain-4-moderation` | Safety & Moderation domain |
| `domain-5-notifications` | Notifications & Engagement domain |
| `domain-6-analytics` | Analytics & Admin domain |
| `frontend` | Frontend tasks |
| `integration` | Cross-domain integration |
| `api-contract` | API spec definition |
| `blocked` | Blocked by something |
| `urgent` | Needs immediate attention |

---

## Git Branching Strategy

Keep it simple for 3 weeks:

- `main` — stable, deployable code
- `dev` — integration branch, merge here first
- `domain-N/service-name` — feature branches per service

**Workflow:**
1. Create branch: `domain-1/auth-service`
2. Work on your service
3. PR → `dev` (get 1 review from your domain partner)
4. After integration testing, PM merges `dev` → `main`

---

## Week 1 Task Checklist (GitHub Issues to Create)

### Setup (PM / everyone)
- [ ] Create GitHub repo with folder structure
- [ ] Create Discord server with channels
- [ ] Set up GitHub Projects board
- [ ] Verify AWS service access (Cognito, Rekognition, Bedrock, Kinesis, ElastiCache, Comprehend)
- [ ] Assign people to domains
- [ ] Share AWS account / IAM setup instructions

### API Contracts (each domain pair)
- [ ] Domain 1: Define auth, profile, photo, verification API contracts
- [ ] Domain 2: Define discovery, swipe, match, recommendation API contracts
- [ ] Domain 3: Define chat gateway, message, presence, icebreaker API contracts
- [ ] Domain 4: Define text moderation, image moderation, report, rate limiter API contracts
- [ ] Domain 5: Define push notification, email, event bus, scheduler API contracts
- [ ] Domain 6: Define activity logger, analytics, admin dashboard, health monitor API contracts

### EventBridge Events (PM + all domains)
- [ ] Define shared event schema: which domain publishes what events
  - e.g., `match.created` → Notifications listens → sends push + email
  - e.g., `message.sent` → Moderation listens → scans for toxicity
  - e.g., `photo.uploaded` → Moderation listens → scans for inappropriate content
  - e.g., `user.action` → Analytics listens → logs to Kinesis

### Individual (each person)
- [ ] Scaffold Lambda function skeleton for your 2 services
- [ ] Write README for each service using the template
- [ ] Push initial code to your branch
