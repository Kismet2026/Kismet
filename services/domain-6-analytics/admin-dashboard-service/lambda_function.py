import base64
import json
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3

dynamodb = boto3.resource("dynamodb")
events_client = boto3.client("events")

ADMIN_STATS_TABLE = os.environ.get("ADMIN_STATS_TABLE", "kismet-admin-stats")
FLAGGED_CONTENT_TABLE = os.environ.get(
    "FLAGGED_CONTENT_TABLE", "kismet-flagged-content"
)
# Cross-service: kismet-profiles is owned by domain-1 (Quinn).
# The CDK stack must grant this Lambda read/write access to kismet-profiles.
PROFILES_TABLE = os.environ.get("PROFILES_TABLE", "kismet-profiles")
EVENT_BUS_NAME = os.environ.get("EVENT_BUS_NAME", "kismet-events")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@kismet.com")
ADMIN_GROUP_NAMES = {"admin", "admins"}


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=_json_default),
    }


def _json_default(obj):
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _encode_cursor(key: dict) -> str:
    return base64.b64encode(json.dumps(key).encode()).decode()


def _decode_cursor(cursor: str) -> dict:
    return json.loads(base64.b64decode(cursor.encode()).decode())


def _get_admin_id(event) -> str:
    return extract_claims(event).get("sub", "unknown")


def extract_claims(event) -> dict:
    request_context = event.get("requestContext") or {}
    authorizer = request_context.get("authorizer")
    if not isinstance(authorizer, dict):
        return {}

    claims = authorizer.get("claims")
    if isinstance(claims, dict):
        return claims

    jwt = authorizer.get("jwt")
    if isinstance(jwt, dict) and isinstance(jwt.get("claims"), dict):
        return jwt["claims"]

    return {}


def _parse_groups(raw) -> set:
    if raw is None:
        return set()
    if isinstance(raw, list):
        return {str(group).strip() for group in raw if str(group).strip()}
    if isinstance(raw, str):
        value = raw.strip()
        if not value:
            return set()
        if value.startswith("["):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return {str(group).strip() for group in parsed if str(group).strip()}
            except json.JSONDecodeError:
                pass
        return {group.strip() for group in value.replace(",", " ").split() if group.strip()}
    return set()


def _is_admin(claims: dict) -> bool:
    groups = _parse_groups(claims.get("cognito:groups"))
    if groups & ADMIN_GROUP_NAMES:
        return True

    email = (claims.get("email") or claims.get("cognito:username") or "").strip().lower()
    return email == ADMIN_EMAIL.lower()


def handler(event, context):
    # EventBridge events have "detail-type"; HTTP requests have "httpMethod"
    if "detail-type" in event:
        detail_type = event["detail-type"]
        if detail_type == "content.flagged":
            return handle_content_flagged(event)
        if detail_type == "user.reported":
            return handle_user_reported(event)
        return None

    method = event.get("httpMethod", "")
    resource = event.get("resource", "")
    claims = extract_claims(event)

    if not _is_admin(claims):
        return _response(403, {"error": "FORBIDDEN", "message": "Admin access required"})

    routes = {
        ("GET", "/admin/stats"): get_stats,
        ("GET", "/admin/flagged-content"): get_flagged_content,
        ("PUT", "/admin/flagged-content/{contentId}/resolve"): resolve_flagged_content,
        ("GET", "/admin/users"): get_users,
        ("PUT", "/admin/users/{userId}/ban"): ban_user,
        ("PUT", "/admin/users/{userId}/unban"): unban_user,
    }
    fn = routes.get((method, resource))
    if fn:
        return fn(event, context)
    return _response(404, {"error": "Not found"})


# GET /admin/stats
def get_stats(event, context):
    stat_keys = [
        "totalUsers",
        "activeUsers",
        "matchesToday",
        "messagesToday",
        "flaggedContentCount",
    ]

    # Batch-read all stats in one call (each stored at SK=LATEST)
    keys = [{"PK": f"STAT#{k}", "SK": "LATEST"} for k in stat_keys]
    response = dynamodb.batch_get_item(RequestItems={ADMIN_STATS_TABLE: {"Keys": keys}})
    items = {
        item["PK"].split("#")[1]: item.get("value", 0)
        for item in response["Responses"].get(ADMIN_STATS_TABLE, [])
    }

    return _response(
        200,
        {
            "totalUsers": int(items.get("totalUsers", 0)),
            "activeUsers": int(items.get("activeUsers", 0)),
            "matchesToday": int(items.get("matchesToday", 0)),
            "messagesToday": int(items.get("messagesToday", 0)),
            "flaggedContentCount": int(items.get("flaggedContentCount", 0)),
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        },
    )


# GET /admin/flagged-content?type=text&limit=20&cursor=xxx
def get_flagged_content(event, context):
    params = event.get("queryStringParameters") or {}
    content_type = params.get("type")
    limit = min(int(params.get("limit", 20)), 50)
    cursor = params.get("cursor")

    if content_type and content_type not in ("text", "image"):
        return _response(
            400,
            {"error": "VALIDATION_ERROR", "message": "type must be 'text' or 'image'"},
        )

    table = dynamodb.Table(FLAGGED_CONTENT_TABLE)
    scan_kwargs = {"Limit": limit}

    if content_type:
        scan_kwargs["FilterExpression"] = "#type = :type"
        scan_kwargs["ExpressionAttributeNames"] = {"#type": "type"}
        scan_kwargs["ExpressionAttributeValues"] = {":type": content_type}

    if cursor:
        scan_kwargs["ExclusiveStartKey"] = _decode_cursor(cursor)

    result = table.scan(**scan_kwargs)

    items = []
    for item in result.get("Items", []):
        content_id = item["PK"].replace("CONTENT#", "")
        entry = {
            "contentId": content_id,
            "type": item.get("type"),
            "userId": item.get("userId"),
            "reason": item.get("reason"),
            "confidence": float(item.get("confidence", 0)),
            "flaggedAt": item.get("flaggedAt"),
            "status": item.get("status", "pending"),
        }
        if item.get("type") == "image":
            entry["imageUrl"] = item.get("imageUrl")
        else:
            entry["content"] = item.get("content")
        items.append(entry)

    next_cursor = None
    if "LastEvaluatedKey" in result:
        next_cursor = _encode_cursor(result["LastEvaluatedKey"])

    return _response(
        200,
        {
            "items": items,
            "nextCursor": next_cursor,
            "count": len(items),
        },
    )


# PUT /admin/flagged-content/{contentId}/resolve
def resolve_flagged_content(event, context):
    content_id = event["pathParameters"]["contentId"]
    body = json.loads(event.get("body") or "{}")
    action = body.get("action")

    if action not in ("approve", "remove", "ban_user"):
        return _response(
            400,
            {
                "error": "VALIDATION_ERROR",
                "message": "action must be 'approve', 'remove', or 'ban_user'",
            },
        )

    table = dynamodb.Table(FLAGGED_CONTENT_TABLE)

    # Check the item exists
    existing = table.get_item(Key={"PK": f"CONTENT#{content_id}", "SK": "META"})
    if "Item" not in existing:
        return _response(404, {"error": "NOT_FOUND", "message": "Content not found"})

    admin_id = _get_admin_id(event)
    resolved_at = datetime.now(timezone.utc).isoformat()

    table.update_item(
        Key={"PK": f"CONTENT#{content_id}", "SK": "META"},
        UpdateExpression="SET #s = :s, resolvedBy = :rb, resolvedAt = :ra",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "resolved",
            ":rb": admin_id,
            ":ra": resolved_at,
        },
    )

    if action == "ban_user":
        content_owner = existing["Item"].get("userId")
        if content_owner:
            ban_result = _ban_user_in_profiles(content_owner, admin_id, resolved_at)
            if ban_result == "ok":
                _publish_user_banned(content_owner, admin_id, resolved_at)

    # Decrement flaggedContentCount stat
    _update_stat("flaggedContentCount", -1)

    return _response(
        200,
        {
            "contentId": content_id,
            "action": action,
            "resolvedBy": admin_id,
            "resolvedAt": resolved_at,
            "status": "resolved",
        },
    )


# GET /admin/users?search=john&limit=20&cursor=xxx
def get_users(event, context):
    params = event.get("queryStringParameters") or {}
    search = params.get("search", "").strip().lower() if params.get("search") else None
    limit = min(int(params.get("limit", 20)), 50)
    cursor = params.get("cursor")

    table = dynamodb.Table(PROFILES_TABLE)
    scan_kwargs = {
        "FilterExpression": "SK = :profile",
        "ExpressionAttributeValues": {":profile": "PROFILE"},
        "Limit": limit,
    }

    if search:
        scan_kwargs["FilterExpression"] = "SK = :profile AND contains(#name, :search)"
        scan_kwargs["ExpressionAttributeNames"] = {"#name": "name"}
        scan_kwargs["ExpressionAttributeValues"] = {
            ":profile": "PROFILE",
            ":search": search,
        }

    if cursor:
        scan_kwargs["ExclusiveStartKey"] = _decode_cursor(cursor)

    result = table.scan(**scan_kwargs)

    items = []
    for item in result.get("Items", []):
        user_id = item["PK"].replace("USER#", "")
        items.append(
            {
                "userId": user_id,
                "displayName": item.get("name"),
                "email": item.get(
                    "email"
                ),  # email not stored in profile table; None unless populated
                "status": item.get("status", "active"),
                "createdAt": item.get("createdAt"),
                "reportCount": int(item.get("reportCount", 0)),
            }
        )

    next_cursor = None
    if "LastEvaluatedKey" in result:
        next_cursor = _encode_cursor(result["LastEvaluatedKey"])

    return _response(
        200,
        {
            "items": items,
            "nextCursor": next_cursor,
            "count": len(items),
        },
    )


# PUT /admin/users/{userId}/ban
def ban_user(event, context):
    user_id = event["pathParameters"]["userId"]
    admin_id = _get_admin_id(event)
    banned_at = datetime.now(timezone.utc).isoformat()

    result = _ban_user_in_profiles(user_id, admin_id, banned_at)

    if result == "not_found":
        return _response(404, {"error": "NOT_FOUND", "message": "User not found"})
    if result == "already_banned":
        return _response(
            409, {"error": "CONFLICT", "message": "User is already banned"}
        )

    _publish_user_banned(user_id, admin_id, banned_at)

    return _response(
        200,
        {
            "userId": user_id,
            "status": "banned",
            "bannedBy": admin_id,
            "bannedAt": banned_at,
        },
    )


def _ban_user_in_profiles(user_id: str, admin_id: str, banned_at: str) -> str:
    """Ban a user in kismet-profiles. Returns 'ok', 'not_found', or 'already_banned'."""
    table = dynamodb.Table(PROFILES_TABLE)

    existing = table.get_item(Key={"PK": f"USER#{user_id}", "SK": "PROFILE"})
    if "Item" not in existing:
        return "not_found"
    if existing["Item"].get("status") == "banned":
        return "already_banned"

    table.update_item(
        Key={"PK": f"USER#{user_id}", "SK": "PROFILE"},
        UpdateExpression="SET #s = :s, bannedBy = :bb, bannedAt = :ba",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "banned",
            ":bb": admin_id,
            ":ba": banned_at,
        },
    )
    return "ok"


# PUT /admin/users/{userId}/unban
def unban_user(event, context):
    user_id = event["pathParameters"]["userId"]
    admin_id = _get_admin_id(event)
    unbanned_at = datetime.now(timezone.utc).isoformat()

    table = dynamodb.Table(PROFILES_TABLE)

    existing = table.get_item(Key={"PK": f"USER#{user_id}", "SK": "PROFILE"})
    if "Item" not in existing:
        return _response(404, {"error": "NOT_FOUND", "message": "User not found"})
    if existing["Item"].get("status") != "banned":
        return _response(409, {"error": "CONFLICT", "message": "User is not banned"})

    table.update_item(
        Key={"PK": f"USER#{user_id}", "SK": "PROFILE"},
        UpdateExpression=(
            "SET #s = :s, unbannedBy = :ub, unbannedAt = :ua "
            "REMOVE bannedBy, bannedAt"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "active",
            ":ub": admin_id,
            ":ua": unbanned_at,
        },
    )

    return _response(
        200,
        {
            "userId": user_id,
            "status": "active",
            "unbannedBy": admin_id,
            "unbannedAt": unbanned_at,
        },
    )


# ── EventBridge handlers ──────────────────────────────────────────────────────


# EventBridge: content.flagged
# Source: kismet.moderation
# Detail: { contentId, contentType, userId, reason, score, timestamp }
def handle_content_flagged(event):
    detail = event["detail"]
    table = dynamodb.Table(FLAGGED_CONTENT_TABLE)

    table.put_item(
        Item={
            "PK": f"CONTENT#{detail['contentId']}",
            "SK": "META",
            "type": detail.get("contentType"),
            "content": detail.get("content"),
            "userId": detail.get("userId"),
            "reason": detail.get("reason"),
            "confidence": Decimal(str(detail.get("score", 0))),
            "status": "pending",
            "flaggedAt": detail.get(
                "timestamp", datetime.now(timezone.utc).isoformat()
            ),
        }
    )

    _update_stat("flaggedContentCount", 1)


# EventBridge: user.reported
# Source: kismet.report-service
# Detail: { reportId, reporterId, reportedUserId, reason, timestamp }
def handle_user_reported(event):
    detail = event["detail"]
    reported_user_id = detail["reportedUserId"]

    table = dynamodb.Table(PROFILES_TABLE)
    table.update_item(
        Key={"PK": f"USER#{reported_user_id}", "SK": "PROFILE"},
        UpdateExpression="ADD reportCount :inc",
        ExpressionAttributeValues={":inc": 1},
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _publish_user_banned(user_id: str, admin_id: str, banned_at: str):
    """Publish user.banned to EventBridge so D1/D2/D3 cascade runs."""
    events_client.put_events(
        Entries=[
            {
                "Source": "kismet.admin-dashboard",
                "DetailType": "user.banned",
                "EventBusName": EVENT_BUS_NAME,
                "Detail": json.dumps({
                    "userId": user_id,
                    "bannedBy": admin_id,
                    "bannedAt": banned_at,
                }),
            }
        ]
    )


def _update_stat(stat_name: str, delta: int):
    """Atomically increment or decrement a running stat in kismet-admin-stats."""
    table = dynamodb.Table(ADMIN_STATS_TABLE)
    table.update_item(
        Key={"PK": f"STAT#{stat_name}", "SK": "LATEST"},
        UpdateExpression="SET updatedAt = :ts ADD #v :delta",
        ExpressionAttributeNames={"#v": "value"},
        ExpressionAttributeValues={
            ":delta": delta,
            ":ts": datetime.now(timezone.utc).isoformat(),
        },
    )
