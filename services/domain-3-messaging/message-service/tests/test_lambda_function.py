import importlib.util
import json
import os
from pathlib import Path
import sys

import boto3
import pytest
from moto import mock_aws

os.environ["TABLE_NAME"] = "kismet-messages"
os.environ["MATCHES_TABLE"] = "kismet-matches"
os.environ["EVENT_BUS_NAME"] = "kismet-events"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_SECURITY_TOKEN"] = "testing"
os.environ["AWS_SESSION_TOKEN"] = "testing"


def load_module():
    module_name = "message_service_lambda_function"
    module_path = Path(__file__).resolve().parents[1] / "lambda_function.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


lambda_function = load_module()


class FakeEventsClient:
    def __init__(self):
        self.entries = []

    def put_events(self, Entries):
        self.entries.extend(Entries)
        return {"FailedEntryCount": 0, "Entries": [{} for _ in Entries]}


@pytest.fixture
def aws_resources():
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

        dynamodb.create_table(
            TableName="kismet-messages",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "messageId", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "messageId-index",
                    "KeySchema": [{"AttributeName": "messageId", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                    "ProvisionedThroughput": {"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
                }
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
        fake_events = FakeEventsClient()
        lambda_function.events_client = fake_events

        yield dynamodb, fake_events


def api_event(method, path="/messages", body=None, user_id="user-123", path_params=None, query=None):
    claims = {"sub": user_id} if user_id else {}
    return {
        "httpMethod": method,
        "path": path,
        "pathParameters": path_params or {},
        "queryStringParameters": query,
        "body": json.dumps(body) if body is not None else "{}",
        "requestContext": {"authorizer": {"claims": claims}},
    }


def seed_match(dynamodb, match_id="match-123", user_a="user-123", user_b="user-456"):
    dynamodb.Table("kismet-matches").put_item(
        Item={
            "PK": f"MATCH#{match_id}",
            "SK": "META",
            "matchId": match_id,
            "userAId": user_a,
            "userBId": user_b,
            "status": "matched",
        }
    )


def seed_message(
    dynamodb,
    match_id="match-123",
    message_id="msg-001",
    sender_id="user-123",
    recipient_id="user-456",
    content="Hello",
    timestamp="2026-04-08T12:00:00+00:00",
    deleted=False,
):
    dynamodb.Table("kismet-messages").put_item(
        Item={
            "PK": f"CONV#{match_id}",
            "SK": f"MSG#{timestamp}#{message_id}",
            "messageId": message_id,
            "matchId": match_id,
            "senderId": sender_id,
            "recipientId": recipient_id,
            "content": content,
            "messageType": "text",
            "timestamp": timestamp,
            "deleted": deleted,
        }
    )


def test_send_requires_auth(aws_resources):
    result = lambda_function.handler(
        api_event("POST", body={"matchId": "match-123", "content": "Hi"}, user_id=None),
        {},
    )
    assert result["statusCode"] == 401


def test_send_validates_match_and_message_type(aws_resources):
    dynamodb, _ = aws_resources
    seed_match(dynamodb)

    forbidden = lambda_function.handler(
        api_event("POST", body={"matchId": "match-123", "content": "Hi"}, user_id="user-999"),
        {},
    )
    invalid_type = lambda_function.handler(
        api_event("POST", body={"matchId": "match-123", "content": "Hi", "messageType": "image"}),
        {},
    )
    missing_match = lambda_function.handler(
        api_event("POST", body={"matchId": "missing", "content": "Hi"}),
        {},
    )

    assert forbidden["statusCode"] == 403
    assert invalid_type["statusCode"] == 400
    assert missing_match["statusCode"] == 404


def test_send_persists_and_derives_recipient(aws_resources):
    dynamodb, fake_events = aws_resources
    seed_match(dynamodb)

    result = lambda_function.handler(
        api_event("POST", body={"matchId": "match-123", "content": "Hi there"}),
        {},
    )

    assert result["statusCode"] == 200
    items = dynamodb.Table("kismet-messages").query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("PK").eq("CONV#match-123")
    )["Items"]
    assert len(items) == 1
    assert items[0]["recipientId"] == "user-456"

    detail = json.loads(fake_events.entries[0]["Detail"])
    assert detail["recipientId"] == "user-456"


def test_get_messages_enforces_membership_and_returns_history(aws_resources):
    dynamodb, _ = aws_resources
    seed_match(dynamodb)
    seed_message(dynamodb, message_id="msg-001", timestamp="2026-04-08T12:00:00+00:00")
    seed_message(
        dynamodb,
        message_id="msg-002",
        sender_id="user-456",
        recipient_id="user-123",
        content="Reply",
        timestamp="2026-04-08T12:01:00+00:00",
    )

    unauthorized = lambda_function.handler(
        api_event("GET", path="/messages/match-123", user_id=None, path_params={"matchId": "match-123"}),
        {},
    )
    forbidden = lambda_function.handler(
        api_event("GET", path="/messages/match-123", user_id="user-999", path_params={"matchId": "match-123"}),
        {},
    )
    success = lambda_function.handler(
        api_event("GET", path="/messages/match-123", path_params={"matchId": "match-123"}),
        {},
    )

    assert unauthorized["statusCode"] == 401
    assert forbidden["statusCode"] == 403
    assert success["statusCode"] == 200
    body = json.loads(success["body"])
    assert [item["messageId"] for item in body["items"]] == ["msg-002", "msg-001"]


def test_delete_requires_sender(aws_resources):
    dynamodb, _ = aws_resources
    seed_message(dynamodb)

    unauthorized = lambda_function.handler(
        api_event("DELETE", path="/messages/msg-001", user_id=None, path_params={"messageId": "msg-001"}),
        {},
    )
    forbidden = lambda_function.handler(
        api_event("DELETE", path="/messages/msg-001", user_id="user-999", path_params={"messageId": "msg-001"}),
        {},
    )
    success = lambda_function.handler(
        api_event("DELETE", path="/messages/msg-001", path_params={"messageId": "msg-001"}),
        {},
    )

    assert unauthorized["statusCode"] == 401
    assert forbidden["statusCode"] == 403
    assert success["statusCode"] == 200
