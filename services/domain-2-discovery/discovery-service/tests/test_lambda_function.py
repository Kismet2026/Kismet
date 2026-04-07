import json
import os
import pytest
from unittest.mock import patch, MagicMock, call
from urllib.error import URLError
from decimal import Decimal

os.environ['TABLE_NAME'] = 'kismet-discovery'
os.environ['SWIPE_TABLE_NAME'] = 'kismet-swipes'
os.environ['EVENT_BUS_NAME'] = 'kismet-events'
os.environ['BAZI_API_URL'] = 'https://mock-bazi/api/match'
os.environ['BAZI_API_KEY'] = 'test-key'

from lambda_function import handler, _calculate_age, _ensure_bazi_cache


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


def _profile_event(user_id, name='Alice', gender='female', birth_date='1999-05-15'):
    return {
        'source': 'kismet.profile-service',
        'detail-type': 'profile.completed',
        'detail': {
            'userId': user_id,
            'name': name,
            'gender': gender,
            'preferred_gender': 'male',
            'birthDate': birth_date,
            'birthTime': '14:30',
            'location_coordinates': [42.36, -71.06],
            'city': 'Boston',
            'avatarUrl': 'https://photos.example.com/alice.jpg',
        },
    }


class TestCalculateAge:
    def test_normal_age(self):
        age = _calculate_age('2000-01-01')
        assert age >= 25

    def test_birthday_not_yet_this_year(self):
        age = _calculate_age('2000-12-31')
        assert age >= 24

    def test_empty_string_returns_zero(self):
        assert _calculate_age('') == 0

    def test_invalid_date_returns_zero(self):
        assert _calculate_age('not-a-date') == 0


class TestHandleProfileCompleted:
    @patch('lambda_function._ensure_bazi_cache')
    @patch('lambda_function.table')
    def test_indexes_user_and_prewarms_cache(self, mock_table, mock_cache):
        mock_cache.return_value = {}

        resp = handler(_profile_event('user-new', 'Bob', 'male', '1998-03-15'), None)

        assert resp['statusCode'] == 200
        mock_table.put_item.assert_called_once()

        item = mock_table.put_item.call_args[1]['Item']
        assert item['userId'] == 'user-new'
        assert item['displayName'] == 'Bob'
        assert item['age'] >= 27
        assert item['birthDate'] == '1998-03-15'
        assert item['location'] == [42.36, -71.06]

        # Verify BaZi cache was pre-warmed
        mock_cache.assert_called_once_with('1998-03-15')

    @patch('lambda_function._ensure_bazi_cache')
    @patch('lambda_function.table')
    def test_missing_birthdate_skips_cache(self, mock_table, mock_cache):
        event = _profile_event('user-new')
        del event['detail']['birthDate']

        resp = handler(event, None)

        assert resp['statusCode'] == 200
        mock_cache.assert_not_called()


class TestBaziCache:
    @patch('lambda_function._call_bazi_api')
    @patch('lambda_function.table')
    def test_cache_hit_skips_api(self, mock_table, mock_api):
        # Cache already has data
        mock_table.get_item.return_value = {
            'Item': {
                'PK': 'BAZI#1995-11-21', 'SK': 'SCORES',
                'scores': {'1991-06-20': Decimal('99'), '1998-07-13': Decimal('95')},
            }
        }

        scores = _ensure_bazi_cache('1995-11-21')

        assert scores == {'1991-06-20': 99, '1998-07-13': 95}
        mock_api.assert_not_called()  # No API call!

    @patch('lambda_function._call_bazi_api')
    @patch('lambda_function.table')
    def test_cache_miss_calls_api_and_stores(self, mock_table, mock_api):
        # Cache miss
        mock_table.get_item.return_value = {}
        mock_api.return_value = {'1991-06-20': 99}

        scores = _ensure_bazi_cache('1995-11-21')

        assert scores == {'1991-06-20': 99}
        mock_api.assert_called_once_with('1995-11-21')
        # Verify cache was written
        assert mock_table.put_item.call_count == 1
        cached_item = mock_table.put_item.call_args[1]['Item']
        assert cached_item['PK'] == 'BAZI#1995-11-21'
        assert cached_item['scores'] == {'1991-06-20': 99}

    @patch('lambda_function._call_bazi_api')
    @patch('lambda_function.table')
    def test_api_failure_returns_empty(self, mock_table, mock_api):
        mock_table.get_item.return_value = {}
        mock_api.side_effect = URLError('Connection refused')

        scores = _ensure_bazi_cache('1995-11-21')

        assert scores == {}
        mock_table.put_item.assert_not_called()  # Don't cache empty


class TestGetCandidates:
    @patch('lambda_function._get_bazi_scores_for_user')
    @patch('lambda_function.swipe_table')
    @patch('lambda_function.table')
    def test_returns_candidates_with_bazi_score(self, mock_table, mock_swipe, mock_bazi):
        mock_swipe.query.return_value = {'Items': []}
        mock_bazi.return_value = {'1999-05-15': 92}
        mock_table.scan.return_value = {
            'Items': [
                {'PK': 'PROFILE#user-456', 'SK': 'META', 'userId': 'user-456',
                 'displayName': 'Alice', 'age': 25, 'gender': 'female',
                 'birthDate': '1999-05-15',
                 'location': [42.36, -71.06], 'city': 'Boston',
                 'avatarUrl': '', 'bio': 'Hello'},
            ]
        }

        resp = handler(_api_event('GET', '/discovery'), None)

        assert resp['statusCode'] == 200
        body = json.loads(resp['body'])
        assert body['count'] == 1
        assert body['items'][0]['baziScore'] == 92

    @patch('lambda_function._get_bazi_scores_for_user')
    @patch('lambda_function.swipe_table')
    @patch('lambda_function.table')
    def test_bazi_score_none_when_not_in_top200(self, mock_table, mock_swipe, mock_bazi):
        mock_swipe.query.return_value = {'Items': []}
        mock_bazi.return_value = {'2000-01-01': 85}
        mock_table.scan.return_value = {
            'Items': [
                {'PK': 'PROFILE#user-456', 'SK': 'META', 'userId': 'user-456',
                 'displayName': 'Alice', 'age': 25, 'gender': 'female',
                 'birthDate': '1999-05-15',
                 'location': [], 'avatarUrl': '', 'bio': ''},
            ]
        }

        resp = handler(_api_event('GET', '/discovery'), None)

        body = json.loads(resp['body'])
        assert body['items'][0]['baziScore'] is None

    @patch('lambda_function._get_bazi_scores_for_user')
    @patch('lambda_function.swipe_table')
    @patch('lambda_function.table')
    def test_excludes_already_swiped_users(self, mock_table, mock_swipe, mock_bazi):
        mock_swipe.query.return_value = {
            'Items': [{'targetUserId': 'user-456'}]
        }
        mock_bazi.return_value = {}
        mock_table.scan.return_value = {
            'Items': [
                {'PK': 'PROFILE#user-456', 'SK': 'META', 'userId': 'user-456',
                 'displayName': 'Alice', 'age': 25, 'gender': 'female',
                 'location': [], 'avatarUrl': '', 'bio': ''},
                {'PK': 'PROFILE#user-789', 'SK': 'META', 'userId': 'user-789',
                 'displayName': 'Carol', 'age': 28, 'gender': 'female',
                 'birthDate': '1998-01-01',
                 'location': [], 'avatarUrl': '', 'bio': ''},
            ]
        }

        resp = handler(_api_event('GET', '/discovery'), None)

        body = json.loads(resp['body'])
        assert body['count'] == 1
        assert body['items'][0]['userId'] == 'user-789'

    @patch('lambda_function._get_bazi_scores_for_user')
    @patch('lambda_function.swipe_table')
    @patch('lambda_function.table')
    def test_filters_by_gender(self, mock_table, mock_swipe, mock_bazi):
        mock_swipe.query.return_value = {'Items': []}
        mock_bazi.return_value = {}
        mock_table.scan.return_value = {
            'Items': [
                {'PK': 'PROFILE#u1', 'SK': 'META', 'userId': 'u1', 'displayName': 'A',
                 'age': 25, 'gender': 'female', 'location': '', 'avatarUrl': '', 'bio': ''},
                {'PK': 'PROFILE#u2', 'SK': 'META', 'userId': 'u2', 'displayName': 'B',
                 'age': 28, 'gender': 'male', 'location': '', 'avatarUrl': '', 'bio': ''},
            ]
        }

        resp = handler(
            _api_event('GET', '/discovery', query_params={'gender': 'female'}),
            None,
        )

        body = json.loads(resp['body'])
        assert body['count'] == 1
        assert body['items'][0]['gender'] == 'female'

    @patch('lambda_function._get_bazi_scores_for_user')
    @patch('lambda_function.swipe_table')
    @patch('lambda_function.table')
    def test_filters_by_age(self, mock_table, mock_swipe, mock_bazi):
        mock_swipe.query.return_value = {'Items': []}
        mock_bazi.return_value = {}
        mock_table.scan.return_value = {
            'Items': [
                {'PK': 'PROFILE#u1', 'SK': 'META', 'userId': 'u1', 'displayName': 'A',
                 'age': 22, 'gender': 'female', 'location': '', 'avatarUrl': '', 'bio': ''},
                {'PK': 'PROFILE#u2', 'SK': 'META', 'userId': 'u2', 'displayName': 'B',
                 'age': 35, 'gender': 'male', 'location': '', 'avatarUrl': '', 'bio': ''},
            ]
        }

        resp = handler(
            _api_event('GET', '/discovery', query_params={'age_min': '25', 'age_max': '40'}),
            None,
        )

        body = json.loads(resp['body'])
        assert body['count'] == 1
        assert body['items'][0]['userId'] == 'u2'

    def test_unauthenticated_returns_401(self):
        resp = handler(_api_event('GET', '/discovery', user_id=None), None)
        assert resp['statusCode'] == 401
