import json
import os
import re
import logging
from urllib import request as urllib_request
from urllib.error import URLError

# BaZi (八字) compatibility service
# Proxies to external BaZi API for compatibility scoring.
# TODO: Add 1v1 compatibility endpoint when external API supports it.

logger = logging.getLogger()
logger.setLevel(logging.INFO)

BAZI_API_URL = os.environ.get('BAZI_API_URL', 'https://match-date-nu.vercel.app/api/match')
BAZI_API_KEY = os.environ.get('BAZI_API_KEY', '')
if not BAZI_API_KEY:
    logger.warning('BAZI_API_KEY not set — BaZi API calls will fail')


def handler(event, context):
    method = _get_method(event)
    path = _get_path(event)
    logger.info('Request: %s %s', method, path)

    if method == 'POST' and path == '/bazi/top-matches':
        return get_top_matches(event)
    else:
        return _response(404, {'code': 'NOT_FOUND', 'message': f'No route: {method} {path}'})


def get_top_matches(event):
    """Return top matching birthdates from external BaZi API."""
    user_id = _get_user_id(event)
    if not user_id:
        return _response(401, {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'})

    body = _parse_body(event)
    if not body or 'birthDate' not in body:
        return _response(400, {'code': 'VALIDATION_ERROR', 'message': 'Missing field: birthDate'})

    if not re.match(r'^\d{4}-\d{2}-\d{2}$', body['birthDate']):
        return _response(400, {'code': 'VALIDATION_ERROR', 'message': 'birthDate must be YYYY-MM-DD format'})

    limit = _safe_int(body.get('limit'), 50, 1, 200)
    logger.info('BaZi top-matches: birthDate=%s limit=%d', body['birthDate'], limit)

    try:
        result = _call_bazi_api(body['birthDate'], limit)
    except (URLError, ValueError) as e:
        logger.error('BaZi API error: %s', e)
        return _response(502, {'code': 'UPSTREAM_ERROR', 'message': f'BaZi API error: {str(e)}'})

    return _response(200, {
        'birthDate': body['birthDate'],
        'matches': result.get('matches', []),
        'hasMore': result.get('has_more', False),
    })


def _call_bazi_api(birth_date, limit=50):
    """Call external BaZi matching API."""
    payload = json.dumps({'birth_date': birth_date, 'limit': limit}).encode()
    req = urllib_request.Request(
        BAZI_API_URL,
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'X-API-KEY': BAZI_API_KEY,
        },
        method='POST',
    )
    with urllib_request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


# --- Helpers ---

def _safe_int(val, default, min_val=0, max_val=None):
    try:
        result = int(val)
        result = max(result, min_val)
        if max_val is not None:
            result = min(result, max_val)
        return result
    except (ValueError, TypeError):
        return default


def _get_method(event):
    return (
        event.get('requestContext', {}).get('http', {}).get('method')
        or event.get('httpMethod')
        or ''
    ).upper()


def _get_path(event):
    path = (
        event.get('rawPath')
        or event.get('path')
        or event.get('requestContext', {}).get('http', {}).get('path')
        or '/'
    )
    return path.rstrip('/') if path != '/' else path


def _get_user_id(event):
    claims = (
        event.get('requestContext', {}).get('authorizer', {}).get('claims')
        or event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims')
        or {}
    )
    return claims.get('sub') or claims.get('cognito:username')


def _parse_body(event):
    body = event.get('body')
    if not body:
        return None
    if isinstance(body, dict):
        return body
    try:
        return json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None


CORS_HEADERS = {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type,Authorization',
    'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS',
}


def _response(status_code, body):
    return {
        'statusCode': status_code,
        'headers': CORS_HEADERS,
        'body': json.dumps(body, ensure_ascii=False),
    }
