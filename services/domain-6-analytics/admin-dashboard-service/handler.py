import json
import boto3
import os
from datetime import datetime, timezone

dynamodb = boto3.resource("dynamodb")
ADMIN_STATS_TABLE = os.environ.get("ADMIN_STATS_TABLE", "kismet-admin-stats")
FLAGGED_CONTENT_TABLE = os.environ.get("FLAGGED_CONTENT_TABLE", "kismet-flagged-content")


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def handler(event, context):
    # EventBridge events have "detail-type"; HTTP requests have "httpMethod"
    if "detail-type" in event:
        detail_type = event["detail-type"]
        if detail_type == "content.flagged":
            return handle_content_flagged(event)
        elif detail_type == "user.reported":
            return handle_user_reported(event)
        return

    method = event.get("httpMethod", "")
    resource = event.get("resource", "")

    if method == "GET" and resource == "/admin/stats":
        return get_stats(event, context)
    elif method == "GET" and resource == "/admin/flagged-content":
        return get_flagged_content(event, context)
    elif method == "PUT" and resource == "/admin/flagged-content/{contentId}/resolve":
        return resolve_flagged_content(event, context)
    elif method == "GET" and resource == "/admin/users":
        return get_users(event, context)
    elif method == "PUT" and resource == "/admin/users/{userId}/ban":
        return ban_user(event, context)
    elif method == "PUT" and resource == "/admin/users/{userId}/unban":
        return unban_user(event, context)
    else:
        return _response(404, {"error": "Not found"})


# GET /admin/stats
def get_stats(event, context):
    # TODO: Read pre-aggregated stats from kismet-admin-stats DynamoDB
    # Stats are kept up to date by handle_content_flagged / handle_user_reported
    # and by periodic aggregation jobs (confirm approach with team)
    return _response(200, {
        "totalUsers": 0,
        "activeUsers": 0,
        "matchesToday": 0,
        "messagesToday": 0,
        "flaggedContentCount": 0,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    })


# GET /admin/flagged-content?type=text&limit=20&cursor=xxx
def get_flagged_content(event, context):
    params = event.get("queryStringParameters") or {}
    content_type = params.get("type")          # "text", "image", or None (all)
    limit = min(int(params.get("limit", 20)), 50)
    cursor = params.get("cursor")

    # TODO: Query kismet-flagged-content DynamoDB table
    # TODO: Filter by contentType if provided
    # TODO: Apply cursor-based pagination using cursor param

    return _response(200, {
        "items": [],
        "nextCursor": None,
        "count": 0,
    })


# PUT /admin/flagged-content/{contentId}/resolve
def resolve_flagged_content(event, context):
    content_id = event["pathParameters"]["contentId"]
    body = json.loads(event.get("body") or "{}")
    action = body.get("action")

    if action not in ("approve", "remove", "ban_user"):
        return _response(400, {"error": "action must be 'approve', 'remove', or 'ban_user'"})

    # TODO: Update kismet-flagged-content item status to "resolved"
    # TODO: If action == "remove": call originating service to delete the content
    # TODO: If action == "ban_user": call ban_user() for the content owner's userId

    admin_id = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("claims", {})
        .get("sub", "unknown")
    )
    resolved_at = datetime.now(timezone.utc).isoformat()

    return _response(200, {
        "contentId": content_id,
        "action": action,
        "resolvedBy": admin_id,
        "resolvedAt": resolved_at,
        "status": "resolved",
    })


# GET /admin/users?search=john&limit=20&cursor=xxx
def get_users(event, context):
    params = event.get("queryStringParameters") or {}
    search = params.get("search")
    limit = min(int(params.get("limit", 20)), 50)
    cursor = params.get("cursor")

    # TODO: Query profile-service DynamoDB for user list (confirm table name with Quinn)
    # TODO: Apply search filter on displayName or email if provided
    # TODO: Apply cursor-based pagination

    return _response(200, {
        "items": [],
        "nextCursor": None,
        "count": 0,
    })


# PUT /admin/users/{userId}/ban
def ban_user(event, context):
    user_id = event["pathParameters"]["userId"]
    admin_id = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("claims", {})
        .get("sub", "unknown")
    )

    # TODO: Look up user in profile-service DynamoDB (confirm table name with Quinn)
    # TODO: Return 404 if user not found
    # TODO: Return 409 if user is already banned
    # TODO: Update user status to "banned" in profile-service DynamoDB

    return _response(200, {
        "userId": user_id,
        "status": "banned",
        "bannedBy": admin_id,
        "bannedAt": datetime.now(timezone.utc).isoformat(),
    })


# PUT /admin/users/{userId}/unban
def unban_user(event, context):
    user_id = event["pathParameters"]["userId"]
    admin_id = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("claims", {})
        .get("sub", "unknown")
    )

    # TODO: Look up user in profile-service DynamoDB
    # TODO: Return 404 if user not found
    # TODO: Return 409 if user is not currently banned
    # TODO: Update user status to "active" in profile-service DynamoDB

    return _response(200, {
        "userId": user_id,
        "status": "active",
        "unbannedBy": admin_id,
        "unbannedAt": datetime.now(timezone.utc).isoformat(),
    })


# EventBridge: content.flagged
# Source: kismet.moderation  Detail: { contentId, contentType, userId, reason, score, timestamp }
def handle_content_flagged(event):
    detail = event["detail"]
    # TODO: Write to kismet-flagged-content DynamoDB
    # table = dynamodb.Table(FLAGGED_CONTENT_TABLE)
    # table.put_item(Item={
    #     "PK": f"CONTENT#{detail['contentId']}",
    #     "SK": "META",
    #     "contentType": detail["contentType"],
    #     "userId": detail["userId"],
    #     "reason": detail["reason"],
    #     "score": detail["score"],
    #     "status": "pending",
    #     "flaggedAt": detail["timestamp"],
    # })
    # TODO: Increment flaggedContentCount in kismet-admin-stats


# EventBridge: user.reported
# Source: kismet.report-service  Detail: { reportId, reporterId, reportedUserId, reason, timestamp }
def handle_user_reported(event):
    detail = event["detail"]
    reported_user_id = detail["reportedUserId"]
    # TODO: Increment reportCount for reportedUserId in profile-service DynamoDB
    # TODO: Confirm table name and key schema with Quinn (profile-service owner)
