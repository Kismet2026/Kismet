import json
import os
import uuid
import base64
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import boto3
from boto3.dynamodb.conditions import Key

SERVICE_NAME = "message-service"
TABLE_NAME = os.environ["TABLE_NAME"]
EVENT_BUS_NAME = os.environ.get("EVENT_BUS_NAME", "kismet-events")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
events_client = boto3.client("events")


def lambda_handler(event: Optional[Dict[str, Any]], context: Any) -> Dict[str, Any]:
    event = event or {}
    method = get_http_method(event)
    path_params = event.get("pathParameters") or {}
    query_params = event.get("queryStringParameters") or {}

    # Extract authenticated user from Cognito JWT claims
    claims = event.get("requestContext", {}).get("authorizer", {}).get("claims", {})
    user_id = claims.get("sub") or claims.get("cognito:username", "")

    # ── Route dispatch ────────────────────────────────────────────────────────
    if method == "POST":
        payload, error = parse_json_body(event)
        if error:
            return error
        return handle_send_message(payload, user_id)

    if method == "GET" and "matchId" in path_params:
        return handle_get_messages(path_params["matchId"], user_id, query_params)

    if method == "DELETE" and "messageId" in path_params:
        return handle_delete_message(path_params["messageId"], user_id)

    return json_response(404, {"code": "NOT_FOUND", "message": f"No route matches {method}"})


# ── Handlers ──────────────────────────────────────────────────────────────────

def handle_send_message(body: dict, sender_id: str) -> Dict[str, Any]:
    """POST /messages — Persist a new message and publish message.sent event."""
    match_id = (body or {}).get("matchId")
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

    # Publish message.sent to EventBridge (consumed by Text Moderation + Activity Logger)
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
        # Don't fail the user request if event publishing has a hiccup
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


def handle_get_messages(match_id: str, user_id: str, query_params: dict) -> Dict[str, Any]:
    """GET /messages/{matchId} — Paginated conversation history, newest first."""
    limit = min(int(query_params.get("limit", 50)), 50)
    cursor = query_params.get("cursor")

    kwargs: Dict[str, Any] = {
        "KeyConditionExpression": Key("PK").eq(f"CONV#{match_id}"),
        "ScanIndexForward": False,  # newest first
        "Limit": limit,
    }

    if cursor:
        try:
            last_key = json.loads(base64.b64decode(cursor).decode())
            kwargs["ExclusiveStartKey"] = last_key
        except Exception:
            return json_response(
                400, {"code": "VALIDATION_ERROR", "message": "Invalid cursor value"}
            )

    result = table.query(**kwargs)
    items = [i for i in result.get("Items", []) if not i.get("deleted", False)]

    next_cursor = None
    if "LastEvaluatedKey" in result:
        next_cursor = base64.b64encode(
            json.dumps(result["LastEvaluatedKey"]).encode()
        ).decode()

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

    return json_response(200, {"items": messages, "nextCursor": next_cursor, "count": len(messages)})


def handle_delete_message(message_id: str, user_id: str) -> Dict[str, Any]:
    """DELETE /messages/{messageId} — Soft delete; only the sender can delete."""
    # Look up the item via messageId GSI to get the full DynamoDB key
    result = table.query(
        IndexName="messageId-index",
        KeyConditionExpression=Key("messageId").eq(message_id),
    )
    items = result.get("Items", [])

    if not items:
        return json_response(404, {"code": "NOT_FOUND", "message": "Message not found"})

    item = items[0]

    if item.get("senderId") != user_id:
        return json_response(
            403, {"code": "FORBIDDEN", "message": "Only the sender can delete this message"}
        )

    if item.get("deleted"):
        return json_response(
            400, {"code": "VALIDATION_ERROR", "message": "Message already deleted"}
        )

    now = datetime.now(timezone.utc).isoformat()

    table.update_item(
        Key={"PK": item["PK"], "SK": item["SK"]},
        UpdateExpression="SET deleted = :d, deletedAt = :at",
        ExpressionAttributeValues={":d": True, ":at": now},
    )

    return json_response(200, {"messageId": message_id, "deleted": True, "deletedAt": now})


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_http_method(event: Dict[str, Any]) -> str:
    method = (
        event.get("requestContext", {}).get("http", {}).get("method")
        or event.get("httpMethod")
        or ""
    )
    return str(method).upper()


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
