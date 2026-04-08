import json
import os
import pytest
from unittest.mock import patch, MagicMock
from decimal import Decimal

os.environ['TABLE_NAME'] = 'kismet-recommendations'
os.environ['DISCOVERY_TABLE_NAME'] = 'kismet-discovery'
os.environ['SWIPE_TABLE_NAME'] = 'kismet-swipes'
os.environ['EVENT_BUS_NAME'] = 'kismet-events'

from lambda_function import handler, _calculate_score


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


class TestCalculateScore:
    def test_with_bazi_match(self):
        profile = {'birthDate': '1999-05-15', 'avatarUrl': 'https://...', 'bio': 'hi', 'city': 'Boston'}
        bazi_scores = {'1999-05-15': 92}

        result = _calculate_score(profile, bazi_scores)

        assert result['baziCompatibility'] == int(92 * 40 / 100)  # 36
        assert result['profileCompleteness'] == 20  # avatar(8) + bio(7) + city(5)
        assert result['activityRecency'] == 10

    def test_without_bazi_match(self):
        profile = {'birthDate': '1999-05-15', 'avatarUrl': '', 'bio': '', 'city': ''}
        bazi_scores = {'2000-01-01': 85}  # different date

        result = _calculate_score(profile, bazi_scores)

        assert result['baziCompatibility'] == 20  # default
        assert result['profileCompleteness'] == 0  # no avatar/bio/city

    def test_empty_bazi_scores(self):
        profile = {'birthDate': '1999-05-15'}
        result = _calculate_score(profile, {})
        assert result['baziCompatibility'] == 20


class TestGetRecommendations:
    @patch('lambda_function.discovery_table')
    @patch('lambda_function.table')
    def test_returns_cached_recommendations(self, mock_table, mock_discovery):
        mock_table.query.return_value = {
            'Items': [
                {
                    'candidateUserId': 'user-456', 'displayName': 'Alice',
                    'age': 25, 'gender': 'female', 'location': [42.36, -71.06],
                    'avatarUrl': '', 'score': 85,
                    'scoreBreakdown': {'baziCompatibility': 36, 'profileCompleteness': 20, 'activityRecency': 10},
                },
            ]
        }

        resp = handler(_api_event('GET', '/recommend'), None)

        assert resp['statusCode'] == 200
        body = json.loads(resp['body'])
        assert body['count'] == 1
        assert body['items'][0]['userId'] == 'user-456'
        assert body['items'][0]['score'] == 85

    @patch('lambda_function.swipe_table')
    @patch('lambda_function.discovery_table')
    @patch('lambda_function.table')
    def test_computes_on_empty_cache_with_bazi(self, mock_table, mock_discovery, mock_swipe):
        mock_table.query.return_value = {'Items': []}
        mock_swipe.query.return_value = {'Items': []}

        # User profile with birthDate
        def get_item_side_effect(**kwargs):
            key = kwargs.get('Key', {})
            pk = key.get('PK', '')
            if pk == 'PROFILE#user-123':
                return {'Item': {'birthDate': '1995-11-21'}}
            elif pk == 'BAZI#1995-11-21':
                return {'Item': {'scores': {'1999-05-15': Decimal('92')}}}
            return {}

        mock_discovery.get_item.side_effect = get_item_side_effect
        mock_discovery.scan.return_value = {
            'Items': [
                {'PK': 'PROFILE#u2', 'SK': 'META', 'userId': 'u2',
                 'displayName': 'Alice', 'age': 25, 'gender': 'female',
                 'birthDate': '1999-05-15',
                 'location': [], 'city': 'Boston', 'avatarUrl': 'https://...', 'bio': 'hello'},
            ]
        }

        resp = handler(_api_event('GET', '/recommend'), None)

        assert resp['statusCode'] == 200
        body = json.loads(resp['body'])
        assert body['count'] == 1
        # Should use real BaZi score, not random
        assert body['items'][0]['scoreBreakdown']['baziCompatibility'] == int(92 * 40 / 100)
        mock_table.put_item.assert_called()

    @patch('lambda_function.swipe_table')
    @patch('lambda_function.discovery_table')
    @patch('lambda_function.table')
    def test_excludes_swiped_candidates(self, mock_table, mock_discovery, mock_swipe):
        mock_table.query.return_value = {'Items': []}
        mock_swipe.query.return_value = {'Items': [{'targetUserId': 'u2'}]}
        mock_discovery.get_item.return_value = {}
        mock_discovery.scan.return_value = {
            'Items': [
                {'PK': 'PROFILE#u2', 'SK': 'META', 'userId': 'u2',
                 'displayName': 'Alice', 'age': 25, 'gender': 'female',
                 'location': [], 'avatarUrl': '', 'bio': ''},
                {'PK': 'PROFILE#u3', 'SK': 'META', 'userId': 'u3',
                 'displayName': 'Carol', 'age': 28, 'gender': 'female',
                 'birthDate': '1998-01-01',
                 'location': [], 'avatarUrl': '', 'bio': ''},
            ]
        }

        resp = handler(_api_event('GET', '/recommend'), None)

        body = json.loads(resp['body'])
        assert body['count'] == 1
        assert body['items'][0]['userId'] == 'u3'

    def test_unauthenticated_returns_401(self):
        resp = handler(_api_event('GET', '/recommend', user_id=None), None)
        assert resp['statusCode'] == 401


class TestRefreshRecommendations:
    @patch('lambda_function.swipe_table')
    @patch('lambda_function.discovery_table')
    @patch('lambda_function.table')
    def test_refresh_clears_and_recomputes(self, mock_table, mock_discovery, mock_swipe):
        mock_table.query.return_value = {'Items': []}
        mock_swipe.query.return_value = {'Items': []}
        mock_discovery.get_item.return_value = {}
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


class TestHandleProfileCompleted:
    @patch('lambda_function.table')
    def test_writes_system_marker(self, mock_table):
        resp = handler({
            'source': 'kismet.profile-service',
            'detail-type': 'profile.completed',
            'detail': {'userId': 'user-new'},
        }, None)

        assert resp['statusCode'] == 200
        mock_table.put_item.assert_called_once()
        item = mock_table.put_item.call_args[1]['Item']
        assert item['PK'] == 'SYSTEM'
        assert item['SK'] == 'LAST_PROFILE_UPDATE'
        assert item['userId'] == 'user-new'
