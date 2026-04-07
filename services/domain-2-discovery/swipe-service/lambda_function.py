import json
import boto3
import os
import uuid
from datetime import datetime

dynamodb = boto3.resource('dynamodb')
events_client = boto3.client('events')

TABLE_NAME = os.environ.get('TABLE_NAME', 'kismet-swipes')
EVENT_BUS_NAME = os.environ.get('EVENT_BUS_NAME', 'kismet-events')

table = dynamodb.Table(TABLE_NAME)


def handler(event, context):
    method = _get_method(event)
    path = _get_path(event)

    if method == 'POST' and path == '/swipe':
        return create_swipe(event)
    elif method == 'GET' and path == '/swipe/history':
        return get_swipe_history(event)
    else:
        return _response(404, {'code': 'NOT_FOUND', 'message': f'No route: {method} {path}'})


def create_swipe(event):
    user_id = _get_user_id(event)
    if not user_id:
        return _response(401, {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'})

    body = _parse_body(event)
    if not body:
        return _response(400, {'code': 'VALIDATION_ERROR', 'message': 'Request body required'})

    target_user_id = body.get('targetUserId')
    action = body.get('action')

    if not target_user_id or action not in ('like', 'pass'):
        return _response(400, {'code': 'VALIDATION_ERROR', 'message': 'targetUserId and action (like/pass) required'})

    if target_user_id == user_id:
        return _response(400, {'code': 'VALIDATION_ERROR', 'message': 'Cannot swipe on yourself'})

    swipe_id = f'swipe-{uuid.uuid4().hex[:8]}'
    timestamp = datetime.utcnow().isoformat() + 'Z'

    item = {
        'userId': user_id,
        'targetUserId': target_user_id,
        'swipeId': swipe_id,
        'action': action,
        'timestamp': timestamp,
    }

    # Atomic put — fails if swipe already exists
    try:
        table.put_item(
            Item=item,
            ConditionExpression='attribute_not_exists(userId) AND attribute_not_exists(targetUserId)',
        )
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        return _response(409, {'code': 'CONFLICT', 'message': 'Already swiped on this user'})

    # Publish event only for likes
    if action == 'like':
        events_client.put_events(Entries=[{
            'Source': 'kismet.swipe-service',
            'DetailType': 'swipe.created',
            'EventBusName': EVENT_BUS_NAME,
            'Detail': json.dumps({
                'swipeId': swipe_id,
                'userId': user_id,
                'targetUserId': target_user_id,
                'action': 'like',
                'timestamp': timestamp,
            }),
        }])

    return _response(200, {
        'swipeId': swipe_id,
        'action': action,
        'targetUserId': target_user_id,
        'timestamp': timestamp,
    })


def get_swipe_history(event):
    user_id = _get_user_id(event)
    if not user_id:
        return _response(401, {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'})

    params = event.get('queryStringParameters') or {}
    limit = min(int(params.get('limit', 20)), 50)
    action_filter = params.get('action')
    cursor = params.get('cursor')

    query_params = {
        'KeyConditionExpression': boto3.dynamodb.conditions.Key('userId').eq(user_id),
        'Limit': limit,
        'ScanIndexForward': False,
    }

    if action_filter in ('like', 'pass'):
        query_params['FilterExpression'] = boto3.dynamodb.conditions.Attr('action').eq(action_filter)

    if cursor:
        query_params['ExclusiveStartKey'] = json.loads(
            __import__('base64').b64decode(cursor).decode()
        )

    result = table.query(**query_params)

    items = [{
        'swipeId': item['swipeId'],
        'targetUserId': item['targetUserId'],
        'action': item['action'],
        'timestamp': item['timestamp'],
    } for item in result.get('Items', [])]

    response_body = {'items': items, 'count': len(items)}

    if 'LastEvaluatedKey' in result:
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


def _response(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps(body),
    }
