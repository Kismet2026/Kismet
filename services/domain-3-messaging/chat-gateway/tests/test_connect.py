import os
import sys
import time
from unittest.mock import MagicMock, patch

os.environ["CONNECTIONS_TABLE"] = "kismet-connections"
os.environ["MATCHES_TABLE"]     = "kismet-matches"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

with patch("boto3.resource"):
    import connect


def make_event(connection_id="conn-123", user_id=None, match_id=None):
    params = {}
    if user_id:
        params["userId"] = user_id
    if match_id:
        params["matchId"] = match_id
    return {
        "requestContext": {"connectionId": connection_id},
        "queryStringParameters": params or None,
    }


def _match_item(user_a="user-1", user_b="user-2"):
    """Fake match record where user_a and user_b are participants."""
    return {
        "Item": {
            "PK": "MATCH#match-1",
            "SK": "META",
            "matchId": "match-1",
            "userAId": user_a,
            "userBId": user_b,
        }
    }


def setup_mocks(mock_connections=None, mock_matches=None):
    """Replace module-level tables with mocks."""
    connect.db      = mock_connections or MagicMock()
    connect.matches = mock_matches or MagicMock()


def test_connect_success():
    """Valid userId + matchId where user is a participant → 200, connection stored."""
    mock_connections = MagicMock()
    mock_matches = MagicMock()
    mock_matches.get_item.return_value = _match_item(user_a="user-1", user_b="user-2")
    setup_mocks(mock_connections, mock_matches)

    event = make_event(connection_id="conn-abc", user_id="user-1", match_id="match-1")
    result = connect.handler(event, None)

    assert result["statusCode"] == 200
    assert result["body"] == "Connected"
    mock_connections.put_item.assert_called_once()

    item = mock_connections.put_item.call_args[1]["Item"]
    assert item["PK"] == "CONN#conn-abc"
    assert item["SK"] == "META"
    assert item["userId"] == "user-1"
    assert item["matchId"] == "match-1"
    assert "ttl" in item


def test_connect_requires_user_id_and_match_id():
    """Missing userId or matchId → 400, no DB writes."""
    mock_connections = MagicMock()
    mock_matches = MagicMock()
    setup_mocks(mock_connections, mock_matches)

    event = make_event(connection_id="conn-xyz")
    result = connect.handler(event, None)

    assert result["statusCode"] == 400
    assert result["body"] == "userId and matchId are required"
    mock_connections.put_item.assert_not_called()
    mock_matches.get_item.assert_not_called()


def test_connect_rejects_non_participant():
    """User who is not in the match → 403, no connection stored."""
    mock_connections = MagicMock()
    mock_matches = MagicMock()
    mock_matches.get_item.return_value = _match_item(user_a="other-1", user_b="other-2")
    setup_mocks(mock_connections, mock_matches)

    event = make_event(connection_id="conn-intruder", user_id="intruder", match_id="match-1")
    result = connect.handler(event, None)

    assert result["statusCode"] == 403
    mock_connections.put_item.assert_not_called()


def test_connect_rejects_unknown_match():
    """Match not found → 404, no connection stored."""
    mock_connections = MagicMock()
    mock_matches = MagicMock()
    mock_matches.get_item.return_value = {}   # no "Item" key = not found
    setup_mocks(mock_connections, mock_matches)

    event = make_event(connection_id="conn-ghost", user_id="user-1", match_id="nonexistent")
    result = connect.handler(event, None)

    assert result["statusCode"] == 404
    mock_connections.put_item.assert_not_called()


def test_connect_ttl_is_in_future():
    """TTL attribute is a Unix timestamp greater than now."""
    mock_connections = MagicMock()
    mock_matches = MagicMock()
    mock_matches.get_item.return_value = _match_item()
    setup_mocks(mock_connections, mock_matches)

    event = make_event(user_id="user-1", match_id="match-1")
    connect.handler(event, None)

    item = mock_connections.put_item.call_args[1]["Item"]
    assert item["ttl"] > int(time.time())
