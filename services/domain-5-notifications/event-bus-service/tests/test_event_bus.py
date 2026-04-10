"""Unit tests for Event Bus Service Lambda handlers."""

import json
import os
import unittest
from unittest.mock import MagicMock, patch

# Set env vars before importing the module
os.environ["EVENT_LOG_TABLE"] = "kismet-event-log-test"
os.environ["EVENT_BUS_NAME"] = "kismet-events"
os.environ["ENVIRONMENT"] = "test"


class TestCatchAllHandler(unittest.TestCase):
    """Tests for the catch_all_handler (EventBridge → DynamoDB logger)."""

    @patch("lambda_function.table")
    def test_logs_event_to_dynamodb(self, mock_table):
        from lambda_function import catch_all_handler

        event = {
            "id": "evt-test-001",
            "source": "kismet.match-service",
            "detail-type": "match.created",
            "detail": {
                "matchId": "match-789",
                "userIds": ["user-123", "user-456"],
            },
            "time": "2026-04-01T12:00:00Z",
        }

        result = catch_all_handler(event, None)

        assert result["statusCode"] == 200
        mock_table.put_item.assert_called_once()
        call_args = mock_table.put_item.call_args[1]["Item"]
        assert call_args["PK"] == "EVENT#evt-test-001"
        assert call_args["SK"] == "META"
        assert call_args["source"] == "kismet.match-service"
        assert call_args["detailType"] == "match.created"
        assert call_args["status"] == "delivered"

    @patch("lambda_function.table")
    def test_generates_uuid_when_no_id(self, mock_table):
        from lambda_function import catch_all_handler

        event = {
            "source": "kismet.auth-service",
            "detail-type": "user.created",
            "detail": {"userId": "user-123"},
        }

        result = catch_all_handler(event, None)

        assert result["statusCode"] == 200
        call_args = mock_table.put_item.call_args[1]["Item"]
        assert call_args["PK"].startswith("EVENT#")


class TestAdminApiHandler(unittest.TestCase):
    """Tests for the admin_api_handler (API Gateway router)."""

    @patch("lambda_function._get_rules")
    def test_routes_get_rules(self, mock_get_rules):
        from lambda_function import admin_api_handler

        mock_get_rules.return_value = {"statusCode": 200}
        event = {"httpMethod": "GET", "path": "/events/rules"}

        result = admin_api_handler(event, None)
        mock_get_rules.assert_called_once()

    @patch("lambda_function._get_history")
    def test_routes_get_history(self, mock_get_history):
        from lambda_function import admin_api_handler

        mock_get_history.return_value = {"statusCode": 200}
        event = {"httpMethod": "GET", "path": "/events/history"}

        result = admin_api_handler(event, None)
        mock_get_history.assert_called_once()

    @patch("lambda_function._replay_event")
    def test_routes_post_replay(self, mock_replay):
        from lambda_function import admin_api_handler

        mock_replay.return_value = {"statusCode": 200}
        event = {"httpMethod": "POST", "path": "/events/replay"}

        result = admin_api_handler(event, None)
        mock_replay.assert_called_once()

    def test_returns_404_for_unknown_route(self):
        from lambda_function import admin_api_handler

        event = {"httpMethod": "GET", "path": "/events/unknown"}
        result = admin_api_handler(event, None)

        assert result["statusCode"] == 404
        body = json.loads(result["body"])
        assert body["error"]["code"] == "NOT_FOUND"


class TestGetHistory(unittest.TestCase):
    """Tests for GET /events/history."""

    @patch("lambda_function.table")
    def test_returns_events_with_default_limit(self, mock_table):
        from lambda_function import _get_history

        mock_table.scan.return_value = {
            "Items": [
                {
                    "eventId": "evt-001",
                    "source": "kismet.match-service",
                    "detailType": "match.created",
                    "detail": {"matchId": "m1"},
                    "timestamp": "2026-04-01T12:00:00Z",
                    "status": "delivered",
                }
            ]
        }

        event = {"queryStringParameters": None}
        result = _get_history(event)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["count"] == 1
        assert body["items"][0]["eventId"] == "evt-001"

    @patch("lambda_function.table")
    def test_filters_by_source_uses_gsi(self, mock_table):
        from lambda_function import _get_history

        mock_table.query.return_value = {"Items": []}

        event = {"queryStringParameters": {"source": "kismet.auth-service"}}
        result = _get_history(event)

        assert result["statusCode"] == 200
        mock_table.query.assert_called_once()
        call_kwargs = mock_table.query.call_args[1]
        assert call_kwargs["IndexName"] == "source-timestamp-index"

    @patch("lambda_function.table")
    def test_limits_capped_at_100(self, mock_table):
        from lambda_function import _get_history

        mock_table.scan.return_value = {"Items": []}

        event = {"queryStringParameters": {"limit": "500"}}
        result = _get_history(event)

        call_kwargs = mock_table.scan.call_args[1]
        assert call_kwargs["Limit"] == 100


class TestReplayEvent(unittest.TestCase):
    """Tests for POST /events/replay."""

    @patch("lambda_function.table")
    @patch("lambda_function.events_client")
    def test_replays_existing_event(self, mock_events, mock_table):
        from lambda_function import _replay_event

        mock_table.get_item.return_value = {
            "Item": {
                "PK": "EVENT#evt-003",
                "SK": "META",
                "eventId": "evt-003",
                "source": "kismet.match-service",
                "detailType": "match.created",
                "detail": {"matchId": "m1"},
                "timestamp": "2026-04-01T12:00:00Z",
                "status": "delivered",
            }
        }

        event = {"body": json.dumps({"eventId": "evt-003"})}
        result = _replay_event(event)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["status"] == "replayed"
        assert body["eventId"] == "evt-003"
        mock_events.put_events.assert_called_once()

    def test_returns_400_when_no_event_id(self):
        from lambda_function import _replay_event

        event = {"body": "{}"}
        result = _replay_event(event)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error"]["code"] == "VALIDATION_ERROR"

    @patch("lambda_function.table")
    def test_returns_404_when_event_not_found(self, mock_table):
        from lambda_function import _replay_event

        mock_table.get_item.return_value = {}

        event = {"body": json.dumps({"eventId": "evt-nonexistent"})}
        result = _replay_event(event)

        assert result["statusCode"] == 404
        body = json.loads(result["body"])
        assert body["error"]["code"] == "NOT_FOUND"


class TestGetRules(unittest.TestCase):
    """Tests for GET /events/rules."""

    @patch("lambda_function.events_client")
    def test_lists_rules_with_targets(self, mock_events):
        from lambda_function import _get_rules

        mock_events.list_rules.return_value = {
            "Rules": [
                {
                    "Name": "catch-all-logger",
                    "EventPattern": '{"source": [{"prefix": "kismet."}]}',
                    "State": "ENABLED",
                }
            ]
        }
        mock_events.list_targets_by_rule.return_value = {
            "Targets": [
                {"Arn": "arn:aws:lambda:us-east-1:123:function:kismet-event-bus-logger"}
            ]
        }

        result = _get_rules({})

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["count"] == 1
        assert body["rules"][0]["ruleName"] == "catch-all-logger"
        assert body["rules"][0]["state"] == "ENABLED"


if __name__ == "__main__":
    unittest.main()
