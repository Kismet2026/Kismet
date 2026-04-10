import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from lambda_function import handler


ENV = {
    "PHOTOS_TABLE_NAME": "kismet-photos-dev",
    "PHOTOS_BUCKET_NAME": "kismet-photos-dev",
    "PHOTOS_CDN_BASE_URL": "https://photos.kismet.dev",
    "EVENT_BUS_NAME": "kismet-events",
}

AUTHED_EVENT_CONTEXT = {
    "requestContext": {"authorizer": {"claims": {"sub": "user-123"}}}
}


class UploadPhotoTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-photo-456")

    def test_upload_success(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb, \
             patch("lambda_function.s3") as mock_s3, \
             patch("lambda_function.events") as mock_events:

            mock_table = mock_dynamodb.Table.return_value
            mock_table.query.return_value = {"Count": 0, "Items": []}
            mock_table.put_item.return_value = {}
            mock_s3.generate_presigned_url.return_value = "https://s3.example.com/presigned"
            mock_events.put_events.return_value = {"FailedEntryCount": 0, "Entries": [{"EventId": "e1"}]}

            event = {**make_event("/photos/upload", "POST", body={"contentType": "image/jpeg", "filename": "profile.jpg"}), **AUTHED_EVENT_CONTEXT}
            response = handler(event, self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 200)
            self.assertIn("photoId", payload)
            self.assertEqual(payload["uploadUrl"], "https://s3.example.com/presigned")
            self.assertEqual(payload["expiresIn"], 300)

    def test_upload_unauthenticated_returns_401(self):
        with patch.dict("os.environ", ENV):
            response = handler(make_event("/photos/upload", "POST", body={"contentType": "image/jpeg"}), self.context)
            self.assertEqual(response["statusCode"], 401)

    def test_upload_missing_content_type_returns_400(self):
        with patch.dict("os.environ", ENV):
            event = {**make_event("/photos/upload", "POST", body={}), **AUTHED_EVENT_CONTEXT}
            response = handler(event, self.context)
            self.assertEqual(response["statusCode"], 400)

    def test_upload_invalid_content_type_returns_400(self):
        with patch.dict("os.environ", ENV):
            event = {**make_event("/photos/upload", "POST", body={"contentType": "image/gif"}), **AUTHED_EVENT_CONTEXT}
            response = handler(event, self.context)
            payload = json.loads(response["body"])
            self.assertEqual(response["statusCode"], 400)
            self.assertEqual(payload["code"], "VALIDATION_ERROR")

    def test_upload_exceeds_limit_returns_422(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb:

            mock_dynamodb.Table.return_value.query.return_value = {"Count": 6, "Items": []}

            event = {**make_event("/photos/upload", "POST", body={"contentType": "image/jpeg"}), **AUTHED_EVENT_CONTEXT}
            response = handler(event, self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 422)
            self.assertEqual(payload["code"], "LIMIT_EXCEEDED")


class ListPhotosTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-photo-456")

    def test_list_returns_photos_with_cdn_urls(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.PHOTOS_CDN_BASE_URL", ENV["PHOTOS_CDN_BASE_URL"]), \
             patch("lambda_function.dynamodb") as mock_dynamodb:

            mock_dynamodb.Table.return_value.query.return_value = {"Items": [
                {"photoId": "photo-001", "s3Key": "user-123/photo-001.jpg", "isPrimary": True, "uploadedAt": "2026-04-01T12:00:00+00:00"},
                {"photoId": "photo-002", "s3Key": "user-123/photo-002.jpg", "isPrimary": False, "uploadedAt": "2026-04-01T11:00:00+00:00"},
            ]}

            response = handler(make_event("/users/user-123/photos", "GET"), self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 200)
            self.assertEqual(payload["count"], 2)
            self.assertEqual(payload["photos"][0]["url"], "https://photos.kismet.dev/user-123/photo-001.jpg")
            self.assertTrue(payload["photos"][0]["isPrimary"])

    def test_list_empty_returns_empty_array(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb:

            mock_dynamodb.Table.return_value.query.return_value = {"Items": []}

            response = handler(make_event("/users/user-999/photos", "GET"), self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 200)
            self.assertEqual(payload["count"], 0)
            self.assertEqual(payload["photos"], [])

    def test_get_route_extracts_user_id(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb:

            mock_dynamodb.Table.return_value.query.return_value = {"Items": []}

            response = handler(make_event("/users/user-123/photos", "GET"), self.context)
            self.assertEqual(response["statusCode"], 200)
            mock_dynamodb.Table.return_value.query.assert_called_once()


class DeletePhotoTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-photo-456")

    def test_delete_success(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.PHOTOS_BUCKET_NAME", ENV["PHOTOS_BUCKET_NAME"]), \
             patch("lambda_function.dynamodb") as mock_dynamodb, \
             patch("lambda_function.s3") as mock_s3:

            mock_table = mock_dynamodb.Table.return_value
            mock_table.get_item.return_value = {"Item": {
                "photoId": "photo-001",
                "s3Key": "user-123/photo-001.jpg",
                "isPrimary": False,
            }}
            mock_table.delete_item.return_value = {}
            mock_s3.delete_object.return_value = {}

            event = {**make_event("/photos/photo-001", "DELETE"), **AUTHED_EVENT_CONTEXT}
            response = handler(event, self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 200)
            self.assertEqual(payload["message"], "Photo deleted successfully")
            mock_s3.delete_object.assert_called_once_with(Bucket=ENV["PHOTOS_BUCKET_NAME"], Key="user-123/photo-001.jpg")

    def test_delete_not_found_returns_404(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb:

            mock_dynamodb.Table.return_value.get_item.return_value = {}

            event = {**make_event("/photos/nonexistent", "DELETE"), **AUTHED_EVENT_CONTEXT}
            response = handler(event, self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 404)

    def test_delete_unauthenticated_returns_401(self):
        with patch.dict("os.environ", ENV):
            response = handler(make_event("/photos/photo-001", "DELETE"), self.context)
            self.assertEqual(response["statusCode"], 401)


class SetPrimaryPhotoTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-photo-456")

    def test_set_primary_success(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb:

            mock_table = mock_dynamodb.Table.return_value
            mock_table.get_item.return_value = {"Item": {"photoId": "photo-002", "isPrimary": False}}
            mock_table.query.return_value = {"Items": [
                {"photoId": "photo-001", "isPrimary": True},
            ]}
            mock_table.update_item.return_value = {}

            event = {**make_event("/photos/photo-002/primary", "PUT"), **AUTHED_EVENT_CONTEXT}
            response = handler(event, self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 200)
            self.assertEqual(payload["photoId"], "photo-002")
            self.assertTrue(payload["isPrimary"])

    def test_set_primary_not_found_returns_404(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb:

            mock_dynamodb.Table.return_value.get_item.return_value = {}

            event = {**make_event("/photos/nonexistent/primary", "PUT"), **AUTHED_EVENT_CONTEXT}
            response = handler(event, self.context)

            self.assertEqual(response["statusCode"], 404)

    def test_set_primary_unauthenticated_returns_401(self):
        with patch.dict("os.environ", ENV):
            response = handler(make_event("/photos/photo-002/primary", "PUT"), self.context)
            self.assertEqual(response["statusCode"], 401)

    def test_set_primary_route_extracts_photo_id(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb:

            mock_table = mock_dynamodb.Table.return_value
            mock_table.get_item.return_value = {"Item": {"photoId": "photo-002"}}
            mock_table.query.return_value = {"Items": []}
            mock_table.update_item.return_value = {}

            event = {**make_event("/photos/photo-002/primary", "PUT"), **AUTHED_EVENT_CONTEXT}
            response = handler(event, self.context)
            payload = json.loads(response["body"])

            self.assertEqual(payload["photoId"], "photo-002")


class CorsTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-photo-456")

    def test_response_includes_cors_headers(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb:
            mock_dynamodb.Table.return_value.query.return_value = {"Items": []}
            response = handler(make_event("/users/user-123/photos", "GET"), self.context)
            self.assertEqual(response["headers"]["Access-Control-Allow-Origin"], "*")
            self.assertIn("Authorization", response["headers"]["Access-Control-Allow-Headers"])


class PhotoEventTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-photo-456")

    def test_upload_event_includes_cdn_url(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.PHOTOS_CDN_BASE_URL", "https://photos.kismet.dev"), \
             patch("lambda_function.dynamodb") as mock_dynamodb, \
             patch("lambda_function.s3") as mock_s3, \
             patch("lambda_function.events") as mock_events:

            mock_table = mock_dynamodb.Table.return_value
            mock_table.query.return_value = {"Count": 0, "Items": []}
            mock_table.put_item.return_value = {}
            mock_s3.generate_presigned_url.return_value = "https://s3.example.com/presigned"
            mock_events.put_events.return_value = {"FailedEntryCount": 0, "Entries": [{"EventId": "e1"}]}

            event = {**make_event("/photos/upload", "POST", body={"contentType": "image/jpeg"}), **AUTHED_EVENT_CONTEXT}
            handler(event, self.context)

            call_args = mock_events.put_events.call_args
            detail = json.loads(call_args[1]["Entries"][0]["Detail"])
            self.assertIn("cdnUrl", detail)
            self.assertTrue(detail["cdnUrl"].startswith("https://photos.kismet.dev/"))
            self.assertIn("isPrimary", detail)


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-photo-456")

    def test_invalid_json_body_returns_validation_error(self):
        event = {**make_event("/photos/upload", "POST", raw_body='{"broken"'), **AUTHED_EVENT_CONTEXT}
        response = handler(event, self.context)
        payload = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(payload["code"], "VALIDATION_ERROR")

    def test_unknown_route_returns_not_found(self):
        response = handler(make_event("/photos/photo-001/archive", "PUT"), self.context)
        payload = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 404)
        self.assertEqual(payload["code"], "NOT_FOUND")

    def test_old_list_route_returns_not_found(self):
        response = handler(make_event("/photos/user-123", "GET"), self.context)
        payload = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 404)
        self.assertEqual(payload["code"], "NOT_FOUND")

    def test_get_upload_path_returns_not_found(self):
        # GET /photos/upload matches the /photos/upload branch first, which only
        # allows POST — so non-POST methods correctly return 404
        response = handler(make_event("/photos/upload", "GET"), self.context)
        self.assertEqual(response["statusCode"], 404)


def make_event(path, method, body=None, raw_body=None):
    payload = raw_body
    if payload is None and body is not None:
        payload = json.dumps(body)
    return {"path": path, "httpMethod": method, "body": payload}


if __name__ == "__main__":
    unittest.main()


