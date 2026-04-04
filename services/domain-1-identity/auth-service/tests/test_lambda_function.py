import json
import unittest
from types import SimpleNamespace

from lambda_function import lambda_handler


class AuthServiceHandlerTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-123")

    def test_signup_route_returns_not_implemented(self):
        event = make_event(
            path="/auth/signup",
            method="POST",
            body={
                "email": "student@university.edu",
                "password": "SecureP@ss123",
                "birthDate": "1999-05-15",
            },
        )

        response = lambda_handler(event, self.context)
        payload = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 501)
        self.assertEqual(payload["operation"], "signup")
        self.assertEqual(payload["requestId"], "req-123")

    def test_invalid_json_body_returns_validation_error(self):
        event = make_event(
            path="/auth/login",
            method="POST",
            raw_body='{"email": "broken"',
        )

        response = lambda_handler(event, self.context)
        payload = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(payload["code"], "VALIDATION_ERROR")

    def test_unknown_route_returns_not_found(self):
        event = make_event(path="/auth/unknown", method="GET")

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
