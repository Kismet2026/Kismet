import json
import os
import sys
from unittest.mock import MagicMock, patch, call

import pytest

os.environ["CONNECTIONS_TABLE"] = "kismet-connections"
os.environ["MESSAGES_TABLE"] = "kismet-messages"
os.environ["EVENT_BUS_NAME"] = "kismet-events"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def make_event(body=None, connection_id="conn-sender"):
    return {
        "requestContext": {
            "connectionId": connection_id,
            "domainName": "abc123.execute-api.us-east-1.amazonaws.com",
            "stage": "dev",
        },
        "body": json.dumps(body or {}),
    }


@patch("boto3.client")
@patch("boto3.resource")
def test_send_message_success(mock_resource, mock_client):
    mock_messages = MagicMock()
    mock_connections = MagicMock()
    mock_resource.return_value.Table.side_effect = lambda name: (
        mock_connections if name == "kismet-connections" else mock_messages
    )

    mock_events = MagicMock()
    mock_apigw = MagicMock()
    mock_client.side_effect = lambda service, **kwargs: (
        mock_apigw if service == "apigatewaymanagementapi" else mock_events
    )

    # Receiver has one active connection
    mock_connections.query.return_value = {
        "Items": [{"connectionId": "conn-receiver", "matchId": "match-1"}]
    }

    import send_message
    send_message.messages = mock_messages
    send_message.connections = mock_connections
    send_message.events_client = mock_events

    event = make_event({
        "matchId": "match-1",
        "content": "Hello!",
        "senderId": "user-1",
        "receiverId": "user-2",
    })

    result = send_message.handler(event, None)

    assert result["statusCode"] == 200
    assert result["body"] == "Message delivered"

    # Message persisted to DynamoDB
    mock_messages.put_item.assert_called_once()
    item = mock_messages.put_item.call_args[1]["Item"]
    assert item["matchId"] == "match-1"
    assert item["content"] == "Hello!"
    assert item["senderId"] == "user-1"
    assert item["PK"] == "CONV#match-1"
    assert item["deleted"] is False

    # EventBridge event published
    mock_events.put_events.assert_called_once()
    entry = mock_events.put_events.call_args[1]["Entries"][0]
    assert entry["DetailType"] == "message.sent"
    assert entry["Source"] == "kismet.message-service"


@patch("boto3.client")
@patch("boto3.resource")
def test_send_message_missing_match_id(mock_resource, mock_client):
    mock_messages = MagicMock()
    mock_connections = MagicMock()
    mock_resource.return_value.Table.side_effect = lambda name: (
        mock_connections if name == "kismet-connections" else mock_messages
    )

    import send_message
    send_message.messages = mock_messages
    send_message.connections = mock_connections

    event = make_event({"content": "Hello!"})  # missing matchId
    result = send_message.handler(event, None)

    assert result["statusCode"] == 400
    mock_messages.put_item.assert_not_called()


@patch("boto3.client")
@patch("boto3.resource")
def test_send_message_missing_content(mock_resource, mock_client):
    mock_messages = MagicMock()
    mock_connections = MagicMock()
    mock_resource.return_value.Table.side_effect = lambda name: (
        mock_connections if name == "kismet-connections" else mock_messages
    )

    import send_message
    send_message.messages = mock_messages
    send_message.connections = mock_connections

    event = make_event({"matchId": "match-1"})  # missing content
    result = send_message.handler(event, None)

    assert result["statusCode"] == 400
    mock_messages.put_item.assert_not_called()


@patch("boto3.client")
@patch("boto3.resource")
def test_send_message_does_not_echo_to_sender(mock_resource, mock_client):
    mock_messages = MagicMock()
    mock_connections = MagicMock()
    mock_resource.return_value.Table.side_effect = lambda name: (
        mock_connections if name == "kismet-connections" else mock_messages
    )

    mock_apigw = MagicMock()
    mock_client.return_value = mock_apigw

    # Both sender and receiver connections returned
    mock_connections.query.return_value = {
        "Items": [
            {"connectionId": "conn-sender", "matchId": "match-1"},
            {"connectionId": "conn-receiver", "matchId": "match-1"},
        ]
    }

    import send_message
    send_message.messages = mock_messages
    send_message.connections = mock_connections
    send_message.events_client = MagicMock()

    event = make_event(
        {"matchId": "match-1", "content": "Hi!", "senderId": "user-1", "receiverId": "user-2"},
        connection_id="conn-sender",
    )
    send_message.handler(event, None)

    # Only pushed to receiver, not sender
    pushed_ids = [
        c[1]["ConnectionId"] for c in mock_apigw.post_to_connection.call_args_list
    ]
    assert "conn-receiver" in pushed_ids
    assert "conn-sender" not in pushed_ids


@patch("boto3.client")
@patch("boto3.resource")
def test_send_message_eventbridge_failure_does_not_fail_request(mock_resource, mock_client):
    mock_messages = MagicMock()
    mock_connections = MagicMock()
    mock_resource.return_value.Table.side_effect = lambda name: (
        mock_connections if name == "kismet-connections" else mock_messages
    )

    mock_events = MagicMock()
    mock_events.put_events.side_effect = Exception("EventBridge unavailable")
    mock_apigw = MagicMock()
    mock_client.side_effect = lambda service, **kwargs: (
        mock_apigw if service == "apigatewaymanagementapi" else mock_events
    )

    mock_connections.query.return_value = {"Items": []}

    import send_message
    send_message.messages = mock_messages
    send_message.connections = mock_connections
    send_message.events_client = mock_events

    event = make_event({"matchId": "match-1", "content": "Hi!", "senderId": "user-1"})
    result = send_message.handler(event, None)

    # Should still succeed even if EventBridge fails
    assert result["statusCode"] == 200
