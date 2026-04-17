# Kismet Admin Dashboard

A Streamlit-based admin interface for viewing live platform stats, moderating flagged content, managing users, monitoring service health, and checking analytics pipeline output.

**Owner:** Lingyun Xiao

---

## Local Setup & Run

### 1. Navigate to this directory

```bash
cd frontend/admin
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the app

```bash
streamlit run app.py --server.headless true
```

### 5. Open in browser

```
http://localhost:8501
```

---

## Features

### Stats Tab
Reads `GET /admin/stats` and shows live admin metrics:

- total users
- active users
- matches today
- pending flagged content count

### Flagged Content Tab
Reads `GET /admin/flagged-content` and lets admins resolve items through `PUT /admin/flagged-content/{contentId}/resolve`.

### Users Tab
Reads `GET /admin/users` with optional name search and supports banning/unbanning through:

- `PUT /admin/users/{userId}/ban`
- `PUT /admin/users/{userId}/unban`

### Health Monitor Tab
Reads `GET /health` and `GET /health/alarms`.

Health status meanings:

- `healthy`: recent traffic exists and current metrics are within threshold
- `degraded`: recent traffic exists but latency is above threshold
- `unhealthy`: recent traffic exists and error rate is above threshold

### Analytics Pipeline Tab
Reads `GET /analytics/dashboard` for Athena-backed analytics and `GET /analytics/log/recent` for the near-real-time DynamoDB activity log.

If the Athena pipeline is unavailable, the backend now returns `503` with `ANALYTICS_UNAVAILABLE` instead of silently returning zeros.

---

## Connecting to Backend

Set the backend base URL before starting Streamlit:

```bash
export API_BASE_URL="https://<your-api-gateway-url>/dev"
```

The app expects a working login endpoint at `/auth/login` and uses the returned `idToken` as a bearer token for protected admin APIs.
