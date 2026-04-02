import json
import os
import boto3
from datetime import datetime, timezone

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ.get("TABLE_NAME", "kismet-push-notification"))


def handler(event, context):
    http_method = event.get("httpMethod", "")
    path = event.get("path", "")
    user_id = event.get("requestContext", {}).get("authorizer", {}).get("claims", {}).get("sub", "")

    if http_method == "POST" and path == "/notifications/register":
        return register_device(event, user_id)
    elif http_method == "GET" and path == "/notifications/unread-count":
        return get_unread_count(event, user_id)
    elif http_method == "GET" and path == "/notifications":
        return list_notifications(event, user_id)
    elif http_method == "PUT" and "/read" in path:
        return mark_as_read(event, user_id)
    else:
        return response(404, {"error": {"code": "NOT_FOUND", "message": "Route not found"}})


def register_device(event, user_id):
    body = json.loads(event.get("body", "{}"))
    device_token = body.get("deviceToken")
    platform = body.get("platform")

    if not device_token or platform not in ("ios", "android", "web"):
        return response(400, {"error": {"code": "VALIDATION_ERROR", "message": "Missing deviceToken or invalid platform"}})

    # TODO: write to DynamoDB, register SNS platform endpoint
    return response(200, {
        "deviceToken": device_token,
        "platform": platform,
        "registeredAt": datetime.now(timezone.utc).isoformat(),
    })


def list_notifications(event, user_id):
    params = event.get("queryStringParameters") or {}
    limit = int(params.get("limit", 20))
    cursor = params.get("cursor")

    # TODO: query DynamoDB with PK=USER#{user_id}, SK begins_with NOTIF#
    return response(200, {
        "items": [],
        "nextCursor": None,
        "count": 0,
    })


def mark_as_read(event, user_id):
    parts = event.get("path", "").split("/")
    notification_id = parts[2] if len(parts) >= 4 else None

    if not notification_id:
        return response(400, {"error": {"code": "VALIDATION_ERROR", "message": "Missing notificationId"}})

    # TODO: update DynamoDB item read=True
    return response(200, {
        "notificationId": notification_id,
        "read": True,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    })


def get_unread_count(event, user_id):
    # TODO: query DynamoDB, count items where read=False
    return response(200, {"unreadCount": 0})


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }