"""
Unit tests for icebreaker-service/lambda_function.py

Mocks:
  - table.query / table.put_item  → DynamoDB icebreakers table
  - matches_table.get_item        → DynamoDB matches table
  - bedrock.invoke_model          → Bedrock Claude call
"""

import json
import os
import sys
import unittest
from io import BytesIO
from unittest.mock import MagicMock, patch

# ── Bootstrap: set required env vars before importing the Lambda ───────────────
os.environ.setdefault("TABLE_NAME", "kismet-icebreakers")
os.environ.setdefault("MATCHES_TABLE", "kismet-matches")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

# Add the service root to sys.path so we can import lambda_function directly
SERVICE_DIR = os.path.join(os.path.dirname(__file__), "..")
if SERVICE_DIR not in sys.path:
    sys.path.insert(0, SERVICE_DIR)

# Patch boto3 before the module is imported so no real AWS calls are made
with patch("boto3.resource"), patch("boto3.client"):
    import lambda_function as lf


# ── Helpers ───────────────────────────────────────────────────────────────────

USER_A = "user-aaa"
USER_B = "user-bbb"
MATCH_ID = "match-001"

def _authed_event(method="GET", path="/icebreaker/generate", path_params=None, body=None, user_id=USER_A):
    """Build a fake API Gateway event with Cognito claims."""
    event = {
        "httpMethod": method,
        "path": path,
        "requestContext": {
            "authorizer": {
                "claims": {"sub": user_id}
            }
        },
        "pathParameters": path_params or {},
    }
    if body is not None:
        event["body"] = json.dumps(body) if isinstance(body, dict) else body
    return event


def _match_item(user_a=USER_A, user_b=USER_B):
    """Fake DynamoDB match record."""
    return {
        "Item": {
            "PK": f"MATCH#{MATCH_ID}",
            "SK": "META",
            "matchId": MATCH_ID,
            "userAId": user_a,
            "userBId": user_b,
        }
    }


def _make_bedrock_response(suggestions: list) -> dict:
    """Build a fake Bedrock invoke_model response."""
    body_bytes = json.dumps({
        "content": [{"text": json.dumps(suggestions)}]
    }).encode()
    return {"body": BytesIO(body_bytes)}


def _cached_item(match_id=MATCH_ID, source="bedrock"):
    """Fake DynamoDB get_item response with cached icebreakers (cache hit)."""
    suggestions = [
        {"id": "ice-001", "text": "What's your favourite hobby?", "source": source},
        {"id": "ice-002", "text": "Where would you travel next?",  "source": source},
        {"id": "ice-003", "text": "Best thing this week?",         "source": source},
    ]
    return {
        "Item": {
            "PK": f"MATCH#{match_id}",
            "SK": "META",
            "matchId": match_id,
            "suggestions": suggestions,
            "source": source,
            "generatedAt": "2026-04-10T00:00:00+00:00",
        }
    }


def _cache_miss():
    """Fake DynamoDB get_item response with no cached item (cache miss)."""
    return {}  # boto3 get_item returns no "Item" key when not found


# ══════════════════════════════════════════════════════════════════════════════
# Auth checks
# ══════════════════════════════════════════════════════════════════════════════

class TestAuth(unittest.TestCase):

    def setUp(self):
        self.mock_table = MagicMock()
        self.mock_matches = MagicMock()
        self.mock_bedrock = MagicMock()
        lf.table = self.mock_table
        lf.matches_table = self.mock_matches
        lf.bedrock = self.mock_bedrock

    def test_missing_jwt_returns_401(self):
        """No Cognito claims → 401 UNAUTHORIZED."""
        event = {
            "httpMethod": "GET",
            "path": f"/icebreaker/{MATCH_ID}",
            "pathParameters": {"matchId": MATCH_ID},
        }
        response = lf.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 401)
        self.mock_table.get_item.assert_not_called()

    def test_non_participant_returns_403(self):
        """Authenticated user who is not a match participant → 403 FORBIDDEN."""
        self.mock_matches.get_item.return_value = _match_item(user_a="other-1", user_b="other-2")

        event = _authed_event(
            method="GET",
            path=f"/icebreaker/{MATCH_ID}",
            path_params={"matchId": MATCH_ID},
            user_id="intruder-user",
        )
        response = lf.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 403)
        self.mock_table.get_item.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# POST /icebreaker/generate
# ══════════════════════════════════════════════════════════════════════════════

class TestHandleGenerate(unittest.TestCase):

    def setUp(self):
        self.mock_table = MagicMock()
        self.mock_matches = MagicMock()
        self.mock_bedrock = MagicMock()
        lf.table = self.mock_table
        lf.matches_table = self.mock_matches
        lf.bedrock = self.mock_bedrock

    def test_generate_missing_match_id_returns_400(self):
        """POST body without matchId → 400 VALIDATION_ERROR."""
        self.mock_matches.get_item.return_value = _match_item()
        event = _authed_event(method="POST", path="/icebreaker/generate", body={})
        response = lf.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["code"], "VALIDATION_ERROR")
        self.mock_bedrock.invoke_model.assert_not_called()

    def test_generate_returns_cache_without_calling_bedrock(self):
        """Cache hit → return cached result, skip Bedrock."""
        self.mock_matches.get_item.return_value = _match_item()
        self.mock_table.get_item.return_value = _cached_item()

        event = _authed_event(
            method="POST", path="/icebreaker/generate",
            body={"matchId": MATCH_ID},
        )
        response = lf.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["matchId"], MATCH_ID)
        self.mock_bedrock.invoke_model.assert_not_called()

    def test_generate_calls_bedrock_on_cache_miss(self):
        """Cache miss → call Bedrock and write to DynamoDB."""
        ai_suggestions = ["Opener A", "Opener B", "Opener C"]
        self.mock_matches.get_item.return_value = _match_item()
        self.mock_table.get_item.return_value = _cache_miss()
        self.mock_bedrock.invoke_model.return_value = _make_bedrock_response(ai_suggestions)

        event = _authed_event(
            method="POST", path="/icebreaker/generate",
            body={"matchId": MATCH_ID, "userA": {}, "userB": {}},
        )
        response = lf.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(len(body["suggestions"]), 3)
        self.assertEqual(body["suggestions"][0]["text"], "Opener A")
        self.assertEqual(body["suggestions"][0]["source"], "bedrock")
        self.mock_bedrock.invoke_model.assert_called_once()
        self.mock_table.put_item.assert_called_once()

    def test_generate_uses_fallback_when_bedrock_fails(self):
        """Bedrock exception → fallback icebreakers used, source='template'."""
        self.mock_matches.get_item.return_value = _match_item()
        self.mock_table.get_item.return_value = _cache_miss()
        self.mock_bedrock.invoke_model.side_effect = Exception("Bedrock timeout")

        event = _authed_event(
            method="POST", path="/icebreaker/generate",
            body={"matchId": MATCH_ID},
        )
        response = lf.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(len(body["suggestions"]), 3)
        for s in body["suggestions"]:
            self.assertEqual(s["source"], "template")
        self.mock_table.put_item.assert_called_once()

    def test_generate_invalid_json_body_returns_400(self):
        """Malformed JSON body → 400."""
        event = _authed_event(method="POST", path="/icebreaker/generate", body="not-json")
        event["body"] = "not-valid-json"
        response = lf.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 400)


# ══════════════════════════════════════════════════════════════════════════════
# GET /icebreaker/{matchId}
# ══════════════════════════════════════════════════════════════════════════════

class TestHandleGet(unittest.TestCase):

    def setUp(self):
        self.mock_table = MagicMock()
        self.mock_matches = MagicMock()
        self.mock_bedrock = MagicMock()
        lf.table = self.mock_table
        lf.matches_table = self.mock_matches
        lf.bedrock = self.mock_bedrock

    def test_get_returns_cached_suggestions(self):
        """GET with cached data → 200 with suggestions."""
        self.mock_matches.get_item.return_value = _match_item()
        self.mock_table.get_item.return_value = _cached_item()

        event = _authed_event(
            method="GET", path=f"/icebreaker/{MATCH_ID}",
            path_params={"matchId": MATCH_ID},
        )
        response = lf.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(body["matchId"], MATCH_ID)
        self.assertEqual(len(body["suggestions"]), 3)
        self.mock_bedrock.invoke_model.assert_not_called()

    def test_get_returns_none_when_no_cache(self):
        """GET with no cached data → 200 with suggestions=None."""
        self.mock_matches.get_item.return_value = _match_item()
        self.mock_table.get_item.return_value = _cache_miss()

        event = _authed_event(
            method="GET", path=f"/icebreaker/{MATCH_ID}",
            path_params={"matchId": MATCH_ID},
        )
        response = lf.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertIsNone(json.loads(response["body"])["suggestions"])
        self.mock_bedrock.invoke_model.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# EventBridge: match.created trigger
# ══════════════════════════════════════════════════════════════════════════════

class TestEventBridgeTrigger(unittest.TestCase):

    def setUp(self):
        self.mock_table = MagicMock()
        self.mock_matches = MagicMock()
        self.mock_bedrock = MagicMock()
        lf.table = self.mock_table
        lf.matches_table = self.mock_matches
        lf.bedrock = self.mock_bedrock

    def test_match_created_event_auto_generates_icebreakers(self):
        """Correct EventBridge event → icebreakers generated and cached."""
        ai_suggestions = ["Hello!", "How are you?", "What's up?"]
        self.mock_table.get_item.return_value = _cache_miss()
        self.mock_bedrock.invoke_model.return_value = _make_bedrock_response(ai_suggestions)

        event = {
            "source": "kismet.match-service",
            "detail-type": "match.created",
            "detail": {"matchId": MATCH_ID},
        }
        response = lf.lambda_handler(event, None)

        self.assertEqual(response, {})
        self.mock_table.put_item.assert_called_once()

    def test_match_created_event_without_match_id_does_nothing(self):
        """EventBridge event missing matchId → no DynamoDB write."""
        event = {
            "source": "kismet.match-service",
            "detail-type": "match.created",
            "detail": {},
        }
        response = lf.lambda_handler(event, None)
        self.assertEqual(response, {})
        self.mock_table.put_item.assert_not_called()

    def test_wrong_detail_type_is_ignored(self):
        """EventBridge event with wrong detail-type → not treated as match.created."""
        event = {
            "source": "kismet.match-service",
            "detail-type": "match.deleted",   # wrong detail-type
            "detail": {"matchId": MATCH_ID},
        }
        response = lf.lambda_handler(event, None)
        # Falls through to HTTP routing, which returns 401 (no auth claims)
        self.assertNotEqual(response, {})
        self.mock_table.put_item.assert_not_called()


if __name__ == "__main__":
    unittest.main()
