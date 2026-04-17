import json
import os
import importlib
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

os.environ["ADMIN_STATS_TABLE"] = "kismet-admin-stats"
os.environ["FLAGGED_CONTENT_TABLE"] = "kismet-flagged-content"
os.environ["PROFILES_TABLE"] = "kismet-profiles"
os.environ["MATCHES_TABLE"] = "kismet-matches"
os.environ["MESSAGES_TABLE"] = "kismet-messages"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_SECURITY_TOKEN"] = "testing"
os.environ["AWS_SESSION_TOKEN"] = "testing"

import lambda_function

PK_SK = [
    {"AttributeName": "PK", "KeyType": "HASH"},
    {"AttributeName": "SK", "KeyType": "RANGE"},
]
PK_SK_ATTR = [
    {"AttributeName": "PK", "AttributeType": "S"},
    {"AttributeName": "SK", "AttributeType": "S"},
]


@pytest.fixture
def aws():
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        for tbl in [
            "kismet-admin-stats",
            "kismet-flagged-content",
            "kismet-profiles",
            "kismet-matches",
            "kismet-messages",
        ]:
            dynamodb.create_table(
                TableName=tbl, KeySchema=PK_SK,
                AttributeDefinitions=PK_SK_ATTR, BillingMode="PAY_PER_REQUEST",
            )
        boto3.client("events", region_name="us-east-1").create_event_bus(Name="kismet-events")
        importlib.reload(lambda_function)
        yield dynamodb


def http_event(
    method,
    resource,
    body=None,
    path_params=None,
    query=None,
    admin_id="admin-1",
    email="admin@kismet.com",
    groups=None,
):
    claims = {"sub": admin_id}
    if email is not None:
        claims["email"] = email
    if groups is not None:
        claims["cognito:groups"] = groups

    return {
        "httpMethod": method,
        "resource": resource,
        "body": json.dumps(body) if body else None,
        "pathParameters": path_params,
        "queryStringParameters": query,
        "requestContext": {"authorizer": {"claims": claims}},
    }


def eb_event(detail_type, detail):
    return {"detail-type": detail_type, "detail": detail}


def _seed_stat(aws, name, value):
    aws.Table("kismet-admin-stats").put_item(
        Item={"PK": f"STAT#{name}", "SK": "LATEST", "value": value}
    )


def _seed_flagged(aws, content_id, **extra):
    aws.Table("kismet-flagged-content").put_item(
        Item={"PK": f"CONTENT#{content_id}", "SK": "META",
              "type": "text", "userId": "user-1", "reason": "toxicity",
              "confidence": 0, "status": "pending",
              "flaggedAt": "2026-04-01T12:00:00Z", **extra}
    )


def _seed_profile(aws, user_id, **extra):
    aws.Table("kismet-profiles").put_item(
        Item={"PK": f"USER#{user_id}", "SK": "PROFILE",
              "name": user_id, "status": "active", "reportCount": 0, **extra}
    )


def _seed_match(aws, match_id, matched_at, **extra):
    aws.Table("kismet-matches").put_item(
        Item={
            "PK": f"MATCH#{match_id}",
            "SK": "META",
            "matchId": match_id,
            "matchedAt": matched_at,
            "status": "active",
            **extra,
        }
    )


def _seed_message(aws, match_id, message_id, timestamp, **extra):
    aws.Table("kismet-messages").put_item(
        Item={
            "PK": f"CONV#{match_id}",
            "SK": f"MSG#{timestamp}#{message_id}",
            "messageId": message_id,
            "timestamp": timestamp,
            **extra,
        }
    )


# ── GET /admin/stats ─────────────────────────────────────────────────────────


class TestGetStats:
    def test_returns_stats(self, aws):
        _seed_profile(aws, "user-1")
        _seed_profile(aws, "user-2", status="banned")
        _seed_flagged(aws, "c-1")
        _seed_match(aws, "match-1", "2026-04-17T12:00:00Z")
        _seed_message(aws, "match-1", "msg-1", "2026-04-17T12:30:00Z")
        r = lambda_function.handler(http_event("GET", "/admin/stats"), {})
        assert r["statusCode"] == 200
        body = json.loads(r["body"])
        assert body["totalUsers"] == 2
        assert body["activeUsers"] == 1
        assert body["matchesToday"] == 1
        assert body["messagesToday"] == 1
        assert body["flaggedContentCount"] == 1
        assert "generatedAt" in body

    def test_defaults_to_zero(self, aws):
        r = lambda_function.handler(http_event("GET", "/admin/stats"), {})
        body = json.loads(r["body"])
        assert body["totalUsers"] == 0

    def test_non_admin_is_forbidden(self, aws):
        r = lambda_function.handler(
            http_event("GET", "/admin/stats", email="test1@kismet.com"),
            {},
        )
        assert r["statusCode"] == 403

    def test_admin_group_is_allowed(self, aws):
        r = lambda_function.handler(
            http_event("GET", "/admin/stats", email="test1@kismet.com", groups="admins"),
            {},
        )
        assert r["statusCode"] == 200


# ── GET /admin/flagged-content ───────────────────────────────────────────────


class TestGetFlagged:
    def test_returns_items(self, aws):
        _seed_flagged(aws, "c-1")
        _seed_flagged(aws, "c-2", type="image", imageUrl="https://cdn/img.jpg")
        r = lambda_function.handler(
            http_event("GET", "/admin/flagged-content"), {},
        )
        assert r["statusCode"] == 200
        body = json.loads(r["body"])
        assert body["count"] == 2

    def test_filter_by_type(self, aws):
        _seed_flagged(aws, "c-1", type="text")
        _seed_flagged(aws, "c-2", type="image")
        r = lambda_function.handler(
            http_event("GET", "/admin/flagged-content", query={"type": "text"}), {},
        )
        items = json.loads(r["body"])["items"]
        assert all(i["type"] == "text" for i in items)

    def test_invalid_type_returns_400(self, aws):
        r = lambda_function.handler(
            http_event("GET", "/admin/flagged-content", query={"type": "video"}), {},
        )
        assert r["statusCode"] == 400


# ── PUT /admin/flagged-content/{contentId}/resolve ───────────────────────────


class TestResolve:
    def test_approve(self, aws):
        _seed_flagged(aws, "c-1")
        r = lambda_function.handler(
            http_event("PUT", "/admin/flagged-content/{contentId}/resolve",
                       body={"action": "approve"}, path_params={"contentId": "c-1"}), {},
        )
        assert r["statusCode"] == 200
        assert json.loads(r["body"])["status"] == "resolved"

    def test_ban_user_bans_profile(self, aws):
        _seed_flagged(aws, "c-1", userId="user-bad")
        _seed_profile(aws, "user-bad")
        lambda_function.handler(
            http_event("PUT", "/admin/flagged-content/{contentId}/resolve",
                       body={"action": "ban_user"}, path_params={"contentId": "c-1"}), {},
        )
        profile = aws.Table("kismet-profiles").get_item(
            Key={"PK": "USER#user-bad", "SK": "PROFILE"}
        )["Item"]
        assert profile["status"] == "banned"

    def test_ban_user_returns_502_when_event_publish_fails(self, aws):
        _seed_flagged(aws, "c-1", userId="user-bad")
        _seed_profile(aws, "user-bad")
        with patch.object(lambda_function.events_client, "put_events") as put_events:
            put_events.return_value = {"FailedEntryCount": 1, "Entries": [{"ErrorCode": "InternalFailure"}]}
            r = lambda_function.handler(
                http_event("PUT", "/admin/flagged-content/{contentId}/resolve",
                           body={"action": "ban_user"}, path_params={"contentId": "c-1"}), {},
            )

        assert r["statusCode"] == 502

    def test_invalid_action_returns_400(self, aws):
        r = lambda_function.handler(
            http_event("PUT", "/admin/flagged-content/{contentId}/resolve",
                       body={"action": "delete"}, path_params={"contentId": "c-1"}), {},
        )
        assert r["statusCode"] == 400

    def test_not_found_returns_404(self, aws):
        r = lambda_function.handler(
            http_event("PUT", "/admin/flagged-content/{contentId}/resolve",
                       body={"action": "approve"}, path_params={"contentId": "missing"}), {},
        )
        assert r["statusCode"] == 404


# ── GET /admin/users ─────────────────────────────────────────────────────────


class TestGetUsers:
    def test_returns_users(self, aws):
        _seed_profile(aws, "user-1")
        _seed_profile(aws, "user-2")
        r = lambda_function.handler(http_event("GET", "/admin/users"), {})
        assert r["statusCode"] == 200
        assert json.loads(r["body"])["count"] == 2

    def test_search_filter(self, aws):
        _seed_profile(aws, "alice", name="alice")
        _seed_profile(aws, "bob", name="bob")
        r = lambda_function.handler(
            http_event("GET", "/admin/users", query={"search": "alice"}), {},
        )
        items = json.loads(r["body"])["items"]
        assert all("alice" in i["displayName"] for i in items)


# ── PUT /admin/users/{userId}/ban ────────────────────────────────────────────


class TestBanUser:
    def test_bans_active_user(self, aws):
        _seed_profile(aws, "user-1")
        r = lambda_function.handler(
            http_event("PUT", "/admin/users/{userId}/ban",
                       path_params={"userId": "user-1"}), {},
        )
        assert r["statusCode"] == 200
        assert json.loads(r["body"])["status"] == "banned"

    def test_already_banned_returns_409(self, aws):
        _seed_profile(aws, "user-1", status="banned")
        with patch.object(lambda_function.events_client, "put_events") as put_events:
            put_events.return_value = {"FailedEntryCount": 0, "Entries": [{"EventId": "evt-1"}]}
            r = lambda_function.handler(
                http_event("PUT", "/admin/users/{userId}/ban",
                           path_params={"userId": "user-1"}), {},
            )

        assert r["statusCode"] == 409
        put_events.assert_called_once()

    def test_not_found_returns_404(self, aws):
        r = lambda_function.handler(
            http_event("PUT", "/admin/users/{userId}/ban",
                       path_params={"userId": "ghost"}), {},
        )
        assert r["statusCode"] == 404

    def test_returns_502_when_event_publish_fails(self, aws):
        _seed_profile(aws, "user-1")
        with patch.object(lambda_function.events_client, "put_events") as put_events:
            put_events.return_value = {"FailedEntryCount": 1, "Entries": [{"ErrorCode": "InternalFailure"}]}
            r = lambda_function.handler(
                http_event("PUT", "/admin/users/{userId}/ban",
                           path_params={"userId": "user-1"}), {},
            )
        assert r["statusCode"] == 502


# ── PUT /admin/users/{userId}/unban ──────────────────────────────────────────


class TestUnbanUser:
    def test_unbans_banned_user(self, aws):
        _seed_profile(aws, "user-1", status="banned")
        r = lambda_function.handler(
            http_event("PUT", "/admin/users/{userId}/unban",
                       path_params={"userId": "user-1"}), {},
        )
        assert r["statusCode"] == 200
        assert json.loads(r["body"])["status"] == "active"

    def test_not_banned_returns_409(self, aws):
        _seed_profile(aws, "user-1")
        r = lambda_function.handler(
            http_event("PUT", "/admin/users/{userId}/unban",
                       path_params={"userId": "user-1"}), {},
        )
        assert r["statusCode"] == 409


# ── EventBridge: content.flagged ─────────────────────────────────────────────


class TestContentFlagged:
    def test_writes_to_flagged_table(self, aws):
        lambda_function.handler(
            eb_event("content.flagged", {
                "contentId": "msg-1", "contentType": "text",
                "userId": "user-1", "reason": "toxicity",
                "score": 0.9, "timestamp": "2026-04-01T12:00:00Z",
            }), {},
        )
        item = aws.Table("kismet-flagged-content").get_item(
            Key={"PK": "CONTENT#msg-1", "SK": "META"}
        )["Item"]
        assert item["status"] == "pending"
        assert item["type"] == "text"


# ── EventBridge: user.reported ───────────────────────────────────────────────


class TestUserReported:
    def test_increments_report_count(self, aws):
        _seed_profile(aws, "user-bad")
        lambda_function.handler(
            eb_event("user.reported", {
                "reportId": "r-1", "reporterId": "user-1",
                "reportedUserId": "user-bad", "reason": "harassment",
                "timestamp": "2026-04-01T12:00:00Z",
            }), {},
        )
        item = aws.Table("kismet-profiles").get_item(
            Key={"PK": "USER#user-bad", "SK": "PROFILE"}
        )["Item"]
        assert item["reportCount"] == 1


# ── Routing ───────────────────────────────────────────────────────────────────


class TestRouting:
    def test_unknown_returns_404(self, aws):
        r = lambda_function.handler(http_event("GET", "/admin/nope"), {})
        assert r["statusCode"] == 404
