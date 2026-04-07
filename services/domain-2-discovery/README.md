# Domain 2 — Discovery & Matching

Owner: Qinyuan

Five microservices handling user discovery, swiping, matching, recommendations, and BaZi compatibility.

## Architecture Overview

```
profile.completed ──→ Discovery Service (indexes candidates)
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

Indexes user profiles and serves the discovery feed.

| Method | Path         | Auth | Description        |
|--------|--------------|------|--------------------|
| GET    | `/discovery` | Yes  | Get candidates     |

- **Query params:** `limit` (max 50), `age_min`, `age_max`, `gender`, `cursor`
- Consumes `profile.completed` events to index candidate profiles

**Table:** `kismet-discovery` — PK: `PROFILE#{userId}`, SK: `META`

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

**Score breakdown:** `locationProximity`, `sharedInterests`, `baziCompatibility`, `activityRecency`

---

### 5. BaZi Service (八字服务)

Chinese astrology compatibility calculation. Stateless — no table, no events.

| Method | Path                     | Auth | Description             |
|--------|--------------------------|------|-------------------------|
| POST   | `/bazi/compatibility`    | Yes  | Compute compatibility   |
| GET    | `/bazi/profile/{userId}` | Yes  | Get BaZi chart          |

- **POST body:** `{"userABirthDate": "1995-06-15", "userABirthTime": "14:30", "userBBirthDate": "1997-03-22", "userBBirthTime": "08:00"}`
- Returns score (0–100), Five Elements breakdown, Chinese analysis
- Scoring: generating pairs (+8), same element (+5), controlling pairs (-5), day pillar bonus (+10)
- Analysis tiers: 天作之合 (85+) / 良缘佳配 (70+) / 中等缘分 (55+) / 需多磨合 (<55)

## Events Summary

| Event              | Producer         | Consumers                        |
|--------------------|------------------|----------------------------------|
| `swipe.created`    | Swipe Service    | Match Service, Recommendation    |
| `match.created`    | Match Service    | Chat, Notification, Analytics    |
| `profile.completed`| Profile Service (D1) | Discovery, Recommendation    |

## Cross-Service Dependencies

| Service         | Reads From              | Why                              |
|-----------------|-------------------------|----------------------------------|
| Match           | `kismet-swipes` table   | Check reverse like for mutual match |
| Recommendation  | `kismet-discovery` table| Fetch candidate profiles for scoring |

## Environment Variables

| Variable               | Used By          | Default                  |
|------------------------|------------------|--------------------------|
| `TABLE_NAME`           | All (except BaZi)| Service-specific         |
| `EVENT_BUS_NAME`       | All (except BaZi)| `kismet-events`          |
| `SWIPE_TABLE_NAME`     | Match            | `kismet-swipes`          |
| `DISCOVERY_TABLE_NAME` | Recommendation   | `kismet-discovery`       |

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
