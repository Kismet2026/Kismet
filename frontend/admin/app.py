import streamlit as st
import pandas as pd

# TODO: Replace mock data with real API calls to admin-dashboard-service and health-monitor-service
# Example: response = requests.get(f"{API_BASE_URL}/admin/stats", headers={"Authorization": f"Bearer {token}"})
API_BASE_URL = "https://<your-api-gateway-url>/prod"

st.set_page_config(page_title="Kismet Admin", layout="wide")
st.title("Kismet Admin Dashboard")

tab1, tab2, tab3 = st.tabs(["Stats", "Reports", "Health Monitor"])

# ─── Tab 1: Stats ────────────────────────────────────────────────────────────
with tab1:
    st.header("App Overview")

    # TODO: Replace with GET /admin/stats
    stats = {
        "Total Users": 1024,
        "New Users Today": 38,
        "Total Matches": 412,
        "Matches Today": 21,
        "Messages Today": 890,
        "Swipes Today": 3200,
    }

    col1, col2, col3 = st.columns(3)
    items = list(stats.items())
    for i, col in enumerate([col1, col2, col3]):
        with col:
            k, v = items[i * 2]
            st.metric(k, v)
            k2, v2 = items[i * 2 + 1]
            st.metric(k2, v2)

# ─── Tab 2: Reports ───────────────────────────────────────────────────────────
with tab2:
    st.header("User Reports")

    status_filter = st.selectbox("Filter by status", ["pending", "resolved", "dismissed"])

    # TODO: Replace with GET /admin/reports?status={status_filter}
    mock_reports = [
        {"reportId": "rpt_001", "reporterId": "user_111", "reportedUserId": "user_222",
         "reason": "Harassment", "status": "pending", "createdAt": "2026-03-31"},
        {"reportId": "rpt_002", "reporterId": "user_333", "reportedUserId": "user_444",
         "reason": "Inappropriate photo", "status": "pending", "createdAt": "2026-03-30"},
    ]
    reports = [r for r in mock_reports if r["status"] == status_filter]

    if not reports:
        st.info("No reports found.")
    else:
        for r in reports:
            with st.expander(f"{r['reportId']} — {r['reason']} ({r['createdAt']})"):
                st.write(f"**Reporter:** {r['reporterId']}")
                st.write(f"**Reported user:** {r['reportedUserId']}")
                st.write(f"**Reason:** {r['reason']}")
                st.write(f"**Status:** {r['status']}")

                if r["status"] == "pending":
                    col_a, col_b = st.columns(2)
                    with col_a:
                        if st.button("Ban user", key=f"ban_{r['reportId']}"):
                            # TODO: Call PUT /admin/reports/{reportId}/resolve with action="ban"
                            st.success("User banned (mock)")
                    with col_b:
                        if st.button("Dismiss", key=f"dismiss_{r['reportId']}"):
                            # TODO: Call PUT /admin/reports/{reportId}/resolve with action="dismiss"
                            st.success("Report dismissed (mock)")

# ─── Tab 3: Health Monitor ────────────────────────────────────────────────────
with tab3:
    st.header("Service Health")

    if st.button("Refresh"):
        st.rerun()

    # TODO: Replace with GET /admin/health
    mock_health = [
        {"service": "auth-service",        "status": "OK",    "errorRate": 0.0,  "avgDurationMs": 45},
        {"service": "profile-service",     "status": "OK",    "errorRate": 0.1,  "avgDurationMs": 120},
        {"service": "bazi-service",        "status": "ALARM", "errorRate": 12.5, "avgDurationMs": 3200},
        {"service": "chat-gateway",        "status": "ALARM", "errorRate": 6.1,  "avgDurationMs": 800},
        {"service": "match-service",       "status": "OK",    "errorRate": 0.0,  "avgDurationMs": 200},
        {"service": "discovery-service",   "status": "OK",    "errorRate": 0.3,  "avgDurationMs": 310},
        {"service": "message-service",     "status": "OK",    "errorRate": 0.0,  "avgDurationMs": 95},
        {"service": "health-monitor",      "status": "OK",    "errorRate": 0.0,  "avgDurationMs": 60},
    ]

    df = pd.DataFrame(mock_health)

    def status_icon(s):
        return "🟢 OK" if s == "OK" else "🔴 ALARM"

    df["Status"] = df["status"].apply(status_icon)
    df["Error Rate"] = df["errorRate"].apply(lambda x: f"{x}%")
    df["Avg Duration"] = df["avgDurationMs"].apply(lambda x: f"{x} ms")

    st.dataframe(
        df[["service", "Status", "Error Rate", "Avg Duration"]].rename(columns={"service": "Service"}),
        use_container_width=True,
        hide_index=True,
    )

    alarm_count = sum(1 for r in mock_health if r["status"] == "ALARM")
    if alarm_count > 0:
        st.error(f"{alarm_count} service(s) in ALARM state")
    else:
        st.success("All services healthy")
