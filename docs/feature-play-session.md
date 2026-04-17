# Feature Play Session Guide

Frontend: https://frontend-hazel-two-58.vercel.app
Admin: http://localhost:8501 (or Streamlit Cloud once deployed)

---

## Setup
1. Open the frontend in **two different browsers** (e.g. Chrome + Safari) to simulate two users
2. Log in as `test1@kismet.com` in one, `test2@kismet.com` in the other

---

## D1 — Identity & Profiles
- Sign up → check email for verification code → confirm
- Fill in profile (name, bio, age, gender, birth date/time for BaZi)
- Upload a profile photo
- View / edit profile

## D2 — Discovery & Matching
- Go to Discovery feed → browse candidate profiles
- Swipe right (Like) / left (Pass)
- From browser 2, swipe right on the same user → **match should appear**
- Check Matches tab to see the match

## D3 — Messaging
- Open a match → enter chat
- Send messages back and forth between the two browsers
- Watch real-time delivery (WebSocket)
- Check if an AI icebreaker message appears on first match

## D4 — Moderation
- Send a message with toxic content (e.g. "I hate you, kill yourself")
- Message should be flagged → check Admin Dashboard → Flagged Content tab
- Try uploading an inappropriate photo → should be rejected

## D5 — Notifications
- After a match, check if a push notification or email is received
- Check notification bell in the app

## D6 — Admin Dashboard
- Open Admin Dashboard (Streamlit)
- **Stats tab**: check total users, matches, messages count
- **Flagged Content tab**: review flagged messages/photos, click Approve / Remove / Ban User
- **Users tab**: search for a user, click Ban → verify they can't log in
- **Health Monitor tab**: see all 6 services green

---

## Quick E2E Flow (5 min demo)
1. test1 signs up + creates profile
2. test2 signs up + creates profile
3. test1 likes test2 → test2 likes test1 → **match**
4. test1 sends a message → test2 sees it instantly
5. test1 sends toxic message → admin sees it flagged
6. Admin bans test1 → test1 can't access app
