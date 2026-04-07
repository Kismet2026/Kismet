import json
import unittest
from types import SimpleNamespace

from lambda_function import lambda_handler


class PhotoServiceHandlerTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-photo-456")

    def test_upload_route_returns_not_implemented(self):
        event = make_event(
            path="/photos/upload",
            method="POST",
            body={"contentType": "image/jpeg", "filename": "profile.jpg"},
        )

        response = lambda_handler(event, self.context)
        payload = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 501)
        self.assertEqual(payload["operation"], "uploadPhoto")
        self.assertEqual(payload["requestId"], "req-photo-456")

    def test_get_route_extracts_user_id(self):
        event = make_event(path="/photos/user-123", method="GET")

        response = lambda_handler(event, self.context)
        payload = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 501)
        self.assertEqual(payload["operation"], "listPhotos")
        self.assertEqual(payload["pathParameters"]["userId"], "user-123")

    def test_delete_route_extracts_photo_id(self):
        event = make_event(path="/photos/photo-001", method="DELETE")

        response = lambda_handler(event, self.context)
        payload = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 501)
        self.assertEqual(payload["operation"], "deletePhoto")
        self.assertEqual(payload["pathParameters"]["photoId"], "photo-001")

    def test_set_primary_route_extracts_photo_id(self):
        event = make_event(path="/photos/photo-002/primary", method="PUT")

        response = lambda_handler(event, self.context)
        payload = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 501)
        self.assertEqual(payload["operation"], "setPrimaryPhoto")
        self.assertEqual(payload["pathParameters"]["photoId"], "photo-002")

    def test_invalid_json_body_returns_validation_error(self):
        event = make_event(
            path="/photos/upload",
            method="POST",
            raw_body='{"contentType": "image/jpeg"',
        )

        response = lambda_handler(event, self.context)
        payload = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(payload["code"], "VALIDATION_ERROR")

    def test_unknown_route_returns_not_found(self):
        event = make_event(path="/photos/photo-001/archive", method="PUT")

        response = lambda_handler(event, self.context)
        payload = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 404)
        self.assertEqual(payload["code"], "NOT_FOUND")


def make_event(path, method, body=None, raw_body=None):
    payload = raw_body
    if payload is None and body is not None:
        payload = json.dumps(body)

    return {
        "path": path,
        "httpMethod": method,
        "body": payload,
    }


if __name__ == "__main__":
    unittest.main()
