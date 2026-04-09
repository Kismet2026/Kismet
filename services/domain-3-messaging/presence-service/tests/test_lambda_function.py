import importlib.util
import json
import os
from pathlib import Path
import sys
import time

import boto3
import pytest
from moto import mock_aws

os.environ["PRESENCE_TABLE"] = "kismet-presence"
os.environ["TYPING_TABLE"] = "kismet-typing"
os.environ["MATCHES_TABLE"] = "kismet-matches"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_SECURITY_TOKEN"] = "testing"
os.environ["AWS_SESSION_TOKEN"] = "testing"


def load_module():
    module_name = "presence_service_lambda_function"
    module_path = Path(__file__).resolve().parents[1] / "lambda_function.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


lambda_function = load_module()


@pytest.fixture
def aws_resources():
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

        dynamodb.create_table(
            TableName="kismet-presence",
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
            TableName="kismet-typing",
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
            TableName="kismet-matches",
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

        global lambda_function
        lambda_function = load_module()
        yield dynamodb


def api_event(method, path="/presence", body=None, user_id="user-123", path_params=None):
    claims = {"sub": user_id} if user_id else {}
    return {
        "httpMethod": method,
        "path": path,
        "pathParameters": path_params or {},
        "queryStringParameters": {},
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {"authorizer": {"claims": claims}},
    }


def seed_match(dynamodb, match_id="match-123", user_a="user-123", user_b="user-456"):
    dynamodb.Table("kismet-matches").put_item(Item={
        "PK": f"MATCH#{match_id}",
        "SK": "META",
        "matchId": match_id,
        "userAId": user_a,
        "userBId": user_b,
        "status": "matched",
    })


# ── Heartbeat ─────────────────────────────────────────────────────────────────

def test_heartbeat_marks_user_online(aws_resources):
    result = lambda_function.handler(
        api_event("POST", path="/presence/heartbeat"),
        {},
    )
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["userId"] == "user-123"
    assert body["status"] == "online"
    assert "expiresAt" in body

    item = aws_resources.Table("kismet-presence").get_item(
        Key={"PK": "USER#user-123", "SK": "STATUS"}
    ).get("Item")
    assert item is not None
    assert item["status"] == "online"


def test_heartbeat_requires_auth(aws_resources):
    result = lambda_function.handler(
        api_event("POST", path="/presence/heartbeat", user_id=None),
        {},
    )
    assert result["statusCode"] == 401


def test_heartbeat_sets_ttl(aws_resources):
    result = lambda_function.handler(
        api_event("POST", path="/presence/heartbeat"),
        {},
    )
    item = aws_resources.Table("kismet-presence").get_item(
        Key={"PK": "USER#user-123", "SK": "STATUS"}
    ).get("Item")
    # TTL should be ~60s from now
    assert item["ttl"] > int(time.time())
    assert item["ttl"] <= int(time.time()) + 61


# ── Get Presence ──────────────────────────────────────────────────────────────

def test_get_presence_online_user(aws_resources):
    # First send a heartbeat to make the user appear online
    lambda_function.handler(api_event("POST", path="/presence/heartbeat"), {})

    result = lambda_function.handler(
        api_event("GET", path="/presence/user-123", path_params={"userId": "user-123"}),
        {},
    )
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["status"] == "online"
    assert body["userId"] == "user-123"
    assert "lastSeen" in body


def test_get_presence_unknown_user_returns_404(aws_resources):
    result = lambda_function.handler(
        api_event("GET", path="/presence/nobody", path_params={"userId": "nobody"}),
        {},
    )
    assert result["statusCode"] == 404


def test_get_presence_requires_auth(aws_resources):
    result = lambda_function.handler(
        api_event("GET", path="/presence/user-123", path_params={"userId": "user-123"}, user_id=None),
        {},
    )
    assert result["statusCode"] == 401


# ── Typing Start ──────────────────────────────────────────────────────────────

def test_typing_start_success(aws_resources):
    seed_match(aws_resources)

    result = lambda_function.handler(
        api_event("POST", path="/presence/match-123/typing", path_params={"matchId": "match-123"}),
        {},
    )
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["typing"] is True
    assert body["userId"] == "user-123"
    assert body["matchId"] == "match-123"

    item = aws_resources.Table("kismet-typing").get_item(
        Key={"PK": "MATCH#match-123#USER#user-123", "SK": "TYPING"}
    ).get("Item")
    assert item is not None
    assert item["ttl"] <= int(time.time()) + 6


def test_typing_start_forbidden_non_participant(aws_resources):
    seed_match(aws_resources)

    result = lambda_function.handler(
        api_event(
            "POST",
            path="/presence/match-123/typing",
            path_params={"matchId": "match-123"},
            user_id="user-999",
        ),
        {},
    )
    assert result["statusCode"] == 403


def test_typing_start_match_not_found(aws_resources):
    result = lambda_function.handler(
        api_event("POST", path="/presence/bad-match/typing", path_params={"matchId": "bad-match"}),
        {},
    )
    assert result["statusCode"] == 404


# ── Typing Get ────────────────────────────────────────────────────────────────

def test_typing_get_shows_other_user_typing(aws_resources):
    seed_match(aws_resources)

    # user-456 starts typing
    lambda_function.handler(
        api_event(
            "POST",
            path="/presence/match-123/typing",
            path_params={"matchId": "match-123"},
            user_id="user-456",
        ),
        {},
    )

    # user-123 checks who is typing
    result = lambda_function.handler(
        api_event("GET", path="/presence/match-123/typing", path_params={"matchId": "match-123"}),
        {},
    )
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert len(body["typingUsers"]) == 1
    assert body["typingUsers"][0]["userId"] == "user-456"


def test_typing_get_empty_when_nobody_typing(aws_resources):
    seed_match(aws_resources)

    result = lambda_function.handler(
        api_event("GET", path="/presence/match-123/typing", path_params={"matchId": "match-123"}),
        {},
    )
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["typingUsers"] == []


def test_typing_get_does_not_show_own_typing(aws_resources):
    seed_match(aws_resources)

    # user-123 starts typing
    lambda_function.handler(
        api_event("POST", path="/presence/match-123/typing", path_params={"matchId": "match-123"}),
        {},
    )

    # user-123 checks — should NOT see themselves
    result = lambda_function.handler(
        api_event("GET", path="/presence/match-123/typing", path_params={"matchId": "match-123"}),
        {},
    )
    body = json.loads(result["body"])
    assert body["typingUsers"] == []


def test_typing_get_forbidden_non_participant(aws_resources):
    seed_match(aws_resources)

    result = lambda_function.handler(
        api_event(
            "GET",
            path="/presence/match-123/typing",
            path_params={"matchId": "match-123"},
            user_id="user-999",
        ),
        {},
    )
    assert result["statusCode"] == 403
