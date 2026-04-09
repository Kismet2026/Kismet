import json
import os
import pytest
from unittest.mock import patch
from urllib.error import URLError

os.environ['BAZI_API_URL'] = 'https://mock-bazi-api/api/match'
os.environ['BAZI_API_KEY'] = 'test-key'

from lambda_function import handler


def _api_event(method, path, body=None, user_id='user-123'):
    event = {
        'httpMethod': method,
        'path': path,
        'requestContext': {
            'authorizer': {
                'claims': {'sub': user_id} if user_id else {}
            }
        },
    }
    if body:
        event['body'] = json.dumps(body)
    return event


class TestTopMatches:
    @patch('lambda_function._call_bazi_api')
    def test_success(self, mock_api):
        mock_api.return_value = {
            'matches': [
                {'ranking': 1, 'birthdate': '1991-06-20', 'score': 99},
                {'ranking': 2, 'birthdate': '1998-07-13', 'score': 95},
            ],
            'has_more': True,
        }

        resp = handler(_api_event('POST', '/bazi/top-matches', {
            'birthDate': '1995-11-21',
            'limit': 50,
        }), None)

        assert resp['statusCode'] == 200
        body = json.loads(resp['body'])
        assert body['birthDate'] == '1995-11-21'
        assert len(body['matches']) == 2
        assert body['matches'][0]['score'] == 99
        assert body['hasMore'] is True
        mock_api.assert_called_once_with('1995-11-21', 50)

    @patch('lambda_function._call_bazi_api')
    def test_default_limit(self, mock_api):
        mock_api.return_value = {'matches': [], 'has_more': False}

        handler(_api_event('POST', '/bazi/top-matches', {
            'birthDate': '1995-11-21',
        }), None)

        mock_api.assert_called_once_with('1995-11-21', 50)

    @patch('lambda_function._call_bazi_api')
    def test_limit_capped_at_200(self, mock_api):
        mock_api.return_value = {'matches': [], 'has_more': False}

        handler(_api_event('POST', '/bazi/top-matches', {
            'birthDate': '1995-11-21',
            'limit': 999,
        }), None)

        mock_api.assert_called_once_with('1995-11-21', 200)

    def test_missing_birthdate_returns_400(self):
        resp = handler(_api_event('POST', '/bazi/top-matches', {}), None)
        assert resp['statusCode'] == 400

    def test_no_body_returns_400(self):
        resp = handler(_api_event('POST', '/bazi/top-matches'), None)
        assert resp['statusCode'] == 400

    def test_unauthenticated_returns_401(self):
        resp = handler(_api_event('POST', '/bazi/top-matches', {
            'birthDate': '1995-11-21',
        }, user_id=None), None)
        assert resp['statusCode'] == 401

    @patch('lambda_function._call_bazi_api')
    def test_api_error_returns_502(self, mock_api):
        mock_api.side_effect = URLError('Connection refused')

        resp = handler(_api_event('POST', '/bazi/top-matches', {
            'birthDate': '1995-11-21',
        }), None)

        assert resp['statusCode'] == 502
        body = json.loads(resp['body'])
        assert body['code'] == 'UPSTREAM_ERROR'


class TestInputValidation:
    @patch('lambda_function._call_bazi_api')
    def test_bad_birthdate_format_returns_400(self, mock_api):
        resp = handler(_api_event('POST', '/bazi/top-matches', {
            'birthDate': '11-21-1995',
        }), None)
        assert resp['statusCode'] == 400
        body = json.loads(resp['body'])
        assert 'YYYY-MM-DD' in body['message']
        mock_api.assert_not_called()

    @patch('lambda_function._call_bazi_api')
    def test_bad_limit_uses_default(self, mock_api):
        mock_api.return_value = {'matches': [], 'has_more': False}
        resp = handler(_api_event('POST', '/bazi/top-matches', {
            'birthDate': '1995-11-21',
            'limit': 'abc',
        }), None)
        assert resp['statusCode'] == 200
        mock_api.assert_called_once_with('1995-11-21', 50)


class TestRouting:
    def test_unknown_route_returns_404(self):
        resp = handler(_api_event('GET', '/unknown'), None)
        assert resp['statusCode'] == 404

    def test_old_compatibility_endpoint_returns_404(self):
        resp = handler(_api_event('POST', '/bazi/compatibility', {
            'userABirthDate': '1998-03-15',
        }), None)
        assert resp['statusCode'] == 404

    def test_old_profile_endpoint_returns_404(self):
        resp = handler(_api_event('GET', '/bazi/profile/user-123'), None)
        assert resp['statusCode'] == 404
