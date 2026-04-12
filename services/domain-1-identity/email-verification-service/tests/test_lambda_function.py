import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from botocore.exceptions import ClientError

from lambda_function import handler


ENV = {
    "COGNITO_USER_POOL_ID": "us-east-1_TEST",
    "VERIFICATIONS_TABLE_NAME": "kismet-verifications-dev",
    "SES_SOURCE_EMAIL": "noreply@kismet.edu",
}


class SendVerificationCodeTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-email-123")

    def test_send_success(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb, \
             patch("lambda_function.ses") as mock_ses:

            mock_dynamodb.Table.return_value.put_item.return_value = {}
            mock_ses.send_email.return_value = {"MessageId": "msg-001"}

            response = handler(make_event("/verify/send", "POST", body={"email": "student@university.edu"}), self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 200)
            self.assertEqual(payload["email"], "student@university.edu")
            self.assertEqual(payload["expiresIn"], 600)
            mock_ses.send_email.assert_called_once()

    def test_send_non_edu_email_rejected(self):
        with patch.dict("os.environ", ENV):
            response = handler(make_event("/verify/send", "POST", body={"email": "user@gmail.com"}), self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 400)
            self.assertEqual(payload["code"], "VALIDATION_ERROR")

    def test_send_missing_email_returns_validation_error(self):
        with patch.dict("os.environ", ENV):
            response = handler(make_event("/verify/send", "POST", body={}), self.context)
            self.assertEqual(response["statusCode"], 400)

    def test_send_normalizes_email_to_lowercase(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb, \
             patch("lambda_function.ses") as mock_ses:

            mock_dynamodb.Table.return_value.put_item.return_value = {}
            mock_ses.send_email.return_value = {"MessageId": "msg-001"}

            response = handler(make_event("/verify/send", "POST", body={"email": "Student@University.EDU"}), self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 200)
            self.assertEqual(payload["email"], "student@university.edu")


class ConfirmVerificationCodeTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-email-123")

    def test_confirm_success(self):
        future_ttl = int(time.time()) + 600
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb, \
             patch("lambda_function.cognito") as mock_cognito:

            mock_table = mock_dynamodb.Table.return_value
            mock_table.get_item.return_value = {"Item": {
                "PK": "EMAIL#student@university.edu",
                "SK": "LATEST",
                "email": "student@university.edu",
                "code": "123456",
                "verified": False,
                "ttl": future_ttl,
            }}
            mock_table.update_item.return_value = {}
            mock_cognito.admin_update_user_attributes.return_value = {}

            response = handler(make_event("/verify/confirm", "POST", body={
                "email": "student@university.edu",
                "code": "123456",
            }), self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 200)
            self.assertTrue(payload["verified"])
            mock_table.update_item.assert_called_once()

    def test_confirm_wrong_code_returns_validation_error(self):
        future_ttl = int(time.time()) + 600
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb:

            mock_dynamodb.Table.return_value.get_item.return_value = {"Item": {
                "email": "student@university.edu",
                "code": "123456",
                "verified": False,
                "ttl": future_ttl,
            }}

            response = handler(make_event("/verify/confirm", "POST", body={
                "email": "student@university.edu",
                "code": "000000",
            }), self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 400)
            self.assertEqual(payload["code"], "VALIDATION_ERROR")

    def test_confirm_expired_code_returns_410(self):
        past_ttl = int(time.time()) - 1
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb:

            mock_dynamodb.Table.return_value.get_item.return_value = {"Item": {
                "email": "student@university.edu",
                "code": "123456",
                "verified": False,
                "ttl": past_ttl,
            }}

            response = handler(make_event("/verify/confirm", "POST", body={
                "email": "student@university.edu",
                "code": "123456",
            }), self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 410)
            self.assertEqual(payload["code"], "EXPIRED")

    def test_confirm_no_record_returns_404(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb:

            mock_dynamodb.Table.return_value.get_item.return_value = {}

            response = handler(make_event("/verify/confirm", "POST", body={
                "email": "unknown@university.edu",
                "code": "123456",
            }), self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 404)

    def test_confirm_already_verified_returns_200(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb:

            mock_dynamodb.Table.return_value.get_item.return_value = {"Item": {
                "email": "student@university.edu",
                "verified": True,
                "verifiedAt": "2026-04-01T12:00:00+00:00",
            }}

            response = handler(make_event("/verify/confirm", "POST", body={
                "email": "student@university.edu",
                "code": "123456",
            }), self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 200)
            self.assertTrue(payload["verified"])


class GetVerificationStatusTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-email-123")

    def test_status_from_jwt_claims(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb:

            mock_dynamodb.Table.return_value.get_item.return_value = {"Item": {
                "email": "student@university.edu",
                "verified": True,
                "verifiedAt": "2026-04-01T12:05:00+00:00",
            }}

            event = make_event("/verify/status", "GET")
            event["requestContext"] = {"authorizer": {"claims": {"email": "student@university.edu"}}}

            response = handler(event, self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 200)
            self.assertTrue(payload["verified"])
            self.assertEqual(payload["verifiedAt"], "2026-04-01T12:05:00+00:00")

    def test_status_from_query_param(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb:

            mock_dynamodb.Table.return_value.get_item.return_value = {}

            event = make_event("/verify/status", "GET")
            event["queryStringParameters"] = {"email": "student@university.edu"}

            response = handler(event, self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 200)
            self.assertFalse(payload["verified"])

    def test_status_no_auth_returns_401(self):
        with patch.dict("os.environ", ENV):
            response = handler(make_event("/verify/status", "GET"), self.context)
            self.assertEqual(response["statusCode"], 401)


class CorsTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-email-123")

    def test_response_includes_cors_headers(self):
        with patch.dict("os.environ", ENV):
            response = handler(make_event("/verify/send", "POST", body={}), self.context)
            self.assertEqual(response["headers"]["Access-Control-Allow-Origin"], "*")
            self.assertIn("Authorization", response["headers"]["Access-Control-Allow-Headers"])


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-email-123")

    def test_invalid_json_body_returns_validation_error(self):
        response = handler(make_event("/verify/send", "POST", raw_body='{"broken"'), self.context)
        payload = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(payload["code"], "VALIDATION_ERROR")

    def test_unknown_route_returns_not_found(self):
        response = handler(make_event("/verify/resend", "POST"), self.context)
        payload = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 404)
        self.assertEqual(payload["code"], "NOT_FOUND")


def make_event(path, method, body=None, raw_body=None):
    payload = raw_body
    if payload is None and body is not None:
        payload = json.dumps(body)
    return {"path": path, "httpMethod": method, "body": payload}


if __name__ == "__main__":
    unittest.main()


