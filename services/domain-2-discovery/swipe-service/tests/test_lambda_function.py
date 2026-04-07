import json
import os
import pytest
from unittest.mock import patch, MagicMock

os.environ['TABLE_NAME'] = 'kismet-swipes'
os.environ['EVENT_BUS_NAME'] = 'kismet-events'

from lambda_function import handler


def _api_event(method, path, body=None, user_id='user-123', query_params=None):
    event = {
        'httpMethod': method,
        'path': path,
        'requestContext': {
            'authorizer': {
                'claims': {'sub': user_id} if user_id else {}
            }
        },
        'queryStringParameters': query_params,
    }
    if body:
        event['body'] = json.dumps(body)
    return event


class TestCreateSwipe:
    @patch('lambda_function.events_client')
    @patch('lambda_function.table')
    def test_like_creates_swipe_and_publishes_event(self, mock_table, mock_events):
        mock_table.get_item.return_value = {}

        resp = handler(
            _api_event('POST', '/swipe', {'targetUserId': 'user-456', 'action': 'like'}),
            None,
        )

        assert resp['statusCode'] == 200
        body = json.loads(resp['body'])
        assert body['action'] == 'like'
        assert body['targetUserId'] == 'user-456'
        assert 'swipeId' in body

        mock_table.put_item.assert_called_once()
        mock_events.put_events.assert_called_once()

    @patch('lambda_function.events_client')
    @patch('lambda_function.table')
    def test_pass_creates_swipe_no_event(self, mock_table, mock_events):
        mock_table.get_item.return_value = {}

        resp = handler(
            _api_event('POST', '/swipe', {'targetUserId': 'user-456', 'action': 'pass'}),
            None,
        )

        assert resp['statusCode'] == 200
        body = json.loads(resp['body'])
        assert body['action'] == 'pass'
        mock_table.put_item.assert_called_once()
        mock_events.put_events.assert_not_called()

    @patch('lambda_function.table')
    def test_duplicate_swipe_returns_409(self, mock_table):
        mock_table.get_item.return_value = {'Item': {'userId': 'user-123', 'targetUserId': 'user-456'}}

        resp = handler(
            _api_event('POST', '/swipe', {'targetUserId': 'user-456', 'action': 'like'}),
            None,
        )

        assert resp['statusCode'] == 409

    def test_missing_body_returns_400(self):
        resp = handler(_api_event('POST', '/swipe'), None)
        assert resp['statusCode'] == 400

    def test_invalid_action_returns_400(self):
        resp = handler(
            _api_event('POST', '/swipe', {'targetUserId': 'user-456', 'action': 'superlike'}),
            None,
        )
        assert resp['statusCode'] == 400

    def test_self_swipe_returns_400(self):
        resp = handler(
            _api_event('POST', '/swipe', {'targetUserId': 'user-123', 'action': 'like'}),
            None,
        )
        assert resp['statusCode'] == 400

    def test_unauthenticated_returns_401(self):
        resp = handler(
            _api_event('POST', '/swipe', {'targetUserId': 'user-456', 'action': 'like'}, user_id=None),
            None,
        )
        assert resp['statusCode'] == 401


class TestGetSwipeHistory:
    @patch('lambda_function.table')
    def test_returns_swipe_history(self, mock_table):
        mock_table.query.return_value = {
            'Items': [
                {'swipeId': 's1', 'targetUserId': 'user-456', 'action': 'like', 'timestamp': '2026-04-01T12:00:00Z'},
            ]
        }

        resp = handler(_api_event('GET', '/swipe/history'), None)

        assert resp['statusCode'] == 200
        body = json.loads(resp['body'])
        assert body['count'] == 1
        assert body['items'][0]['swipeId'] == 's1'

    def test_unauthenticated_returns_401(self):
        resp = handler(_api_event('GET', '/swipe/history', user_id=None), None)
        assert resp['statusCode'] == 401


class TestRouting:
    def test_unknown_route_returns_404(self):
        resp = handler(_api_event('GET', '/unknown'), None)
        assert resp['statusCode'] == 404
