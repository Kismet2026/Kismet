import json
import boto3
import os
from datetime import datetime
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')

TABLE_NAME = os.environ.get('TABLE_NAME', 'kismet-recommendations')
DISCOVERY_TABLE = os.environ.get('DISCOVERY_TABLE_NAME', 'kismet-discovery')
EVENT_BUS_NAME = os.environ.get('EVENT_BUS_NAME', 'kismet-events')

table = dynamodb.Table(TABLE_NAME)
discovery_table = dynamodb.Table(DISCOVERY_TABLE)


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj) if obj == int(obj) else float(obj)
        return super().default(obj)


def handler(event, context):
    # EventBridge: profile.completed → add to recommendation pool
    if event.get('source') == 'kismet.profile-service':
        return handle_profile_completed(event)

    # EventBridge: swipe.created → remove swiped candidate
    if event.get('source') == 'kismet.swipe-service':
        return handle_swipe_created(event)

    method = _get_method(event)
    path = _get_path(event)

    if method == 'GET' and path == '/recommend':
        return get_recommendations(event)
    elif method == 'POST' and path == '/recommend/refresh':
        return refresh_recommendations(event)
    else:
        return _response(404, {'code': 'NOT_FOUND', 'message': f'No route: {method} {path}'})


def handle_profile_completed(event):
    """When a new user completes profile, compute scores for existing users."""
    detail = event.get('detail', {})
    new_user_id = detail.get('userId')
    if not new_user_id:
        return {'statusCode': 400, 'body': 'Missing userId'}

    # In production, iterate existing users and compute pairwise scores.
    # For MVP, scores are computed on-demand in get_recommendations.
    return {'statusCode': 200, 'body': 'Profile noted for recommendation'}


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
    limit = min(int(params.get('limit', 20)), 50)

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
        items = _compute_recommendations(user_id, limit)

    recommendations = [{
        'userId': item.get('candidateUserId', ''),
        'displayName': item.get('displayName', ''),
        'age': item.get('age', 0),
        'gender': item.get('gender', ''),
        'location': item.get('location', ''),
        'avatarUrl': item.get('avatarUrl', ''),
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

    # Get all candidate profiles from discovery table
    result = discovery_table.scan(
        FilterExpression=Key('SK').eq('META') & Attr('userId').ne(user_id),
        Limit=200,
    )

    candidates = []
    timestamp = datetime.utcnow().isoformat() + 'Z'

    for profile in result.get('Items', []):
        candidate_id = profile.get('userId', '')
        score_breakdown = _calculate_score(profile)
        total_score = sum(score_breakdown.values())

        candidate = {
            'PK': f'USER#{user_id}',
            'SK': f'SCORE#{total_score:04d}#{candidate_id}',
            'candidateUserId': candidate_id,
            'displayName': profile.get('displayName', ''),
            'age': profile.get('age', 0),
            'gender': profile.get('gender', ''),
            'location': profile.get('location', ''),
            'avatarUrl': profile.get('avatarUrl', ''),
            'score': total_score,
            'scoreBreakdown': score_breakdown,
            'calculatedAt': timestamp,
        }
        candidates.append(candidate)

        # Cache in DynamoDB
        table.put_item(Item=json.loads(json.dumps(candidate), parse_float=Decimal, parse_int=Decimal))

    # Sort by score descending
    candidates.sort(key=lambda x: x.get('score', 0), reverse=True)
    return candidates[:limit]


def _calculate_score(profile):
    """Simple scoring — in production, would call BaZi service and use richer signals."""
    import random
    random.seed(hash(profile.get('userId', '')))

    return {
        'locationProximity': random.randint(10, 30),
        'sharedInterests': random.randint(5, 25),
        'baziCompatibility': random.randint(15, 40),
        'activityRecency': random.randint(5, 15),
    }


# --- Helpers ---

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
