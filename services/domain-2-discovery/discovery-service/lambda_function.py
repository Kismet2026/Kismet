import json
import boto3
import os
from datetime import datetime

dynamodb = boto3.resource('dynamodb')

TABLE_NAME = os.environ.get('TABLE_NAME', 'kismet-discovery')
EVENT_BUS_NAME = os.environ.get('EVENT_BUS_NAME', 'kismet-events')

table = dynamodb.Table(TABLE_NAME)


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

    table.put_item(Item={
        'PK': f'PROFILE#{user_id}',
        'SK': 'META',
        'userId': user_id,
        'displayName': detail.get('name', ''),
        'gender': detail.get('gender', ''),
        'location': detail.get('location', ''),
        'age': detail.get('age', 0),
        'avatarUrl': detail.get('avatarUrl', ''),
        'bio': detail.get('bio', ''),
        'cachedAt': timestamp,
    })

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
        age = item.get('age', 0)
        if isinstance(age, str):
            age = int(age) if age.isdigit() else 0

        if age < age_min or age > age_max:
            continue
        if gender_filter and item.get('gender') != gender_filter:
            continue

        candidates.append({
            'userId': item['userId'],
            'displayName': item.get('displayName', ''),
            'age': age,
            'gender': item.get('gender', ''),
            'location': item.get('location', ''),
            'avatarUrl': item.get('avatarUrl', ''),
            'bio': item.get('bio', ''),
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


def _response(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps(body),
    }
