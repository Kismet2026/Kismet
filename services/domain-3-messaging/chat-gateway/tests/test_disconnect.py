import os
import sys
from unittest.mock import MagicMock, patch

import pytest

os.environ["CONNECTIONS_TABLE"] = "kismet-connections"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def make_event(connection_id="conn-123"):
    return {
        "requestContext": {"connectionId": connection_id},
    }


@patch("boto3.resource")
def test_disconnect_success(mock_boto):
    mock_table = MagicMock()
    mock_boto.return_value.Table.return_value = mock_table

    import disconnect
    disconnect.db = mock_table

    event = make_event(connection_id="conn-abc")
    result = disconnect.handler(event, None)

    assert result["statusCode"] == 200
    assert result["body"] == "Disconnected"
    mock_table.delete_item.assert_called_once_with(
        Key={"PK": "CONN#conn-abc", "SK": "META"}
    )


@patch("boto3.resource")
def test_disconnect_different_connection_ids(mock_boto):
    mock_table = MagicMock()
    mock_boto.return_value.Table.return_value = mock_table

    import disconnect
    disconnect.db = mock_table

    for conn_id in ["conn-1", "conn-2", "conn-3"]:
        mock_table.reset_mock()
        result = disconnect.handler(make_event(conn_id), None)
        assert result["statusCode"] == 200
        mock_table.delete_item.assert_called_once_with(
            Key={"PK": f"CONN#{conn_id}", "SK": "META"}
        )
