import json
import os
import pytest
import boto3
from moto import mock_aws
import importlib

# Env vars — must be set before importing the handler
os.environ["TEXT_MODERATION_TABLE_NAME"] = "kismet-text-moderation-dev"
os.environ["EVENT_BUS_NAME"] = "kismet-events"
os.environ["TOXICITY_THRESHOLD"] = "0.65"
os.environ["CATEGORY_SCORE_FLOOR"] = "0.35"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_SECURITY_TOKEN"] = "testing"
os.environ["AWS_SESSION_TOKEN"] = "testing"

import lambda_function


# Fixtures
@pytest.fixture
def aws_resources():
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

        dynamodb.create_table(
            TableName="kismet-text-moderation-dev",
            KeySchema=[
                {"AttributeName": "contentId", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "contentId", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
                {"AttributeName": "gsi1pk", "AttributeType": "S"},
                {"AttributeName": "gsi1sk", "AttributeType": "N"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "gsi1",
                    "KeySchema": [
                        {"AttributeName": "gsi1pk", "KeyType": "HASH"},
                        {"AttributeName": "gsi1sk", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        boto3.client("events", region_name="us-east-1").create_event_bus(
            Name="kismet-events"
        )

        importlib.reload(lambda_function)

        yield dynamodb


def api_event(method, path, body=None, user_id="user-123"):
    return {
        "httpMethod": method,
        "path": path,
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {"authorizer": {"claims": {"sub": user_id}}},
    }


def eb_event(source, detail_type, detail):
    return {
        "source": source,
        "detail-type": detail_type,
        "detail": detail,
    }


def get_moderation_row(dynamodb, content_id):
    table = dynamodb.Table("kismet-text-moderation-dev")
    return table.get_item(
        Key={"contentId": f"CONTENT#{content_id}", "sk": "RESULT"}
    ).get("Item")


# moto doesn't support detect_toxic_content, so these two helpers
# monkeypatch only that one SDK call. DynamoDB and EventBridge stay on moto.
def mock_comprehend_score(monkeypatch, label="INSULT", score=0.1):
    monkeypatch.setattr(
        lambda_function.comprehend,
        "detect_toxic_content",
        lambda **kw: {"ResultList": [{"Labels": [{"Name": label, "Score": score}]}]},
    )


def mock_comprehend_flagged(monkeypatch, label="HATE_SPEECH", score=0.95):
    mock_comprehend_score(monkeypatch, label=label, score=score)


def mock_comprehend_clean(monkeypatch):
    mock_comprehend_score(monkeypatch, score=0.1)


# POST /moderate/text
class TestPostModerateText:
    def test_returns_moderation_result(self, aws_resources, monkeypatch):
        mock_comprehend_clean(monkeypatch)
        result = lambda_function.lambda_handler(
            api_event("POST", "/moderate/text", body={
                "content": "hi", "contentId": "m1", "contentType": "message",
            }), {}
        )
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["contentId"] == "m1"
        assert body["contentType"] == "message"
        assert "flagged" in body
        assert "toxicityScore" in body
        assert "timestamp" in body

    def test_result_written_to_dynamodb(self, aws_resources, monkeypatch):
        mock_comprehend_clean(monkeypatch)
        lambda_function.lambda_handler(
            api_event("POST", "/moderate/text", body={
                "content": "hi", "contentId": "m1", "contentType": "message",
            }), {}
        )
        item = get_moderation_row(aws_resources, "m1")
        assert item is not None
        assert item["contentType"] == "message"
        assert item["flagged"] is False

    def test_optional_user_id_stored(self, aws_resources, monkeypatch):
        mock_comprehend_clean(monkeypatch)
        lambda_function.lambda_handler(
            api_event("POST", "/moderate/text", body={
                "content": "hi", "contentId": "m2", "contentType": "message", "userId": "u-99",
            }), {}
        )
        item = get_moderation_row(aws_resources, "m2")
        assert item["userId"] == "u-99"

    def test_empty_content_returns_400(self, aws_resources):
        result = lambda_function.lambda_handler(
            api_event("POST", "/moderate/text", body={
                "content": "", "contentId": "m1", "contentType": "message",
            }), {}
        )
        assert result["statusCode"] == 400
        assert json.loads(result["body"])["error"]["code"] == "VALIDATION_ERROR"

    def test_content_exceeds_max_bytes_returns_400(self, aws_resources):
        result = lambda_function.lambda_handler(
            api_event("POST", "/moderate/text", body={
                "content": "a" * 4501, "contentId": "m1", "contentType": "message",
            }), {}
        )
        assert result["statusCode"] == 400
        assert json.loads(result["body"])["error"]["code"] == "VALIDATION_ERROR"

    def test_comprehend_error_returns_500(self, aws_resources, monkeypatch):
        from botocore.exceptions import ClientError
        monkeypatch.setattr(
            lambda_function.comprehend,
            "detect_toxic_content",
            lambda **kw: (_ for _ in ()).throw(
                ClientError(
                    {"Error": {"Code": "ValidationException", "Message": "bad"}},
                    "DetectToxicContent",
                )
            ),
        )
        result = lambda_function.lambda_handler(
            api_event("POST", "/moderate/text", body={
                "content": "x", "contentId": "m1", "contentType": "message",
            }), {}
        )
        assert result["statusCode"] == 500
        assert json.loads(result["body"])["error"]["code"] == "COMPREHEND_ERROR"

    def test_invalid_json_body_returns_400(self, aws_resources):
        event = {
            "httpMethod": "POST",
            "path": "/moderate/text",
            "body": '{"broken":',
        }
        result = lambda_function.lambda_handler(event, {})
        assert result["statusCode"] == 400
        assert json.loads(result["body"])["error"]["code"] == "VALIDATION_ERROR"

    def test_missing_content_id_returns_400(self, aws_resources):
        result = lambda_function.lambda_handler(
            api_event("POST", "/moderate/text", body={
                "content": "hi", "contentType": "message",
            }), {}
        )
        assert result["statusCode"] == 400
        assert json.loads(result["body"])["error"]["code"] == "VALIDATION_ERROR"

    def test_http_api_v2_style_post_succeeds(self, aws_resources, monkeypatch):
        mock_comprehend_clean(monkeypatch)
        event = {
            "requestContext": {"http": {"method": "POST", "path": "/moderate/text"}},
            "body": json.dumps({
                "content": "ok", "contentId": "api2", "contentType": "message",
            }),
        }
        result = lambda_function.lambda_handler(event, {})
        assert result["statusCode"] == 200
        assert json.loads(result["body"])["contentId"] == "api2"


# validate_post_body
class TestValidatePostBody:
    def test_valid_message_strips_whitespace(self):
        code, data = lambda_function.validate_post_body({
            "content": " hi ", "contentId": "m1", "contentType": "message",
        })
        assert code is None
        assert data["content"] == "hi"
        assert data["userId"] is None

    def test_valid_bio_with_user_id(self):
        code, data = lambda_function.validate_post_body({
            "content": "bio text", "contentId": "user-1",
            "contentType": "bio", "userId": "user-1",
        })
        assert code is None
        assert data["userId"] == "user-1"

    def test_invalid_content_type_returns_error(self):
        code, data = lambda_function.validate_post_body({
            "content": "a", "contentId": "1", "contentType": "image",
        })
        assert code == "VALIDATION_ERROR"
        assert data is None

    def test_overlong_content_counts_utf8_bytes(self):
        code, _ = lambda_function.validate_post_body({
            "content": "x" * 4501, "contentId": "m1", "contentType": "message",
        })
        assert code == "VALIDATION_ERROR"

    def test_content_at_byte_limit_is_valid(self):
        code, _ = lambda_function.validate_post_body({
            "content": "x" * 4500, "contentId": "m1", "contentType": "message",
        })
        assert code is None


# GET /moderate/text/history
class TestGetHistory:
    def test_admin_returns_200_with_expected_shape(self, aws_resources):
        result = lambda_function.lambda_handler(
            {
                "httpMethod": "GET",
                "path": "/moderate/text/history",
                "requestContext": {"authorizer": {"claims": {"cognito:groups": "admin"}}},
            }, {}
        )
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["items"] == []
        assert body["nextCursor"] is None
        assert body["count"] == 0

    def test_history_reflects_moderated_content(self, aws_resources, monkeypatch):
        mock_comprehend_clean(monkeypatch)
        lambda_function.lambda_handler(
            api_event("POST", "/moderate/text", body={
                "content": "hello", "contentId": "m1", "contentType": "message",
            }), {}
        )
        result = lambda_function.lambda_handler(
            {
                "httpMethod": "GET",
                "path": "/moderate/text/history",
                "requestContext": {"authorizer": {"claims": {"cognito:groups": "admin"}}},
            }, {}
        )
        body = json.loads(result["body"])
        assert body["count"] == 1
        assert body["items"][0]["contentId"] == "m1"

    def test_invalid_cursor_returns_400(self, aws_resources):
        result = lambda_function.lambda_handler(
            {
                "httpMethod": "GET",
                "path": "/moderate/text/history",
                "queryStringParameters": {"cursor": "not-valid"},
                "requestContext": {"authorizer": {"claims": {"cognito:groups": "admin"}}},
            }, {}
        )
        assert result["statusCode"] == 400
        assert json.loads(result["body"])["error"]["code"] == "VALIDATION_ERROR"

    def test_dynamo_error_returns_500(self, aws_resources, monkeypatch):
        # testing the HTTP layer's error handling, not DynamoDB itself
        monkeypatch.setattr(
            lambda_function, "query_history_page",
            lambda **kw: (_ for _ in ()).throw(RuntimeError("dynamo down")),
        )
        result = lambda_function.lambda_handler(
            {
                "httpMethod": "GET",
                "path": "/moderate/text/history",
                "requestContext": {"authorizer": {"claims": {"cognito:groups": "admin"}}},
            }, {}
        )
        assert result["statusCode"] == 500
        assert json.loads(result["body"])["error"]["code"] == "INTERNAL_ERROR"

    def test_no_auth_returns_401(self, aws_resources):
        result = lambda_function.lambda_handler(
            {"httpMethod": "GET", "path": "/moderate/text/history"}, {}
        )
        assert result["statusCode"] == 401

    def test_non_admin_returns_403(self, aws_resources):
        result = lambda_function.lambda_handler(
            {
                "httpMethod": "GET",
                "path": "/moderate/text/history",
                "requestContext": {"authorizer": {"claims": {"cognito:groups": "users"}}},
            }, {}
        )
        assert result["statusCode"] == 403


# Routing
class TestRouting:
    def test_unknown_path_returns_404(self, aws_resources):
        result = lambda_function.lambda_handler(
            {"httpMethod": "GET", "path": "/moderate/text/unknown"}, {}
        )
        assert result["statusCode"] == 404


# EventBridge: message.sent
class TestEventBridge:
    def test_message_sent_writes_to_dynamodb(self, aws_resources, monkeypatch):
        mock_comprehend_clean(monkeypatch)
        result = lambda_function.lambda_handler(
            eb_event("kismet.message-service", "message.sent", {
                "messageId": "m1", "senderId": "u1", "content": "hello",
            }), {}
        )
        assert result["statusCode"] == 200
        item = get_moderation_row(aws_resources, "m1")
        assert item is not None
        assert item["userId"] == "u1"

    def test_detail_as_json_string(self, aws_resources, monkeypatch):
        mock_comprehend_clean(monkeypatch)
        result = lambda_function.lambda_handler(
            eb_event(
                "kismet.message-service",
                "message.sent",
                json.dumps({"messageId": "m2", "senderId": "u2", "content": "yo"}),
            ), {}
        )
        assert result["statusCode"] == 200
        assert get_moderation_row(aws_resources, "m2") is not None

    def test_no_sender_id_still_writes_row(self, aws_resources, monkeypatch):
        mock_comprehend_clean(monkeypatch)
        lambda_function.lambda_handler(
            eb_event("kismet.message-service", "message.sent", {
                "messageId": "m3", "content": "hello",
            }), {}
        )
        item = get_moderation_row(aws_resources, "m3")
        assert item is not None
        assert "userId" not in item

    def test_wrong_source_is_skipped(self, aws_resources):
        result = lambda_function.lambda_handler(
            eb_event("other.service", "message.sent", {
                "messageId": "m1", "content": "x",
            }), {}
        )
        assert json.loads(result["body"]).get("skipped") is True

    def test_wrong_detail_type_is_skipped(self, aws_resources):
        result = lambda_function.lambda_handler(
            eb_event("kismet.message-service", "message.delivered", {
                "messageId": "m1", "content": "x",
            }), {}
        )
        assert json.loads(result["body"]).get("skipped") is True


# run_moderation — core logic
class TestRunModeration:
    def test_clean_message_not_flagged_no_event(self, aws_resources, monkeypatch):
        mock_comprehend_clean(monkeypatch)
        published = []
        monkeypatch.setattr(
            lambda_function.events, "put_events",
            lambda Entries: published.extend(Entries),
        )
        out = lambda_function.run_moderation(
            content="hi", content_type="message", content_id="c1", user_id="u1",
        )
        assert out["flagged"] is False
        assert get_moderation_row(aws_resources, "c1") is not None
        assert len(published) == 0

    def test_flagged_message_with_user_publishes_event(self, aws_resources, monkeypatch):
        mock_comprehend_flagged(monkeypatch)
        published = []
        original_put = lambda_function.events.put_events

        def capture(Entries):
            published.extend(Entries)
            return original_put(Entries=Entries)

        monkeypatch.setattr(lambda_function.events, "put_events", capture)

        lambda_function.run_moderation(
            content="bad", content_type="message", content_id="c2", user_id="u2",
        )
        assert len(published) == 1
        detail = json.loads(published[0]["Detail"])
        assert detail["userId"] == "u2"
        assert detail["contentId"] == "c2"
        assert detail["contentType"] == "text"
        assert detail["reason"] == "toxicity_detected"
        assert detail["score"] == pytest.approx(0.95, abs=1e-3)

    def test_flagged_message_without_user_skips_event(self, aws_resources, monkeypatch):
        mock_comprehend_flagged(monkeypatch)
        published = []
        monkeypatch.setattr(
            lambda_function.events, "put_events",
            lambda Entries: published.extend(Entries),
        )
        out = lambda_function.run_moderation(
            content="toxic", content_type="message", content_id="msg-only", user_id=None,
        )
        assert out["flagged"] is True
        assert get_moderation_row(aws_resources, "msg-only") is not None
        assert len(published) == 0

    def test_flagged_bio_without_user_falls_back_to_content_id(self, aws_resources, monkeypatch):
        mock_comprehend_flagged(monkeypatch)
        published = []
        original_put = lambda_function.events.put_events

        def capture(Entries):
            published.extend(Entries)
            return original_put(Entries=Entries)

        monkeypatch.setattr(lambda_function.events, "put_events", capture)

        lambda_function.run_moderation(
            content="bad bio", content_type="bio", content_id="user-42", user_id=None,
        )
        assert len(published) == 1
        assert json.loads(published[0]["Detail"])["userId"] == "user-42"