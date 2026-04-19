import json
import os
import uuid
import boto3
from datetime import datetime, timezone
from botocore.exceptions import ClientError

dynamodb = boto3.resource('dynamodb')
events = boto3.client('events')
ses = boto3.client('ses')

TABLE_NAME = "kismet-reports"
VALID_REASONS = ["harassment", "inappropriate_content", "spam", "fake_profile", "other"]
VALID_RESOLUTIONS = ["warning", "ban", "dismiss"]

# Number of distinct PENDING reports against a user that triggers an automatic ban.
AUTO_BAN_THRESHOLD = int(os.environ.get('AUTO_BAN_THRESHOLD', '2'))

def handler(event, context):
    method = event.get('httpMethod')
    path = event.get('resource', event.get('path', ''))
    
    claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
    headers = event.get('headers', {}) or {}
    
    user_id = claims.get('sub') or headers.get('x-user-id')
    is_admin = claims.get('custom:role') == 'admin' or headers.get('x-is-admin') == 'true'

    if not user_id:
        return {"statusCode": 401, "body": json.dumps({"error": "UNAUTHORIZED"})}

    try:
        if method == "POST" and (path == "/reports" or path.endswith("/reports")):
            return create_report(event, user_id)
        
        if method == "GET" and (path == "/reports" or path.endswith("/reports")):
            if not is_admin: return {"statusCode": 403, "body": json.dumps({"error": "FORBIDDEN"})}
            return list_reports(event)
        
        if method == "GET" and "/reports/" in path and not path.endswith("/resolve"):
            if not is_admin: return {"statusCode": 403, "body": json.dumps({"error": "FORBIDDEN"})}
            return get_report(event)
        
        if method == "PUT" and path.endswith("/resolve"):
            if not is_admin: return {"statusCode": 403, "body": json.dumps({"error": "FORBIDDEN"})}
            return resolve_report(event)
            
        return {"statusCode": 404, "body": json.dumps({"error": "Not Found"})}
    except Exception as e:
        print(f"Error: {e}")
        return {"statusCode": 500, "body": json.dumps({"error": "Internal Server Error"})}

def create_report(event, reporter_id):
    body = json.loads(event.get('body') or '{}')
    reported_user_id = body.get('reportedUserId')
    reason = body.get('reason')
    description = body.get('description', '')

    if not reported_user_id or reason not in VALID_REASONS:
        return {"statusCode": 400, "body": json.dumps({"error": "VALIDATION_ERROR"})}

    table = dynamodb.Table(TABLE_NAME)
    
    # Conflict check
    response = table.scan(
        FilterExpression="reporterId = :rid AND reportedUserId = :ruid AND #status = :s",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":rid": reporter_id, ":ruid": reported_user_id, ":s": "PENDING"}
    )
    if response.get('Items'):
        return {"statusCode": 409, "body": json.dumps({"error": "CONFLICT"})}

    report_id = f"report-{uuid.uuid4()}"
    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    
    item = {
        "pk": f"REPORT#{report_id}",
        "sk": "META",
        "reportId": report_id,
        "reporterId": reporter_id,
        "reportedUserId": reported_user_id,
        "reason": reason,
        "description": description,
        "status": "PENDING",
        "resolution": None,
        "createdAt": now,
        "resolvedAt": None
    }
    
    table.put_item(Item=item)

    # Auto-ban: count distinct PENDING reports against this user across all reporters
    pending_count = _count_pending_reports_for_user(reported_user_id)
    if pending_count >= AUTO_BAN_THRESHOLD:
        print(f"Auto-ban triggered for {reported_user_id} ({pending_count} pending reports)")
        _auto_ban_user(reported_user_id, report_id, reason, now)

    # EventBridge
    events.put_events(
        Entries=[{
            "Source": "kismet.report-service",
            "DetailType": "user.reported",
            "Detail": json.dumps({
                "reportId": report_id,
                "reporterId": reporter_id,
                "reportedUserId": reported_user_id,
                "reason": reason,
                "timestamp": now
            }),
            "EventBusName": "kismet-events"
        }]
    )

    # SES
    try:
        ses.send_email(
            Source=os.environ.get("SYSTEM_EMAIL", "noreply@kismet.com"),
            Destination={"ToAddresses": [os.environ.get("ADMIN_EMAIL", "admin@kismet.com")]},
            Message={
                "Subject": {"Data": f"[Kismet Admin Alert] New User Report: {reason}"},
                "Body": {"Text": {"Data": f"New user report received.\n\nReport ID: {report_id}\nReporter: {reporter_id}\nReported User: {reported_user_id}\nReason: {reason}\nDescription: {description}\n\nPlease check the admin dashboard to review this report."}}
            }
        )
    except Exception as e:
        print(f"SES Error: {e}")

    resp_item = {k: v for k, v in item.items() if k not in ["pk", "sk", "resolution", "resolvedAt"]}
    return {"statusCode": 201, "body": json.dumps(resp_item)}

def list_reports(event):
    qs = event.get('queryStringParameters') or {}
    limit = min(int(qs.get('limit', 20)), 50)
    status_filter = (qs.get('status') or '').upper() or None  # e.g. PENDING, RESOLVED, DISMISSED

    table = dynamodb.Table(TABLE_NAME)
    scan_kwargs = {"Limit": limit}

    if status_filter:
        scan_kwargs['FilterExpression'] = '#status = :s'
        scan_kwargs['ExpressionAttributeNames'] = {'#status': 'status'}
        scan_kwargs['ExpressionAttributeValues'] = {':s': status_filter}

    cursor = qs.get('cursor')
    if cursor:
        import base64
        scan_kwargs["ExclusiveStartKey"] = json.loads(base64.b64decode(cursor).decode('utf-8'))

    response = table.scan(**scan_kwargs)
    items = []
    for i in response.get('Items', []):
        i.pop('pk', None)
        i.pop('sk', None)
        i.pop('description', None)
        i.pop('resolution', None)
        i.pop('resolvedAt', None)
        items.append(i)
        
    next_cursor = None
    if 'LastEvaluatedKey' in response:
        import base64
        next_cursor = base64.b64encode(json.dumps(response['LastEvaluatedKey']).encode('utf-8')).decode('utf-8')
        
    return {
        "statusCode": 200, 
        "body": json.dumps({
            "items": items,
            "count": len(items),
            "nextCursor": next_cursor
        })
    }

def get_report(event):
    report_id = event.get('pathParameters', {}).get('reportId')
    if not report_id: return {"statusCode": 404, "body": json.dumps({"error": "NOT_FOUND"})}
    
    table = dynamodb.Table(TABLE_NAME)
    response = table.get_item(Key={"pk": f"REPORT#{report_id}", "sk": "META"})
    
    item = response.get('Item')
    if not item: return {"statusCode": 404, "body": json.dumps({"error": "NOT_FOUND"})}
    
    item.pop('pk', None)
    item.pop('sk', None)
    return {"statusCode": 200, "body": json.dumps(item)}

def resolve_report(event):
    report_id = event.get('pathParameters', {}).get('reportId')
    body = json.loads(event.get('body') or '{}')
    resolution = body.get('resolution')
    
    if not report_id: return {"statusCode": 404, "body": json.dumps({"error": "NOT_FOUND"})}
    if resolution not in VALID_RESOLUTIONS: return {"statusCode": 400, "body": json.dumps({"error": "VALIDATION_ERROR"})}
    
    table = dynamodb.Table(TABLE_NAME)
    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    new_status = "DISMISSED" if resolution == "dismiss" else "RESOLVED"
    
    try:
        response = table.update_item(
            Key={"pk": f"REPORT#{report_id}", "sk": "META"},
            UpdateExpression="SET #status = :resolvedStatus, resolution = :res, resolvedAt = :now",
            ConditionExpression="attribute_exists(pk) AND #status = :pendingStatus",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":resolvedStatus": new_status,
                ":res": resolution,
                ":now": now,
                ":pendingStatus": "PENDING"
            },
            ReturnValues="ALL_NEW"
        )
        item = response.get('Attributes', {})
        
        if resolution == "ban":
            events.put_events(Entries=[{
                "Source": "kismet.report-service",
                "DetailType": "user.banned",
                "Detail": json.dumps({
                    "userId": item.get("reportedUserId"),
                    "reportId": report_id,
                    "reason": item.get("reason"),
                    "timestamp": now
                }),
                "EventBusName": "kismet-events"
            }])

        return {
            "statusCode": 200,
            "body": json.dumps({
                "reportId": item.get('reportId'),
                "reportedUserId": item.get('reportedUserId'),
                "reason": item.get('reason'),
                "status": item.get('status'),
                "resolution": item.get('resolution'),
                "resolvedAt": item.get('resolvedAt')
            })
        }
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            check = table.get_item(Key={"pk": f"REPORT#{report_id}", "sk": "META"})
            if not check.get('Item'): return {"statusCode": 404, "body": json.dumps({"error": "NOT_FOUND"})}
            return {"statusCode": 409, "body": json.dumps({"error": "CONFLICT"})}
        raise e


# ── Auto-ban helpers ──────────────────────────────────────────────────────────

def _count_pending_reports_for_user(reported_user_id: str) -> int:
    """Return the number of distinct PENDING reports filed against reported_user_id.

    Uses the reportedUserId GSI for an efficient key-based query instead of a full scan.
    """
    from boto3.dynamodb.conditions import Key, Attr
    table = dynamodb.Table(TABLE_NAME)
    response = table.query(
        IndexName='reportedUserId-index',
        KeyConditionExpression=Key('reportedUserId').eq(reported_user_id),
        FilterExpression=Attr('status').eq('PENDING'),
        Select='COUNT',
    )
    count = response.get('Count', 0)
    while 'LastEvaluatedKey' in response:
        response = table.query(
            IndexName='reportedUserId-index',
            KeyConditionExpression=Key('reportedUserId').eq(reported_user_id),
            FilterExpression=Attr('status').eq('PENDING'),
            Select='COUNT',
            ExclusiveStartKey=response['LastEvaluatedKey'],
        )
        count += response.get('Count', 0)
    return count


def _auto_ban_user(reported_user_id: str, trigger_report_id: str, reason: str, now: str) -> None:
    """Mark all PENDING reports for reported_user_id as RESOLVED/ban and fire user.banned."""
    table = dynamodb.Table(TABLE_NAME)

    # Resolve all outstanding PENDING reports for this user (via GSI)
    from boto3.dynamodb.conditions import Key, Attr
    pending = table.query(
        IndexName='reportedUserId-index',
        KeyConditionExpression=Key('reportedUserId').eq(reported_user_id),
        FilterExpression=Attr('status').eq('PENDING'),
    )
    for item in pending.get('Items', []):
        try:
            table.update_item(
                Key={'pk': item['pk'], 'sk': item['sk']},
                UpdateExpression='SET #status = :s, resolution = :r, resolvedAt = :t',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={':s': 'RESOLVED', ':r': 'ban', ':t': now},
            )
        except Exception as e:
            print(f"Auto-ban: failed to resolve report {item.get('reportId')}: {e}")

    # Fire user.banned event — downstream services handle cleanup
    events.put_events(Entries=[{
        'Source': 'kismet.report-service',
        'DetailType': 'user.banned',
        'Detail': json.dumps({
            'userId': reported_user_id,
            'reportId': trigger_report_id,
            'reason': reason,
            'autoBanned': True,
            'threshold': AUTO_BAN_THRESHOLD,
            'timestamp': now,
        }),
        'EventBusName': 'kismet-events',
    }])
