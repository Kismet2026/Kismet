import json
import boto3
import os
import logging
from datetime import datetime
from decimal import Decimal

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')

TABLE_NAME = os.environ.get('TABLE_NAME', 'kismet-recommendations')
DISCOVERY_TABLE = os.environ.get('DISCOVERY_TABLE_NAME', 'kismet-discovery')
SWIPE_TABLE_NAME = os.environ.get('SWIPE_TABLE_NAME', 'kismet-swipes')
EVENT_BUS_NAME = os.environ.get('EVENT_BUS_NAME', 'kismet-events')

table = dynamodb.Table(TABLE_NAME)
discovery_table = dynamodb.Table(DISCOVERY_TABLE)
swipe_table = dynamodb.Table(SWIPE_TABLE_NAME)


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj) if obj == int(obj) else float(obj)
        return super().default(obj)


def handler(event, context):
    # EventBridge: profile.completed → add to recommendation pool
    if event.get('source') == 'kismet.profile-service':
        detail_type = event.get('detail-type') or event.get('detailType')
        if detail_type == 'profile.completed':
            logger.info('EventBridge: profile.completed')
            return handle_profile_completed(event)
        if detail_type == 'user.deleted':
            logger.info('EventBridge: user.deleted')
            return handle_user_deleted(event)

    # EventBridge: swipe.created → remove swiped candidate
    if event.get('source') == 'kismet.swipe-service':
        logger.info('EventBridge: swipe.created')
        return handle_swipe_created(event)

    method = _get_method(event)
    path = _get_path(event)
    logger.info('Request: %s %s', method, path)

    if method == 'GET' and path == '/recommend':
        return get_recommendations(event)
    elif method == 'POST' and path == '/recommend/refresh':
        return refresh_recommendations(event)
    else:
        return _response(404, {'code': 'NOT_FOUND', 'message': f'No route: {method} {path}'})


def handle_user_deleted(event):
    """Delete all recommendation cache entries for a deleted user."""
    detail = event.get('detail') or {}
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except (json.JSONDecodeError, TypeError):
            detail = {}
    user_id = detail.get('userId')
    if not user_id:
        logger.warning('user.deleted event missing userId')
        return {'statusCode': 400, 'body': 'Missing userId'}

    from boto3.dynamodb.conditions import Key
    result = table.query(
        KeyConditionExpression=Key('PK').eq(f'USER#{user_id}'),
    )
    with table.batch_writer() as batch:
        for item in result.get('Items', []):
            batch.delete_item(Key={'PK': item['PK'], 'SK': item['SK']})
    while 'LastEvaluatedKey' in result:
        result = table.query(
            KeyConditionExpression=Key('PK').eq(f'USER#{user_id}'),
            ExclusiveStartKey=result['LastEvaluatedKey'],
        )
        with table.batch_writer() as batch:
            for item in result.get('Items', []):
                batch.delete_item(Key={'PK': item['PK'], 'SK': item['SK']})

    logger.info('Deleted recommendation cache for user %s', user_id)
    return {'statusCode': 200, 'body': 'Recommendation cache deleted'}


def handle_profile_completed(event):
    """When a new user completes profile, invalidate cached recommendations for all users.
    New candidate in the pool means existing caches may be stale.
    For MVP, we just note it — caches are lazy-recomputed on next GET /recommend."""
    detail = event.get('detail', {})
    new_user_id = detail.get('userId')
    if not new_user_id:
        return {'statusCode': 400, 'body': 'Missing userId'}

    # Store a marker so get_recommendations knows the pool changed
    table.put_item(Item={
        'PK': 'SYSTEM',
        'SK': 'LAST_PROFILE_UPDATE',
        'userId': new_user_id,
        'updatedAt': datetime.utcnow().isoformat() + 'Z',
    })

    return {'statusCode': 200, 'body': 'Profile noted, caches will refresh on next request'}


def handle_swipe_created(event):
    """Remove swiped candidate from user's recommendation cache."""
    detail = event.get('detail', {})
    user_id = detail.get('userId')
    target_id = detail.get('targetUserId')

    if not user_id or not target_id:
        return {'statusCode': 400, 'body': 'Missing fields'}

    # Delete the recommendation entry for this candidate
    from boto3.dynamodb.conditions import Key, Attr
    results = table.query(
        KeyConditionExpression=Key('PK').eq(f'USER#{user_id}'),
        FilterExpression=Attr('candidateUserId').eq(target_id),
    )

    for item in results.get('Items', []):
        table.delete_item(Key={'PK': item['PK'], 'SK': item['SK']})

    return {'statusCode': 200, 'body': 'Candidate removed from recommendations'}


def get_recommendations(event):
    user_id = _get_user_id(event)
    if not user_id:
        return _response(401, {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'})

    params = event.get('queryStringParameters') or {}
    limit = _safe_int(params.get('limit'), 20, 1, 50)

    from boto3.dynamodb.conditions import Key

    # Try cached recommendations first
    result = table.query(
        KeyConditionExpression=Key('PK').eq(f'USER#{user_id}') & Key('SK').begins_with('SCORE#'),
        ScanIndexForward=False,
        Limit=limit,
    )

    items = result.get('Items', [])

    # If no cached recommendations, compute on the fly
    if not items:
        logger.info('No cached recommendations for user=%s, computing', user_id)
        items = _compute_recommendations(user_id, limit)
    else:
        logger.info('Returning %d cached recommendations for user=%s', len(items), user_id)

    recommendations = [{
        'userId': item.get('candidateUserId', ''),
        'displayName': item.get('displayName', ''),
        'age': item.get('age', 0),
        'gender': item.get('gender', ''),
        'location': item.get('location', ''),
        'avatarUrl': item.get('avatarUrl', ''),
        'bio': item.get('bio', ''),
        'city': item.get('city', ''),
        'baziScore': item.get('baziScore'),
        'reverseBaziScore': item.get('reverseBaziScore'),
        'score': item.get('score', 0),
        'scoreBreakdown': item.get('scoreBreakdown', {}),
    } for item in items]

    return _response(200, json.loads(
        json.dumps({'items': recommendations, 'count': len(recommendations)}, cls=DecimalEncoder)
    ))


def refresh_recommendations(event):
    user_id = _get_user_id(event)
    if not user_id:
        return _response(401, {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'})

    # Clear existing cache
    from boto3.dynamodb.conditions import Key
    old = table.query(
        KeyConditionExpression=Key('PK').eq(f'USER#{user_id}') & Key('SK').begins_with('SCORE#'),
    )
    for item in old.get('Items', []):
        table.delete_item(Key={'PK': item['PK'], 'SK': item['SK']})

    # Recompute
    items = _compute_recommendations(user_id, 50)
    timestamp = datetime.utcnow().isoformat() + 'Z'

    return _response(200, json.loads(json.dumps({
        'status': 'refreshed',
        'candidateCount': len(items),
        'refreshedAt': timestamp,
    }, cls=DecimalEncoder)))


def _compute_recommendations(user_id, limit):
    """Compute recommendation scores for a user from the discovery pool."""
    from boto3.dynamodb.conditions import Key, Attr

    # Get user's own profile for BaZi lookup
    user_profile = discovery_table.get_item(
        Key={'PK': f'PROFILE#{user_id}', 'SK': 'META'}
    ).get('Item', {})
    user_birth = user_profile.get('birthDate', '')

    # Get BaZi scores from discovery table cache
    bazi_scores = {}
    if user_birth:
        bazi_result = discovery_table.get_item(
            Key={'PK': f'BAZI#{user_birth}', 'SK': 'SCORES'}
        ).get('Item', {})
        raw_scores = bazi_result.get('scores', {})
        bazi_scores = {k: int(v) for k, v in raw_scores.items()}

    # Get already-swiped users to exclude
    swiped_ids = _get_swiped_user_ids(user_id)

    # Get all candidate profiles from discovery table
    result = discovery_table.scan(
        FilterExpression=Key('SK').eq('META') & Attr('userId').ne(user_id),
        Limit=200,
    )

    # Collect unique candidate birth dates to batch-lookup reverse BaZi scores
    candidate_birth_dates = set()
    for profile in result.get('Items', []):
        if profile.get('userId') not in swiped_ids:
            b = profile.get('birthDate', '')
            if b:
                candidate_birth_dates.add(b)

    # Reverse BaZi lookup: candidate's cache → user's score
    reverse_bazi = _fetch_reverse_bazi_scores(candidate_birth_dates, user_birth)

    candidates = []
    timestamp = datetime.utcnow().isoformat() + 'Z'

    for profile in result.get('Items', []):
        candidate_id = profile.get('userId', '')

        # Skip already-swiped
        if candidate_id in swiped_ids:
            continue

        score_breakdown = _calculate_score(profile, bazi_scores)
        total_score = sum(score_breakdown.values())

        candidate_birth = profile.get('birthDate', '')
        raw_bazi = bazi_scores.get(candidate_birth)
        reverse_score = reverse_bazi.get(candidate_birth)
        candidate = {
            'PK': f'USER#{user_id}',
            'SK': f'SCORE#{total_score:04d}#{candidate_id}',
            'candidateUserId': candidate_id,
            'displayName': profile.get('displayName', ''),
            'age': profile.get('age', 0),
            'gender': profile.get('gender', ''),
            'location': profile.get('location', ''),
            'city': profile.get('city', ''),
            'avatarUrl': profile.get('avatarUrl', ''),
            'bio': profile.get('bio', ''),
            'baziScore': raw_bazi,
            'reverseBaziScore': reverse_score,
            'score': total_score,
            'scoreBreakdown': score_breakdown,
            'calculatedAt': timestamp,
        }
        candidates.append(candidate)

        # Cache in DynamoDB
        table.put_item(Item=json.loads(json.dumps(candidate, default=str), parse_float=Decimal, parse_int=Decimal))

    # Sort by score descending
    candidates.sort(key=lambda x: x.get('score', 0), reverse=True)
    logger.info('Computed %d recommendations for user=%s (swiped=%d excluded)', len(candidates), user_id, len(swiped_ids))
    return candidates[:limit]


def _calculate_score(profile, bazi_scores):
    """Score a candidate using BaZi compatibility + profile completeness signals."""
    candidate_birth = profile.get('birthDate', '')

    # BaZi compatibility (0-99 from external API, scaled to 0-40 weight)
    raw_bazi = bazi_scores.get(candidate_birth)
    bazi_score = int(raw_bazi * 40 / 100) if raw_bazi is not None else 20  # default 20 if unknown

    # Profile completeness (has avatar, bio, etc.)
    completeness = 0
    if profile.get('avatarUrl'):
        completeness += 8
    if profile.get('bio'):
        completeness += 7
    if profile.get('city'):
        completeness += 5

    # Activity recency — placeholder until we have real login data
    recency = 10

    return {
        'baziCompatibility': bazi_score,
        'profileCompleteness': completeness,
        'activityRecency': recency,
    }


def _fetch_reverse_bazi_scores(candidate_birth_dates, user_birth):
    """For each candidate birthDate, look up user's score in that candidate's BaZi cache.

    Returns dict {candidate_birthDate: score_or_None}. Uses batch_get_item for efficiency.
    """
    if not user_birth or not candidate_birth_dates:
        return {}

    reverse = {}
    birth_list = list(candidate_birth_dates)
    # DynamoDB batch_get_item supports up to 100 keys per call
    for i in range(0, len(birth_list), 100):
        batch = birth_list[i:i + 100]
        keys = [{'PK': f'BAZI#{b}', 'SK': 'SCORES'} for b in batch]
        try:
            response = dynamodb.batch_get_item(
                RequestItems={DISCOVERY_TABLE: {'Keys': keys}}
            )
            for item in response.get('Responses', {}).get(DISCOVERY_TABLE, []):
                candidate_birth = item.get('birthDate', '')
                scores = item.get('scores', {})
                score = scores.get(user_birth)
                if score is not None:
                    reverse[candidate_birth] = int(score)
        except Exception as e:
            logger.warning('Reverse BaZi batch read failed: %s', e)

    return reverse


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
    while 'LastEvaluatedKey' in result:
        result = swipe_table.query(
            KeyConditionExpression=Key('userId').eq(user_id),
            ProjectionExpression='targetUserId',
            ExclusiveStartKey=result['LastEvaluatedKey'],
        )
        for item in result.get('Items', []):
            swiped.add(item['targetUserId'])
    return swiped


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
        'body': json.dumps(body, cls=DecimalEncoder),
    }
