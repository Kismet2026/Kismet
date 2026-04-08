import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from lambda_function import lambda_handler


ENV = {
    "COGNITO_APP_CLIENT_ID": "test-client-id",
    "COGNITO_USER_POOL_ID": "us-east-1_TEST",
    "USERS_TABLE_NAME": "kismet-users-dev",
    "EVENT_BUS_NAME": "kismet-events",
}


class AuthServiceSignupTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-123")

    def test_signup_success(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.cognito") as mock_cognito, \
             patch("lambda_function.dynamodb") as mock_dynamodb, \
             patch("lambda_function.events") as mock_events:

            mock_cognito.sign_up.return_value = {"UserSub": "user-abc-123"}
            mock_dynamodb.Table.return_value.put_item.return_value = {}
            mock_events.put_events.return_value = {"FailedEntryCount": 0, "Entries": [{"EventId": "e1"}]}

            response = lambda_handler(make_event("/auth/signup", "POST", body={
                "email": "student@university.edu",
                "password": "SecureP@ss123",
                "birthDate": "1999-05-15",
            }), self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 201)
            self.assertEqual(payload["userId"], "user-abc-123")
            self.assertEqual(payload["email"], "student@university.edu")
            self.assertIn("createdAt", payload)

            mock_events.put_events.assert_called_once()
            call_detail = json.loads(mock_events.put_events.call_args[1]["Entries"][0]["Detail"])
            self.assertEqual(call_detail["userId"], "user-abc-123")

    def test_signup_duplicate_email_returns_conflict(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.cognito") as mock_cognito, \
             patch("lambda_function.dynamodb"), \
             patch("lambda_function.events"):

            mock_cognito.sign_up.side_effect = _cognito_error("UsernameExistsException")

            response = lambda_handler(make_event("/auth/signup", "POST", body={
                "email": "existing@university.edu",
                "password": "SecureP@ss123",
            }), self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 409)
            self.assertEqual(payload["code"], "CONFLICT")

    def test_signup_missing_email_returns_validation_error(self):
        with patch.dict("os.environ", ENV):
            response = lambda_handler(make_event("/auth/signup", "POST", body={"password": "SecureP@ss123"}), self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 400)
            self.assertEqual(payload["code"], "VALIDATION_ERROR")

    def test_signup_missing_password_returns_validation_error(self):
        with patch.dict("os.environ", ENV):
            response = lambda_handler(make_event("/auth/signup", "POST", body={"email": "a@university.edu"}), self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 400)
            self.assertEqual(payload["code"], "VALIDATION_ERROR")


class AuthServiceLoginTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-123")

    def test_login_success(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.cognito") as mock_cognito:

            mock_cognito.initiate_auth.return_value = {"AuthenticationResult": {
                "AccessToken": "access-xyz",
                "RefreshToken": "refresh-xyz",
                "IdToken": "id-xyz",
                "ExpiresIn": 3600,
            }}

            response = lambda_handler(make_event("/auth/login", "POST", body={
                "email": "student@university.edu",
                "password": "SecureP@ss123",
            }), self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 200)
            self.assertEqual(payload["accessToken"], "access-xyz")
            self.assertEqual(payload["refreshToken"], "refresh-xyz")
            self.assertEqual(payload["expiresIn"], 3600)

    def test_login_wrong_password_returns_unauthorized(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.cognito") as mock_cognito:

            mock_cognito.initiate_auth.side_effect = _cognito_error("NotAuthorizedException")

            response = lambda_handler(make_event("/auth/login", "POST", body={
                "email": "student@university.edu",
                "password": "wrong",
            }), self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 401)
            self.assertEqual(payload["code"], "UNAUTHORIZED")

    def test_login_missing_fields_returns_validation_error(self):
        with patch.dict("os.environ", ENV):
            response = lambda_handler(make_event("/auth/login", "POST", body={"email": "a@b.com"}), self.context)
            self.assertEqual(response["statusCode"], 400)


class AuthServiceRefreshTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-123")

    def test_refresh_success(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.cognito") as mock_cognito:

            mock_cognito.initiate_auth.return_value = {"AuthenticationResult": {
                "AccessToken": "new-access-xyz",
                "ExpiresIn": 3600,
            }}

            response = lambda_handler(make_event("/auth/refresh", "POST", body={"refreshToken": "valid-refresh"}), self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 200)
            self.assertEqual(payload["accessToken"], "new-access-xyz")
            self.assertNotIn("refreshToken", payload)

    def test_refresh_missing_token_returns_validation_error(self):
        with patch.dict("os.environ", ENV):
            response = lambda_handler(make_event("/auth/refresh", "POST", body={}), self.context)
            self.assertEqual(response["statusCode"], 400)


class AuthServiceLogoutTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-123")

    def test_logout_success(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.cognito") as mock_cognito:

            mock_cognito.revoke_token.return_value = {}

            response = lambda_handler(make_event("/auth/logout", "POST", body={"refreshToken": "valid-refresh"}), self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 200)
            self.assertEqual(payload["message"], "Successfully logged out")
            mock_cognito.revoke_token.assert_called_once_with(Token="valid-refresh", ClientId=ENV["COGNITO_APP_CLIENT_ID"])

    def test_logout_missing_token_returns_validation_error(self):
        with patch.dict("os.environ", ENV):
            response = lambda_handler(make_event("/auth/logout", "POST", body={}), self.context)
            self.assertEqual(response["statusCode"], 400)


class AuthServiceRoutingTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-123")

    def test_invalid_json_body_returns_validation_error(self):
        response = lambda_handler(make_event("/auth/login", "POST", raw_body='{"broken"'), self.context)
        payload = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(payload["code"], "VALIDATION_ERROR")

    def test_unknown_route_returns_not_found(self):
        response = lambda_handler(make_event("/auth/unknown", "GET"), self.context)
        payload = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 404)
        self.assertEqual(payload["code"], "NOT_FOUND")


def make_event(path, method, body=None, raw_body=None):
    payload = raw_body
    if payload is None and body is not None:
        payload = json.dumps(body)
    return {"path": path, "httpMethod": method, "body": payload}


def _cognito_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "CognitoOperation")


if __name__ == "__main__":
    unittest.main()
