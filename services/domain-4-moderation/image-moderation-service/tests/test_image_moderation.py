import json
import os
import pytest
import boto3
from moto import mock_aws
from botocore.exceptions import ClientError
import importlib

# Env vars — must be set before importing the handler
os.environ["IMAGE_MODERATION_TABLE_NAME"] = "kismet-image-moderation-dev"
os.environ["PHOTOS_TABLE_NAME"] = "kismet-photos-dev"
os.environ["PHOTO_S3_BUCKET"] = "kismet-photos-test"
os.environ["EVENT_BUS_NAME"] = "kismet-events"
os.environ["MODERATION_FLAG_CONFIDENCE"] = "80.0"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_SECURITY_TOKEN"] = "testing"
os.environ["AWS_SESSION_TOKEN"] = "testing"

import lambda_function

TEST_PHOTO_BUCKET = os.environ["PHOTO_S3_BUCKET"]


def _eb_photo_detail(**extra):
    """Minimal photo.uploaded detail aligned with docs/system-design/event-schema.json."""
    base = {
        "photoId": "p1",
        "userId": "u1",
        "s3Key": "u1/p1.jpg",
        "s3Bucket": TEST_PHOTO_BUCKET,
    }
    base.update(extra)
    return base


# Fixtures
@pytest.fixture
def aws_resources():
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

        # Image moderation results — schema mirrors text moderation's GSI pattern
        dynamodb.create_table(
            TableName="kismet-image-moderation-dev",
            KeySchema=[
                {"AttributeName": "photoId", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "photoId", "AttributeType": "S"},
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

        # Photos table — mark_photo_rejected writes here
        dynamodb.create_table(
            TableName="kismet-photos-dev",
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

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="kismet-photos-test")

        boto3.client("events", region_name="us-east-1").create_event_bus(
            Name="kismet-events"
        )

        importlib.reload(lambda_function)

        yield {"dynamodb": dynamodb, "s3": s3}


def api_event(method, path, body=None, user_id="user-123"):
    return {
        "httpMethod": method,
        "path": path,
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {"authorizer": {"claims": {"sub": user_id}}},
    }


def admin_api_event(method, path, query_params=None):
    event = {
        "httpMethod": method,
        "path": path,
        "requestContext": {
            "authorizer": {"claims": {"cognito:groups": "admin"}}
        },
    }
    if query_params:
        event["queryStringParameters"] = query_params
    return event


def eb_event(source, detail_type, detail):
    return {
        "source": source,
        "detail-type": detail_type,
        "detail": detail,
    }


def upload_photo(aws_resources, s3_key, body=b"fake-image-data"):
    aws_resources["s3"].put_object(
        Bucket="kismet-photos-test", Key=s3_key, Body=body
    )


def seed_photo_record(aws_resources, user_id, photo_id):
    """Insert a photos-table row so mark_photo_rejected has an item to update."""
    aws_resources["dynamodb"].Table("kismet-photos-dev").put_item(
        Item={
            "PK": f"USER#{user_id}",
            "SK": f"PHOTO#{photo_id}",
            "photoId": photo_id,
            "userId": user_id,
            "status": "active",
        }
    )


# Moto does not stub Rekognition detect_moderation_labels responses, so only those
# calls are monkeypatched. DynamoDB, S3, and EventBridge go through moto.
def mock_rekognition_flagged(monkeypatch, label="Explicit Nudity", confidence=95.6):
    monkeypatch.setattr(
        lambda_function.rekognition,
        "detect_moderation_labels",
        lambda **kw: {"ModerationLabels": [{"Name": label, "Confidence": confidence}]},
    )


def mock_rekognition_clean(monkeypatch):
    monkeypatch.setattr(
        lambda_function.rekognition,
        "detect_moderation_labels",
        lambda **kw: {"ModerationLabels": []},
    )


# POST /moderate/image
class TestPostModerateImage:
    def test_missing_s3_key_returns_400(self, aws_resources):
        event = api_event("POST", "/moderate/image", body={
            "photoId": "p1", "userId": "u1",
        })
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 400
        assert json.loads(result["body"])["error"]["code"] == "VALIDATION_ERROR"

    def test_missing_photo_id_returns_400(self, aws_resources):
        event = api_event("POST", "/moderate/image", body={
            "s3Key": "u1/p1.jpg", "userId": "u1",
        })
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 400

    def test_missing_user_id_returns_400(self, aws_resources):
        event = api_event("POST", "/moderate/image", body={
            "s3Key": "u1/p1.jpg", "photoId": "p1",
        })
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 400

    def test_clean_image_returns_not_flagged(self, aws_resources, monkeypatch):
        upload_photo(aws_resources, "u1/p1.jpg")
        mock_rekognition_clean(monkeypatch)

        event = api_event("POST", "/moderate/image", body={
            "s3Key": "u1/p1.jpg", "photoId": "p1", "userId": "u1",
        })
        result = lambda_function.handler(event, {})

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["flagged"] is False
        assert body["photoId"] == "p1"
        assert body["confidence"] == 0.0

    def test_clean_image_written_to_dynamodb(self, aws_resources, monkeypatch):
        upload_photo(aws_resources, "u1/p1.jpg")
        mock_rekognition_clean(monkeypatch)

        lambda_function.handler(
            api_event("POST", "/moderate/image", body={
                "s3Key": "u1/p1.jpg", "photoId": "p1", "userId": "u1",
            }), {}
        )

        table = aws_resources["dynamodb"].Table("kismet-image-moderation-dev")
        item = table.get_item(Key={"photoId": "PHOTO#p1", "sk": "RESULT"}).get("Item")
        assert item is not None
        assert item["flagged"] is False

    def test_flagged_image_returns_flagged(self, aws_resources, monkeypatch):
        upload_photo(aws_resources, "u1/p1.jpg")
        seed_photo_record(aws_resources, "u1", "p1")
        mock_rekognition_flagged(monkeypatch)

        event = api_event("POST", "/moderate/image", body={
            "s3Key": "u1/p1.jpg", "photoId": "p1", "userId": "u1",
        })
        result = lambda_function.handler(event, {})

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["flagged"] is True
        assert body["confidence"] > 0

    def test_flagged_image_marks_photo_rejected_in_dynamodb(self, aws_resources, monkeypatch):
        upload_photo(aws_resources, "u1/p1.jpg")
        seed_photo_record(aws_resources, "u1", "p1")
        mock_rekognition_flagged(monkeypatch)

        lambda_function.handler(
            api_event("POST", "/moderate/image", body={
                "s3Key": "u1/p1.jpg", "photoId": "p1", "userId": "u1",
            }), {}
        )

        table = aws_resources["dynamodb"].Table("kismet-photos-dev")
        item = table.get_item(Key={"PK": "USER#u1", "SK": "PHOTO#p1"}).get("Item")
        assert item is not None
        assert item["status"] == "rejected"

    def test_image_not_found_returns_404(self, aws_resources, monkeypatch):
        monkeypatch.setattr(
            lambda_function.rekognition,
            "detect_moderation_labels",
            lambda **kw: (_ for _ in ()).throw(
                ClientError(
                    {"Error": {"Code": "InvalidS3ObjectException", "Message": "not found"}},
                    "DetectModerationLabels",
                )
            ),
        )
        event = api_event("POST", "/moderate/image", body={
            "s3Key": "missing.jpg", "photoId": "p_missing", "userId": "u1",
        })
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 404
        assert json.loads(result["body"])["error"]["code"] == "IMAGE_NOT_FOUND"

    def test_rekognition_error_returns_500(self, aws_resources, monkeypatch):
        monkeypatch.setattr(
            lambda_function.rekognition,
            "detect_moderation_labels",
            lambda **kw: (_ for _ in ()).throw(
                ClientError(
                    {"Error": {"Code": "ThrottlingException", "Message": "throttled"}},
                    "DetectModerationLabels",
                )
            ),
        )
        event = api_event("POST", "/moderate/image", body={
            "s3Key": "u1/p1.jpg", "photoId": "p1", "userId": "u1",
        })
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 500
        assert json.loads(result["body"])["error"]["code"] == "REKOGNITION_ERROR"

    def test_invalid_json_body_returns_400(self, aws_resources):
        event = {
            "httpMethod": "POST",
            "path": "/moderate/image",
            "body": '{"not":',
        }
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 400
        assert json.loads(result["body"])["error"]["code"] == "VALIDATION_ERROR"

    def test_http_api_v2_style_post_succeeds(self, aws_resources, monkeypatch):
        upload_photo(aws_resources, "u9/p9.jpg")
        mock_rekognition_clean(monkeypatch)
        event = {
            "requestContext": {"http": {"method": "POST", "path": "/moderate/image"}},
            "body": json.dumps({
                "s3Key": "u9/p9.jpg", "photoId": "p9", "userId": "u9",
            }),
        }
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 200
        assert json.loads(result["body"])["photoId"] == "p9"


# validate_post_body
class TestValidatePostBody:
    def test_valid_body_strips_whitespace(self):
        code, data = lambda_function.validate_post_body({
            "s3Key": " u1/p1.jpg ", "photoId": "p1", "userId": " u1 ",
        })
        assert code is None
        assert data["s3Key"] == "u1/p1.jpg"
        assert data["userId"] == "u1"

    def test_empty_s3_key_returns_error(self):
        code, data = lambda_function.validate_post_body({
            "s3Key": "", "photoId": "p", "userId": "u",
        })
        assert code == "VALIDATION_ERROR"
        assert data is None

    def test_missing_user_id_returns_error(self):
        code, data = lambda_function.validate_post_body({
            "s3Key": "k", "photoId": "p", "userId": "",
        })
        assert code == "VALIDATION_ERROR"
        assert data is None


# GET /moderate/image/history
class TestGetHistory:
    def test_admin_returns_200_with_expected_shape(self, aws_resources):
        result = lambda_function.handler(
            admin_api_event("GET", "/moderate/image/history"), {}
        )
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert "items" in body
        assert "count" in body

    def test_history_reflects_moderated_photos(self, aws_resources, monkeypatch):
        upload_photo(aws_resources, "u1/p1.jpg")
        mock_rekognition_clean(monkeypatch)
        lambda_function.handler(
            api_event("POST", "/moderate/image", body={
                "s3Key": "u1/p1.jpg", "photoId": "p1", "userId": "u1",
            }), {}
        )

        result = lambda_function.handler(
            admin_api_event("GET", "/moderate/image/history"), {}
        )
        body = json.loads(result["body"])
        assert body["count"] == 1
        assert body["items"][0]["photoId"] == "p1"

    def test_no_auth_returns_401(self, aws_resources):
        result = lambda_function.handler(
            {"httpMethod": "GET", "path": "/moderate/image/history"}, {}
        )
        assert result["statusCode"] == 401

    def test_non_admin_returns_403(self, aws_resources):
        event = {
            "httpMethod": "GET",
            "path": "/moderate/image/history",
            "requestContext": {"authorizer": {"claims": {"cognito:groups": "users"}}},
        }
        result = lambda_function.handler(event, {})
        assert result["statusCode"] == 403

    def test_invalid_cursor_returns_400(self, aws_resources):
        result = lambda_function.handler(
            admin_api_event("GET", "/moderate/image/history", query_params={"cursor": "!!!bad!!!"}),
            {},
        )
        assert result["statusCode"] == 400
        assert json.loads(result["body"])["error"]["code"] == "VALIDATION_ERROR"

    def test_dynamo_error_returns_500(self, aws_resources, monkeypatch):
        monkeypatch.setattr(
            lambda_function,
            "query_history_page",
            lambda **kw: (_ for _ in ()).throw(RuntimeError("dynamo down")),
        )
        result = lambda_function.handler(
            admin_api_event("GET", "/moderate/image/history"), {}
        )
        assert result["statusCode"] == 500
        assert json.loads(result["body"])["error"]["code"] == "INTERNAL_ERROR"


# EventBridge: photo.uploaded
class TestEventBridge:
    def test_photo_uploaded_writes_to_dynamodb(self, aws_resources, monkeypatch):
        upload_photo(aws_resources, "u1/p1.jpg")
        mock_rekognition_clean(monkeypatch)

        result = lambda_function.handler(
            eb_event("kismet.photo-service", "photo.uploaded", _eb_photo_detail()),
            {},
        )
        assert result["statusCode"] == 200

        table = aws_resources["dynamodb"].Table("kismet-image-moderation-dev")
        item = table.get_item(Key={"photoId": "PHOTO#p1", "sk": "RESULT"}).get("Item")
        assert item is not None

    def test_detail_as_json_string(self, aws_resources, monkeypatch):
        upload_photo(aws_resources, "u2/p2.png")
        mock_rekognition_clean(monkeypatch)

        result = lambda_function.handler(
            eb_event(
                "kismet.photo-service",
                "photo.uploaded",
                json.dumps(
                    {
                        "photoId": "p2",
                        "userId": "u2",
                        "s3Key": "u2/p2.png",
                        "s3Bucket": TEST_PHOTO_BUCKET,
                    }
                ),
            ),
            {},
        )
        assert result["statusCode"] == 200

    def test_missing_s3_bucket_skipped(self, aws_resources, monkeypatch):
        upload_photo(aws_resources, "u1/p1.jpg")
        mock_rekognition_clean(monkeypatch)
        result = lambda_function.handler(
            eb_event(
                "kismet.photo-service",
                "photo.uploaded",
                {"photoId": "p1", "userId": "u1", "s3Key": "u1/p1.jpg"},
            ),
            {},
        )
        assert result["statusCode"] == 200
        assert json.loads(result["body"]).get("reason") == "missing-s3-bucket"

    def test_detail_s3_bucket_used_for_rekognition(self, aws_resources, monkeypatch):
        alt = "kismet-photos-alt"
        aws_resources["s3"].create_bucket(Bucket=alt)
        aws_resources["s3"].put_object(Bucket=alt, Key="path/img.jpg", Body=b"x")
        captured: dict = {}

        def capture(**kw):
            captured.update(kw)
            return {"ModerationLabels": []}

        monkeypatch.setattr(
            lambda_function.rekognition, "detect_moderation_labels", capture
        )
        lambda_function.handler(
            eb_event(
                "kismet.photo-service",
                "photo.uploaded",
                {
                    "photoId": "px",
                    "userId": "ux",
                    "s3Key": "path/img.jpg",
                    "s3Bucket": alt,
                },
            ),
            {},
        )
        assert captured["Image"]["S3Object"]["Bucket"] == alt
        assert captured["Image"]["S3Object"]["Name"] == "path/img.jpg"

    def test_wrong_source_is_skipped(self, aws_resources):
        result = lambda_function.handler(
            eb_event(
                "other.service",
                "photo.uploaded",
                _eb_photo_detail(photoId="p", userId="u", s3Key="k"),
            ),
            {},
        )
        assert json.loads(result["body"]).get("skipped") is True

    def test_wrong_detail_type_is_skipped(self, aws_resources):
        result = lambda_function.handler(
            eb_event(
                "kismet.photo-service",
                "photo.deleted",
                _eb_photo_detail(photoId="p", userId="u", s3Key="k"),
            ),
            {},
        )
        assert json.loads(result["body"]).get("skipped") is True

    def test_flagged_photo_publishes_content_flagged_event(self, aws_resources, monkeypatch):
        upload_photo(aws_resources, "u1/p1.jpg")
        seed_photo_record(aws_resources, "u1", "p1")
        mock_rekognition_flagged(monkeypatch, label="Explicit Nudity", confidence=95.6)

        published = []
        original_put = lambda_function.events.put_events

        def capture(Entries):
            published.extend(Entries)
            return original_put(Entries=Entries)

        monkeypatch.setattr(lambda_function.events, "put_events", capture)

        lambda_function.handler(
            eb_event(
                "kismet.photo-service",
                "photo.uploaded",
                _eb_photo_detail(),
            ),
            {},
        )

        assert len(published) == 1
        detail = json.loads(published[0]["Detail"])
        assert detail["contentType"] == "image"
        assert detail["contentId"] == "p1"
        assert detail["userId"] == "u1"
        assert detail["reason"] == "explicit_nudity"
        assert detail["score"] == pytest.approx(0.956, abs=1e-3)


# Routing
class TestRouting:
    def test_unknown_path_returns_404(self, aws_resources):
        result = lambda_function.handler(
            {"httpMethod": "GET", "path": "/moderate/image/unknown"}, {}
        )
        assert result["statusCode"] == 404