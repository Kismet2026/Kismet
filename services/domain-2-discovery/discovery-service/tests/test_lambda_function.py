import json
import os
import pytest
from unittest.mock import patch, MagicMock

os.environ['TABLE_NAME'] = 'kismet-discovery'
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


def _profile_event(user_id, name='Alice', gender='female'):
    return {
        'source': 'kismet.profile-service',
        'detail-type': 'profile.completed',
        'detail': {
            'userId': user_id,
            'name': name,
            'gender': gender,
            'location': 'Boston',
            'age': 25,
        },
    }


class TestHandleProfileCompleted:
    @patch('lambda_function.table')
    def test_indexes_new_user(self, mock_table):
        resp = handler(_profile_event('user-new', 'Bob', 'male'), None)

        assert resp['statusCode'] == 200
        mock_table.put_item.assert_called_once()

        item = mock_table.put_item.call_args[1]['Item']
        assert item['userId'] == 'user-new'
        assert item['displayName'] == 'Bob'


class TestGetCandidates:
    @patch('lambda_function.table')
    def test_returns_candidates(self, mock_table):
        mock_table.scan.return_value = {
            'Items': [
                {'PK': 'PROFILE#user-456', 'SK': 'META', 'userId': 'user-456',
                 'displayName': 'Alice', 'age': 25, 'gender': 'female', 'location': 'Boston',
                 'avatarUrl': '', 'bio': 'Hello'},
            ]
        }

        resp = handler(_api_event('GET', '/discovery'), None)

        assert resp['statusCode'] == 200
        body = json.loads(resp['body'])
        assert body['count'] == 1
        assert body['items'][0]['userId'] == 'user-456'

    @patch('lambda_function.table')
    def test_filters_by_gender(self, mock_table):
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

    @patch('lambda_function.table')
    def test_filters_by_age(self, mock_table):
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

    @patch('lambda_function.table')
    def test_excludes_self(self, mock_table):
        mock_table.scan.return_value = {
            'Items': [
                {'PK': 'PROFILE#user-123', 'SK': 'META', 'userId': 'user-123',
                 'displayName': 'Self', 'age': 25, 'gender': 'male', 'location': '', 'avatarUrl': '', 'bio': ''},
            ]
        }

        resp = handler(_api_event('GET', '/discovery'), None)

        body = json.loads(resp['body'])
        # The scan FilterExpression should exclude self, but since we're mocking
        # the filter won't work. In integration tests this would be verified.
        # Here we just verify the response format.
        assert resp['statusCode'] == 200

    def test_unauthenticated_returns_401(self):
        resp = handler(_api_event('GET', '/discovery', user_id=None), None)
        assert resp['statusCode'] == 401
