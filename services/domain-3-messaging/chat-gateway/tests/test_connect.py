import os
import sys
from unittest.mock import MagicMock, patch

os.environ["CONNECTIONS_TABLE"] = "kismet-connections"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


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


@patch("boto3.resource")
def test_connect_success(mock_boto):
    mock_table = MagicMock()
    mock_boto.return_value.Table.return_value = mock_table

    import connect

    connect.db = mock_table

    event = make_event(connection_id="conn-abc", user_id="user-1", match_id="match-1")
    result = connect.handler(event, None)

    assert result["statusCode"] == 200
    assert result["body"] == "Connected"
    mock_table.put_item.assert_called_once()

    item = mock_table.put_item.call_args[1]["Item"]
    assert item["PK"] == "CONN#conn-abc"
    assert item["SK"] == "META"
    assert item["userId"] == "user-1"
    assert item["matchId"] == "match-1"
    assert "ttl" in item


@patch("boto3.resource")
def test_connect_requires_user_id_and_match_id(mock_boto):
    mock_table = MagicMock()
    mock_boto.return_value.Table.return_value = mock_table

    import connect

    connect.db = mock_table

    event = make_event(connection_id="conn-xyz")
    result = connect.handler(event, None)

    assert result["statusCode"] == 400
    assert result["body"] == "userId and matchId are required"
    mock_table.put_item.assert_not_called()


@patch("boto3.resource")
def test_connect_ttl_is_in_future(mock_boto):
    import time

    mock_table = MagicMock()
    mock_boto.return_value.Table.return_value = mock_table

    import connect

    connect.db = mock_table

    event = make_event(user_id="user-1", match_id="match-1")
    connect.handler(event, None)

    item = mock_table.put_item.call_args[1]["Item"]
    assert item["ttl"] > int(time.time())
