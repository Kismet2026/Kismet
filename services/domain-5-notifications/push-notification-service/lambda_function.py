import json
import os
import uuid
import boto3
from boto3.dynamodb.conditions import Key
from datetime import datetime, timezone

dynamodb = boto3.resource("dynamodb")
sns = boto3.client("sns")

tokens_table = dynamodb.Table(os.environ.get("DEVICE_TOKENS_TABLE", "kismet-device-tokens"))
notifications_table = dynamodb.Table(os.environ.get("NOTIFICATIONS_TABLE", "kismet-notifications"))

SNS_PLATFORM_ARNS = {
    "ios": os.environ.get("SNS_PLATFORM_ARN_IOS", ""),
    "android": os.environ.get("SNS_PLATFORM_ARN_ANDROID", ""),
    "web": os.environ.get("SNS_PLATFORM_ARN_WEB", ""),
}

# IAM least-privilege: In CDK stack, scope SNS permissions to kismet-* resources:
#   sns:CreatePlatformEndpoint → arn:aws:sns:{region}:{account}:app/*/kismet-*
#   sns:Publish               → arn:aws:sns:{region}:{account}:endpoint/*/kismet-*/*


def handler(event, context):
    # EventBridge event — has "source" and "detail-type"
    if "source" in event and "detail-type" in event:
        return handle_event(event, context)

    # API Gateway HTTP request
    http_method = event.get("httpMethod", "")
    path = event.get("path", "")
    user_id = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("claims", {})
        .get("sub", "")
    )

    if http_method == "POST" and path == "/notifications/register":
        return register_device(event, user_id)
    elif http_method == "GET" and path == "/notifications/unread-count":
        return get_unread_count(user_id)
    elif http_method == "GET" and path == "/notifications":
        return list_notifications(event, user_id)
    elif http_method == "PUT" and "/read" in path:
        return mark_as_read(event, user_id)
    else:
        return response(404, {"error": {"code": "NOT_FOUND", "message": "Route not found"}})


# ---------------------------------------------------------------------------
# EventBridge handlers
# ---------------------------------------------------------------------------

def handle_event(event, context):
    detail_type = event.get("detail-type", "")
    detail = event.get("detail", {})

    if detail_type == "match.created":
        return on_match_created(detail)
    elif detail_type == "message.sent":
        return on_message_sent(detail)
    else:
        print(f"Unhandled event type: {detail_type}")
        return {"statusCode": 200}


def on_match_created(detail):
    """Send push notification to both matched users."""
    match_id = detail.get("matchId", "")
    user_ids = detail.get("userIds", [])
    timestamp = detail.get("timestamp", datetime.now(timezone.utc).isoformat())

    for user_id in user_ids:
        notif = create_notification(
            user_id=user_id,
            notif_type="match",
            title="You have a new match!",
            body="You matched with someone new. Start a conversation!",
            timestamp=timestamp,
        )
        send_push_to_user(user_id, notif["title"], notif["body"])

    return {"statusCode": 200}


def on_message_sent(detail):
    """Send push notification to the message recipient."""
    sender_id = detail.get("senderId", "")
    match_id = detail.get("matchId", "")
    content = detail.get("content", "")
    timestamp = detail.get("timestamp", datetime.now(timezone.utc).isoformat())

    # Determine recipient: from event schema, message.sent has senderId + matchId
    # The recipient lookup would require querying the match table, but since
    # the push-notification-service shouldn't couple to match-service's DB,
    # we rely on the event payload. If recipientId is present, use it directly.
    recipient_id = detail.get("recipientId", "")
    if not recipient_id:
        print(f"message.sent event missing recipientId, skipping push for match {match_id}")
        return {"statusCode": 200}

    preview = content[:50] + "..." if len(content) > 50 else content
    notif = create_notification(
        user_id=recipient_id,
        notif_type="message",
        title="New message",
        body=preview,
        timestamp=timestamp,
    )
    send_push_to_user(recipient_id, notif["title"], notif["body"])
    return {"statusCode": 200}


# ---------------------------------------------------------------------------
# REST API handlers
# ---------------------------------------------------------------------------

def register_device(event, user_id):
    body = json.loads(event.get("body", "{}"))
    device_token = body.get("deviceToken")
    platform = body.get("platform")

    if not device_token or platform not in ("ios", "android", "web"):
        return response(400, {
            "error": {"code": "VALIDATION_ERROR", "message": "Missing deviceToken or invalid platform"}
        })

    now = datetime.now(timezone.utc).isoformat()

    # Check for existing registration
    existing = tokens_table.get_item(
        Key={"PK": f"USER#{user_id}", "SK": f"DEVICE#{device_token}"}
    ).get("Item")
    if existing:
        return response(409, {
            "error": {"code": "CONFLICT", "message": "Device token already registered for this user"}
        })

    # Register SNS platform endpoint
    sns_endpoint_arn = ""
    platform_arn = SNS_PLATFORM_ARNS.get(platform, "")
    if platform_arn:
        try:
            resp = sns.create_platform_endpoint(
                PlatformApplicationArn=platform_arn,
                Token=device_token,
                CustomUserData=user_id,
            )
            sns_endpoint_arn = resp.get("EndpointArn", "")
        except Exception as e:
            print(f"SNS create_platform_endpoint failed: {e}")

    # Write to DynamoDB
    tokens_table.put_item(Item={
        "PK": f"USER#{user_id}",
        "SK": f"DEVICE#{device_token}",
        "platform": platform,
        "snsEndpointArn": sns_endpoint_arn,
        "registeredAt": now,
    })

    return response(200, {
        "deviceToken": device_token,
        "platform": platform,
        "registeredAt": now,
    })


def list_notifications(event, user_id):
    params = event.get("queryStringParameters") or {}
    limit = min(int(params.get("limit", 20)), 50)
    cursor = params.get("cursor")

    query_params = {
        "KeyConditionExpression": Key("PK").eq(f"USER#{user_id}") & Key("SK").begins_with("NOTIF#"),
        "ScanIndexForward": False,  # newest first
        "Limit": limit,
    }
    if cursor:
        query_params["ExclusiveStartKey"] = json.loads(
            __import__("base64").b64decode(cursor).decode()
        )

    result = notifications_table.query(**query_params)
    items = [
        {
            "notificationId": item["notificationId"],
            "type": item["type"],
            "title": item["title"],
            "body": item["body"],
            "read": item["read"],
            "timestamp": item["timestamp"],
        }
        for item in result.get("Items", [])
    ]

    next_cursor = None
    if "LastEvaluatedKey" in result:
        import base64
        next_cursor = base64.b64encode(
            json.dumps(result["LastEvaluatedKey"]).encode()
        ).decode()

    return response(200, {
        "items": items,
        "nextCursor": next_cursor,
        "count": len(items),
    })


def mark_as_read(event, user_id):
    # Path: /notifications/{notificationId}/read
    parts = event.get("path", "").split("/")
    notification_id = parts[2] if len(parts) >= 4 else None

    if not notification_id:
        return response(400, {
            "error": {"code": "VALIDATION_ERROR", "message": "Missing notificationId"}
        })

    # Find the notification by scanning user's items for matching notificationId
    result = notifications_table.query(
        KeyConditionExpression=Key("PK").eq(f"USER#{user_id}") & Key("SK").begins_with("NOTIF#"),
    )
    target = None
    for item in result.get("Items", []):
        if item["notificationId"] == notification_id:
            target = item
            break

    if not target:
        return response(404, {
            "error": {"code": "NOT_FOUND", "message": "Notification not found"}
        })

    now = datetime.now(timezone.utc).isoformat()
    notifications_table.update_item(
        Key={"PK": target["PK"], "SK": target["SK"]},
        UpdateExpression="SET #r = :val, updatedAt = :now",
        ExpressionAttributeNames={"#r": "read"},
        ExpressionAttributeValues={":val": True, ":now": now},
    )

    return response(200, {
        "notificationId": notification_id,
        "read": True,
        "updatedAt": now,
    })


def get_unread_count(user_id):
    result = notifications_table.query(
        KeyConditionExpression=Key("PK").eq(f"USER#{user_id}") & Key("SK").begins_with("NOTIF#"),
        FilterExpression="#r = :val",
        ExpressionAttributeNames={"#r": "read"},
        ExpressionAttributeValues={":val": False},
        Select="COUNT",
    )
    return response(200, {"unreadCount": result.get("Count", 0)})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def create_notification(user_id, notif_type, title, body, timestamp=None):
    """Write a notification record to DynamoDB."""
    now = timestamp or datetime.now(timezone.utc).isoformat()
    notif_id = f"notif-{uuid.uuid4().hex[:8]}"

    notifications_table.put_item(Item={
        "PK": f"USER#{user_id}",
        "SK": f"NOTIF#{now}#{notif_id}",
        "notificationId": notif_id,
        "type": notif_type,
        "title": title,
        "body": body,
        "read": False,
        "timestamp": now,
    })

    return {"notificationId": notif_id, "title": title, "body": body}


def send_push_to_user(user_id, title, body):
    """Send push notification to all registered devices for a user."""
    result = tokens_table.query(
        KeyConditionExpression=Key("PK").eq(f"USER#{user_id}") & Key("SK").begins_with("DEVICE#"),
    )

    for device in result.get("Items", []):
        endpoint_arn = device.get("snsEndpointArn", "")
        if not endpoint_arn:
            continue
        try:
            sns.publish(
                TargetArn=endpoint_arn,
                Message=json.dumps({
                    "default": body,
                    "GCM": json.dumps({"notification": {"title": title, "body": body}}),
                    "APNS": json.dumps({"aps": {"alert": {"title": title, "body": body}}}),
                }),
                MessageStructure="json",
            )
        except Exception as e:
            print(f"SNS publish failed for {endpoint_arn}: {e}")


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }
