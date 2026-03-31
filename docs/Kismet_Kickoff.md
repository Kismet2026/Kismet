# Kismet — Team Allocation & Kickoff

## Team (14 people)

**PM / Architect / Frontend:** Qinyuan

### Domain 1 — Identity & Profiles (2 people)
| Service | Owner | AWS Services |
|---------|-------|-------------|
| Auth Service | Quinn Gao | Cognito, Lambda |
| Profile Service | Quinn Gao | Lambda, DynamoDB |
| Photo Service | Zhiping | S3, Lambda, CloudFront |
| Email Verification | Zhiping | SES, Lambda, Cognito |

### Domain 2 — Discovery & Matching (2 people)
| Service | Owner | AWS Services |
|---------|-------|-------------|
| Discovery Service | Hao | Lambda, DynamoDB |
| Swipe Service | Hao | Lambda, DynamoDB |
| Match Service | Hao | Lambda, DynamoDB Streams, SNS |
| Recommendation Service | Qinyuan | Lambda, DynamoDB |
| BaZi Compatibility Service | Qinyuan | Lambda (external API) |

### Domain 3 — Messaging (3 people, QX also on integration)
| Service | Owner | AWS Services |
|---------|-------|-------------|
| Chat Gateway | Parker | API Gateway WebSocket, Lambda |
| Message Service | Parker | Lambda, DynamoDB |
| Presence Service | QX | ElastiCache, Lambda |
| Icebreaker Service | Jiaxin | Bedrock, Lambda |

### Domain 4 — Safety & Moderation (3 people, KS also on integration)
| Service | Owner | AWS Services |
|---------|-------|-------------|
| Text Moderation | Yue | Comprehend, Lambda |
| Image Moderation | KS | Rekognition, Lambda |
| Report Service | Amber | Lambda, DynamoDB, SES |
| Rate Limiter | Amber | API Gateway, ElastiCache |

### Domain 5 — Notifications & Engagement (2 people)
| Service | Owner | AWS Services |
|---------|-------|-------------|
| Push Notification Service | Nili | SNS, Lambda |
| Email Service | Nili | SES, Lambda |
| Event Bus | Xiaoyuan | EventBridge, Lambda |
| Scheduler Service | Xiaoyuan | EventBridge Scheduler, Step Functions |

### Domain 6 — Analytics & Admin (2 people)
| Service | Owner | AWS Services |
|---------|-------|-------------|
| Activity Logger | Jessica | Kinesis Data Streams, Lambda |
| Analytics Pipeline | Jessica | Kinesis Firehose, S3, Athena |
| Admin Dashboard API | Lingyun | Lambda, DynamoDB |
| Health Monitor | Lingyun | CloudWatch, Lambda, SNS |

### Cross-cutting: Integration Team
| Person | Home Domain | Integration Responsibility |
|--------|------------|---------------------------|
| Zhiping | Identity | Cross-domain service orchestration |
| QX | Messaging | Cross-domain service orchestration |
| KS | Moderation | Cross-domain service orchestration |

---

## Totals
- **25 microservices**
- **18+ AWS services**: Lambda, API Gateway (REST + WebSocket), Cognito, DynamoDB, DynamoDB Streams, S3, CloudFront, ElastiCache, Rekognition, Comprehend, Bedrock, SNS, SES, EventBridge, Step Functions, Kinesis (Streams + Firehose), Athena, CloudWatch
- **14 people**, everyone owns 1-3 microservices

---

## Discord Kickoff Message (copy-paste below)

---

@everyone

**Kismet — Project Kickoff**

We're building a dating app with 25 microservices on AWS. Here's the plan:

**Your domain assignments:**
🔐 Identity & Profiles → Quinn Gao, Zhiping
🔍 Discovery & Matching → Qinyuan, Hao
💬 Messaging → Parker, QX, Jiaxin
🛡️ Safety & Moderation → Yue, KS, Amber
🔔 Notifications → Nili, Xiaoyuan
📊 Analytics & Admin → Jessica, Lingyun
🔗 Integration → Zhiping, QX, KS (cross-domain)
🎨 Frontend → Qinyuan (AI-generated)

**What each person owns:** (see pinned doc for full table)

**Week 1 tasks (due this Sunday):**
1. ✅ Join your domain channel in Discord
2. ✅ Find your partner(s), read through your assigned services
3. ✅ Write API contracts for your services — define every endpoint's request/response JSON
4. ✅ Push initial Lambda skeleton to your branch in the repo
5. ✅ Post in #standup what you've started

**Repo:** [link TBD]
**Standup format:**
```
[Name] — [Date]
✅ Done:
🔄 Doing:
🚧 Blocked:
```

**Timeline:**
- Week 1 (now → Apr 6): API contracts + Lambda scaffolding
- Week 2 (Apr 7–13): Build & unit test individual services
- Week 3 (Apr 14–16): Integration, demo prep, presentation slides
- Apr 17: 🎤 Presentation day

Questions? Drop them in #help or your domain channel.

Let's go 🚀
