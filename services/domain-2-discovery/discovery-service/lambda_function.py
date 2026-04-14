import json
import boto3
import os
import logging
from datetime import datetime
from decimal import Decimal
from urllib import request as urllib_request
from urllib.error import URLError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')

TABLE_NAME = os.environ.get('TABLE_NAME', 'kismet-discovery')
SWIPE_TABLE_NAME = os.environ.get('SWIPE_TABLE_NAME', 'kismet-swipes')
EVENT_BUS_NAME = os.environ.get('EVENT_BUS_NAME', 'kismet-events')
BAZI_API_URL = os.environ.get('BAZI_API_URL', 'https://match-date-nu.vercel.app/api/match')
BAZI_API_KEY = os.environ.get('BAZI_API_KEY', '')
if not BAZI_API_KEY:
    logger.warning('BAZI_API_KEY not set — BaZi API calls will fail')

table = dynamodb.Table(TABLE_NAME)
swipe_table = dynamodb.Table(SWIPE_TABLE_NAME)


def handler(event, context):
    detail_type = event.get('detail-type') or event.get('detailType')

    if event.get('source') == 'kismet.profile-service':
        if detail_type == 'profile.completed':
            logger.info('EventBridge: profile.completed')
            return handle_profile_completed(event)
        if detail_type == 'profile.banned':
            logger.info('EventBridge: profile.banned')
            return handle_profile_banned(event)
        logger.info('Ignoring profile-service event: %s', detail_type)
        return {'statusCode': 200, 'body': 'Ignored event'}

    method = _get_method(event)
    path = _get_path(event)
    logger.info('Request: %s %s', method, path)

    if method == 'GET' and path == '/discovery':
        return get_candidates(event)
    else:
        return _response(404, {'code': 'NOT_FOUND', 'message': f'No route: {method} {path}'})


def handle_profile_completed(event):
    """Index a new user as a candidate when they complete their profile."""
    detail = event.get('detail', {})
    user_id = detail.get('userId')
    if not user_id:
        return {'statusCode': 400, 'body': 'Missing userId'}

    timestamp = datetime.utcnow().isoformat() + 'Z'

    # Compute age from birthDate (event doesn't carry age directly)
    age = _calculate_age(detail.get('birthDate', ''))

    # location_coordinates comes as [lat, lng] from profile.completed event
    location = detail.get('location_coordinates', [])

    birth_date = detail.get('birthDate', '')

    logger.info('Indexing profile: userId=%s birthDate=%s', user_id, birth_date)
    table.put_item(Item={
        'PK': f'PROFILE#{user_id}',
        'SK': 'META',
        'userId': user_id,
        'displayName': detail.get('name', ''),
        'gender': detail.get('gender', ''),
        'preferredGender': detail.get('preferred_gender', ''),
        'location': [Decimal(str(v)) for v in location] if location else [],
        'city': detail.get('city', ''),
        'age': age,
        'birthDate': birth_date,
        'avatarUrl': detail.get('avatarUrl', ''),
        'bio': detail.get('bio', '')[:500],
        'cachedAt': timestamp,
    })

    # Pre-warm BaZi cache for this birthDate (if not already cached)
    if birth_date:
        _ensure_bazi_cache(birth_date)

    return {'statusCode': 200, 'body': 'Profile indexed'}


def handle_profile_banned(event):
    """Remove a banned user from the discovery pool."""
    detail = _get_event_detail(event)
    user_id = detail.get('userId')
    if not user_id:
        return {'statusCode': 400, 'body': 'Missing userId'}

    table.delete_item(Key={
        'PK': f'PROFILE#{user_id}',
        'SK': 'META',
    })
    return {'statusCode': 200, 'body': 'Profile removed from discovery'}


def get_candidates(event):
    user_id = _get_user_id(event)
    if not user_id:
        return _response(401, {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'})

    params = event.get('queryStringParameters') or {}
    limit = _safe_int(params.get('limit'), 20, 1, 50)
    age_min = _safe_int(params.get('age_min'), 0, 0, 200)
    age_max = _safe_int(params.get('age_max'), 200, 0, 200)
    gender_filter = params.get('gender')
    cursor = params.get('cursor')

    from boto3.dynamodb.conditions import Key, Attr

    # Get user's already-swiped targets to exclude them
    swiped_ids = _get_swiped_user_ids(user_id)

    # Get current user's birthDate for BaZi scoring
    bazi_scores = _get_bazi_scores_for_user(user_id)

    # Scan all profiles (in production, use GSI or pre-computed candidate lists)
    scan_params = {
        'FilterExpression': Key('SK').eq('META') & Attr('userId').ne(user_id),
        'Limit': limit * 3,  # over-fetch to account for filters
    }

    if cursor:
        try:
            import base64
            scan_params['ExclusiveStartKey'] = json.loads(
                base64.b64decode(cursor).decode()
            )
        except (json.JSONDecodeError, Exception):
            return _response(400, {'code': 'VALIDATION_ERROR', 'message': 'Invalid cursor'})

    result = table.scan(**scan_params)

    candidates = []
    for item in result.get('Items', []):
        candidate_id = item['userId']

        # Skip already-swiped users
        if candidate_id in swiped_ids:
            continue

        age = item.get('age', 0)
        if isinstance(age, (str, float)):
            age = int(age) if str(age).replace('.', '').isdigit() else 0

        if age < age_min or age > age_max:
            continue
        if gender_filter and item.get('gender') != gender_filter:
            continue

        # Look up BaZi score by candidate's birthDate
        candidate_birth = item.get('birthDate', '')
        bazi_score = bazi_scores.get(candidate_birth)

        candidates.append({
            'userId': candidate_id,
            'displayName': item.get('displayName', ''),
            'age': age,
            'gender': item.get('gender', ''),
            'location': item.get('location', ''),
            'city': item.get('city', ''),
            'avatarUrl': item.get('avatarUrl', ''),
            'bio': item.get('bio', ''),
            'baziScore': bazi_score,
        })

        if len(candidates) >= limit:
            break

    logger.info('Candidates returned: %d (limit=%d, swiped=%d)', len(candidates), limit, len(swiped_ids))
    response_body = {'items': candidates, 'count': len(candidates)}

    if 'LastEvaluatedKey' in result and len(candidates) >= limit:
        import base64
        response_body['nextCursor'] = base64.b64encode(
            json.dumps(result['LastEvaluatedKey']).encode()
        ).decode()

    return _response(200, response_body)


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


def _calculate_age(birth_date_str):
    """Calculate age from YYYY-MM-DD birth date string."""
    if not birth_date_str:
        return 0
    try:
        birth = datetime.strptime(birth_date_str, '%Y-%m-%d')
        today = datetime.utcnow()
        age = today.year - birth.year
        if (today.month, today.day) < (birth.month, birth.day):
            age -= 1
        return age
    except ValueError:
        return 0


def _get_bazi_scores_for_user(user_id):
    """Get BaZi scores for a user. Reads from cache, falls back to API."""
    # Look up user's own birthDate
    result = table.get_item(Key={'PK': f'PROFILE#{user_id}', 'SK': 'META'})
    user_profile = result.get('Item')
    if not user_profile or not user_profile.get('birthDate'):
        return {}

    birth_date = user_profile['birthDate']
    return _ensure_bazi_cache(birth_date)


def _ensure_bazi_cache(birth_date):
    """Read BaZi cache for a birthDate. If cache miss, call API and store. Returns {date: score} dict."""
    cache_key = {'PK': f'BAZI#{birth_date}', 'SK': 'SCORES'}

    # Try cache first
    result = table.get_item(Key=cache_key)
    cached = result.get('Item')
    if cached and 'scores' in cached:
        logger.info('BaZi cache hit: birthDate=%s', birth_date)
        # DynamoDB stores numbers as Decimal — convert to int for JSON
        return {k: int(v) for k, v in cached['scores'].items()}

    # Cache miss — call external API
    logger.info('BaZi cache miss: birthDate=%s, calling API', birth_date)
    try:
        scores = _call_bazi_api(birth_date)
    except (URLError, ValueError) as e:
        logger.error('BaZi API error for birthDate=%s: %s', birth_date, e)
        return {}

    # Write to cache (birthDate never changes, so no TTL needed)
    if scores:
        table.put_item(Item={
            **cache_key,
            'birthDate': birth_date,
            'scores': scores,
            'cachedAt': datetime.utcnow().isoformat() + 'Z',
        })

    return scores


def _call_bazi_api(birth_date):
    """Call external BaZi API and return {birthdate: score} lookup dict."""
    payload = json.dumps({'birth_date': birth_date, 'limit': 200}).encode()
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
        data = json.loads(resp.read().decode())

    return {m['birthdate']: m['score'] for m in data.get('matches', [])}


def _get_swiped_user_ids(user_id):
    """Get set of user IDs that this user has already swiped on."""
    from boto3.dynamodb.conditions import Key
    swiped = set()
    result = swipe_table.query(
        KeyConditionExpression=Key('userId').eq(user_id),
        ProjectionExpression='targetUserId',
    )
    for item in result.get('Items', []):
        swiped.add(item['targetUserId'])

    # Handle pagination for users with many swipes
    while 'LastEvaluatedKey' in result:
        result = swipe_table.query(
            KeyConditionExpression=Key('userId').eq(user_id),
            ProjectionExpression='targetUserId',
            ExclusiveStartKey=result['LastEvaluatedKey'],
        )
        for item in result.get('Items', []):
            swiped.add(item['targetUserId'])

    return swiped


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


def _get_event_detail(event):
    detail = event.get('detail') or {}
    if isinstance(detail, dict):
        return detail
    if isinstance(detail, str):
        try:
            parsed = json.loads(detail)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


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
        'body': json.dumps(body, default=str),
    }
