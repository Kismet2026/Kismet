import json
import os
import pytest
import boto3
from moto import mock_aws
from datetime import datetime, timezone

# Set env vars before importing the handler
os.environ["PREFERENCES_TABLE"] = "kismet-email-preferences"
os.environ["SENDER_EMAIL"] = "noreply@kismet.app"
os.environ["ADMIN_EMAIL"] = "admin@kismet.app"
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
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

        dynamodb.create_table(
            TableName="kismet-email-preferences",
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

        # Verify sender in mocked SES
        ses = boto3.client("ses", region_name="us-east-1")
        ses.verify_email_identity(EmailAddress="noreply@kismet.app")
        ses.verify_email_identity(EmailAddress="admin@kismet.app")

        import importlib
        importlib.reload(lambda_function)

        yield dynamodb


def api_event(method, path, body=None, user_id="user-123"):
    return {
        "httpMethod": method,
        "path": path,
        "body": json.dumps(body) if body else "{}",
        "requestContext": {
            "authorizer": {"claims": {"sub": user_id}}
        },
    }


def eb_event(source, detail_type, detail):
    return {
        "source": source,
        "detail-type": detail_type,
        "detail": detail,
    }


def seed_preferences(aws_resources, user_id, **overrides):
    table = aws_resources.Table("kismet-email-preferences")
    prefs = {
        "PK": f"USER#{user_id}",
        "SK": "PREFS",
        "email": f"{user_id}@example.com",
        "matchNotifications": True,
        "messageNotifications": True,
        "weeklyDigest": True,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        **overrides,
    }
    table.put_item(Item=prefs)
    return prefs


# ---------------------------------------------------------------------------
# GET /email/preferences
# ---------------------------------------------------------------------------

class TestGetPreferences:
    def test_returns_defaults_when_no_record(self, aws_resources):
        event = api_event("GET", "/email/preferences", user_id="user-new")
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["matchNotifications"] is True
        assert body["messageNotifications"] is True
        assert body["weeklyDigest"] is True
        assert body["userId"] == "user-new"

    def test_returns_stored_preferences(self, aws_resources):
        seed_preferences(aws_resources, "user-123",
                         matchNotifications=False, weeklyDigest=False)
        event = api_event("GET", "/email/preferences", user_id="user-123")
        result = lambda_function.handler(event, {})
        body = json.loads(result["body"])
        assert body["matchNotifications"] is False
        assert body["weeklyDigest"] is False
        assert body["messageNotifications"] is True


# ---------------------------------------------------------------------------
# PUT /email/preferences
# ---------------------------------------------------------------------------

class TestUpdatePreferences:
    def test_updates_single_field(self, aws_resources):
        seed_preferences(aws_resources, "user-123")
        event = api_event("PUT", "/email/preferences",
                          body={"weeklyDigest": False},
                          user_id="user-123")
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["weeklyDigest"] is False
        assert body["matchNotifications"] is True  # unchanged

    def test_non_boolean_returns_400(self, aws_resources):
        event = api_event("PUT", "/email/preferences",
                          body={"matchNotifications": "yes"},
                          user_id="user-123")
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 400
        assert json.loads(result["body"])["error"]["code"] == "VALIDATION_ERROR"

    def test_empty_body_returns_400(self, aws_resources):
        event = api_event("PUT", "/email/preferences",
                          body={},
                          user_id="user-123")
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 400

    def test_persisted_to_dynamodb(self, aws_resources):
        seed_preferences(aws_resources, "user-123")
        event = api_event("PUT", "/email/preferences",
                          body={"matchNotifications": False},
                          user_id="user-123")
        lambda_function.handler(event, {})

        table = aws_resources.Table("kismet-email-preferences")
        item = table.get_item(Key={"PK": "USER#user-123", "SK": "PREFS"}).get("Item")
        assert item["matchNotifications"] is False


# ---------------------------------------------------------------------------
# EventBridge: user.created
# ---------------------------------------------------------------------------

class TestOnUserCreated:
    def test_initializes_default_preferences(self, aws_resources):
        event = eb_event("kismet.auth-service", "user.created", {
            "userId": "user-new",
            "email": "new@example.com",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 200

        table = aws_resources.Table("kismet-email-preferences")
        item = table.get_item(Key={"PK": "USER#user-new", "SK": "PREFS"}).get("Item")
        assert item is not None
        assert item["matchNotifications"] is True
        assert item["messageNotifications"] is True
        assert item["weeklyDigest"] is True

    def test_does_not_overwrite_existing_preferences(self, aws_resources):
        # Seed existing preferences
        seed_preferences(aws_resources, "user-existing", matchNotifications=False)

        event = eb_event("kismet.auth-service", "user.created", {
            "userId": "user-existing",
            "email": "existing@example.com",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        lambda_function.handler(event, {})

        table = aws_resources.Table("kismet-email-preferences")
        item = table.get_item(Key={"PK": "USER#user-existing", "SK": "PREFS"}).get("Item")
        assert item["matchNotifications"] is False  # not overwritten


# ---------------------------------------------------------------------------
# EventBridge: match.created
# ---------------------------------------------------------------------------

class TestOnMatchCreated:
    def test_sends_to_opted_in_users(self, aws_resources):
        seed_preferences(aws_resources, "user-a", matchNotifications=True)
        seed_preferences(aws_resources, "user-b", matchNotifications=True)

        event = eb_event("kismet.match-service", "match.created", {
            "matchId": "match-001",
            "userIds": ["user-a", "user-b"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 200

    def test_skips_opted_out_users(self, aws_resources):
        seed_preferences(aws_resources, "user-optout", matchNotifications=False)

        event = eb_event("kismet.match-service", "match.created", {
            "matchId": "match-002",
            "userIds": ["user-optout"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 200  # no error, just skipped


# ---------------------------------------------------------------------------
# EventBridge: user.reported
# ---------------------------------------------------------------------------

class TestOnUserReported:
    def test_sends_admin_alert(self, aws_resources):
        event = eb_event("kismet.report-service", "user.reported", {
            "reportId": "report-001",
            "reporterId": "user-123",
            "reportedUserId": "user-456",
            "reason": "harassment",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 200

    def test_all_report_reasons_handled(self, aws_resources):
        reasons = ["harassment", "inappropriate_content", "spam", "fake_profile", "other"]
        for reason in reasons:
            event = eb_event("kismet.report-service", "user.reported", {
                "reportId": f"report-{reason}",
                "reporterId": "user-123",
                "reportedUserId": "user-456",
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            result = lambda_function.handler(event, {})
            assert result["statusCode"] == 200, f"Failed for reason: {reason}"


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

class TestRouting:
    def test_unknown_route_returns_404(self, aws_resources):
        event = api_event("GET", "/unknown/path")
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 404

    def test_unhandled_event_type_returns_200(self, aws_resources):
        event = eb_event("kismet.other", "other.event", {"foo": "bar"})
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 200
