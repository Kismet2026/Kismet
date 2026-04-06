"""
Kismet Event Bus Service — Lambda Handlers

Two entry points:
  1. catch_all_handler  — EventBridge target; logs every event to DynamoDB
  2. admin_api_handler  — API Gateway; GET /events/rules, GET /events/history, POST /events/replay
"""

import json
import os
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key, Attr

# ─── Clients ──────────────────────────────────────────────────
dynamodb = boto3.resource("dynamodb")
events_client = boto3.client("events")

EVENT_LOG_TABLE = os.environ["EVENT_LOG_TABLE"]
EVENT_BUS_NAME = os.environ["EVENT_BUS_NAME"]

table = dynamodb.Table(EVENT_LOG_TABLE)


# ─── Helpers ──────────────────────────────────────────────────
def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }


def _error(status_code, code, message):
    return _response(status_code, {"error": {"code": code, "message": message}})


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. Catch-All Logger (EventBridge → DynamoDB)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def catch_all_handler(event, context):
    """Receives every event from the kismet-events bus and logs it to DynamoDB."""
    event_id = event.get("id", str(uuid.uuid4()))
    source = event.get("source", "unknown")
    detail_type = event.get("detail-type", "unknown")
    detail = event.get("detail", {})
    timestamp = event.get("time", _now_iso())

    table.put_item(
        Item={
            "PK": f"EVENT#{event_id}",
            "SK": "META",
            "eventId": event_id,
            "source": source,
            "detailType": detail_type,
            "detail": detail,
            "timestamp": timestamp,
            "status": "delivered",
        }
    )

    return {"statusCode": 200}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. Admin API (API Gateway)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def admin_api_handler(event, context):
    """Routes API Gateway requests to the correct handler."""
    http_method = event.get("httpMethod", "")
    path = event.get("path", "")

    if path == "/events/rules" and http_method == "GET":
        return _get_rules(event)
    elif path == "/events/history" and http_method == "GET":
        return _get_history(event)
    elif path == "/events/replay" and http_method == "POST":
        return _replay_event(event)
    else:
        return _error(404, "NOT_FOUND", f"No route for {http_method} {path}")


# ─── GET /events/rules ────────────────────────────────────────
def _get_rules(event):
    """List all active EventBridge rules on the kismet-events bus."""
    response = events_client.list_rules(EventBusName=EVENT_BUS_NAME)

    rules = []
    for rule in response.get("Rules", []):
        rule_name = rule["Name"]
        pattern = json.loads(rule.get("EventPattern", "{}"))

        targets_resp = events_client.list_targets_by_rule(
            Rule=rule_name, EventBusName=EVENT_BUS_NAME
        )
        targets = [t["Arn"].split(":")[-1] for t in targets_resp.get("Targets", [])]

        rules.append(
            {
                "ruleName": rule_name,
                "eventPattern": pattern,
                "targets": targets,
                "state": rule.get("State", "UNKNOWN"),
            }
        )

    return _response(200, {"rules": rules, "count": len(rules)})


# ─── GET /events/history ──────────────────────────────────────
def _get_history(event):
    """Query recent events from the event log with optional filters."""
    params = event.get("queryStringParameters") or {}
    source_filter = params.get("source")
    detail_type_filter = params.get("detailType")
    raw_limit = params.get("limit", 20)
    try:
        limit = min(int(raw_limit), 100)
    except (TypeError, ValueError):
        return _error(400, "VALIDATION_ERROR", "Query parameter 'limit' must be an integer")

    if source_filter:
        # Use GSI for efficient source-based queries
        scan_kwargs = {
            "IndexName": "source-timestamp-index",
            "KeyConditionExpression": Key("source").eq(source_filter),
            "ScanIndexForward": False,
            "Limit": limit,
        }
        if detail_type_filter:
            scan_kwargs["FilterExpression"] = Attr("detailType").eq(detail_type_filter)
        response = table.query(**scan_kwargs)
    else:
        # Full scan — acceptable for admin-only, low-traffic endpoint
        scan_kwargs = {"Limit": limit}
        filter_expressions = []
        if detail_type_filter:
            filter_expressions.append(Attr("detailType").eq(detail_type_filter))
        if filter_expressions:
            combined = filter_expressions[0]
            for expr in filter_expressions[1:]:
                combined = combined & expr
            scan_kwargs["FilterExpression"] = combined
        response = table.scan(**scan_kwargs)

    items = [
        {
            "eventId": item["eventId"],
            "source": item["source"],
            "detailType": item["detailType"],
            "detail": item.get("detail", {}),
            "timestamp": item["timestamp"],
            "status": item.get("status", "unknown"),
        }
        for item in response.get("Items", [])
    ]

    # Sort by timestamp descending (needed for scan path; GSI path already sorted)
    if not source_filter:
        items.sort(key=lambda x: x["timestamp"], reverse=True)

    return _response(200, {"items": items, "count": len(items)})


# ─── POST /events/replay ─────────────────────────────────────
def _replay_event(event):
    """Re-publish a failed event from the event log to the EventBridge bus."""
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _error(400, "VALIDATION_ERROR", "Request body must be valid JSON")
    event_id = body.get("eventId")

    if not event_id:
        return _error(400, "VALIDATION_ERROR", "Missing eventId in request body")

    # Look up the original event
    result = table.get_item(Key={"PK": f"EVENT#{event_id}", "SK": "META"})
    item = result.get("Item")

    if not item:
        return _error(404, "NOT_FOUND", f"Event {event_id} not found in event log")

    # Re-publish to EventBridge
    detail = item.get("detail", {})
    if isinstance(detail, str):
        detail_str = detail
    else:
        detail_str = json.dumps(detail, default=str)

    events_client.put_events(
        Entries=[
            {
                "Source": item["source"],
                "DetailType": item["detailType"],
                "Detail": detail_str,
                "EventBusName": EVENT_BUS_NAME,
            }
        ]
    )

    replayed_at = _now_iso()

    # Log the replay as a new event entry
    replay_id = str(uuid.uuid4())
    table.put_item(
        Item={
            "PK": f"EVENT#{replay_id}",
            "SK": "META",
            "eventId": replay_id,
            "source": item["source"],
            "detailType": item["detailType"],
            "detail": item.get("detail", {}),
            "timestamp": replayed_at,
            "status": "replayed",
            "originalEventId": event_id,
        }
    )

    return _response(
        200,
        {
            "eventId": event_id,
            "replayedAt": replayed_at,
            "status": "replayed",
        },
    )
