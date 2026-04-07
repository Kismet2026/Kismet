import json
import os
import pytest
from unittest.mock import patch, MagicMock

os.environ['TABLE_NAME'] = 'kismet-matches'
os.environ['SWIPE_TABLE_NAME'] = 'kismet-swipes'
os.environ['EVENT_BUS_NAME'] = 'kismet-events'

from lambda_function import handler


def _api_event(method, path, user_id='user-123', query_params=None):
    return {
        'httpMethod': method,
        'path': path,
        'requestContext': {
            'authorizer': {
                'claims': {'sub': user_id} if user_id else {}
            }
        },
        'queryStringParameters': query_params,
    }


def _swipe_event(swiper_id, target_id):
    return {
        'source': 'kismet.swipe-service',
        'detail-type': 'swipe.created',
        'detail': {
            'swipeId': 'swipe-001',
            'userId': swiper_id,
            'targetUserId': target_id,
            'action': 'like',
            'timestamp': '2026-04-01T12:00:00Z',
        },
    }


class TestHandleSwipeEvent:
    @patch('lambda_function.events_client')
    @patch('lambda_function.dynamodb_client')
    @patch('lambda_function.swipe_table')
    def test_mutual_like_creates_match(self, mock_swipe, mock_ddb_client, mock_events):
        # Target already liked swiper
        mock_swipe.get_item.return_value = {
            'Item': {'userId': 'user-456', 'targetUserId': 'user-123', 'action': 'like'}
        }

        resp = handler(_swipe_event('user-123', 'user-456'), None)

        assert resp['statusCode'] == 200
        body = json.loads(resp['body'])
        assert 'matchId' in body

        # Verify transact_write_items called with 4 items (pair, META, 2 user-index)
        mock_ddb_client.transact_write_items.assert_called_once()
        call_args = mock_ddb_client.transact_write_items.call_args
        items = call_args[1]['TransactItems']
        assert len(items) == 4

        # First item should be the pair record with condition
        pair_item = items[0]['Put']
        assert pair_item['Item']['PK']['S'].startswith('PAIR#')
        assert 'ConditionExpression' in pair_item

        # Verify event published
        mock_events.put_events.assert_called_once()
        event_entry = mock_events.put_events.call_args[1]['Entries'][0]
        assert event_entry['DetailType'] == 'match.created'
        detail = json.loads(event_entry['Detail'])
        assert 'user-123' in detail['userIds']
        assert 'user-456' in detail['userIds']

    @patch('lambda_function.dynamodb_client')
    @patch('lambda_function.swipe_table')
    def test_no_reverse_like_no_match(self, mock_swipe, mock_ddb_client):
        mock_swipe.get_item.return_value = {}

        resp = handler(_swipe_event('user-123', 'user-456'), None)

        assert resp['statusCode'] == 200
        mock_ddb_client.transact_write_items.assert_not_called()

    @patch('lambda_function.dynamodb_client')
    @patch('lambda_function.swipe_table')
    def test_reverse_pass_no_match(self, mock_swipe, mock_ddb_client):
        mock_swipe.get_item.return_value = {
            'Item': {'userId': 'user-456', 'targetUserId': 'user-123', 'action': 'pass'}
        }

        resp = handler(_swipe_event('user-123', 'user-456'), None)

        assert resp['statusCode'] == 200
        mock_ddb_client.transact_write_items.assert_not_called()

    @patch('lambda_function.events_client')
    @patch('lambda_function.dynamodb_client')
    @patch('lambda_function.swipe_table')
    def test_existing_match_not_duplicated(self, mock_swipe, mock_ddb_client, mock_events):
        mock_swipe.get_item.return_value = {
            'Item': {'userId': 'user-456', 'targetUserId': 'user-123', 'action': 'like'}
        }
        # Simulate TransactionCanceledException (pair key already exists)
        exc_class = type('TransactionCanceledException', (Exception,), {})
        mock_ddb_client.exceptions.TransactionCanceledException = exc_class
        mock_ddb_client.transact_write_items.side_effect = exc_class()

        resp = handler(_swipe_event('user-123', 'user-456'), None)

        assert resp['statusCode'] == 200
        assert 'already exists' in resp['body'].lower()
        mock_events.put_events.assert_not_called()


class TestGetMatches:
    @patch('lambda_function.match_table')
    def test_returns_user_matches(self, mock_table):
        mock_table.query.return_value = {
            'Items': [
                {'matchId': 'match-1', 'matchedAt': '2026-04-01T12:00:00Z', 'status': 'active'},
            ]
        }

        resp = handler(_api_event('GET', '/matches'), None)

        assert resp['statusCode'] == 200

    @patch('lambda_function.match_table')
    def test_filters_out_unmatched(self, mock_table):
        mock_table.query.return_value = {
            'Items': [
                {'matchId': 'match-1', 'matchedAt': '2026-04-01T12:00:00Z', 'status': 'active'},
                {'matchId': 'match-2', 'matchedAt': '2026-04-02T12:00:00Z', 'status': 'unmatched'},
            ]
        }

        resp = handler(_api_event('GET', '/matches'), None)

        assert resp['statusCode'] == 200
        body = json.loads(resp['body'])
        assert body['count'] == 1
        assert body['items'][0]['matchId'] == 'match-1'
        body = json.loads(resp['body'])
        assert body['count'] == 1
        assert body['items'][0]['matchId'] == 'match-1'

    def test_unauthenticated_returns_401(self):
        resp = handler(_api_event('GET', '/matches', user_id=None), None)
        assert resp['statusCode'] == 401


class TestGetMatchDetail:
    @patch('lambda_function.match_table')
    def test_returns_match_detail(self, mock_table):
        mock_table.get_item.return_value = {
            'Item': {
                'PK': 'MATCH#match-1', 'SK': 'META',
                'matchId': 'match-1', 'userAId': 'user-123', 'userBId': 'user-456',
                'status': 'active', 'matchedAt': '2026-04-01T12:00:00Z',
            }
        }

        resp = handler(_api_event('GET', '/matches/match-1'), None)

        assert resp['statusCode'] == 200
        body = json.loads(resp['body'])
        assert body['matchId'] == 'match-1'

    @patch('lambda_function.match_table')
    def test_not_found_returns_404(self, mock_table):
        mock_table.get_item.return_value = {}

        resp = handler(_api_event('GET', '/matches/match-999'), None)
        assert resp['statusCode'] == 404

    @patch('lambda_function.match_table')
    def test_other_users_match_returns_403(self, mock_table):
        mock_table.get_item.return_value = {
            'Item': {
                'PK': 'MATCH#match-1', 'SK': 'META',
                'matchId': 'match-1', 'userAId': 'user-A', 'userBId': 'user-B',
                'status': 'active', 'matchedAt': '2026-04-01T12:00:00Z',
            }
        }

        resp = handler(_api_event('GET', '/matches/match-1'), None)
        assert resp['statusCode'] == 403


class TestUnmatch:
    @patch('lambda_function.dynamodb_client')
    @patch('lambda_function.match_table')
    def test_unmatch_success(self, mock_table, mock_ddb_client):
        mock_table.get_item.return_value = {
            'Item': {
                'matchId': 'match-1', 'userAId': 'user-123', 'userBId': 'user-456',
                'status': 'active', 'matchedAt': '2026-04-01T12:00:00Z',
            }
        }

        resp = handler(_api_event('DELETE', '/matches/match-1'), None)

        assert resp['statusCode'] == 200
        body = json.loads(resp['body'])
        assert body['status'] == 'unmatched'

        # Verify transaction updates META + both user-index entries
        mock_ddb_client.transact_write_items.assert_called_once()
        items = mock_ddb_client.transact_write_items.call_args[1]['TransactItems']
        assert len(items) == 3
        # All three should be Update operations
        assert all('Update' in item for item in items)
        # Check keys: MATCH#META, USER#user-123, USER#user-456
        pks = [item['Update']['Key']['PK']['S'] for item in items]
        assert 'MATCH#match-1' in pks
        assert 'USER#user-123' in pks
        assert 'USER#user-456' in pks
