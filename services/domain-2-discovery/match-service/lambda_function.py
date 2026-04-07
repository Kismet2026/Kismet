import json
import boto3
import os
import uuid
from datetime import datetime

dynamodb = boto3.resource('dynamodb')
dynamodb_client = boto3.client('dynamodb')
events_client = boto3.client('events')

MATCH_TABLE = os.environ.get('TABLE_NAME', 'kismet-matches')
SWIPE_TABLE = os.environ.get('SWIPE_TABLE_NAME', 'kismet-swipes')
EVENT_BUS_NAME = os.environ.get('EVENT_BUS_NAME', 'kismet-events')

match_table = dynamodb.Table(MATCH_TABLE)
swipe_table = dynamodb.Table(SWIPE_TABLE)


def handler(event, context):
    # EventBridge event (swipe.created)
    if event.get('source') == 'kismet.swipe-service':
        return handle_swipe_event(event)

    # API Gateway request
    method = _get_method(event)
    path = _get_path(event)

    # Extract path parameter (API Gateway sets pathParameters; fallback to path parsing for local tests)
    match_id = (event.get('pathParameters') or {}).get('matchId')
    if not match_id and path.startswith('/matches/'):
        match_id = path.split('/matches/')[1].split('/')[0]

    if method == 'GET' and path == '/matches':
        return get_matches(event)
    elif method == 'GET' and match_id:
        return get_match_detail(event, match_id)
    elif method == 'DELETE' and match_id:
        return unmatch(event, match_id)
    else:
        return _response(404, {'code': 'NOT_FOUND', 'message': f'No route: {method} {path}'})


def handle_swipe_event(event):
    """Check for mutual like when a swipe.created event arrives."""
    detail = event.get('detail', {})
    swiper_id = detail.get('userId')
    target_id = detail.get('targetUserId')

    if not swiper_id or not target_id:
        return {'statusCode': 400, 'body': 'Missing userId or targetUserId'}

    # Check if target already liked swiper
    reverse_swipe = swipe_table.get_item(
        Key={'userId': target_id, 'targetUserId': swiper_id}
    ).get('Item')

    if not reverse_swipe or reverse_swipe.get('action') != 'like':
        return {'statusCode': 200, 'body': 'No mutual like'}

    # Mutual like detected — create match atomically
    match_id = f'match-{uuid.uuid4().hex[:8]}'
    timestamp = datetime.utcnow().isoformat() + 'Z'
    user_ids = sorted([swiper_id, target_id])
    pair_key = f'PAIR#{user_ids[0]}#{user_ids[1]}'

    # Use transact_write to atomically:
    # 1. Create pair record (with condition to prevent duplicate matches)
    # 2. Create META record
    # 3. Create two user-index records
    try:
        dynamodb_client.transact_write_items(
            TransactItems=[
                {
                    'Put': {
                        'TableName': MATCH_TABLE,
                        'Item': {
                            'PK': {'S': pair_key},
                            'SK': {'S': 'META'},
                            'matchId': {'S': match_id},
                            'userAId': {'S': user_ids[0]},
                            'userBId': {'S': user_ids[1]},
                            'status': {'S': 'active'},
                            'matchedAt': {'S': timestamp},
                        },
                        'ConditionExpression': 'attribute_not_exists(PK)',
                    }
                },
                {
                    'Put': {
                        'TableName': MATCH_TABLE,
                        'Item': {
                            'PK': {'S': f'MATCH#{match_id}'},
                            'SK': {'S': 'META'},
                            'matchId': {'S': match_id},
                            'userAId': {'S': user_ids[0]},
                            'userBId': {'S': user_ids[1]},
                            'status': {'S': 'active'},
                            'matchedAt': {'S': timestamp},
                            'pairKey': {'S': pair_key},
                        },
                    }
                },
                {
                    'Put': {
                        'TableName': MATCH_TABLE,
                        'Item': {
                            'PK': {'S': f'USER#{user_ids[0]}'},
                            'SK': {'S': f'MATCH#{timestamp}#{match_id}'},
                            'matchId': {'S': match_id},
                            'matchedAt': {'S': timestamp},
                            'status': {'S': 'active'},
                        },
                    }
                },
                {
                    'Put': {
                        'TableName': MATCH_TABLE,
                        'Item': {
                            'PK': {'S': f'USER#{user_ids[1]}'},
                            'SK': {'S': f'MATCH#{timestamp}#{match_id}'},
                            'matchId': {'S': match_id},
                            'matchedAt': {'S': timestamp},
                            'status': {'S': 'active'},
                        },
                    }
                },
            ]
        )
    except dynamodb_client.exceptions.TransactionCanceledException:
        # ConditionExpression failed → match already exists for this pair
        return {'statusCode': 200, 'body': 'Match already exists'}

    # Publish match.created event
    events_client.put_events(Entries=[{
        'Source': 'kismet.match-service',
        'DetailType': 'match.created',
        'EventBusName': EVENT_BUS_NAME,
        'Detail': json.dumps({
            'matchId': match_id,
            'userIds': user_ids,
            'timestamp': timestamp,
        }),
    }])

    return {'statusCode': 200, 'body': json.dumps({'matchId': match_id})}


def get_matches(event):
    user_id = _get_user_id(event)
    if not user_id:
        return _response(401, {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'})

    params = event.get('queryStringParameters') or {}
    limit = min(int(params.get('limit', 20)), 50)
    cursor = params.get('cursor')

    from boto3.dynamodb.conditions import Key
    query_params = {
        'KeyConditionExpression': Key('PK').eq(f'USER#{user_id}') & Key('SK').begins_with('MATCH#'),
        'Limit': limit,
        'ScanIndexForward': False,
    }

    if cursor:
        import base64
        query_params['ExclusiveStartKey'] = json.loads(
            base64.b64decode(cursor).decode()
        )

    result = match_table.query(**query_params)

    items = [{
        'matchId': item['matchId'],
        'matchedAt': item['matchedAt'],
        'status': item.get('status', 'active'),
    } for item in result.get('Items', [])]

    response_body = {'items': items, 'count': len(items)}

    if 'LastEvaluatedKey' in result:
        import base64
        response_body['nextCursor'] = base64.b64encode(
            json.dumps(result['LastEvaluatedKey']).encode()
        ).decode()

    return _response(200, response_body)


def get_match_detail(event, match_id):
    user_id = _get_user_id(event)
    if not user_id:
        return _response(401, {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'})

    result = match_table.get_item(Key={'PK': f'MATCH#{match_id}', 'SK': 'META'})
    item = result.get('Item')

    if not item:
        return _response(404, {'code': 'NOT_FOUND', 'message': 'Match not found'})

    if user_id not in (item.get('userAId'), item.get('userBId')):
        return _response(403, {'code': 'FORBIDDEN', 'message': 'Not your match'})

    return _response(200, {
        'matchId': item['matchId'],
        'userAId': item['userAId'],
        'userBId': item['userBId'],
        'status': item.get('status', 'active'),
        'matchedAt': item['matchedAt'],
    })


def unmatch(event, match_id):
    user_id = _get_user_id(event)
    if not user_id:
        return _response(401, {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'})

    result = match_table.get_item(Key={'PK': f'MATCH#{match_id}', 'SK': 'META'})
    item = result.get('Item')

    if not item:
        return _response(404, {'code': 'NOT_FOUND', 'message': 'Match not found'})

    if user_id not in (item.get('userAId'), item.get('userBId')):
        return _response(403, {'code': 'FORBIDDEN', 'message': 'Not your match'})

    timestamp = datetime.utcnow().isoformat() + 'Z'
    matched_at = item['matchedAt']
    user_a = item['userAId']
    user_b = item['userBId']
    user_index_sk = f'MATCH#{matched_at}#{match_id}'

    # Update META + both user-index entries atomically
    dynamodb_client.transact_write_items(
        TransactItems=[
            {
                'Update': {
                    'TableName': MATCH_TABLE,
                    'Key': {'PK': {'S': f'MATCH#{match_id}'}, 'SK': {'S': 'META'}},
                    'UpdateExpression': 'SET #s = :s, unmatchedAt = :t',
                    'ExpressionAttributeNames': {'#s': 'status'},
                    'ExpressionAttributeValues': {':s': {'S': 'unmatched'}, ':t': {'S': timestamp}},
                }
            },
            {
                'Update': {
                    'TableName': MATCH_TABLE,
                    'Key': {'PK': {'S': f'USER#{user_a}'}, 'SK': {'S': user_index_sk}},
                    'UpdateExpression': 'SET #s = :s',
                    'ExpressionAttributeNames': {'#s': 'status'},
                    'ExpressionAttributeValues': {':s': {'S': 'unmatched'}},
                }
            },
            {
                'Update': {
                    'TableName': MATCH_TABLE,
                    'Key': {'PK': {'S': f'USER#{user_b}'}, 'SK': {'S': user_index_sk}},
                    'UpdateExpression': 'SET #s = :s',
                    'ExpressionAttributeNames': {'#s': 'status'},
                    'ExpressionAttributeValues': {':s': {'S': 'unmatched'}},
                }
            },
        ]
    )

    return _response(200, {
        'matchId': match_id,
        'status': 'unmatched',
        'unmatchedAt': timestamp,
    })


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
