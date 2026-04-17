import json
import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import boto3

cloudwatch = boto3.client("cloudwatch")
sns = boto3.client("sns")
dynamodb = boto3.resource("dynamodb")

HEALTH_HISTORY_TABLE = os.environ.get("HEALTH_HISTORY_TABLE", "kismet-health-history")
HEALTH_ALERTS_TOPIC_ARN = os.environ.get("HEALTH_ALERTS_TOPIC_ARN", "")

# All monitored services. Lambda function name = kismet-{service_name}.
KNOWN_SERVICES = [
    "auth-service",
    "profile-service",
    "swipe-service",
    "match-service",
    "message-service",
    "chat-gateway",
]

# Status thresholds
DEGRADED_LATENCY_MS = 300    # avgDuration above this → degraded
UNHEALTHY_ERROR_RATE = 0.05  # errorRate above this → unhealthy


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=_json_default),
    }


def _json_default(obj):
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def handler(event, context):  # noqa: ARG001
    method = event.get("httpMethod", "")
    resource = event.get("resource", "")

    if method == "GET" and resource == "/health":
        return get_health()
    if method == "GET" and resource == "/health/alarms":
        return get_alarms()
    if method == "GET" and resource == "/health/{serviceName}":
        return get_service_health(event)
    if method == "POST" and resource == "/health/check":
        return post_health_check()
    return _response(404, {"error": "Not found"})


# GET /health  (public, no auth)
def get_health():
    try:
        checked_at = datetime.now(timezone.utc).isoformat()
        service_results = {}
        overall = "unknown"

        for service_name in KNOWN_SERVICES:
            metrics = _get_cloudwatch_metrics(service_name)
            status = _derive_status(metrics)
            service_results[service_name] = {
                "status": status,
                "latency": metrics["avgDuration"],
            }
            overall = _rollup_status(overall, status)

        return _response(200, {
            "status": overall,
            "services": service_results,
            "checkedAt": checked_at,
        })
    except Exception as e:  # noqa: BLE001
        return _response(500, {"error": "INTERNAL_ERROR", "message": str(e)})


# GET /health/{serviceName}  (admin)
def get_service_health(event):
    service_name = event["pathParameters"]["serviceName"]

    if service_name not in KNOWN_SERVICES:
        return _response(404, {"error": "NOT_FOUND", "message": f"Unknown service: {service_name}"})

    metrics = _get_cloudwatch_metrics(service_name)
    status = _derive_status(metrics)
    checked_at = datetime.now(timezone.utc).isoformat()

    return _response(200, {
        "serviceName": service_name,
        "status": status,
        "metrics": metrics,
        "period": "last_5_minutes",
        "checkedAt": checked_at,
    })


# GET /health/alarms  (admin)
def get_alarms():
    checked_at = datetime.now(timezone.utc).isoformat()
    response = cloudwatch.describe_alarms(StateValue="ALARM")

    alarms = []
    for alarm in response.get("MetricAlarms", []):
        alarm_name = alarm["AlarmName"]
        # Alarm naming convention: {serviceName}-error-rate
        service_name = (
            alarm_name[: -len("-error-rate")]
            if alarm_name.endswith("-error-rate")
            else alarm_name
        )
        state_changed_at = alarm.get("StateUpdatedTimestamp")
        alarms.append({
            "alarmName": alarm_name,
            "serviceName": service_name,
            "state": alarm["StateValue"],
            "reason": alarm.get("StateReason", ""),
            "stateChangedAt": state_changed_at.isoformat() if state_changed_at else None,
        })

    return _response(200, {
        "alarms": alarms,
        "activeCount": len(alarms),
        "checkedAt": checked_at,
    })


# POST /health/check  (admin)
def post_health_check():
    try:
        checked_at = datetime.now(timezone.utc).isoformat()
        service_results = {}
        overall = "unknown"

        for service_name in KNOWN_SERVICES:
            metrics = _get_cloudwatch_metrics(service_name)
            status = _derive_status(metrics)
            service_results[service_name] = {
                "status": status,
                "latency": metrics["avgDuration"],
            }
            overall = _rollup_status(overall, status)

        _save_health_history(service_results, overall, checked_at)

        if overall != "healthy":
            _publish_health_alert(service_results, overall, checked_at)

        return _response(200, {
            "status": overall,
            "services": service_results,
            "checkedAt": checked_at,
        })
    except Exception as e:  # noqa: BLE001
        return _response(500, {"error": "INTERNAL_ERROR", "message": str(e)})


# ── CloudWatch helpers ────────────────────────────────────────────────────────

def _get_cloudwatch_metrics(service_name: str, period_minutes: int = 5) -> dict:
    """Query CloudWatch Lambda metrics for a service over the last period_minutes."""
    fn_name = f"kismet-{service_name}"
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=period_minutes)
    period_seconds = period_minutes * 60
    dimensions = [{"Name": "FunctionName", "Value": fn_name}]

    def _metric_query(query_id, metric_name, stat):
        return {
            "Id": query_id,
            "MetricStat": {
                "Metric": {
                    "Namespace": "AWS/Lambda",
                    "MetricName": metric_name,
                    "Dimensions": dimensions,
                },
                "Period": period_seconds,
                "Stat": stat,
            },
            "ReturnData": True,
        }

    response = cloudwatch.get_metric_data(
        MetricDataQueries=[
            _metric_query("errors", "Errors", "Sum"),
            _metric_query("invocations", "Invocations", "Sum"),
            _metric_query("duration_avg", "Duration", "Average"),
            _metric_query("duration_p99", "Duration", "p99"),
            _metric_query("throttles", "Throttles", "Sum"),
        ],
        StartTime=start_time,
        EndTime=end_time,
    )

    data = {
        r["Id"]: r["Values"][0] if r["Values"] else 0.0
        for r in response["MetricDataResults"]
    }

    errors = int(data.get("errors", 0))
    invocations = int(data.get("invocations", 0))
    avg_duration = round(data.get("duration_avg", 0))
    p99_duration = round(data.get("duration_p99", 0))
    throttles = int(data.get("throttles", 0))
    error_rate = errors / invocations if invocations > 0 else 0.0

    return {
        "errors": errors,
        "errorRate": round(error_rate, 4),
        "avgDuration": avg_duration,
        "p99Duration": p99_duration,
        "invocations": invocations,
        "throttles": throttles,
    }


def _derive_status(metrics: dict) -> str:
    if metrics["invocations"] == 0:
        return "unknown"
    if metrics["errorRate"] > UNHEALTHY_ERROR_RATE:
        return "unhealthy"
    if metrics["avgDuration"] > DEGRADED_LATENCY_MS:
        return "degraded"
    return "healthy"


def _rollup_status(current: str, new: str) -> str:
    """Return the worse of two statuses."""
    order = {"unknown": 0, "healthy": 1, "degraded": 2, "unhealthy": 3}
    return current if order[current] >= order[new] else new


# ── DynamoDB + SNS helpers ────────────────────────────────────────────────────

def _save_health_history(service_results: dict, overall: str, checked_at: str):
    table = dynamodb.Table(HEALTH_HISTORY_TABLE)
    table.put_item(Item={
        "PK": "SERVICE#_all",
        "SK": f"CHECK#{checked_at}",
        "status": overall,
        "metrics": {
            svc: {"status": v["status"], "latency": v["latency"]}
            for svc, v in service_results.items()
        },
        "checkedAt": checked_at,
    })


def _publish_health_alert(service_results: dict, overall: str, checked_at: str):
    if not HEALTH_ALERTS_TOPIC_ARN:
        return

    degraded = [svc for svc, v in service_results.items() if v["status"] != "healthy"]
    message = {
        "alarmName": "kismet-system-health",
        "serviceName": "_all",
        "state": overall.upper(),
        "reason": f"Degraded/unhealthy services: {', '.join(degraded)}",
        "timestamp": checked_at,
    }
    sns.publish(
        TopicArn=HEALTH_ALERTS_TOPIC_ARN,
        Message=json.dumps(message),
        Subject=f"Kismet Health Alert: system is {overall}",
    )
