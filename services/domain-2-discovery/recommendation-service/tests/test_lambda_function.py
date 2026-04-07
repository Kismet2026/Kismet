import json
import os
import pytest
from unittest.mock import patch, MagicMock

os.environ['TABLE_NAME'] = 'kismet-recommendations'
os.environ['DISCOVERY_TABLE_NAME'] = 'kismet-discovery'
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


class TestGetRecommendations:
    @patch('lambda_function.discovery_table')
    @patch('lambda_function.table')
    def test_returns_cached_recommendations(self, mock_table, mock_discovery):
        mock_table.query.return_value = {
            'Items': [
                {
                    'candidateUserId': 'user-456', 'displayName': 'Alice',
                    'age': 25, 'gender': 'female', 'location': 'Boston',
                    'avatarUrl': '', 'score': 85,
                    'scoreBreakdown': {'locationProximity': 25, 'sharedInterests': 20,
                                       'baziCompatibility': 30, 'activityRecency': 10},
                },
            ]
        }

        resp = handler(_api_event('GET', '/recommend'), None)

        assert resp['statusCode'] == 200
        body = json.loads(resp['body'])
        assert body['count'] == 1
        assert body['items'][0]['userId'] == 'user-456'
        assert body['items'][0]['score'] == 85

    @patch('lambda_function.discovery_table')
    @patch('lambda_function.table')
    def test_computes_on_empty_cache(self, mock_table, mock_discovery):
        mock_table.query.return_value = {'Items': []}
        mock_discovery.scan.return_value = {
            'Items': [
                {'PK': 'PROFILE#u2', 'SK': 'META', 'userId': 'u2',
                 'displayName': 'Bob', 'age': 28, 'gender': 'male',
                 'location': 'Cambridge', 'avatarUrl': '', 'bio': ''},
            ]
        }

        resp = handler(_api_event('GET', '/recommend'), None)

        assert resp['statusCode'] == 200
        body = json.loads(resp['body'])
        assert body['count'] >= 1
        mock_table.put_item.assert_called()  # cached the computed scores

    def test_unauthenticated_returns_401(self):
        resp = handler(_api_event('GET', '/recommend', user_id=None), None)
        assert resp['statusCode'] == 401


class TestRefreshRecommendations:
    @patch('lambda_function.discovery_table')
    @patch('lambda_function.table')
    def test_refresh_clears_and_recomputes(self, mock_table, mock_discovery):
        mock_table.query.return_value = {'Items': []}
        mock_discovery.scan.return_value = {'Items': []}

        resp = handler(_api_event('POST', '/recommend/refresh'), None)

        assert resp['statusCode'] == 200
        body = json.loads(resp['body'])
        assert body['status'] == 'refreshed'


class TestHandleSwipeCreated:
    @patch('lambda_function.table')
    def test_removes_swiped_candidate(self, mock_table):
        mock_table.query.return_value = {
            'Items': [{'PK': 'USER#user-123', 'SK': 'SCORE#0085#user-456'}]
        }

        resp = handler({
            'source': 'kismet.swipe-service',
            'detail': {'userId': 'user-123', 'targetUserId': 'user-456', 'action': 'like'},
        }, None)

        assert resp['statusCode'] == 200
        mock_table.delete_item.assert_called_once()
