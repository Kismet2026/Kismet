import importlib.util
import json
import os
from io import BytesIO
from pathlib import Path
import sys

import boto3
import pytest
from moto import mock_aws

os.environ["CONNECTIONS_TABLE"] = "kismet-connections"
os.environ["MATCHES_TABLE"] = "kismet-matches"
os.environ["MESSAGE_SERVICE_FUNCTION_NAME"] = "kismet-message-service"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_SECURITY_TOKEN"] = "testing"
os.environ["AWS_SESSION_TOKEN"] = "testing"


def load_module():
    module_name = "chat_gateway_send_message"
    module_path = Path(__file__).resolve().parents[1] / "send_message.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


send_message = load_module()


class FakeLambdaClient:
    def __init__(self, response=None):
        self.calls = []
        self.response = response or {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "messageId": "msg-123",
                    "matchId": "match-123",
                    "senderId": "user-123",
                    "content": "Hi",
                    "messageType": "text",
                    "timestamp": "2026-04-08T12:00:00+00:00",
                }
            ),
        }

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        return {"Payload": BytesIO(json.dumps(self.response).encode())}


class FakeApiGatewayClient:
    class Exceptions:
        class GoneException(Exception):
            pass

    def __init__(self):
        self.sent = []
        self.exceptions = self.Exceptions()

    def post_to_connection(self, ConnectionId, Data):
        self.sent.append({"ConnectionId": ConnectionId, "Data": Data})


@pytest.fixture
def aws_resources():
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

        dynamodb.create_table(
            TableName="kismet-connections",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "matchId", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "matchId-index",
                    "KeySchema": [{"AttributeName": "matchId", "KeyType": "HASH"}],
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

        global send_message
        send_message = load_module()
        send_message.lambda_client = FakeLambdaClient()
        fake_apigw = FakeApiGatewayClient()
        original_boto3_client = send_message.boto3.client

        def fake_client(name, *args, **kwargs):
            if name == "apigatewaymanagementapi":
                return fake_apigw
            return original_boto3_client(name, *args, **kwargs)

        send_message.boto3.client = fake_client

        yield dynamodb, send_message.lambda_client, fake_apigw


def seed_connection(dynamodb, connection_id="conn-123", user_id="user-123", match_id="match-123"):
    dynamodb.Table("kismet-connections").put_item(
        Item={
            "PK": f"CONN#{connection_id}",
            "SK": "META",
            "connectionId": connection_id,
            "userId": user_id,
            "matchId": match_id,
        }
    )


def seed_match(dynamodb, match_id="match-123", user_a="user-123", user_b="user-456"):
    dynamodb.Table("kismet-matches").put_item(
        Item={
            "PK": f"MATCH#{match_id}",
            "SK": "META",
            "matchId": match_id,
            "userAId": user_a,
            "userBId": user_b,
        }
    )


def ws_event(connection_id="conn-123", body=None):
    return {
        "requestContext": {
            "connectionId": connection_id,
            "domainName": "example.com",
            "stage": "dev",
        },
        "body": json.dumps(body or {"content": "Hi"}),
    }


def test_send_message_requires_registered_connection(aws_resources):
    result = send_message.handler(ws_event(), {})
    assert result["statusCode"] == 401


def test_send_message_validates_membership_and_type(aws_resources):
    dynamodb, _, _ = aws_resources
    seed_connection(dynamodb)
    seed_match(dynamodb)

    invalid_type = send_message.handler(ws_event(body={"content": "Hi", "messageType": "image"}), {})

    dynamodb.Table("kismet-connections").put_item(
        Item={
            "PK": "CONN#conn-999",
            "SK": "META",
            "connectionId": "conn-999",
            "userId": "user-999",
            "matchId": "match-123",
        }
    )
    forbidden = send_message.handler(ws_event(connection_id="conn-999"), {})

    assert invalid_type["statusCode"] == 400
    assert forbidden["statusCode"] == 403


def test_send_message_invokes_message_service_and_broadcasts(aws_resources):
    dynamodb, fake_lambda, fake_apigw = aws_resources
    seed_connection(dynamodb, connection_id="conn-sender", user_id="user-123")
    seed_connection(dynamodb, connection_id="conn-recipient", user_id="user-456")
    seed_match(dynamodb)

    result = send_message.handler(ws_event(connection_id="conn-sender"), {})

    assert result["statusCode"] == 200
    assert len(fake_lambda.calls) == 1
    invocation_event = json.loads(fake_lambda.calls[0]["Payload"].decode())
    assert invocation_event["path"] == "/messages"
    assert json.loads(invocation_event["body"])["matchId"] == "match-123"
    assert len(fake_apigw.sent) == 1
    assert fake_apigw.sent[0]["ConnectionId"] == "conn-recipient"
