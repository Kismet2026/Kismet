import json
import os
import pytest

from lambda_function import handler, _compute_bazi_chart, _compute_compatibility_score


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


class TestBaziChart:
    def test_compute_chart_returns_four_pillars(self):
        chart = _compute_bazi_chart('1998-03-15', '14:30')

        assert 'year' in chart
        assert 'month' in chart
        assert 'day' in chart
        assert 'hour' in chart

        for pillar in chart.values():
            assert 'stem' in pillar
            assert 'branch' in pillar
            assert 'element' in pillar

    def test_different_dates_produce_different_charts(self):
        chart_a = _compute_bazi_chart('1998-03-15', '14:30')
        chart_b = _compute_bazi_chart('1997-08-22', '09:00')

        # At least some pillars should differ
        differs = False
        for pillar in ['year', 'month', 'day', 'hour']:
            if chart_a[pillar]['stem'] != chart_b[pillar]['stem']:
                differs = True
                break
        assert differs

    def test_invalid_date_raises_error(self):
        with pytest.raises(ValueError):
            _compute_bazi_chart('not-a-date', '14:30')

    def test_invalid_time_raises_error(self):
        with pytest.raises(ValueError):
            _compute_bazi_chart('1998-03-15', 'bad')


class TestCompatibilityScore:
    def test_score_in_range(self):
        chart_a = _compute_bazi_chart('1998-03-15', '14:30')
        chart_b = _compute_bazi_chart('1997-08-22', '09:00')

        score = _compute_compatibility_score(chart_a, chart_b)
        assert 0 <= score <= 100

    def test_same_person_has_high_score(self):
        chart = _compute_bazi_chart('1998-03-15', '14:30')
        score = _compute_compatibility_score(chart, chart)
        assert score >= 60  # same elements → bonus


class TestCompatibilityEndpoint:
    def test_success(self):
        resp = handler(_api_event('POST', '/bazi/compatibility', {
            'userABirthDate': '1998-03-15',
            'userABirthTime': '14:30',
            'userBBirthDate': '1997-08-22',
            'userBBirthTime': '09:00',
        }), None)

        assert resp['statusCode'] == 200
        body = json.loads(resp['body'])
        assert 0 <= body['compatibilityScore'] <= 100
        assert 'analysis' in body
        assert 'userAElements' in body
        assert 'userBElements' in body

    def test_missing_field_returns_400(self):
        resp = handler(_api_event('POST', '/bazi/compatibility', {
            'userABirthDate': '1998-03-15',
        }), None)
        assert resp['statusCode'] == 400

    def test_invalid_date_returns_400(self):
        resp = handler(_api_event('POST', '/bazi/compatibility', {
            'userABirthDate': 'bad',
            'userABirthTime': '14:30',
            'userBBirthDate': '1997-08-22',
            'userBBirthTime': '09:00',
        }), None)
        assert resp['statusCode'] == 400

    def test_unauthenticated_returns_401(self):
        resp = handler(_api_event('POST', '/bazi/compatibility', {
            'userABirthDate': '1998-03-15',
            'userABirthTime': '14:30',
            'userBBirthDate': '1997-08-22',
            'userBBirthTime': '09:00',
        }, user_id=None), None)
        assert resp['statusCode'] == 401


class TestBaziProfileEndpoint:
    def test_success(self):
        resp = handler(_api_event(
            'GET', '/bazi/profile/user-456',
            query_params={'birthDate': '1998-03-15', 'birthTime': '14:30'},
        ), None)

        assert resp['statusCode'] == 200
        body = json.loads(resp['body'])
        assert body['userId'] == 'user-456'
        assert 'baziChart' in body
        assert 'fiveElements' in body
        assert 'summary' in body

    def test_no_birth_data_returns_404(self):
        resp = handler(_api_event('GET', '/bazi/profile/user-456'), None)
        assert resp['statusCode'] == 404


class TestRouting:
    def test_unknown_route_returns_404(self):
        resp = handler(_api_event('GET', '/unknown'), None)
        assert resp['statusCode'] == 404
