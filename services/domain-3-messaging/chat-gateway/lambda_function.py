import json
import os
import uuid
import base64
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import boto3
from boto3.dynamodb.conditions import Key

SERVICE_NAME = "chat-gateway"
MESSAGES_TABLE = os.environ["MESSAGES_TABLE"]
EVENT_BUS_NAME = os.environ.get("EVENT_BUS_NAME", "kismet-events")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(MESSAGES_TABLE)
events_client = boto3.client("events")


def lambda_handler(event: Optional[Dict[str, Any]], context: Any) -> Dict[str, Any]:
    event = event or {}
    method = get_http_method(event)
    path = normalize_path(get_request_path(event))
    path_params = event.get("pathParameters") or {}
    query_params = event.get("queryStringParameters") or {}

    # Extract authenticated user from Cognito JWT claims
    claims = event.get("requestContext", {}).get("authorizer", {}).get("claims", {})
    user_id = claims.get("sub") or claims.get("cognito:username", "")

    match_id = path_params.get("matchId", "")

    # ── Route dispatch ────────────────────────────────────────────────────────
    # POST /chat/{matchId}/send
    if method == "POST" and path.endswith("/send"):
        payload, error = parse_json_body(event)
        if error:
            return error
        return handle_send(match_id, payload, user_id)

    # GET /chat/{matchId}/status
    if method == "GET" and path.endswith("/status"):
        return handle_status(match_id, user_id, query_params)

    # GET /chat/{matchId}/messages
    if method == "GET" and match_id:
        return handle_poll(match_id, user_id, query_params)

    return json_response(404, {"code": "NOT_FOUND", "message": f"No route matches {method} {path}"})


# ── Handlers ──────────────────────────────────────────────────────────────────

def handle_send(match_id: str, body: dict, sender_id: str) -> Dict[str, Any]:
    """POST /chat/{matchId}/send — Send a message and push to EventBridge."""
    content = (body or {}).get("content")
    message_type = (body or {}).get("messageType", "text")
    recipient_id = (body or {}).get("recipientId", "")

    if not match_id or not content:
        return json_response(
            400,
            {"code": "VALIDATION_ERROR", "message": "matchId and content are required"},
        )

    now = datetime.now(timezone.utc).isoformat()
    message_id = str(uuid.uuid4())

    item = {
        "PK": f"CONV#{match_id}",
        "SK": f"MSG#{now}#{message_id}",
        "messageId": message_id,
        "matchId": match_id,
        "senderId": sender_id,
        "recipientId": recipient_id,
        "content": content,
        "messageType": message_type,
        "timestamp": now,
        "deleted": False,
    }

    table.put_item(Item=item)

    # Publish message.sent (Text Moderation + Activity Logger will consume this)
    try:
        events_client.put_events(
            Entries=[
                {
                    "Source": "kismet.message-service",
                    "DetailType": "message.sent",
                    "Detail": json.dumps(
                        {
                            "messageId": message_id,
                            "matchId": match_id,
                            "senderId": sender_id,
                            "recipientId": recipient_id,
                            "content": content,
                            "messageType": message_type,
                            "timestamp": now,
                        }
                    ),
                    "EventBusName": EVENT_BUS_NAME,
                }
            ]
        )
    except Exception as exc:
        print(f"[WARN] Failed to publish message.sent event: {exc}")

    return json_response(
        200,
        {
            "messageId": message_id,
            "matchId": match_id,
            "senderId": sender_id,
            "content": content,
            "messageType": message_type,
            "timestamp": now,
        },
    )


def handle_poll(match_id: str, user_id: str, query_params: dict) -> Dict[str, Any]:
    """GET /chat/{matchId}/messages — Poll for messages, optionally since a timestamp."""
    since = query_params.get("since")  # ISO 8601 timestamp
    limit = min(int(query_params.get("limit", 50)), 50)

    kwargs: Dict[str, Any] = {
        "ScanIndexForward": False,  # newest first
        "Limit": limit,
    }

    if since:
        # Return only messages after this timestamp
        kwargs["KeyConditionExpression"] = (
            Key("PK").eq(f"CONV#{match_id}") & Key("SK").gt(f"MSG#{since}")
        )
    else:
        kwargs["KeyConditionExpression"] = Key("PK").eq(f"CONV#{match_id}")

    result = table.query(**kwargs)
    items = [i for i in result.get("Items", []) if not i.get("deleted", False)]

    messages = [
        {
            "messageId": i["messageId"],
            "matchId": i["matchId"],
            "senderId": i["senderId"],
            "content": i["content"],
            "messageType": i.get("messageType", "text"),
            "timestamp": i["timestamp"],
        }
        for i in items
    ]

    return json_response(200, {"items": messages, "count": len(messages)})


def handle_status(match_id: str, user_id: str, query_params: dict) -> Dict[str, Any]:
    """GET /chat/{matchId}/status — Last message + unread count for this conversation."""
    result = table.query(
        KeyConditionExpression=Key("PK").eq(f"CONV#{match_id}"),
        ScanIndexForward=False,
        Limit=50,
    )
    items = [i for i in result.get("Items", []) if not i.get("deleted", False)]

    last_message = None
    unread_count = 0

    if items:
        latest = items[0]
        last_message = {
            "messageId": latest["messageId"],
            "senderId": latest["senderId"],
            "content": latest["content"],
            "timestamp": latest["timestamp"],
        }
        # Count messages not sent by the current user as "unread"
        unread_count = sum(1 for i in items if i.get("senderId") != user_id)

    return json_response(
        200,
        {
            "matchId": match_id,
            "unreadCount": unread_count,
            "lastMessage": last_message,
        },
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_http_method(event: Dict[str, Any]) -> str:
    method = (
        event.get("requestContext", {}).get("http", {}).get("method")
        or event.get("httpMethod")
        or ""
    )
    return str(method).upper()


def get_request_path(event: Dict[str, Any]) -> str:
    return (
        event.get("rawPath")
        or event.get("path")
        or event.get("requestContext", {}).get("http", {}).get("path")
        or "/"
    )


def normalize_path(path: Any) -> str:
    p = str(path or "/").strip()
    if not p.startswith("/"):
        p = f"/{p}"
    if p != "/" and p.endswith("/"):
        p = p.rstrip("/")
    return p


def parse_json_body(event: Dict[str, Any]):
    body = event.get("body")
    if body in (None, ""):
        return {}, None
    if isinstance(body, dict):
        return body, None
    try:
        return json.loads(body), None
    except json.JSONDecodeError:
        return None, json_response(
            400, {"code": "VALIDATION_ERROR", "message": "Request body must be valid JSON"}
        )


def json_response(status_code: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }


# Local test entrypoint
handler = lambda_handler
