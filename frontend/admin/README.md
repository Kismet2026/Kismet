# Kismet Admin Dashboard

A Streamlit-based admin interface for viewing app stats, managing user reports, and monitoring service health.

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
Displays app-wide metrics: total users, new users today, total matches, matches today, messages today, and swipes today.

> Currently using mock data. Will connect to `GET /admin/stats` once backend is deployed.

### Reports Tab
Lists user reports with filters by status (`pending`, `resolved`, `dismissed`). Admins can ban a user or dismiss a report directly from the UI.

> Currently using mock data. Will connect to `GET /admin/reports` and `PUT /admin/reports/{reportId}/resolve`.

### Health Monitor Tab
Shows real-time health status of all 25 microservices, including error rate and average latency. Services in ALARM state are highlighted in red.

> Currently using mock data. Will connect to `GET /admin/health` once health-monitor-service is deployed.

---

## Connecting to Real Backend (Week 2)

Update `API_BASE_URL` at the top of `app.py`:

```python
API_BASE_URL = "https://<your-api-gateway-url>/prod"
```

Then replace each `# TODO` block in `app.py` with the corresponding `requests.get()` or `requests.put()` call.
