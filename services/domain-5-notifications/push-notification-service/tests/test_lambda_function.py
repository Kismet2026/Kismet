import json
import os
import pytest
import boto3
from moto import mock_aws
from datetime import datetime, timezone

# Set env vars before importing the handler
os.environ["DEVICE_TOKENS_TABLE"] = "kismet-device-tokens"
os.environ["NOTIFICATIONS_TABLE"] = "kismet-notifications"
os.environ["SNS_PLATFORM_ARN_IOS"] = "arn:aws:sns:us-east-1:123456789012:app/APNS/kismet-ios"
os.environ["SNS_PLATFORM_ARN_ANDROID"] = "arn:aws:sns:us-east-1:123456789012:app/GCM/kismet-android"
os.environ["SNS_PLATFORM_ARN_WEB"] = "arn:aws:sns:us-east-1:123456789012:app/WEBPUSH/kismet-web"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_SECURITY_TOKEN"] = "testing"
os.environ["AWS_SESSION_TOKEN"] = "testing"

import lambda_function


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def aws_resources():
    """Spin up mocked DynamoDB tables and SNS for each test."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

        dynamodb.create_table(
            TableName="kismet-device-tokens",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        dynamodb.create_table(
            TableName="kismet-notifications",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Reload module-level clients so they point to mocked AWS
        import importlib
        importlib.reload(lambda_function)

        yield dynamodb


def api_event(method, path, body=None, user_id="user-123", query=None):
    return {
        "httpMethod": method,
        "path": path,
        "queryStringParameters": query,
        "body": json.dumps(body) if body else "{}",
        "requestContext": {
            "authorizer": {"claims": {"sub": user_id}}
        },
    }


def eb_event(detail_type, detail):
    return {
        "source": "kismet.match-service",
        "detail-type": detail_type,
        "detail": detail,
    }


# ---------------------------------------------------------------------------
# POST /notifications/register
# ---------------------------------------------------------------------------

class TestRegisterDevice:
    def test_success_ios(self, aws_resources):
        event = api_event("POST", "/notifications/register",
                          body={"deviceToken": "token-abc", "platform": "ios"})
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["deviceToken"] == "token-abc"
        assert body["platform"] == "ios"
        assert "registeredAt" in body

    def test_success_android(self, aws_resources):
        event = api_event("POST", "/notifications/register",
                          body={"deviceToken": "token-xyz", "platform": "android"})
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 200

    def test_missing_device_token(self, aws_resources):
        event = api_event("POST", "/notifications/register",
                          body={"platform": "ios"})
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 400
        assert json.loads(result["body"])["error"]["code"] == "VALIDATION_ERROR"

    def test_invalid_platform(self, aws_resources):
        event = api_event("POST", "/notifications/register",
                          body={"deviceToken": "token-abc", "platform": "windows"})
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 400

    def test_duplicate_registration_returns_409(self, aws_resources):
        body = {"deviceToken": "token-dup", "platform": "ios"}
        event = api_event("POST", "/notifications/register", body=body)
        lambda_function.handler(event, {})  # first registration
        result = lambda_function.handler(event, {})  # duplicate
        assert result["statusCode"] == 409
        assert json.loads(result["body"])["error"]["code"] == "CONFLICT"

    def test_persisted_to_dynamodb(self, aws_resources):
        event = api_event("POST", "/notifications/register",
                          body={"deviceToken": "token-persist", "platform": "web"},
                          user_id="user-persist")
        lambda_function.handler(event, {})

        table = aws_resources.Table("kismet-device-tokens")
        item = table.get_item(
            Key={"PK": "USER#user-persist", "SK": "DEVICE#token-persist"}
        ).get("Item")
        assert item is not None
        assert item["platform"] == "web"


# ---------------------------------------------------------------------------
# GET /notifications
# ---------------------------------------------------------------------------

class TestListNotifications:
    def test_empty_list(self, aws_resources):
        event = api_event("GET", "/notifications", user_id="user-empty")
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["items"] == []
        assert body["count"] == 0
        assert body["nextCursor"] is None

    def test_returns_stored_notifications(self, aws_resources):
        # Seed a notification directly
        now = datetime.now(timezone.utc).isoformat()
        table = aws_resources.Table("kismet-notifications")
        table.put_item(Item={
            "PK": "USER#user-123",
            "SK": f"NOTIF#{now}#notif-001",
            "notificationId": "notif-001",
            "type": "match",
            "title": "New match!",
            "body": "You matched!",
            "read": False,
            "timestamp": now,
        })

        event = api_event("GET", "/notifications", user_id="user-123")
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["count"] == 1
        assert body["items"][0]["notificationId"] == "notif-001"

    def test_limit_param_respected(self, aws_resources):
        table = aws_resources.Table("kismet-notifications")
        now = datetime.now(timezone.utc).isoformat()
        for i in range(5):
            table.put_item(Item={
                "PK": "USER#user-limit",
                "SK": f"NOTIF#{now}#notif-{i:03d}",
                "notificationId": f"notif-{i:03d}",
                "type": "match", "title": "t", "body": "b",
                "read": False, "timestamp": now,
            })

        event = api_event("GET", "/notifications", user_id="user-limit", query={"limit": "2"})
        result = lambda_function.handler(event, {})
        body = json.loads(result["body"])
        assert body["count"] == 2
        assert body["nextCursor"] is not None


# ---------------------------------------------------------------------------
# PUT /notifications/{notificationId}/read
# ---------------------------------------------------------------------------

class TestMarkAsRead:
    def test_marks_existing_notification(self, aws_resources):
        now = datetime.now(timezone.utc).isoformat()
        notif_id = "0001234567890-abcd1234"  # new epoch_ms-uuid format
        table = aws_resources.Table("kismet-notifications")
        table.put_item(Item={
            "PK": "USER#user-123",
            "SK": f"NOTIF#{notif_id}",
            "notificationId": notif_id,
            "type": "match", "title": "t", "body": "b",
            "read": False, "timestamp": now,
        })

        event = api_event("PUT", f"/notifications/{notif_id}/read", user_id="user-123")
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 200
        assert json.loads(result["body"])["read"] is True

    def test_not_found_returns_404(self, aws_resources):
        event = api_event("PUT", "/notifications/notif-ghost/read", user_id="user-123")
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 404
        assert json.loads(result["body"])["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# GET /notifications/unread-count
# ---------------------------------------------------------------------------

class TestUnreadCount:
    def test_zero_when_empty(self, aws_resources):
        event = api_event("GET", "/notifications/unread-count", user_id="user-zero")
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 200
        assert json.loads(result["body"])["unreadCount"] == 0

    def test_counts_only_unread(self, aws_resources):
        # Seed counter item directly — unread count is now maintained as a counter,
        # not derived from scanning all notification items
        table = aws_resources.Table("kismet-notifications")
        table.put_item(Item={
            "PK": "USER#user-count",
            "SK": "UNREAD_COUNT",
            "count": 2,
        })

        event = api_event("GET", "/notifications/unread-count", user_id="user-count")
        result = lambda_function.handler(event, {})
        assert json.loads(result["body"])["unreadCount"] == 2


# ---------------------------------------------------------------------------
# EventBridge: match.created
# ---------------------------------------------------------------------------

class TestOnMatchCreated:
    def test_creates_notifications_for_both_users(self, aws_resources):
        event = eb_event("match.created", {
            "matchId": "match-001",
            "userIds": ["user-a", "user-b"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 200

        table = aws_resources.Table("kismet-notifications")
        for uid in ["user-a", "user-b"]:
            items = table.query(
                KeyConditionExpression=boto3.dynamodb.conditions.Key("PK").eq(f"USER#{uid}")
                    & boto3.dynamodb.conditions.Key("SK").begins_with("NOTIF#")
            )["Items"]
            assert len(items) == 1
            assert items[0]["type"] == "match"
            assert items[0]["read"] is False

    def test_handles_empty_user_ids(self, aws_resources):
        event = eb_event("match.created", {
            "matchId": "match-empty",
            "userIds": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 200


# ---------------------------------------------------------------------------
# EventBridge: message.sent
# ---------------------------------------------------------------------------

class TestOnMessageSent:
    def test_creates_notification_for_recipient(self, aws_resources):
        event = eb_event("message.sent", {
            "messageId": "msg-001",
            "matchId": "match-001",
            "senderId": "user-sender",
            "recipientId": "user-recipient",
            "content": "Hey!",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 200

        table = aws_resources.Table("kismet-notifications")
        items = table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("PK").eq("USER#user-recipient")
                & boto3.dynamodb.conditions.Key("SK").begins_with("NOTIF#")
        )["Items"]
        assert len(items) == 1
        assert items[0]["type"] == "message"

    def test_skips_when_no_recipient_id(self, aws_resources):
        event = eb_event("message.sent", {
            "messageId": "msg-002",
            "matchId": "match-001",
            "senderId": "user-sender",
            "content": "Hey!",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 200  # graceful skip, no crash

    def test_truncates_long_content_preview(self, aws_resources):
        long_content = "A" * 100
        event = eb_event("message.sent", {
            "messageId": "msg-003",
            "matchId": "match-001",
            "senderId": "user-sender",
            "recipientId": "user-recipient",
            "content": long_content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        lambda_function.handler(event, {})

        table = aws_resources.Table("kismet-notifications")
        items = table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("PK").eq("USER#user-recipient")
                & boto3.dynamodb.conditions.Key("SK").begins_with("NOTIF#")
        )["Items"]
        assert len(items[0]["body"]) <= 53  # 50 chars + "..."


# ---------------------------------------------------------------------------
# Unknown route
# ---------------------------------------------------------------------------

class TestRouting:
    def test_unknown_route_returns_404(self, aws_resources):
        event = api_event("GET", "/unknown/path")
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 404

    def test_unhandled_event_type_returns_200(self, aws_resources):
        event = eb_event("some.other.event", {"foo": "bar"})
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 200
