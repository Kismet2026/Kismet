# Domain 1 — Identity & Profiles

> Detailed design for the auth, profile, and photo services.
> Source of truth: [`infra/stacks/domain1_stack.py`](../../infra/stacks/domain1_stack.py) + [`services/domain-1-identity/`](../../services/domain-1-identity/)
> Last verified: Apr 16, 2026

---

## 1. Purpose

Domain 1 is the "front door" of Kismet — it owns **who a user is, how they log in, what their profile looks like, and which photos they've uploaded**. Three Lambda services are wired into the shared REST API via `Domain1Stack`: Auth, Profile, and Photo. Cognito's built-in auto-verification handles email confirmation at signup, so no separate verification service is needed. (An `email-verification-service/` directory exists in-tree as legacy code but is not provisioned — see §8.)

Downstream, D1 publishes the lifecycle events that every other domain keys off: `user.created`, `profile.completed`, `profile.updated`, `profile.banned`, `user.deleted`, and `photo.uploaded`. Upstream, D1 consumes `user.banned` from D4 (re-emitted as `profile.banned`) and — for the Photo service — its own `user.deleted` fan-out.

---

## 2. Architecture

```
                    ┌─────────────────────────────────┐
                    │   Imported REST API + Cognito   │
                    └───┬───────┬───────┬─────────────┘
                        │       │       │
                  ┌─────▼──┐ ┌──▼─────┐ ┌▼─────────┐
                  │  Auth  │ │Profile │ │  Photo   │──► S3 (presigned PUT)
                  └───┬────┘ └───┬────┘ └────┬─────┘     + CloudFront
                      │          │           │
                ┌─────▼──┐  ┌────▼─────┐ ┌──▼──────┐
                │kismet- │  │ kismet-  │ │kismet-  │
                │users   │  │ profiles │ │ photos  │
                └────────┘  └──────────┘ └─────────┘

    EventBridge: kismet-events
      in:  user.banned (D4), user.deleted (self, to Photo)
      out: user.created, profile.completed, profile.updated,
           profile.banned, user.deleted, photo.uploaded
```

See [`diagrams/domain1-architecture.drawio`](./diagrams/) for the full picture with Cognito, SES, and downstream consumers.

---

## 3. Services

### 3.1 Auth Service

| | |
|---|---|
| **Entry** | `POST /auth/signup`, `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/confirm` (all unauthenticated) |
| **Table** | `kismet-users` (PK `USER#{userId}`, SK `METADATA`) |
| **Consumes events** | none |
| **Publishes** | `user.created` (on signup) |

**Responsibilities**

1. Thin shell over Cognito User Pool operations — `sign_up`, `initiate_auth` (USER_PASSWORD_AUTH and REFRESH_TOKEN_AUTH), `revoke_token`, `confirm_sign_up`.
2. Mirror the minimal user metadata (`userId`, `email`, `createdAt`, plus optional `birthDate`/`birthTime`) into `kismet-users` so other services aren't coupled to Cognito's API surface.
3. Publish `user.created` once the Cognito SignUp returns a `UserSub`.

**Key design choices**

- **Cognito is the identity source of truth.** `kismet-users` is a small denormalization keyed on `sub`, written immediately after `sign_up`. No auth verification logic lives here — JWTs are validated by API Gateway's Cognito authorizer on every other D1/D2/D3 route.
- **Error mapping is centralized** in `_handle_cognito_error` — Cognito exception codes (`UsernameExistsException`, `NotAuthorizedException`, `CodeMismatchException`, etc.) map to stable HTTP status + `code` pairs so the frontend never sees raw AWS errors.
- **Refresh returns the same refresh token.** Cognito's REFRESH_TOKEN_AUTH flow doesn't re-issue one; the handler echoes the original so clients can treat the response shape as uniform.

### 3.2 Profile Service

| | |
|---|---|
| **Entry** | `POST /profiles`, `GET/PUT/DELETE /profiles/{userId}` (all Cognito-authenticated) |
| **Table** | `kismet-profiles` (PK `USER#{userId}`, SK `PROFILE`) |
| **Consumes events** | `user.banned` (from D4 report-service) |
| **Publishes** | `profile.completed`, `profile.updated`, `profile.banned`, `user.deleted` |

**Responsibilities**

1. Own the canonical user doc — name, gender, interestedIn, birthDate/birthTime, location (lat/long), city, bio, interests, avatarUrl, status.
2. Enforce the `status ∈ {active, banned}` contract: banned profiles return 404 from `GET /profiles/{userId}` so they effectively vanish for end-users.
3. Be the **bridge between moderation and downstream consumers**: translate D4's `user.banned` into `profile.banned` so D2/D3/D5 can wire a single upstream source. See §5.3.
4. Fan out `user.deleted` on self-service account deletion so D1 Photo, D2, D3, and D5 can all clean up.

**Key design choices**

- **Strict validation on create**: `gender ∈ {male, female, non-binary}`, `interestedIn ∈ {male, female, non-binary, everyone}`, `birthDate` and `location` required. A `409 CONFLICT` is returned if a PROFILE row already exists for the user.
- **`UPDATABLE_FIELDS` allowlist** on PUT — a client can't accidentally overwrite `status`, `createdAt`, `bannedAt`, or any moderation-set field by including it in the request body.
- **`profile.updated` payload always reflects the post-write state.** The handler does a fresh `get_item` after `update_item` and builds the event detail from that, so D2 discovery's denormalized copy never drifts.
- **Caller/path authz**: PUT and DELETE require `caller_id == user_id`. There is no admin edit path in this service — admin bans flow through D4 → `user.banned`.
- **Idempotent DELETE** (#113-followup): `delete_item` on a non-existent row is a no-op, so retries after partial failure are safe. The EventBridge publish is the one thing that must succeed — a `FailedEntryCount > 0` returns 500 and the caller can retry.

### 3.3 Photo Service

| | |
|---|---|
| **Entry** | `POST /photos/upload`, `POST /photos/{photoId}/confirm`, `GET /users/{userId}/photos`, `DELETE /photos/{photoId}`, `PUT /photos/{photoId}/primary` |
| **Table** | `kismet-photos` (PK `USER#{userId}`, SK `PHOTO#{photoId}`) |
| **Consumes events** | `user.deleted` |
| **Publishes** | `photo.uploaded` (on confirm only) |

**Responsibilities**

1. Generate presigned S3 PUT URLs so the frontend uploads directly to the `kismet-photos-*` bucket — Lambda never touches image bytes.
2. Track per-user photo metadata and enforce the `MAX_PHOTOS_PER_USER = 6` cap.
3. Maintain exactly one `isPrimary = True` photo per user, and mirror the primary photo's CDN URL into `kismet-profiles.avatarUrl` and `kismet-discovery.avatarUrl`.
4. Garbage-collect on `user.deleted`: query all PHOTO rows for the user, delete each S3 object (best-effort), then delete the DynamoDB rows.

**Two-step upload pattern** (#112)

```
1. POST /photos/upload          ──► returns { photoId, uploadUrl } ; row.status = "pending"
2. PUT  {uploadUrl} (to S3)     ──► client uploads bytes directly
3. POST /photos/{photoId}/confirm ──► row.status = "active"
                                      publishes photo.uploaded
                                      if primary, mirrors avatarUrl
```

The confirm endpoint exists because **D4 image-moderation needs a stable S3 object to scan**. The naive one-step flow would publish `photo.uploaded` immediately on `POST /photos/upload`, before bytes are in S3 — Rekognition would get `NoSuchKey` roughly every time. Split into two steps: the server only publishes once the client confirms the PUT succeeded.

**Photo status lifecycle**

```
   pending ──(POST /confirm)──► active ──(D4 Rekognition NSFW hit)──► rejected
```

`handle_list` filters out both `pending` and `rejected` items — so a freshly uploaded-but-not-confirmed photo is invisible, and a moderation-rejected photo stops being shown to the user **and** stops being included in the profile feed D2 uses. This is what makes the D4 moderation loop work end-to-end without Photo service having to consume a moderation event: D4 writes `status=rejected` directly, and the next `GET /users/{userId}/photos` just stops returning it.

**Content-type gate**: `ALLOWED_CONTENT_TYPES = {image/jpeg, image/png, image/webp}` at upload. Note Rekognition only supports JPEG/PNG — the frontend normalizes WebP/HEIC to JPEG client-side (see §7).

**Primary-photo maintenance**:

- First upload for a user auto-becomes primary.
- `PUT /photos/{photoId}/primary` unsets any existing primary, sets the target, then mirrors `avatarUrl` into `kismet-profiles` and `kismet-discovery` (both guarded with `ConditionExpression: attribute_exists(PK)` so it's a no-op if the row isn't there yet).
- `DELETE` of the primary promotes the most-recent remaining photo (by `uploadedAt`) so the user is never left avatar-less with photos still on file.

### 3.4 Email Verification (Cognito built-in)

No standalone service — Cognito's user pool is configured with `auto_verify=cognito.AutoVerifiedAttrs(email=True)` in `SharedStack`, which triggers the built-in confirmation-code email at signup. A legacy `email-verification-service/` directory exists in the repo from an earlier design iteration but is **not wired into any CDK stack**, has no API Gateway routes, and no DynamoDB table is provisioned for it. Not dead code so much as "moved into Cognito." Safe to delete.

---

## 4. Data Layer

| Table | Owner | Primary key | Size profile | Notes |
|-------|-------|-------------|--------------|-------|
| `kismet-users` | Auth | `USER#{userId}` / `METADATA` | ~N users | denormalization of Cognito `sub`; small, rarely read |
| `kismet-profiles` | Profile | `USER#{userId}` / `PROFILE` | ~N users | canonical profile doc; `status ∈ {active, banned}` |
| `kismet-photos` | Photo | `USER#{userId}` / `PHOTO#{photoId}` | ≤ 6·N | `status ∈ {pending, active, rejected}`; one row per upload |

All tables use on-demand billing. No GSIs — every access pattern is direct-key or a single-PK Query.

**S3**: `kismet-photos-{account}-dev` holds raw uploads. Keys are `{userId}/{photoId}.{ext}`. Frontend reads through CloudFront at `PHOTOS_CDN_BASE_URL`; presigned PUTs go direct to the bucket with a 5-minute `ExpiresIn`.

**Cross-table writes**: Photo's `_update_profile_avatar` is the only cross-domain writer in D1 — it writes `avatarUrl` into both `kismet-profiles` (D1) and `kismet-discovery` (D2). Both writes are conditional on `attribute_exists(PK)` so they're safe if the target row hasn't been created yet. IAM grants for this are scoped in `domain1_stack.py` via `extra_policies`.

---

## 5. Event Flows

### 5.1 Signup + profile creation

```
Client                Auth Service              Profile Service          EventBridge
  │ POST /auth/signup     │                           │                       │
  │──────────────────────►│ cognito.sign_up           │                       │
  │                       │ put kismet-users          │                       │
  │                       │ publish user.created ─────┼──────────────────────►│
  │                       │                           │                       │
  │ POST /profiles        │                           │                       │
  │──────────────────────────────────────────────────►│ put kismet-profiles   │
  │                                                   │ publish               │
  │                                                   │ profile.completed ───►│
                                                                              │
                                         ┌────────────────────────────────────┤
                                         ▼                                    ▼
                                  D2 Discovery insert               D5/D6 consumers
                                  D2 Recommendation marker
```

### 5.2 Photo upload (two-step)

```
Client            Photo Service          S3            D4 Image Moderation
  │ POST /photos/upload  │                │                     │
  │─────────────────────►│ presigned PUT  │                     │
  │                      │ row.status=    │                     │
  │◄─────────────────────│   pending      │                     │
  │ PUT {uploadUrl}      │                │                     │
  │─────────────────────────────────────► │ object created      │
  │ POST /photos/{id}/confirm             │                     │
  │─────────────────────►│ row.status=    │                     │
  │                      │   active       │                     │
  │                      │ publish photo.uploaded ──────────────►│
  │                      │                │                     │ scan → if NSFW,
  │                      │                │                     │ set row.status=rejected
  │◄─────────────────────│ if primary,    │                     │
  │                      │ avatarUrl sync │                     │
```

Because `handle_list` filters out `pending` and `rejected`, a moderation-rejected photo stops showing in both the user's own profile view and D2's discovery card without any further coordination.

### 5.3 Ban cascade (D4 → D1 → everyone)

```
D4 Report Service
   │ (auto-ban threshold hit, or admin resolve=ban)
   └─── user.banned ──► EventBridge
                           │
                           ▼
                    D1 Profile Service  (handle_user_banned)
                      - set status=banned on profile row
                      - attach banReason, banReportId, bannedAt
                      - publish profile.banned
                           │
                           └─► EventBridge
                                   │
          ┌──────────────┬─────────┼───────────────┬────────────┐
          ▼              ▼         ▼               ▼            ▼
      D2 Discovery   D2 Match  D2 Recommend   D3 Message   D5 Email
      delete pool    purge     clear cache    purge        (pending #120)
      row            matches                  threads
```

Profile Service is the single bridge: D4 emits one event, D1 decorates + re-emits as `profile.banned`, and downstream consumers only need to listen to D1. This keeps D2/D3/D5 decoupled from D4's internal event vocabulary.

### 5.4 Account deletion fan-out (#113)

`DELETE /profiles/{userId}` issues three side effects in order:

1. `delete_item` on the profile row (idempotent).
2. `cognito.admin_delete_user` to free the email for re-registration (see gotcha below).
3. `put_events` `user.deleted`.

The `user.deleted` event fans out to:

- **D1 Photo** — deletes S3 objects + table rows
- **D2 Discovery / Swipe / Match / Recommendation** — purge pool row, swipes, matches, cached recommendations
- **D3 Message** — purge conversation threads
- **D5 Email** — purge notification preferences

If the EventBridge publish fails, the handler returns 500 and the client can safely retry — the profile row is already gone, so retry re-runs Cognito delete (no-op on `UserNotFoundException`) and re-publishes.

---

## 6. Cross-Service Dependencies

| Caller | External reads/writes | Why |
|--------|----------------------|-----|
| Auth | Cognito User Pool | source of identity |
| Profile | Cognito `AdminDeleteUser` | self-service account deletion frees the email |
| Photo | S3 `PutObject`/`GetObject`/`DeleteObject`, `kismet-profiles` (write), `kismet-discovery` (write) | presigned URLs; avatarUrl mirroring |

Cross-domain writes are deliberately one-way and guarded with `ConditionExpression: attribute_exists(PK)` so Photo-service can't create phantom rows in tables it doesn't own.

---

## 7. Known Gotchas

1. **Banned-user re-registration loophole** (#121, resolved by #124). `handle_delete` previously called `admin_delete_user` unconditionally, so a banned user could wipe their Cognito record and re-signup. Now: banned → `admin_disable_user` + tombstone row (email frozen); active → `admin_delete_user` + delete row (email freed).
2. **No ban notification** (#120). Users currently learn they've been banned only when their next login fails or their profile 404s. `profile.banned` has no D5 consumer yet; adding one is tracked.
3. **API Gateway stage doesn't auto-redeploy on imported-API route changes** (#118, resolved by #131). When `POST /photos/{photoId}/confirm` was added in #112, `cdk deploy KismetDomain1` created the Resource and Method but the `dev` stage kept serving the old route set. The new `synth_stage_redeploy` helper ensures every route change emits a fresh Deployment; see the 2026-04-16 postmortem.
4. **Rekognition rejects WebP/HEIC.** `ALLOWED_CONTENT_TYPES` at upload includes `image/webp` because the frontend supports it in the picker, but D4 moderation can only scan JPEG/PNG. The frontend now normalizes WebP/HEIC to JPEG client-side via `<canvas>` in [`frontend/src/lib/imageUtils.ts`](../../frontend/src/lib/imageUtils.ts) before calling `/photos/upload`. If that normalizer regresses, uploads still succeed but moderation silently errors.
5. **`kismet-users` is a write-mostly denormalization.** Nothing except Auth signup writes to it, and no D1 route reads it. Kept around so we can detach from Cognito later, but dead weight today.
6. **Photo service does best-effort S3 cleanup.** `handle_user_deleted` logs a warning and continues if `s3.delete_object` fails — the DynamoDB row is always removed. Orphaned S3 objects accumulate silently on repeated failures; no reconciler yet.
7. **Legacy `email-verification-service/` directory.** Self-rolled SES verification flow from an earlier design; superseded by Cognito's built-in `auto_verify`. The code is in-tree but has no CDK block, table, or SES identity. Safe to delete when someone has the cycles.

---

## 8. Open Follow-ups

- **#120** — Ban notification email (wire D5 to `profile.banned`; user learns why account is restricted)
- **Retire legacy `email-verification-service/`** — delete the directory and the `domain-1-email-verification-service.md` contract; Cognito auto-verify supersedes it
- **Orphaned S3 reconciler** — periodic job to diff bucket keys against `kismet-photos` rows
- **`kismet-users`** — decide whether to keep as write-mostly denormalization or retire

---

## 9. References

- API contracts: [`docs/api-contracts/domain-1-auth-service.md`](../api-contracts/domain-1-auth-service.md), [`domain-1-profile-service.md`](../api-contracts/domain-1-profile-service.md), [`domain-1-photo-service.md`](../api-contracts/domain-1-photo-service.md)
- Event shapes: [`event-schema.json`](./event-schema.json)
- Shared infra (Cognito user pool, REST API, S3 bucket, CloudFront): [`shared_stack.py`](../../infra/stacks/shared_stack.py)
- Reusable Lambda + DDB + route + IAM construct: [`kismet_constructs/kismet_service.py`](../../infra/kismet_constructs/kismet_service.py)
- Companion doc: [`Domain2_Design.md`](./Domain2_Design.md) — downstream consumers of every D1 event
