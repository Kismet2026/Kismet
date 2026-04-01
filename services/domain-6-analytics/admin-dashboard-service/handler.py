import json
import boto3
import os
from datetime import datetime, timezone

dynamodb = boto3.resource("dynamodb")
ADMIN_ACTIONS_TABLE = os.environ.get("ADMIN_ACTIONS_TABLE", "admin-actions")


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


# GET /admin/stats
def get_stats(event, context):
    # TODO: Query profile-service DynamoDB for totalUsers, newUsersToday
    # TODO: Query match-service DynamoDB for totalMatches, matchesToday
    # TODO: Query message-service DynamoDB for messagesToday
    # TODO: Query swipe-service DynamoDB for swipesToday
    # NOTE: Confirm table names and access permissions with each service owner

    return _response(200, {
        "totalUsers": 0,
        "newUsersToday": 0,
        "totalMatches": 0,
        "matchesToday": 0,
        "messagesToday": 0,
        "swipesToday": 0,
    })


# GET /admin/reports
def get_reports(event, context):
    params = event.get("queryStringParameters") or {}
    status = params.get("status", "pending")
    limit = int(params.get("limit", 20))
    last_key = params.get("lastKey")

    # TODO: Query report-service DynamoDB table (confirm table name with Amber)
    # TODO: Filter by status, apply pagination using last_key
    # TODO: Confirm report record schema with Amber before implementing

    return _response(200, {
        "reports": [],
        "lastKey": None,
    })


# GET /admin/reports/{reportId}
def get_report(event, context):
    report_id = event["pathParameters"]["reportId"]

    # TODO: Query report-service DynamoDB for the specific reportId
    # TODO: Confirm table name and primary key with Amber

    return _response(200, {
        "reportId": report_id,
        "reporterId": None,
        "reportedUserId": None,
        "reason": None,
        "description": None,
        "status": None,
        "createdAt": None,
        "resolvedAt": None,
        "resolvedBy": None,
        "adminNote": None,
    })


# PUT /admin/reports/{reportId}/resolve
def resolve_report(event, context):
    report_id = event["pathParameters"]["reportId"]
    body = json.loads(event.get("body") or "{}")
    action = body.get("action")
    admin_note = body.get("adminNote", "")

    if action not in ("ban", "dismiss"):
        return _response(400, {"error": "action must be 'ban' or 'dismiss'"})

    # TODO: Update report status in report-service DynamoDB (confirm with Amber)
    # TODO: If action == "ban", call profile-service to suspend user account
    # TODO: Publish admin.user.banned event to EventBridge if action == "ban"

    table = dynamodb.Table(ADMIN_ACTIONS_TABLE)
    # TODO: Write admin action log to admin-actions DynamoDB table
    # table.put_item(Item={
    #     "adminId": event["requestContext"]["authorizer"]["claims"]["sub"],
    #     "timestamp": datetime.now(timezone.utc).isoformat(),
    #     "action": action,
    #     "reportId": report_id,
    #     "note": admin_note,
    # })

    resolved_at = datetime.now(timezone.utc).isoformat()
    return _response(200, {
        "reportId": report_id,
        "status": "resolved",
        "action": action,
        "resolvedAt": resolved_at,
    })


# GET /admin/users/{userId}
def get_user(event, context):
    user_id = event["pathParameters"]["userId"]

    # TODO: Query profile-service DynamoDB for user details (confirm table name with Quinn)
    # TODO: Count number of reports filed against this user from report-service

    return _response(200, {
        "userId": user_id,
        "name": None,
        "email": None,
        "status": None,
        "createdAt": None,
        "reportCount": 0,
    })
