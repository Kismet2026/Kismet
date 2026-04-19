import json
import os
import time
from datetime import datetime, timezone

import boto3

athena = boto3.client("athena")

ANALYTICS_BUCKET = os.environ.get("ANALYTICS_BUCKET", "kismet-analytics-dev")
ATHENA_DATABASE = os.environ.get("ATHENA_DATABASE", "kismet_analytics")
S3_DATA_PREFIX = os.environ.get("S3_DATA_PREFIX", "events")
ATHENA_OUTPUT = f"s3://{ANALYTICS_BUCKET}/athena-results/"

_catalog_ready = False


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def handler(event, context):
    method = event.get("httpMethod", "")
    resource = event.get("resource", "")

    routes = {
        ("POST", "/analytics/query"): post_query,
        ("GET", "/analytics/query/{queryId}"): get_query_results,
        ("GET", "/analytics/dashboard"): get_dashboard,
    }
    fn = routes.get((method, resource))
    if fn:
        return fn(event, context)
    return _response(404, {"error": "Not found"})


# ── POST /analytics/query ────────────────────────────────────────────────────


def post_query(event, context):
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(
            400, {"error": "VALIDATION_ERROR", "message": "Invalid JSON body"}
        )

    sql = body.get("sql", "").strip()
    if not sql:
        return _response(
            400, {"error": "VALIDATION_ERROR", "message": "sql is required"}
        )

    _ensure_catalog()

    try:
        execution_id = _start_query(sql)
        return _response(
            200,
            {
                "queryExecutionId": execution_id,
                "status": "QUEUED",
                "submittedAt": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as e:
        return _response(500, {"error": "ATHENA_ERROR", "message": str(e)})


# ── GET /analytics/query/{queryId} ───────────────────────────────────────────


def get_query_results(event, context):
    query_id = event["pathParameters"]["queryId"]

    try:
        execution = athena.get_query_execution(QueryExecutionId=query_id)
    except athena.exceptions.InvalidRequestException:
        return _response(
            404, {"error": "NOT_FOUND", "message": "Query execution not found"}
        )

    status_info = execution["QueryExecution"]["Status"]
    state = status_info["State"]
    submitted_at = status_info.get("SubmissionDateTime")
    completed_at = status_info.get("CompletionDateTime")

    result = {
        "queryExecutionId": query_id,
        "status": state,
        "submittedAt": submitted_at.isoformat() if submitted_at else None,
    }

    if state == "SUCCEEDED":
        result["completedAt"] = (
            completed_at.isoformat() if completed_at else None
        )
        result["results"] = _fetch_results(query_id)
    elif state == "FAILED":
        result["error"] = status_info.get("StateChangeReason", "Query failed")

    return _response(200, result)


# ── GET /analytics/dashboard ─────────────────────────────────────────────────


def get_dashboard(event, context):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sql = (
        "SELECT "
        "  COUNT(DISTINCT CASE "
        "    WHEN eventType IN ('swipe.created','message.sent','match.created') "
        f"    AND SUBSTR(\"timestamp\", 1, 10) = '{today}' "
        "    THEN userId END) AS dau, "
        "  COUNT(DISTINCT CASE "
        "    WHEN eventType = 'user.created' "
        "    THEN userId END) AS totalUsers, "
        "  COUNT(DISTINCT CASE "
        "    WHEN eventType = 'match.created' "
        f"    AND SUBSTR(\"timestamp\", 1, 10) = '{today}' "
        "    THEN json_extract_scalar(eventData, '$.matchId') END) AS matchesToday, "
        "  COUNT(CASE "
        "    WHEN eventType = 'message.sent' "
        f"    AND SUBSTR(\"timestamp\", 1, 10) = '{today}' "
        "    THEN 1 END) AS messagesToday "
        f"FROM {ATHENA_DATABASE}.activity_events"
    )

    try:
        _ensure_catalog()
        rows = _run_query_sync(sql)
        if not rows:
            return _response(
                503,
                {
                    "error": "ANALYTICS_UNAVAILABLE",
                    "message": "Analytics query returned no usable results",
                },
            )

        row = rows[0]
        return _response(
            200,
            {
                "dau": int(row.get("dau") or 0),
                "totalUsers": int(row.get("totalUsers") or 0),
                "matchesToday": int(row.get("matchesToday") or 0),
                "messagesToday": int(row.get("messagesToday") or 0),
                "generatedAt": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as e:
        print(f"Dashboard Athena query failed: {e}")
        return _response(
            503,
            {
                "error": "ANALYTICS_UNAVAILABLE",
                "message": str(e),
            },
        )


# ── Athena helpers ────────────────────────────────────────────────────────────


def _ensure_catalog():
    """Create the Athena database and external table if they don't exist yet."""
    global _catalog_ready
    if _catalog_ready:
        return

    try:
        _run_query_sync(f"CREATE DATABASE IF NOT EXISTS {ATHENA_DATABASE}")

        create_table = (
            f"CREATE EXTERNAL TABLE IF NOT EXISTS {ATHENA_DATABASE}.activity_events ("
            "  logId STRING,"
            "  eventType STRING,"
            "  userId STRING,"
            "  eventData STRING,"
            "  source STRING,"
            "  `timestamp` STRING"
            ")"
            " ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'"
            " WITH SERDEPROPERTIES ('ignore.malformed.json' = 'true')"
            f" LOCATION 's3://{ANALYTICS_BUCKET}/{S3_DATA_PREFIX}/'"
        )
        _run_query_sync(create_table)
        _catalog_ready = True
    except Exception as e:
        print(f"Catalog setup failed: {e}")


def _start_query(sql):
    response = athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": ATHENA_DATABASE},
        ResultConfiguration={"OutputLocation": ATHENA_OUTPUT},
    )
    return response["QueryExecutionId"]


def _run_query_sync(sql, timeout_seconds=25):
    """Submit an Athena query and poll until it completes or times out."""
    execution_id = _start_query(sql)
    state = "QUEUED"

    for _ in range(timeout_seconds):
        time.sleep(1)
        execution = athena.get_query_execution(QueryExecutionId=execution_id)
        state = execution["QueryExecution"]["Status"]["State"]
        if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break

    if state != "SUCCEEDED":
        reason = (
            execution["QueryExecution"]["Status"]
            .get("StateChangeReason", "unknown")
        )
        raise RuntimeError(
            f"Athena query did not succeed: state={state} reason={reason}"
        )

    return _fetch_results(execution_id)


def _fetch_results(execution_id):
    """Parse all result rows from a completed Athena query into dicts."""
    response = athena.get_query_results(
        QueryExecutionId=execution_id, MaxResults=1000
    )
    rows = response["ResultSet"]["Rows"]
    if len(rows) < 2:
        return []

    headers = [col.get("VarCharValue", "") for col in rows[0]["Data"]]
    results = []
    for row in rows[1:]:
        values = [col.get("VarCharValue", "") for col in row["Data"]]
        results.append(dict(zip(headers, values)))

    # Handle pagination for large result sets
    while "NextToken" in response:
        response = athena.get_query_results(
            QueryExecutionId=execution_id,
            NextToken=response["NextToken"],
            MaxResults=1000,
        )
        for row in response["ResultSet"]["Rows"]:
            values = [col.get("VarCharValue", "") for col in row["Data"]]
            results.append(dict(zip(headers, values)))

    return results
