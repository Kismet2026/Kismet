import json
import boto3
import os
from datetime import datetime
from urllib import request as urllib_request
from urllib.error import URLError

dynamodb = boto3.resource('dynamodb')

TABLE_NAME = os.environ.get('TABLE_NAME', 'kismet-discovery')
SWIPE_TABLE_NAME = os.environ.get('SWIPE_TABLE_NAME', 'kismet-swipes')
EVENT_BUS_NAME = os.environ.get('EVENT_BUS_NAME', 'kismet-events')
BAZI_API_URL = os.environ.get('BAZI_API_URL', 'https://match-date-nu.vercel.app/api/match')
BAZI_API_KEY = os.environ.get('BAZI_API_KEY', 'ABC')

table = dynamodb.Table(TABLE_NAME)
swipe_table = dynamodb.Table(SWIPE_TABLE_NAME)


def handler(event, context):
    # EventBridge event (profile.completed)
    if event.get('source') == 'kismet.profile-service':
        return handle_profile_completed(event)

    method = _get_method(event)
    path = _get_path(event)

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

    table.put_item(Item={
        'PK': f'PROFILE#{user_id}',
        'SK': 'META',
        'userId': user_id,
        'displayName': detail.get('name', ''),
        'gender': detail.get('gender', ''),
        'preferredGender': detail.get('preferred_gender', ''),
        'location': location,
        'city': detail.get('city', ''),
        'age': age,
        'birthDate': birth_date,
        'avatarUrl': detail.get('avatarUrl', ''),
        'bio': detail.get('bio', ''),
        'cachedAt': timestamp,
    })

    # Pre-warm BaZi cache for this birthDate (if not already cached)
    if birth_date:
        _ensure_bazi_cache(birth_date)

    return {'statusCode': 200, 'body': 'Profile indexed'}


def get_candidates(event):
    user_id = _get_user_id(event)
    if not user_id:
        return _response(401, {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'})

    params = event.get('queryStringParameters') or {}
    limit = min(int(params.get('limit', 20)), 50)
    age_min = int(params.get('age_min', 0))
    age_max = int(params.get('age_max', 200))
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
        import base64
        scan_params['ExclusiveStartKey'] = json.loads(
            base64.b64decode(cursor).decode()
        )

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

    response_body = {'items': candidates, 'count': len(candidates)}

    if 'LastEvaluatedKey' in result and len(candidates) >= limit:
        import base64
        response_body['nextCursor'] = base64.b64encode(
            json.dumps(result['LastEvaluatedKey']).encode()
        ).decode()

    return _response(200, response_body)


# --- Helpers ---

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
        # DynamoDB stores numbers as Decimal — convert to int for JSON
        return {k: int(v) for k, v in cached['scores'].items()}

    # Cache miss — call external API
    try:
        scores = _call_bazi_api(birth_date)
    except (URLError, ValueError):
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
        'body': json.dumps(body),
    }
