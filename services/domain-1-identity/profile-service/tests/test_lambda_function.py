import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from lambda_function import handler


ENV = {
    "PROFILES_TABLE_NAME": "kismet-profiles-dev",
    "EVENT_BUS_NAME": "kismet-events",
}

AUTHED_CONTEXT = {
    "requestContext": {"authorizer": {"claims": {"sub": "user-123"}}}
}


class CreateProfileTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-456")

    def test_create_success(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb, \
             patch("lambda_function.events") as mock_events:

            mock_table = mock_dynamodb.Table.return_value
            mock_table.get_item.return_value = {}
            mock_table.put_item.return_value = {}
            mock_events.put_events.return_value = {"FailedEntryCount": 0, "Entries": [{"EventId": "e1"}]}

            event = {**make_event("/profiles", "POST", body={
                "name": "Alice",
                "bio": "Astronomy major",
                "gender": "female",
                "interestedIn": "male",
                "birthDate": "1999-05-15",
                "location": {"latitude": 42.3601, "longitude": -71.0589},
            }), **AUTHED_CONTEXT}
            response = handler(event, self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 201)
            self.assertEqual(payload["userId"], "user-123")
            self.assertEqual(payload["name"], "Alice")
            self.assertIn("createdAt", payload)
            mock_events.put_events.assert_called_once()

    def test_create_event_contains_full_payload(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb, \
             patch("lambda_function.events") as mock_events:

            mock_table = mock_dynamodb.Table.return_value
            mock_table.get_item.return_value = {}
            mock_table.put_item.return_value = {}
            mock_events.put_events.return_value = {"FailedEntryCount": 0, "Entries": [{"EventId": "e1"}]}

            event = {**make_event("/profiles", "POST", body={
                "name": "Alice",
                "bio": "Astronomy major",
                "gender": "female",
                "interestedIn": "male",
                "birthDate": "1999-05-15",
                "city": "Boston",
                "location": [42.36, -71.06],
            }), **AUTHED_CONTEXT}
            handler(event, self.context)

            call_args = mock_events.put_events.call_args
            detail = json.loads(call_args[1]["Entries"][0]["Detail"])
            self.assertEqual(call_args[1]["Entries"][0]["DetailType"], "profile.completed")
            self.assertEqual(detail["userId"], "user-123")
            self.assertEqual(detail["name"], "Alice")
            self.assertEqual(detail["birthDate"], "1999-05-15")
            self.assertEqual(detail["gender"], "female")
            self.assertEqual(detail["preferred_gender"], "male")
            self.assertEqual(detail["location_coordinates"], [42.36, -71.06])
            self.assertEqual(detail["city"], "Boston")
            self.assertEqual(detail["bio"], "Astronomy major")

    def test_create_duplicate_profile_returns_409(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb:

            mock_dynamodb.Table.return_value.get_item.return_value = {"Item": {"userId": "user-123"}}

            event = {**make_event("/profiles", "POST", body={
                "name": "Alice", "gender": "female", "interestedIn": "male",
                "birthDate": "1999-05-15", "location": {"latitude": 42.36, "longitude": -71.06},
            }), **AUTHED_CONTEXT}
            response = handler(event, self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 409)
            self.assertEqual(payload["code"], "CONFLICT")

    def test_create_missing_name_returns_400(self):
        with patch.dict("os.environ", ENV):
            event = {**make_event("/profiles", "POST", body={"bio": "no name"}), **AUTHED_CONTEXT}
            response = handler(event, self.context)
            self.assertEqual(response["statusCode"], 400)

    def test_create_unauthenticated_returns_401(self):
        with patch.dict("os.environ", ENV):
            response = handler(make_event("/profiles", "POST", body={"name": "Alice"}), self.context)
            self.assertEqual(response["statusCode"], 401)


class GetProfileTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-456")

    def test_get_success(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb:

            mock_dynamodb.Table.return_value.get_item.return_value = {"Item": {
                "PK": "USER#user-123",
                "SK": "PROFILE",
                "userId": "user-123",
                "name": "Alice",
                "bio": "Astronomy major",
                "updatedAt": "2026-04-01T12:00:00+00:00",
            }}

            response = handler(make_event("/profiles/user-123", "GET"), self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 200)
            self.assertEqual(payload["userId"], "user-123")
            self.assertEqual(payload["name"], "Alice")
            self.assertNotIn("PK", payload)
            self.assertNotIn("SK", payload)

    def test_get_not_found_returns_404(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb:

            mock_dynamodb.Table.return_value.get_item.return_value = {}

            response = handler(make_event("/profiles/nonexistent", "GET"), self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 404)
            self.assertEqual(payload["code"], "NOT_FOUND")

    def test_get_profile_route_extracts_user_id(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb:

            mock_dynamodb.Table.return_value.get_item.return_value = {"Item": {
                "PK": "USER#user-123", "SK": "PROFILE", "userId": "user-123", "name": "Alice",
            }}

            response = handler(make_event("/profiles/user-123", "GET"), self.context)
            self.assertEqual(response["statusCode"], 200)
            mock_dynamodb.Table.return_value.get_item.assert_called_once_with(
                Key={"PK": "USER#user-123", "SK": "PROFILE"}
            )


class UpdateProfileTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-456")

    def test_update_success(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb, \
             patch("lambda_function.events") as mock_events:

            mock_table = mock_dynamodb.Table.return_value
            # First get_item for existence check, second for event payload
            mock_table.get_item.side_effect = [
                {"Item": {"userId": "user-123"}},
                {"Item": {"userId": "user-123", "name": "Alice", "bio": "Updated bio", "gender": "female", "interestedIn": "male", "updatedAt": "2026-04-01T13:00:00+00:00"}},
            ]
            mock_table.update_item.return_value = {}
            mock_events.put_events.return_value = {"FailedEntryCount": 0, "Entries": [{"EventId": "e1"}]}

            event = {**make_event("/profiles/user-123", "PUT", body={"bio": "Updated bio", "interests": ["yoga"]}), **AUTHED_CONTEXT}
            response = handler(event, self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 200)
            self.assertEqual(payload["userId"], "user-123")
            self.assertEqual(payload["bio"], "Updated bio")
            self.assertIn("updatedAt", payload)

    def test_update_publishes_event(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb, \
             patch("lambda_function.events") as mock_events:

            mock_table = mock_dynamodb.Table.return_value
            mock_table.get_item.side_effect = [
                {"Item": {"userId": "user-123"}},
                {"Item": {"userId": "user-123", "name": "Alice", "bio": "New bio", "gender": "female", "interestedIn": "male", "birthDate": "1999-05-15", "city": "Boston"}},
            ]
            mock_table.update_item.return_value = {}
            mock_events.put_events.return_value = {"FailedEntryCount": 0, "Entries": [{"EventId": "e1"}]}

            event = {**make_event("/profiles/user-123", "PUT", body={"bio": "New bio"}), **AUTHED_CONTEXT}
            handler(event, self.context)

            mock_events.put_events.assert_called_once()
            call_args = mock_events.put_events.call_args
            self.assertEqual(call_args[1]["Entries"][0]["DetailType"], "profile.updated")
            detail = json.loads(call_args[1]["Entries"][0]["Detail"])
            self.assertEqual(detail["userId"], "user-123")
            self.assertEqual(detail["preferred_gender"], "male")
            self.assertEqual(detail["city"], "Boston")

    def test_update_city_and_avatar_url(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb, \
             patch("lambda_function.events") as mock_events:

            mock_table = mock_dynamodb.Table.return_value
            mock_table.get_item.side_effect = [
                {"Item": {"userId": "user-123"}},
                {"Item": {"userId": "user-123", "name": "Alice", "city": "NYC", "avatarUrl": "https://cdn/photo.jpg"}},
            ]
            mock_table.update_item.return_value = {}
            mock_events.put_events.return_value = {"FailedEntryCount": 0, "Entries": [{"EventId": "e1"}]}

            event = {**make_event("/profiles/user-123", "PUT", body={"city": "NYC", "avatarUrl": "https://cdn/photo.jpg"}), **AUTHED_CONTEXT}
            response = handler(event, self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 200)
            self.assertEqual(payload["city"], "NYC")
            self.assertEqual(payload["avatarUrl"], "https://cdn/photo.jpg")

    def test_update_another_users_profile_returns_403(self):
        with patch.dict("os.environ", ENV):
            event = {**make_event("/profiles/other-user", "PUT", body={"bio": "Hacked"}), **AUTHED_CONTEXT}
            response = handler(event, self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 403)
            self.assertEqual(payload["code"], "FORBIDDEN")

    def test_update_no_valid_fields_returns_400(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb:

            mock_dynamodb.Table.return_value.get_item.return_value = {"Item": {"userId": "user-123"}}

            event = {**make_event("/profiles/user-123", "PUT", body={"unknownField": "value"}), **AUTHED_CONTEXT}
            response = handler(event, self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 400)
            self.assertEqual(payload["code"], "VALIDATION_ERROR")

    def test_update_invalid_json_body_returns_400(self):
        event = {**make_event("/profiles/user-123", "PUT", raw_body='{"bio": "broken"'), **AUTHED_CONTEXT}
        response = handler(event, self.context)
        self.assertEqual(response["statusCode"], 400)


class DeleteProfileTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-456")

    def test_delete_success(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb:

            mock_table = mock_dynamodb.Table.return_value
            mock_table.get_item.return_value = {"Item": {"userId": "user-123"}}
            mock_table.delete_item.return_value = {}

            event = {**make_event("/profiles/user-123", "DELETE"), **AUTHED_CONTEXT}
            response = handler(event, self.context)
            payload = json.loads(response["body"])

            self.assertEqual(response["statusCode"], 200)
            self.assertEqual(payload["message"], "Profile deleted successfully")
            mock_table.delete_item.assert_called_once_with(Key={"PK": "USER#user-123", "SK": "PROFILE"})

    def test_delete_another_users_profile_returns_403(self):
        with patch.dict("os.environ", ENV):
            event = {**make_event("/profiles/other-user", "DELETE"), **AUTHED_CONTEXT}
            response = handler(event, self.context)
            self.assertEqual(response["statusCode"], 403)

    def test_delete_not_found_returns_404(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb:

            mock_dynamodb.Table.return_value.get_item.return_value = {}

            event = {**make_event("/profiles/user-123", "DELETE"), **AUTHED_CONTEXT}
            response = handler(event, self.context)
            self.assertEqual(response["statusCode"], 404)


class CorsTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-456")

    def test_response_includes_cors_headers(self):
        with patch.dict("os.environ", ENV), \
             patch("lambda_function.dynamodb") as mock_dynamodb:
            mock_dynamodb.Table.return_value.get_item.return_value = {"Item": {
                "PK": "USER#u1", "SK": "PROFILE", "userId": "u1", "name": "A",
            }}
            response = handler(make_event("/profiles/u1", "GET"), self.context)
            self.assertEqual(response["headers"]["Access-Control-Allow-Origin"], "*")
            self.assertIn("Authorization", response["headers"]["Access-Control-Allow-Headers"])


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-456")

    def test_unknown_route_returns_not_found(self):
        response = handler(make_event("/profiles/user-123/preferences", "GET"), self.context)
        payload = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 404)
        self.assertEqual(payload["code"], "NOT_FOUND")

    def test_invalid_json_body_returns_validation_error(self):
        event = {**make_event("/profiles/user-123", "PUT", raw_body='{"bio": "broken"'), **AUTHED_CONTEXT}
        response = handler(event, self.context)
        payload = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(payload["code"], "VALIDATION_ERROR")


class EventBridgeRoutingTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="req-456")

    def test_user_banned_event_uses_shared_error_handling(self):
        event = {
            "source": "kismet.report-service",
            "detail-type": "user.banned",
            "detail": {"userId": "user-123"},
        }

        with patch("lambda_function.handle_user_banned", side_effect=ValueError("boom")):
            response = handler(event, self.context)
            payload = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(payload["code"], "INTERNAL_ERROR")


def make_event(path, method, body=None, raw_body=None):
    payload = raw_body
    if payload is None and body is not None:
        payload = json.dumps(body)
    return {"path": path, "httpMethod": method, "body": payload}


if __name__ == "__main__":
    unittest.main()


