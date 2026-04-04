import streamlit as st
import pandas as pd

# TODO: Replace mock data with real API calls
# Example: response = requests.get(f"{API_BASE_URL}/admin/stats", headers={"Authorization": f"Bearer {token}"})
API_BASE_URL = "https://<your-api-gateway-url>/prod"

st.set_page_config(page_title="Kismet Admin", layout="wide")
st.title("Kismet Admin Dashboard")

tab1, tab2, tab3 = st.tabs(["Stats", "Flagged Content", "Health Monitor"])

# ─── Tab 1: Stats ─────────────────────────────────────────────────────────────
with tab1:
    st.header("App Overview")

    # TODO: Replace with GET /admin/stats
    # Response shape: { totalUsers, activeUsers, matchesToday, messagesToday, flaggedContentCount, generatedAt }
    stats = {
        "Total Users": 8500,
        "Active Users": 1250,
        "Matches Today": 234,
        "Messages Today": 892,
        "Flagged Content": 15,
    }

    cols = st.columns(len(stats))
    for col, (k, v) in zip(cols, stats.items()):
        col.metric(k, v)

# ─── Tab 2: Flagged Content ────────────────────────────────────────────────────
with tab2:
    st.header("Flagged Content")

    type_filter = st.selectbox("Filter by type", ["all", "text", "image"])

    # TODO: Replace with GET /admin/flagged-content?type={type_filter}
    # Response shape: { items: [{ contentId, type, content/imageUrl, userId, reason, confidence, flaggedAt, status }], nextCursor, count }
    mock_flagged = [
        {
            "contentId": "flag-001", "type": "text",
            "content": "Inappropriate message...",
            "userId": "user-456", "reason": "hate_speech",
            "confidence": 0.92, "flaggedAt": "2026-03-31", "status": "pending",
        },
        {
            "contentId": "flag-002", "type": "image",
            "imageUrl": "https://cdn.kismet.com/photos/flagged/img-002.jpg",
            "userId": "user-789", "reason": "explicit_content",
            "confidence": 0.88, "flaggedAt": "2026-03-30", "status": "pending",
        },
    ]
    items = [i for i in mock_flagged if type_filter == "all" or i["type"] == type_filter]

    if not items:
        st.info("No flagged content.")
    else:
        for item in items:
            with st.expander(f"{item['contentId']} — {item['reason']} ({item['flaggedAt']})"):
                st.write(f"**Type:** {item['type']}")
                st.write(f"**User:** {item['userId']}")
                st.write(f"**Reason:** {item['reason']}")
                st.write(f"**Confidence:** {item['confidence']}")

                if item["status"] == "pending":
                    col_a, col_b, col_c = st.columns(3)
                    with col_a:
                        if st.button("Approve", key=f"approve_{item['contentId']}"):
                            # TODO: PUT /admin/flagged-content/{contentId}/resolve {"action": "approve"}
                            st.success("Approved (mock)")
                    with col_b:
                        if st.button("Remove", key=f"remove_{item['contentId']}"):
                            # TODO: PUT /admin/flagged-content/{contentId}/resolve {"action": "remove"}
                            st.success("Removed (mock)")
                    with col_c:
                        if st.button("Ban User", key=f"ban_{item['contentId']}"):
                            # TODO: PUT /admin/flagged-content/{contentId}/resolve {"action": "ban_user"}
                            st.success("User banned (mock)")

# ─── Tab 3: Health Monitor ─────────────────────────────────────────────────────
with tab3:
    st.header("Service Health")

    if st.button("Refresh"):
        st.rerun()

    # TODO: Replace with GET /health  (base path: /health, not /admin/health)
    # Response shape: { status, services: { name: { status, latency } }, checkedAt }
    mock_health = {
        "status": "degraded",
        "services": {
            "auth-service":    {"status": "healthy",  "latency": 45},
            "profile-service": {"status": "healthy",  "latency": 120},
            "bazi-service":    {"status": "degraded", "latency": 3200},
            "match-service":   {"status": "healthy",  "latency": 200},
            "message-service": {"status": "healthy",  "latency": 95},
            "health-monitor":  {"status": "healthy",  "latency": 60},
        },
        "checkedAt": "2026-04-03T12:00:00Z",
    }

    overall = mock_health["status"]
    if overall == "healthy":
        st.success("All services healthy")
    elif overall == "degraded":
        st.warning("Some services degraded")
    else:
        st.error("One or more services unhealthy")

    def _status_label(s):
        return {"healthy": "🟢 Healthy", "degraded": "🟡 Degraded", "unhealthy": "🔴 Unhealthy"}.get(s, s)

    rows = [
        {"Service": name, "Status": _status_label(svc["status"]), "Latency (ms)": svc["latency"]}
        for name, svc in mock_health["services"].items()
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
