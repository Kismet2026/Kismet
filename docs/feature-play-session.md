# Feature Play Session Guide

**Frontend:** See `NEXT_PUBLIC_APP_URL` in project README
**Admin Dashboard:** http://localhost:8501 (login: admin@kismet.com)

---

## Prerequisites

### Admin Dashboard setup (D6)
1. Deploy shared + domain6 stacks:
   ```bash
   cd infra
   cdk deploy -c enableActivityStream=true KismetShared KismetDomain6
   ```
2. Create the admin Cognito user (run once after deploy):
   ```bash
   ./scripts/create-admin-user.sh <UserPoolId>
   ```
   `UserPoolId` is printed as a CloudFormation output (`KismetShared.UserPoolId`) after deploy.
3. Start the Admin Dashboard with the API Gateway URL:
   ```bash
   API_BASE_URL=<KismetShared.ApiUrl> streamlit run frontend/admin/app.py
   ```

---

## Setup
- All 19 test accounts already created with profiles
- Open frontend in **two different browsers** to simulate two users
- Log in as `test1@kismet.com` in one, `test2@kismet.com` in the other

---

## D1 — Identity & Profiles
- Log in with any test account → profile already exists
- Go to Profile page → view/edit name, bio, interests
- Upload a profile photo (stored in S3, served via CloudFront CDN)

## D2 — Discovery & Matching
- Go to Discovery feed → browse profiles with BaZi compatibility scores
- Swipe right (Like) on a user
- From browser 2, swipe right on the same user → **match notification appears**
- Check Matches tab to see the match

## D3 — Messaging
- Open a match → enter chat room
- Send messages between the two browsers → **real-time delivery via WebSocket**
- An AI-generated icebreaker appears on first match

## D4 — Moderation
- Send a message with toxic content (e.g. "I hate you")
- Message gets flagged → visible in Admin Dashboard → Flagged Content tab
- Upload an inappropriate photo → rejected by Rekognition

## D5 — Notifications
- After a match → push notification / email sent automatically
- Check notification bell in the app

## D6 — Admin Dashboard (admin@kismet.com)
- **Stats tab** — platform-wide metrics (totalUsers, matches, messages)
- **Flagged Content tab** — review flagged messages/photos → Approve / Remove / Ban User
- **Users tab** — search users, ban/unban
- **Health Monitor tab** — all 6 services green in real-time
- **Analytics Pipeline tab** — shows Kinesis → Firehose → S3 → Athena pipeline status + live event stats

---

## Quick E2E Demo (5 min)
1. Login as test1 + test2 in two browsers
2. test1 swipes right on test2 → test2 swipes right back → **match**
3. test1 sends a message → test2 sees it instantly (WebSocket)
4. test1 sends toxic message → Admin Dashboard shows it flagged
5. Admin bans test1 → test1 loses access
6. Admin Dashboard → Analytics Pipeline tab → show Kinesis pipeline data
