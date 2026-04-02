import json
import unittest
from types import SimpleNamespace

from lambda_function import lambda_handler


class ProfileServiceHandlerTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-456")

    def test_create_profile_route_returns_not_implemented(self):
        event = make_event(
            path="/profiles",
            method="POST",
            body={
                "name": "Alice",
                "gender": "female",
                "interestedIn": "male",
                "birthDate": "1999-05-15",
                "location": {"latitude": 42.3601, "longitude": -71.0589},
            },
        )

        response = lambda_handler(event, self.context)
        payload = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 501)
        self.assertEqual(payload["operation"], "createProfile")
        self.assertEqual(payload["requestId"], "req-456")

    def test_get_profile_route_extracts_user_id(self):
        event = make_event(path="/profiles/user-123", method="GET")

        response = lambda_handler(event, self.context)
        payload = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 501)
        self.assertEqual(payload["operation"], "getProfile")
        self.assertEqual(payload["pathParameters"]["userId"], "user-123")

    def test_invalid_json_body_returns_validation_error(self):
        event = make_event(
            path="/profiles/user-123",
            method="PUT",
            raw_body='{"bio": "broken"',
        )

        response = lambda_handler(event, self.context)
        payload = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(payload["code"], "VALIDATION_ERROR")

    def test_unknown_route_returns_not_found(self):
        event = make_event(path="/profiles/user-123/preferences", method="GET")

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
