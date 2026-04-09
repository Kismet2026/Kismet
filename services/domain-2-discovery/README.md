# Domain 2 — Discovery & Matching

Owner: Qinyuan

Five microservices handling user discovery, swiping, matching, recommendations, and BaZi compatibility.

## Architecture Overview

```
profile.completed ──→ Discovery Service (index candidate + pre-warm BaZi cache)
                  ──→ Recommendation Service (notes new user)

User swipes ──→ Swipe Service ──→ swipe.created event
                                       │
                        ┌──────────────┼──────────────┐
                        ▼                              ▼
                 Match Service                 Recommendation Service
              (mutual like? → match)         (remove swiped candidate)
                        │
                        ▼
                 match.created event → Chat, Notification, Analytics

External BaZi API ←── Discovery Service (cached by birthDate in DynamoDB)
```

## Services

### 1. Swipe Service

Records like/pass actions with atomic duplicate prevention.

| Method | Path             | Auth | Description            |
|--------|------------------|------|------------------------|
| POST   | `/swipe`         | Yes  | Record a swipe         |
| GET    | `/swipe/history` | Yes  | Paginated swipe history |

- **POST /swipe** body: `{"targetUserId": "...", "action": "like|pass"}`
- Duplicate swipe returns `409` (enforced via `ConditionExpression` — atomic, no race condition)
- Only `like` actions publish `swipe.created` to EventBridge

**Table:** `kismet-swipes` — PK: `userId`, SK: `targetUserId`

---

### 2. Match Service

Detects mutual likes via events and creates matches atomically.

| Method | Path                  | Auth | Description      |
|--------|-----------------------|------|------------------|
| GET    | `/matches`            | Yes  | List matches     |
| GET    | `/matches/{matchId}`  | Yes  | Match detail     |
| DELETE | `/matches/{matchId}`  | Yes  | Unmatch          |

**Event-driven matching flow:**
1. Receives `swipe.created` → checks if reverse like exists in swipe table
2. Mutual like detected → `transact_write_items` atomically writes 4 records
3. Deterministic pair key (`PAIR#{sorted_ids}`) with `ConditionExpression` prevents duplicate matches
4. Publishes `match.created` event

**Table:** `kismet-matches` (single-table design)

| PK Pattern             | SK Pattern                    | Purpose                  |
|------------------------|-------------------------------|--------------------------|
| `PAIR#{userA}#{userB}` | `META`                        | Dedup unique constraint  |
| `MATCH#{matchId}`      | `META`                        | Match detail lookup      |
| `USER#{userId}`        | `MATCH#{timestamp}#{matchId}` | User's match list        |

---

### 3. Discovery Service

Indexes user profiles, serves the discovery feed with BaZi compatibility scores.

| Method | Path         | Auth | Description        |
|--------|--------------|------|--------------------|
| GET    | `/discovery` | Yes  | Get candidates     |

- **Query params:** `limit` (max 50), `age_min`, `age_max`, `gender`, `cursor`
- Each candidate includes `baziScore` (from external BaZi API, cached per birthDate)
- Filters out already-swiped users (reads `kismet-swipes` table)
- Computes `age` from `birthDate` (not passed directly in event)
- Consumes `profile.completed` events to index candidate profiles + pre-warm BaZi cache

**Table:** `kismet-discovery` (single-table design)

| PK Pattern           | SK       | Purpose                         |
|----------------------|----------|---------------------------------|
| `PROFILE#{userId}`   | `META`   | Candidate profile               |
| `BAZI#{birthDate}`   | `SCORES` | Cached BaZi scores (permanent)  |

---

### 4. Recommendation Service

Computes and caches personalized candidate recommendations.

| Method | Path                 | Auth | Description             |
|--------|----------------------|------|-------------------------|
| GET    | `/recommend`         | Yes  | Get recommendations     |
| POST   | `/recommend/refresh` | Yes  | Force recompute         |

- Returns cached recommendations sorted by score; computes on-the-fly if cache is empty
- Consumes `profile.completed` (notes new user) and `swipe.created` (removes swiped candidate from cache)
- Reads from discovery table for candidate profiles

**Table:** `kismet-recommendations` — PK: `USER#{userId}`, SK: `SCORE#{score}#{candidateId}`

**Score breakdown:** `baziCompatibility` (0-40, from BaZi cache), `profileCompleteness` (0-20, avatar/bio/city), `activityRecency` (10, placeholder)

---

### 5. BaZi Service (八字服务)

Proxies to external BaZi API for compatibility scoring. Stateless — no table, no events.

| Method | Path                  | Auth | Description                      |
|--------|-----------------------|------|----------------------------------|
| POST   | `/bazi/top-matches`   | Yes  | Get best matching birthdates     |

- **POST body:** `{"birthDate": "1995-11-21", "limit": 50}`
- Returns ranked list of best matching birthdates with scores (from external API)
- `POST /bazi/compatibility` (1v1) planned — pending external API support

## Events Summary

| Event              | Producer         | Consumers                        |
|--------------------|------------------|----------------------------------|
| `swipe.created`    | Swipe Service    | Match Service, Recommendation    |
| `match.created`    | Match Service    | Chat, Notification, Analytics    |
| `profile.completed`| Profile Service (D1) | Discovery, Recommendation    |

## Cross-Service Dependencies

| Service         | Reads From              | Why                                    |
|-----------------|-------------------------|----------------------------------------|
| Match           | `kismet-swipes` table   | Check reverse like for mutual match    |
| Discovery       | `kismet-swipes` table   | Filter out already-swiped candidates   |
| Discovery       | External BaZi API       | Fetch compatibility scores (cached)    |
| Recommendation  | `kismet-discovery` table| Fetch candidate profiles + BaZi cache  |
| Recommendation  | `kismet-swipes` table   | Exclude already-swiped candidates      |

## Environment Variables

| Variable               | Used By             | Default                  |
|------------------------|---------------------|--------------------------|
| `TABLE_NAME`           | All (except BaZi)   | Service-specific         |
| `EVENT_BUS_NAME`       | All (except BaZi)   | `kismet-events`          |
| `SWIPE_TABLE_NAME`     | Match, Discovery, Recommendation | `kismet-swipes` |
| `DISCOVERY_TABLE_NAME` | Recommendation      | `kismet-discovery`       |
| `BAZI_API_URL`         | Discovery, BaZi     | `https://match-date-nu.vercel.app/api/match` |
| `BAZI_API_KEY`         | Discovery, BaZi     | *(none — must be set)*   |

## Production TODOs

- **Discovery GSI**: Currently `GET /discovery` does a full DynamoDB `Scan` with client-side filtering. At demo scale (tens to hundreds of profiles) this is fine — a single scan completes in milliseconds and costs <1 RCU. For production scale (100K+ users), add a GSI on `gender` (PK) + `age` (SK, Number) to enable `Query` instead of `Scan`. The `KismetService` construct already supports GSI via the `gsi` array in table config. Note that `age` is computed once at indexing time and becomes stale after a birthday — a production system should index by `birthDate` and convert age ranges to date ranges at query time.
- **BaZi API key**: Move from CDK environment variable to SSM Parameter Store or Secrets Manager.
- **Logging**: Structured JSON logging for easier CloudWatch Insights queries.

## Running Tests

```bash
# All services
for svc in swipe-service match-service discovery-service recommendation-service bazi-service; do
  echo "=== $svc ===" && cd services/domain-2-discovery/$svc/tests && python3 -m pytest -v && cd -
done

# Single service
cd services/domain-2-discovery/swipe-service/tests && python3 -m pytest -v
```

Requires: `pip install pytest boto3`
