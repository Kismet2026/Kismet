import json
import os
import importlib

import boto3
import pytest
from moto import mock_aws

os.environ["ACTIVITY_LOG_TABLE"] = "kismet-activity-log"
os.environ["KINESIS_STREAM_NAME"] = "kismet-activity-stream"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_SECURITY_TOKEN"] = "testing"
os.environ["AWS_SESSION_TOKEN"] = "testing"

import lambda_function


@pytest.fixture
def aws(monkeypatch):
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        dynamodb.create_table(
            TableName="kismet-activity-log",
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

        kinesis = boto3.client("kinesis", region_name="us-east-1")
        kinesis.create_stream(StreamName="kismet-activity-stream", ShardCount=1)

        importlib.reload(lambda_function)
        yield dynamodb


def _items(dynamodb):
    return dynamodb.Table("kismet-activity-log").scan()["Items"]


def eb_event(detail_type, detail, source="kismet.test-service"):
    return {"source": source, "detail-type": detail_type, "detail": detail}


def http_event(method, resource, body=None, query=None):
    return {
        "httpMethod": method,
        "resource": resource,
        "body": json.dumps(body) if body else None,
        "queryStringParameters": query,
    }


# ── EventBridge ───────────────────────────────────────────────────────────────


class TestEventBridgeSwipe:
    def test_writes_to_dynamodb(self, aws):
        r = lambda_function.handler(
            eb_event("swipe.created", {
                "userId": "user-1", "targetUserId": "user-2",
                "action": "like", "timestamp": "2026-04-01T12:00:00Z",
            }), {},
        )
        assert r["statusCode"] == 200
        items = _items(aws)
        assert len(items) == 1
        assert items[0]["PK"] == "USER#user-1"
        assert items[0]["eventType"] == "swipe.created"


class TestEventBridgeMatch:
    def test_writes_for_both_users(self, aws):
        lambda_function.handler(
            eb_event("match.created", {
                "matchId": "m-1", "userIds": ["user-1", "user-2"],
                "timestamp": "2026-04-01T12:00:00Z",
            }), {},
        )
        pks = {i["PK"] for i in _items(aws)}
        assert pks == {"USER#user-1", "USER#user-2"}

    def test_kinesis_failure_prevents_partial_dynamodb_writes(self, aws, monkeypatch):
        original_write = lambda_function._write_to_kinesis
        call_count = {"n": 0}

        def flaky_write(record, partition_key):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("kinesis down")
            return original_write(record, partition_key)

        monkeypatch.setattr(lambda_function, "_write_to_kinesis", flaky_write)

        with pytest.raises(RuntimeError):
            lambda_function.handler(
                eb_event("match.created", {
                    "matchId": "m-1", "userIds": ["user-1", "user-2"],
                    "timestamp": "2026-04-01T12:00:00Z",
                }), {},
            )

        assert _items(aws) == []


class TestEventBridgeMessage:
    def test_extracts_sender_id(self, aws):
        lambda_function.handler(
            eb_event("message.sent", {
                "messageId": "msg-1", "senderId": "user-sender",
                "content": "hi", "timestamp": "2026-04-01T12:00:00Z",
            }), {},
        )
        assert _items(aws)[0]["PK"] == "USER#user-sender"


class TestEventBridgeReport:
    def test_extracts_reporter_id(self, aws):
        lambda_function.handler(
            eb_event("user.reported", {
                "reportId": "r-1", "reporterId": "user-reporter",
                "reportedUserId": "user-bad", "reason": "spam",
                "timestamp": "2026-04-01T12:00:00Z",
            }), {},
        )
        assert _items(aws)[0]["PK"] == "USER#user-reporter"


class TestEventBridgeGeneric:
    def test_user_created(self, aws):
        lambda_function.handler(
            eb_event("user.created", {
                "userId": "user-new", "email": "a@b.edu",
                "timestamp": "2026-04-01T10:00:00Z",
            }), {},
        )
        assert _items(aws)[0]["eventType"] == "user.created"

    def test_content_flagged(self, aws):
        lambda_function.handler(
            eb_event("content.flagged", {
                "contentId": "c-1", "contentType": "text",
                "userId": "user-1", "reason": "toxicity",
                "score": 0.9, "timestamp": "2026-04-01T12:00:00Z",
            }), {},
        )
        assert _items(aws)[0]["eventType"] == "content.flagged"


# ── POST /analytics/log ──────────────────────────────────────────────────────


class TestPostLog:
    def test_valid_request(self, aws):
        r = lambda_function.handler(
            http_event("POST", "/analytics/log", body={
                "eventType": "swipe.created",
                "eventData": {"action": "like"},
                "userId": "user-1",
            }), {},
        )
        assert r["statusCode"] == 200
        body = json.loads(r["body"])
        assert body["status"] == "accepted"
        assert body["eventType"] == "swipe.created"
        assert "logId" in body

    def test_missing_event_type_returns_400(self, aws):
        r = lambda_function.handler(
            http_event("POST", "/analytics/log", body={
                "eventData": {}, "userId": "user-1",
            }), {},
        )
        assert r["statusCode"] == 400
        assert json.loads(r["body"])["error"] == "VALIDATION_ERROR"

    def test_missing_user_id_returns_400(self, aws):
        r = lambda_function.handler(
            http_event("POST", "/analytics/log", body={
                "eventType": "x", "eventData": {},
            }), {},
        )
        assert r["statusCode"] == 400

    def test_invalid_json_returns_400(self, aws):
        r = lambda_function.handler({
            "httpMethod": "POST", "resource": "/analytics/log",
            "body": "{broken", "queryStringParameters": None,
        }, {})
        assert r["statusCode"] == 400

    def test_persists_to_dynamodb(self, aws):
        lambda_function.handler(
            http_event("POST", "/analytics/log", body={
                "eventType": "test.event",
                "eventData": {"k": "v"},
                "userId": "user-1",
            }), {},
        )
        assert len(_items(aws)) == 1

    def test_returns_502_when_kinesis_write_fails(self, aws, monkeypatch):
        monkeypatch.setattr(
            lambda_function,
            "_write_to_kinesis",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("kinesis down")),
        )
        r = lambda_function.handler(
            http_event("POST", "/analytics/log", body={
                "eventType": "test.event",
                "eventData": {"k": "v"},
                "userId": "user-1",
            }), {},
        )
        assert r["statusCode"] == 502
        body = json.loads(r["body"])
        assert body["error"] == "KINESIS_WRITE_FAILED"
        assert _items(aws) == []


# ── GET /analytics/log/recent ────────────────────────────────────────────────


class TestGetRecent:
    def _seed(self, aws):
        for uid, et in [("user-1", "swipe.created"), ("user-1", "message.sent"), ("user-2", "swipe.created")]:
            lambda_function.handler(
                http_event("POST", "/analytics/log", body={
                    "eventType": et, "eventData": {}, "userId": uid,
                }), {},
            )

    def test_returns_all(self, aws):
        self._seed(aws)
        r = lambda_function.handler(http_event("GET", "/analytics/log/recent"), {})
        assert json.loads(r["body"])["count"] == 3

    def test_filter_by_user(self, aws):
        self._seed(aws)
        r = lambda_function.handler(
            http_event("GET", "/analytics/log/recent", query={"userId": "user-1"}), {},
        )
        body = json.loads(r["body"])
        assert body["count"] == 2
        assert all(i["userId"] == "user-1" for i in body["items"])

    def test_filter_by_event_type(self, aws):
        self._seed(aws)
        r = lambda_function.handler(
            http_event("GET", "/analytics/log/recent", query={"eventType": "message.sent"}), {},
        )
        assert all(i["eventType"] == "message.sent" for i in json.loads(r["body"])["items"])

    def test_limit(self, aws):
        self._seed(aws)
        r = lambda_function.handler(
            http_event("GET", "/analytics/log/recent", query={"limit": "1"}), {},
        )
        assert json.loads(r["body"])["count"] == 1


# ── Routing ───────────────────────────────────────────────────────────────────


class TestRouting:
    def test_unknown_route_returns_404(self, aws):
        r = lambda_function.handler(http_event("GET", "/unknown"), {})
        assert r["statusCode"] == 404
