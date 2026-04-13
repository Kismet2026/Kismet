# Kismet Frontend Plan (v1 — Revised 2026-04-12)

> Supersedes `FRONTEND_PLAN_v0_OUTDATED.md`. Key changes: corrected API paths to match actual backend, added WebSocket chat, added `/recommend` endpoint usage, removed phantom endpoints.

## What's Already Built (Backend)

| Domain | Status | Key Endpoints |
|--------|--------|---------------|
| D1 Identity & Profiles | Deployed | `/auth/signup`, `/auth/confirm`, `/auth/login`, `/auth/refresh`, `/auth/logout`, `/profiles`, `/photos/upload`, `/users/{userId}/photos` |
| D2 Discovery & Matching | Deployed | `/discovery`, `/recommend`, `/bazi/top-matches`, `/swipe`, `/swipe/history`, `/matches`, `/matches/{matchId}` |
| D3 Messaging | Deployed | REST: `/messages`, `/messages/read`, `/messages/match/{matchId}`, `/messages/{messageId}`, `/presence/heartbeat`, `/presence/user/{userId}`, `/presence/{matchId}/typing`, `/icebreaker/generate`, `/icebreaker/{matchId}`. **WebSocket**: `wss://` with `$connect`, `$disconnect`, default route for real-time message delivery |
| D4 Safety & Moderation | Deployed | `/reports`, `/moderate/text`, `/moderate/image`, `/ratelimit/status/{userId}` |
| D5 Notifications | Deployed | `/notifications`, `/notifications/unread-count`, `/email/preferences` |
| D6 Analytics & Admin | Deployed | `/analytics/log`, `/admin/stats`, `/health` |

**Cognito**: User Pool `us-east-1_c20sP0XJb`, Client `6e5sk2hile04pihc81cgfn7psb`
**API Base**: `https://ugt4knycyj.execute-api.us-east-1.amazonaws.com/dev/`
**WebSocket**: `wss://<ws-api-id>.execute-api.us-east-1.amazonaws.com/dev`

---

## Tech Stack

- **Next.js 14+** (App Router) + TypeScript
- **Tailwind CSS** + **shadcn/ui** (dark theme)
- **framer-motion** (swipe card gestures)
- **react-hook-form** + **zod** (form validation)
- **jwt-decode** (token parsing)
- **date-fns** (date formatting)
- **Vercel** (deployment, root dir = `frontend/`)

---

## Project Structure

```
frontend/
├── admin/                          # EXISTING Streamlit dashboard — don't touch
├── .env.local                      # API_BASE_URL, WS_URL, Cognito IDs
├── src/
│   ├── app/
│   │   ├── layout.tsx              # Root: dark theme, AuthProvider
│   │   ├── page.tsx                # Landing / redirect
│   │   ├── globals.css
│   │   ├── (auth)/
│   │   │   ├── layout.tsx
│   │   │   ├── login/page.tsx
│   │   │   ├── signup/page.tsx
│   │   │   └── verify/page.tsx
│   │   └── (main)/                 # AuthGuard + BottomTabBar
│   │       ├── layout.tsx
│   │       ├── discover/page.tsx
│   │       ├── matches/page.tsx
│   │       ├── chat/[matchId]/page.tsx
│   │       ├── profile/page.tsx
│   │       ├── profile/edit/page.tsx
│   │       ├── profile/[userId]/page.tsx
│   │       └── onboarding/
│   │           ├── page.tsx        # Create profile
│   │           └── photos/page.tsx # Upload photos
│   ├── components/
│   │   ├── ui/                     # shadcn (auto-managed)
│   │   ├── layout/                 # BottomTabBar, AuthGuard
│   │   ├── auth/                   # LoginForm, SignupForm, VerifyForm
│   │   ├── discovery/              # SwipeCard, SwipeStack, BaziScoreBadge, MatchModal
│   │   ├── profile/               # ProfileForm, ProfileCard, PhotoUploader, PhotoGrid
│   │   ├── matches/               # MatchList, MatchCard
│   │   ├── chat/                  # ChatWindow, MessageBubble, ChatInput, TypingIndicator, IcebreakerSuggestions
│   │   └── shared/                # LoadingSpinner, EmptyState, ErrorBoundary
│   ├── lib/
│   │   ├── api.ts                  # Fetch wrapper: auth headers, 401 refresh, retry
│   │   ├── auth.ts                 # Token save/get/clear, JWT decode
│   │   ├── ws.ts                   # WebSocket client: connect, reconnect, message handler
│   │   └── utils.ts               # cn(), formatRelativeTime, calculateAge
│   ├── hooks/
│   │   ├── useAuth.ts, useProfile.ts, useDiscovery.ts
│   │   ├── useMatches.ts, useChat.ts, usePresence.ts
│   │   └── usePhotos.ts, useIcebreakers.ts
│   ├── context/
│   │   └── AuthContext.tsx
│   └── types/
│       ├── api.ts                  # PaginatedResponse<T>, ApiError
│       ├── user.ts                 # AuthTokens, UserProfile, Photo
│       ├── discovery.ts            # Candidate, SwipeAction, RecommendedCandidate
│       ├── match.ts                # Match, MatchDetail
│       └── chat.ts                 # Message, ChatStatus, IcebreakerSuggestion
```

---

## Correct API Mapping (v0 Errors Fixed)

| Frontend Action | v0 (WRONG) | Actual Backend Endpoint |
|-----------------|------------|------------------------|
| Get candidates | `GET /discovery` | `GET /discovery` OR `GET /recommend` (ranked by BaZi) |
| Send message | `GET /chat/{id}/messages` | `POST /messages` with `{matchId, content, messageType}` |
| Get messages | `GET /chat/{matchId}/messages` | `GET /messages/match/{matchId}` |
| Poll new messages | — | Re-fetch `GET /messages/match/{matchId}` with pagination when WebSocket is unavailable |
| Real-time messages | 3s HTTP polling only | **WebSocket** primary + HTTP polling fallback |
| Send verification | implicit in signup | Cognito sends the email code during `POST /auth/signup` |
| Confirm verification | — | `POST /auth/confirm` |
| Resend verification code | — | Not yet implemented on backend (`POST /auth/resend-code` is still pending) |
| List photos | — | `GET /users/{userId}/photos` |
| Upload photo | — | `POST /photos/upload` → presigned URL → PUT to S3 |
| Delete photo | — | `DELETE /photos/{photoId}` |
| Set primary photo | — | `PUT /photos/{photoId}/primary` |
| Notifications count | not in v0 | `GET /notifications/unread-count` |

---

## Implementation Phases

### Phase 1: Foundation (~3h)
1. `create-next-app` + deps + `shadcn init`
2. Types (`src/types/*`) — aligned with actual API response shapes
3. `lib/utils.ts`, `lib/auth.ts`, `lib/api.ts`
4. `lib/ws.ts` — WebSocket client with auto-reconnect
5. `AuthContext.tsx`
6. Root `layout.tsx` (dark theme + AuthProvider)
7. Shared components (LoadingSpinner, EmptyState, ErrorBoundary)

### Phase 2: Auth Flow (~4h)
1. `(auth)/layout.tsx` — centered card layout
2. `SignupForm` → `signup/page.tsx` (email + password + birthDate + birthTime)
3. After signup → Cognito has already sent the code, redirect to verify page
4. `VerifyForm` → `verify/page.tsx` (6-digit code → `POST /auth/confirm`)
5. Keep resend UI hidden or disabled until backend adds `POST /auth/resend-code`
6. `LoginForm` → `login/page.tsx` (→ onboarding if no profile, → discover if exists)
7. `AuthGuard` component
8. Landing `page.tsx` with redirect logic

**Milestone M1: Signup → verify (2-step) → login. Tokens stored. Protected routes work.**

### Phase 3: Profile & Onboarding (~4h)
1. `BottomTabBar` (Discover, Matches, Profile — 3 tabs)
2. `(main)/layout.tsx` — AuthGuard + BottomTabBar + presence heartbeat
3. `useProfile` hook (`POST /profiles`, `GET /profiles/{userId}`, `PUT /profiles/{userId}`)
4. `ProfileForm`: name, gender, interestedIn, birthDate, birthTime, location, bio, interests
5. `onboarding/page.tsx`
6. `usePhotos` hook (`POST /photos/upload` → S3 PUT, `GET /users/{userId}/photos`, `DELETE`, `PUT .../primary`)
7. `PhotoUploader` — 2x3 grid, file picker, presigned URL upload
8. `onboarding/photos/page.tsx` (require >= 1 photo)

**Milestone M2: Profile + photos created and persisted.**

### Phase 4: Discovery & Swipe (~5h)
1. `useDiscovery` hook — use `GET /recommend` (BaZi-ranked) as primary, `GET /discovery` as fallback
2. `BaziScoreBadge` — circular badge, color tiers (90+ gold, 70+ silver, below neutral)
3. `SwipeCard` — framer-motion drag, photo bg + gradient overlay, name/age/city/bio/bazi
4. `SwipeStack` — deck of 2 cards, `POST /swipe` with `{targetUserId, action: "like"|"pass"}`
5. `MatchModal` — celebration overlay when swipe response indicates mutual match
6. `discover/page.tsx`

**Milestone M3: Swipe works, matches trigger.**

### Phase 5: Matches (~3h)
1. `useMatches` hook (`GET /matches` → enrich with profile data)
2. `PresenceDot` using `GET /presence/user/{userId}`
3. `MatchCard` — avatar, name, last message preview, unread badge, relative time
4. `MatchList` + `matches/page.tsx`

**Milestone M4: Match list with names, avatars, presence.**

### Phase 6: Chat (~5h)
1. `lib/ws.ts` — WebSocket manager: connect with `?userId=&matchId=`, auto-reconnect with exponential backoff, message event dispatch
2. `useChat` hook — WebSocket for real-time receive, `POST /messages` for send, `GET /messages/match/{matchId}` for history, HTTP polling fallback by refetching `GET /messages/match/{matchId}` when WS disconnects
3. `usePresence` hook — `POST /presence/heartbeat` every 30s, `POST /presence/{matchId}/typing`, `GET /presence/{matchId}/typing` every 2s
4. `useIcebreakers` hook — `POST /icebreaker/generate`, `GET /icebreaker/{matchId}`
5. `MessageBubble`, `ChatInput`, `TypingIndicator`, `IcebreakerSuggestions`
6. `ChatWindow` — auto-scroll, scroll lock
7. `chat/[matchId]/page.tsx` — header with back, name, presence, unmatch button (`DELETE /matches/{matchId}`)

**Milestone M5: Real-time chat via WebSocket with polling fallback.**

### Phase 7: Profile Views & Polish (~4h)
1. `ProfileCard` (read-only), `PhotoGrid`
2. `profile/page.tsx`, `profile/edit/page.tsx`, `profile/[userId]/page.tsx`
3. Report dialog → `POST /reports`
4. Notification badge using `GET /notifications/unread-count`
5. Loading skeletons, error toasts, empty states

### Phase 8: Demo Ready (~2h)
1. Page transitions, match celebration animation
2. Mobile viewport testing (375px, 390px, 414px)
3. Favicon, meta tags, page titles
4. Deploy to Vercel
5. E2E test: 2 accounts on separate browsers

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **WebSocket primary + HTTP polling fallback** | Backend has full WS implementation. WS for real-time, HTTP polling when WS disconnects. |
| **`/recommend` over `/discovery`** | BaZi scoring is the app's differentiator. `/recommend` returns pre-ranked results. |
| **No state management library** | Only auth is cross-cutting. Each page fetches on mount. |
| **framer-motion for swipe** | Core UX. Native CSS drag lacks spring physics + exit animations. |
| **Dark theme only** | Modern dating app aesthetic. No light mode for demo. |
| **Client-side only (no SSR)** | All APIs require JWT. No tokens on server. All pages `"use client"`. |
| **Cognito-native verify flow** | Signup triggers Cognito's email code automatically; the verify page submits `POST /auth/confirm`. Resend is a separate future backend task. |
