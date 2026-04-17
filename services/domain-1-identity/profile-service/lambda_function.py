import json
import logging
import os
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SERVICE_NAME = "profile-service"
PROFILE_DETAIL_PATTERN = re.compile(r"^/profiles/(?P<userId>[^/]+)$")

PROFILES_TABLE_NAME = os.environ.get("PROFILES_TABLE_NAME", "")
EVENT_BUS_NAME = os.environ.get("EVENT_BUS_NAME", "")
COGNITO_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "")

dynamodb = boto3.resource("dynamodb")
events = boto3.client("events")
cognito = boto3.client("cognito-idp")

UPDATABLE_FIELDS = frozenset({"name", "bio", "gender", "interestedIn", "birthDate", "birthTime", "location", "interests", "city", "avatarUrl"})
VALID_GENDERS = {"male", "female", "non-binary"}
VALID_INTERESTED_IN = {"male", "female", "non-binary", "everyone"}


def handler(event, context):
    event = event or {}
    event_source = event.get("source")
    detail_type = event.get("detail-type") or event.get("detailType")
    method = _get_method(event)
    path = _get_path(event)
    user_id = _get_user_id(event)
    operation = None
    profile_match = PROFILE_DETAIL_PATTERN.match(path)

    try:
        if event_source == "kismet.report-service" and detail_type == "user.banned":
            operation = "handleUserBanned"
            return handle_user_banned(_get_event_detail(event))
        elif method == "POST" and path == "/profiles":
            operation = "createProfile"
            payload, error = _parse_body(event)
            if error is not None:
                return error
            if not user_id:
                return _response(401, {"code": "UNAUTHORIZED", "message": "Authentication required."})
            return handle_create(user_id, payload or {})
        elif profile_match and method == "GET":
            operation = "getProfile"
            return handle_get(profile_match.group("userId"))
        elif profile_match and method == "PUT":
            operation = "updateProfile"
            payload, error = _parse_body(event)
            if error is not None:
                return error
            if not user_id:
                return _response(401, {"code": "UNAUTHORIZED", "message": "Authentication required."})
            return handle_update(user_id, profile_match.group("userId"), payload or {})
        elif profile_match and method == "DELETE":
            operation = "deleteProfile"
            if not user_id:
                return _response(401, {"code": "UNAUTHORIZED", "message": "Authentication required."})
            return handle_delete(user_id, profile_match.group("userId"))
        else:
            return _response(404, {"code": "NOT_FOUND", "message": f"No route matches {method} {path}."})
    except ClientError:
        logger.exception("AWS error in %s", operation or f"{method} {path}")
        return _response(500, {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."})
    except Exception:
        logger.exception("Unexpected error in %s", operation or f"{method} {path}")
        return _response(500, {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."})


def handle_create(user_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    name = (body.get("name") or "").strip()
    gender = (body.get("gender") or "").strip()
    interested_in = (body.get("interestedIn") or "").strip()
    birth_date = (body.get("birthDate") or "").strip()
    location = body.get("location")

    if not name:
        return _response(400, {"code": "VALIDATION_ERROR", "message": "name is required."})
    if not gender or gender not in VALID_GENDERS:
        return _response(400, {"code": "VALIDATION_ERROR", "message": f"gender is required and must be one of: {', '.join(sorted(VALID_GENDERS))}."})
    if not interested_in or interested_in not in VALID_INTERESTED_IN:
        return _response(400, {"code": "VALIDATION_ERROR", "message": f"interestedIn is required and must be one of: {', '.join(sorted(VALID_INTERESTED_IN))}."})
    if not birth_date:
        return _response(400, {"code": "VALIDATION_ERROR", "message": "birthDate is required."})
    if not location:
        return _response(400, {"code": "VALIDATION_ERROR", "message": "location is required."})

    table = dynamodb.Table(PROFILES_TABLE_NAME)
    existing = table.get_item(Key={"PK": f"USER#{user_id}", "SK": "PROFILE"})
    if existing.get("Item"):
        return _response(409, {"code": "CONFLICT", "message": "Profile already exists."})

    now = datetime.now(timezone.utc).isoformat()
    item: Dict[str, Any] = {
        "PK": f"USER#{user_id}",
        "SK": "PROFILE",
        "userId": user_id,
        "status": "active",
        "name": name,
        "gender": gender,
        "interestedIn": interested_in,
        "birthDate": birth_date,
        "location": json.loads(json.dumps(location), parse_float=Decimal),
        "createdAt": now,
        "updatedAt": now,
    }
    for field in UPDATABLE_FIELDS - {"name", "gender", "interestedIn", "birthDate", "location"}:
        if body.get(field) is not None:
            item[field] = body[field]

    table.put_item(Item=item)

    events.put_events(Entries=[{
        "Source": "kismet.profile-service",
        "DetailType": "profile.completed",
        "Detail": json.dumps(_build_event_detail(item), default=str),
        "EventBusName": EVENT_BUS_NAME,
    }])

    profile = {k: v for k, v in item.items() if k not in ("PK", "SK")}
    return _response(201, profile)


def handle_get(user_id: str) -> Dict[str, Any]:
    table = dynamodb.Table(PROFILES_TABLE_NAME)
    result = table.get_item(Key={"PK": f"USER#{user_id}", "SK": "PROFILE"})
    item = result.get("Item")

    if not item or item.get("status") == "banned":
        return _response(404, {"code": "NOT_FOUND", "message": "Profile not found."})

    profile = {k: v for k, v in item.items() if k not in ("PK", "SK")}
    return _response(200, profile)


def handle_update(caller_id: str, user_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    if caller_id != user_id:
        return _response(403, {"code": "FORBIDDEN", "message": "You can only update your own profile."})

    table = dynamodb.Table(PROFILES_TABLE_NAME)
    if not table.get_item(Key={"PK": f"USER#{user_id}", "SK": "PROFILE"}).get("Item"):
        return _response(404, {"code": "NOT_FOUND", "message": "Profile not found."})

    updates = {k: json.loads(json.dumps(v), parse_float=Decimal) if isinstance(v, (dict, list, float)) else v
                for k, v in body.items() if k in UPDATABLE_FIELDS}
    if not updates:
        return _response(400, {"code": "VALIDATION_ERROR", "message": "No valid fields to update."})

    if "gender" in updates and updates["gender"] not in VALID_GENDERS:
        return _response(400, {"code": "VALIDATION_ERROR", "message": f"gender must be one of: {', '.join(sorted(VALID_GENDERS))}."})
    if "interestedIn" in updates and updates["interestedIn"] not in VALID_INTERESTED_IN:
        return _response(400, {"code": "VALIDATION_ERROR", "message": f"interestedIn must be one of: {', '.join(sorted(VALID_INTERESTED_IN))}."})

    now = datetime.now(timezone.utc).isoformat()
    updates["updatedAt"] = now

    set_parts = []
    expr_names: Dict[str, str] = {}
    expr_values: Dict[str, Any] = {}
    for i, (key, value) in enumerate(updates.items()):
        name_ph = f"#f{i}"
        val_ph = f":v{i}"
        expr_names[name_ph] = key
        expr_values[val_ph] = value
        set_parts.append(f"{name_ph} = {val_ph}")

    table.update_item(
        Key={"PK": f"USER#{user_id}", "SK": "PROFILE"},
        UpdateExpression=f"SET {', '.join(set_parts)}",
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )

    # Publish profile.updated event with full current profile
    updated_item = table.get_item(Key={"PK": f"USER#{user_id}", "SK": "PROFILE"}).get("Item", {})
    events.put_events(Entries=[{
        "Source": "kismet.profile-service",
        "DetailType": "profile.updated",
        "Detail": json.dumps(_build_event_detail(updated_item), default=str),
        "EventBusName": EVENT_BUS_NAME,
    }])

    profile = {k: v for k, v in updated_item.items() if k not in ("PK", "SK")}
    return _response(200, profile)


def handle_delete(caller_id: str, user_id: str) -> Dict[str, Any]:
    if caller_id != user_id:
        return _response(403, {"code": "FORBIDDEN", "message": "You can only delete your own profile."})

    table = dynamodb.Table(PROFILES_TABLE_NAME)

    # Read the profile before acting to check ban status. Use a strongly
    # consistent read so a very-recent ban is never missed.
    existing = table.get_item(
        Key={"PK": f"USER#{user_id}", "SK": "PROFILE"},
        ConsistentRead=True,
        ProjectionExpression="#status",
        ExpressionAttributeNames={"#status": "status"},
    )
    is_banned = existing.get("Item", {}).get("status") == "banned"

    # Perform the Cognito action BEFORE removing the profile row.  This
    # ensures that if the Cognito call fails and the request is retried,
    # the profile row still exists so ban state can be re-read correctly.
    # A ClientError here aborts the handler (returns 500) so the DynamoDB
    # write and EventBridge publish are never reached; UserNotFoundException
    # is treated as idempotent success (Cognito user already gone).
    if COGNITO_USER_POOL_ID:
        if is_banned:
            # Banned user: disable the Cognito account so the email address
            # cannot be used to create a new account, bypassing the ban.
            try:
                cognito.admin_disable_user(
                    UserPoolId=COGNITO_USER_POOL_ID,
                    Username=user_id,
                )
            except cognito.exceptions.UserNotFoundException:
                logger.warning("Cognito user not found during ban-deletion: %s", user_id)
            except ClientError:
                logger.exception("Failed to disable Cognito user %s", user_id)
                return _response(500, {"code": "INTERNAL_ERROR", "message": "Failed to disable Cognito user."})
        else:
            # Active user: delete the Cognito account so the email address
            # is freed for re-registration (normal account deletion UX).
            try:
                cognito.admin_delete_user(
                    UserPoolId=COGNITO_USER_POOL_ID,
                    Username=user_id,
                )
            except cognito.exceptions.UserNotFoundException:
                logger.warning("Cognito user not found during deletion: %s", user_id)
            except ClientError:
                logger.exception("Failed to delete Cognito user %s", user_id)
                return _response(500, {"code": "INTERNAL_ERROR", "message": "Failed to delete Cognito user."})

    now = datetime.now(timezone.utc).isoformat()

    if is_banned:
        # For banned users, replace the full profile with a minimal tombstone
        # instead of deleting it outright.  The tombstone preserves the ban
        # status so that if EventBridge publish fails and the request is
        # retried, the handler can still re-read "banned" and call
        # admin_disable_user correctly (idempotent).  All personal data is
        # removed, satisfying GDPR deletion requirements.
        table.put_item(Item={
            "PK": f"USER#{user_id}",
            "SK": "PROFILE",
            "userId": user_id,
            "status": "banned",
            "deletedAt": now,
        })
    else:
        # Active user: delete the profile row so the slot is fully freed.
        # delete_item is idempotent — it's a no-op if the row is already
        # gone, which allows safe retries if a previous attempt partially
        # succeeded (e.g., profile deleted but EventBridge publish failed).
        table.delete_item(Key={"PK": f"USER#{user_id}", "SK": "PROFILE"})

    # Publish user.deleted event so other domains can clean up their data
    event_response = events.put_events(Entries=[{
        "Source": "kismet.profile-service",
        "DetailType": "user.deleted",
        "Detail": json.dumps({"userId": user_id, "timestamp": now}),
        "EventBusName": EVENT_BUS_NAME,
    }])
    event_entries = event_response.get("Entries", [])
    event_entry = event_entries[0] if event_entries else {}
    if event_response.get("FailedEntryCount", 0) > 0 or not event_entry.get("EventId"):
        logger.error(
            "Failed to publish user.deleted event for user %s: %s",
            user_id,
            json.dumps({
                "failedEntryCount": event_response.get("FailedEntryCount", 0),
                "entry": event_entry,
            }),
        )
        return _response(500, {"code": "INTERNAL_ERROR", "message": "Failed to publish deletion event."})

    return _response(200, {"message": "Profile deleted successfully"})


def handle_user_banned(detail: Dict[str, Any]) -> Dict[str, Any]:
    user_id = (detail.get("userId") or "").strip()
    if not user_id:
        return _response(400, {"code": "VALIDATION_ERROR", "message": "userId is required."})

    table = dynamodb.Table(PROFILES_TABLE_NAME)
    result = table.get_item(Key={"PK": f"USER#{user_id}", "SK": "PROFILE"})
    item = result.get("Item")
    if not item:
        logger.warning("user.banned received for missing profile: %s", user_id)
        return _response(200, {"message": "Profile not found; nothing to ban.", "userId": user_id})

    banned_at = detail.get("timestamp") or datetime.now(timezone.utc).isoformat()
    reason = (detail.get("reason") or "").strip()
    report_id = (detail.get("reportId") or "").strip()

    if item.get("status") != "banned":
        expr_names = {"#status": "status"}
        expr_values: Dict[str, Any] = {
            ":status": "banned",
            ":updatedAt": banned_at,
            ":bannedAt": banned_at,
        }
        set_parts = [
            "#status = :status",
            "updatedAt = :updatedAt",
            "bannedAt = :bannedAt",
        ]
        if reason:
            expr_values[":banReason"] = reason
            set_parts.append("banReason = :banReason")
        if report_id:
            expr_values[":banReportId"] = report_id
            set_parts.append("banReportId = :banReportId")

        table.update_item(
            Key={"PK": f"USER#{user_id}", "SK": "PROFILE"},
            UpdateExpression=f"SET {', '.join(set_parts)}",
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
        )
        item = table.get_item(Key={"PK": f"USER#{user_id}", "SK": "PROFILE"}).get("Item", item)

    events.put_events(Entries=[{
        "Source": "kismet.profile-service",
        "DetailType": "profile.banned",
        "Detail": json.dumps({
            "userId": user_id,
            "reason": item.get("banReason") or reason,
            "reportId": item.get("banReportId") or report_id,
            "timestamp": item.get("bannedAt") or banned_at,
        }),
        "EventBusName": EVENT_BUS_NAME,
    }])

    return _response(200, {"userId": user_id, "status": "banned"})


def _normalize_location(location) -> list:
    if isinstance(location, dict):
        latitude = location.get("latitude", 0)
        longitude = location.get("longitude", 0)
        try:
            return [float(latitude), float(longitude)]
        except (TypeError, ValueError):
            return []
    if isinstance(location, list):
        if len(location) != 2:
            return []
        try:
            return [float(location[0]), float(location[1])]
        except (TypeError, ValueError):
            return []
    return []


def _build_event_detail(item: Dict[str, Any]) -> Dict[str, Any]:
    """Build event payload with all fields D2 discovery-service needs."""
    return {
        "userId": item.get("userId", ""),
        "name": item.get("name", ""),
        "birthDate": item.get("birthDate", ""),
        "birthTime": item.get("birthTime", ""),
        "gender": item.get("gender", ""),
        "preferred_gender": item.get("interestedIn", ""),
        "location_coordinates": _normalize_location(item.get("location")),
        "city": item.get("city", ""),
        "avatarUrl": item.get("avatarUrl", ""),
        "bio": item.get("bio", ""),
        "interests": item.get("interests", []),
        "timestamp": item.get("updatedAt", "") or item.get("createdAt", ""),
    }


def _get_user_id(event: Dict[str, Any]) -> Optional[str]:
    claims = event.get("requestContext", {}).get("authorizer", {}).get("claims", {})
    return claims.get("sub") or claims.get("cognito:username")


def _get_event_detail(event: Dict[str, Any]) -> Dict[str, Any]:
    detail = event.get("detail") or {}
    if isinstance(detail, dict):
        return detail
    if isinstance(detail, str):
        try:
            parsed = json.loads(detail)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _get_method(event: Dict[str, Any]) -> str:
    method = (
        event.get("requestContext", {}).get("http", {}).get("method")
        or event.get("httpMethod")
        or ""
    )
    return str(method).upper()


def _get_path(event: Dict[str, Any]) -> str:
    path = (
        event.get("rawPath")
        or event.get("path")
        or event.get("requestContext", {}).get("http", {}).get("path")
        or "/"
    )
    if not path:
        return "/"
    normalized = str(path).strip()
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if normalized != "/" and normalized.endswith("/"):
        normalized = normalized.rstrip("/")
    return normalized


def _parse_body(event: Dict[str, Any]):
    body = event.get("body")
    if body in (None, ""):
        return None, None
    if isinstance(body, dict):
        return body, None
    try:
        return json.loads(body), None
    except json.JSONDecodeError:
        return None, _response(400, {"code": "VALIDATION_ERROR", "message": "Request body must be valid JSON."})


CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
}


def _response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body, default=str),
    }
