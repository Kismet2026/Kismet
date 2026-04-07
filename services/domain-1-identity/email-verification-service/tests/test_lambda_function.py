import json
import unittest
from types import SimpleNamespace

from lambda_function import lambda_handler


class EmailVerificationServiceHandlerTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-email-123")

    def test_send_verification_route_returns_not_implemented(self):
        event = make_event(
            path="/verify/send",
            method="POST",
            body={"email": "student@university.edu"},
        )

        response = lambda_handler(event, self.context)
        payload = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 501)
        self.assertEqual(payload["operation"], "sendVerificationCode")
        self.assertEqual(payload["requestId"], "req-email-123")

    def test_confirm_verification_route_returns_not_implemented(self):
        event = make_event(
            path="/verify/confirm",
            method="POST",
            body={"email": "student@university.edu", "code": "123456"},
        )

        response = lambda_handler(event, self.context)
        payload = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 501)
        self.assertEqual(payload["operation"], "confirmVerificationCode")
        self.assertEqual(payload["receivedBody"]["code"], "123456")

    def test_invalid_json_body_returns_validation_error(self):
        event = make_event(
            path="/verify/send",
            method="POST",
            raw_body='{"email": "broken"',
        )

        response = lambda_handler(event, self.context)
        payload = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(payload["code"], "VALIDATION_ERROR")

    def test_status_route_returns_not_implemented(self):
        event = make_event(path="/verify/status", method="GET")

        response = lambda_handler(event, self.context)
        payload = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 501)
        self.assertEqual(payload["operation"], "getVerificationStatus")
        self.assertIsNone(payload["receivedBody"])

    def test_unknown_route_returns_not_found(self):
        event = make_event(path="/verify/resend", method="POST")

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
