import requests
import streamlit as st
import pandas as pd
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

def to_pt(utc_str):
    if not utc_str:
        return ""
    try:
        dt = datetime.fromisoformat(utc_str)
        return dt.astimezone(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d %I:%M %p PT")
    except Exception:
        return utc_str

API_BASE_URL = "https://ihdsi4eg31.execute-api.us-east-1.amazonaws.com/dev"

st.set_page_config(page_title="Kismet Admin", layout="wide")
st.title("Kismet Admin Dashboard")


def get_token():
    return st.session_state.get("id_token")


def api_get(path, params=None):
    headers = {}
    if get_token():
        headers["Authorization"] = get_token()
    try:
        r = requests.get(f"{API_BASE_URL}{path}", params=params, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)


def api_put(path, body=None):
    headers = {}
    if get_token():
        headers["Authorization"] = get_token()
    try:
        r = requests.put(f"{API_BASE_URL}{path}", json=body, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)


def api_post(path):
    headers = {}
    if get_token():
        headers["Authorization"] = get_token()
    try:
        r = requests.post(f"{API_BASE_URL}{path}", headers=headers, timeout=10)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)


# ─── Login ────────────────────────────────────────────────────────────────────
if not get_token():
    st.subheader("Login")
    with st.form("login_form"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")

    if submitted:
        try:
            r = requests.post(
                f"{API_BASE_URL}/auth/login",
                json={"email": email, "password": password},
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()
            st.session_state["id_token"] = data["idToken"]
            st.success("Logged in!")
            st.rerun()
        except Exception as e:
            st.error(f"Login failed: {e}")
    st.stop()


st.info("📌 Note: Stats and activity data reflect real user actions only. Test accounts (test1–test19@kismet.com) are excluded from platform metrics.", icon=None)

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["Stats", "Flagged Content", "Users", "Health Monitor", "Analytics Pipeline"]
)

# ─── Tab 1: Stats ─────────────────────────────────────────────────────────────
with tab1:
    st.header("App Overview")
    if st.button("Refresh", key="refresh_stats"):
        st.rerun()

    data, err = api_get("/admin/stats")
    if err:
        st.error(f"Failed to load stats: {err}")
    else:
        cols = st.columns(5)
        cols[0].metric("Total Users", data["totalUsers"])
        cols[1].metric("Active Users", data["activeUsers"])
        cols[2].metric("Matches Today", data["matchesToday"])
        cols[3].metric("Messages Today", data["messagesToday"])
        cols[4].metric("Flagged Content", data["flaggedContentCount"])
        st.caption(f"Generated at: {to_pt(data.get('generatedAt', ''))}")

# ─── Tab 2: Flagged Content ──────────────────────────────��─────────────────────
with tab2:
    st.header("Flagged Content")
    type_filter = st.selectbox("Filter by type", ["all", "text", "image"])

    params = {} if type_filter == "all" else {"type": type_filter}
    data, err = api_get("/admin/flagged-content", params=params)

    if err:
        st.error(f"Failed to load flagged content: {err}")
    elif not data["items"]:
        st.info("No flagged content.")
    else:
        for item in data["items"]:
            with st.expander(
                f"{item['contentId']} — {item['reason']} ({item.get('flaggedAt', '')})"
            ):
                st.write(f"**Type:** {item['type']}")
                st.write(f"**User:** {item['userId']}")
                st.write(f"**Reason:** {item['reason']}")
                st.write(f"**Confidence:** {item['confidence']}")
                if item["type"] == "image":
                    st.write(f"**Image URL:** {item.get('imageUrl')}")
                else:
                    st.write(f"**Content:** {item.get('content')}")

                if item["status"] == "pending":
                    col_a, col_b, col_c = st.columns(3)
                    with col_a:
                        if st.button("Approve", key=f"approve_{item['contentId']}"):
                            _, err = api_put(
                                f"/admin/flagged-content/{item['contentId']}/resolve",
                                {"action": "approve"},
                            )
                            st.success("Approved") if not err else st.error(err)
                    with col_b:
                        if st.button("Remove", key=f"remove_{item['contentId']}"):
                            _, err = api_put(
                                f"/admin/flagged-content/{item['contentId']}/resolve",
                                {"action": "remove"},
                            )
                            st.success("Removed") if not err else st.error(err)
                    with col_c:
                        if st.button("Ban User", key=f"ban_{item['contentId']}"):
                            _, err = api_put(
                                f"/admin/flagged-content/{item['contentId']}/resolve",
                                {"action": "ban_user"},
                            )
                            st.success("User banned") if not err else st.error(err)

# ─── Tab 3: Users ────────────────────────────────────────────────────────���────
with tab3:
    st.header("Users")
    search = st.text_input("Search by name", placeholder="e.g. John")

    params = {"search": search} if search else {}
    data, err = api_get("/admin/users", params=params)

    if err:
        st.error(f"Failed to load users: {err}")
    elif not data["items"]:
        st.info("No users found.")
    else:
        for user in data["items"]:
            status_icon = "🔴" if user["status"] == "banned" else "🟢"
            with st.expander(
                f"{status_icon} {user.get('displayName', user['userId'])} — {user['status']}"
            ):
                st.write(f"**User ID:** {user['userId']}")
                st.write(f"**Email:** {user.get('email') or '—'}")
                st.write(f"**Created:** {user.get('createdAt', '—')}")
                st.write(f"**Report Count:** {user.get('reportCount', 0)}")

                if user["status"] != "banned":
                    if st.button("Ban", key=f"ban_user_{user['userId']}"):
                        _, err = api_put(f"/admin/users/{user['userId']}/ban")
                        st.success("User banned") if not err else st.error(err)
                else:
                    if st.button("Unban", key=f"unban_user_{user['userId']}"):
                        _, err = api_put(f"/admin/users/{user['userId']}/unban")
                        st.success("User unbanned") if not err else st.error(err)

# ─── Tab 4: Health Monitor ──────────────────────────────────��──────────────────
with tab4:
    st.header("Service Health")
    col_refresh, col_check = st.columns([1, 1])

    with col_refresh:
        if st.button("Refresh"):
            st.rerun()
    with col_check:
        if st.button("Run Health Check"):
            result, err = api_post("/health/check")
            if err:
                st.error(f"Health check failed: {err}")
            else:
                st.success(f"Check complete — overall: {result['status']}")

    data, err = api_get("/health")
    if err:
        st.error(f"Failed to load health: {err}")
    else:
        overall = data["status"]
        if overall == "healthy":
            st.success("All services healthy")
        elif overall == "degraded":
            st.warning("Some services degraded")
        else:
            st.error("One or more services unhealthy")

        def _status_label(s):
            return {
                "healthy": "🟢 Healthy",
                "degraded": "🟡 Degraded",
                "unhealthy": "🔴 Unhealthy",
            }.get(s, s)

        rows = [
            {
                "Service": name,
                "Status": _status_label(svc["status"]),
                "Latency (ms)": svc["latency"],
            }
            for name, svc in data["services"].items()
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption(f"Checked at: {to_pt(data.get('checkedAt', ''))}")

    # Active alarms
    alarms, err = api_get("/health/alarms")
    if not err and alarms["activeCount"] > 0:
        st.subheader(f"Active Alarms ({alarms['activeCount']})")
        for alarm in alarms["alarms"]:
            st.error(f"**{alarm['alarmName']}** — {alarm['reason']}")

# ─── Tab 5: Analytics Pipeline ────────────────────────────────────────────────
with tab5:
    st.header("Analytics Pipeline")
    st.caption("Data flow: User Actions → EventBridge → Lambda → Kinesis → Firehose (60s) → S3 → Athena")

    if st.button("Refresh", key="refresh_analytics"):
        st.rerun()

    # Pipeline status
    st.subheader("Pipeline Status")
    cols = st.columns(4)
    cols[0].success("✅ Kinesis Stream")
    cols[1].success("✅ Firehose (60s buffer)")
    cols[2].success("✅ S3 Bucket")
    cols[3].success("✅ Athena")

    st.divider()

    # Athena dashboard stats
    st.subheader("Platform Analytics (via Athena)")
    data, err = api_get("/analytics/dashboard")
    if err:
        st.error(f"Failed to load analytics: {err}")
    else:
        cols = st.columns(4)
        cols[0].metric("Total Events", data.get("totalEvents", 0))
        cols[1].metric("Swipes", data.get("swipeCount", 0))
        cols[2].metric("Matches", data.get("matchCount", 0))
        cols[3].metric("Messages", data.get("messageCount", 0))
        st.caption(f"Query time: {data.get('queryTimeMs', '—')}ms | Source: AWS Athena → S3")

        # Event breakdown chart
        event_data = {
            "Event Type": ["Swipes", "Matches", "Messages", "Other"],
            "Count": [
                data.get("swipeCount", 0),
                data.get("matchCount", 0),
                data.get("messageCount", 0),
                max(0, data.get("totalEvents", 0) - data.get("swipeCount", 0) - data.get("matchCount", 0) - data.get("messageCount", 0)),
            ]
        }
        df = pd.DataFrame(event_data)
        if df["Count"].sum() > 0:
            st.bar_chart(df.set_index("Event Type"))

    st.divider()

    # Recent activity log from DynamoDB (real-time)
    st.subheader("Recent Activity Log (real-time, via DynamoDB)")
    log_data, err = api_get("/analytics/log/recent")
    if err:
        st.warning(f"Could not load activity log (requires auth token): {err}")
    elif log_data:
        rows = []
        for item in log_data.get("items", []):
            rows.append({
                "Time": to_pt(item.get("timestamp", "")),
                "Event": item.get("eventType", ""),
                "User": item.get("userId", "")[:8] + "...",
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No recent activity. Try swiping or sending a message first.")
