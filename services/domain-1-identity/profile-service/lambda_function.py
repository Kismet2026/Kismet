import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SERVICE_NAME = "profile-service"
PROFILE_DETAIL_PATTERN = re.compile(r"^/profiles/(?P<userId>[^/]+)$")

PROFILES_TABLE_NAME = os.environ.get("PROFILES_TABLE_NAME", "")
EVENT_BUS_NAME = os.environ.get("EVENT_BUS_NAME", "")

dynamodb = boto3.resource("dynamodb")
events = boto3.client("events")

UPDATABLE_FIELDS = frozenset({"name", "bio", "gender", "interestedIn", "birthDate", "birthTime", "location", "interests", "city", "avatarUrl"})
VALID_GENDERS = {"male", "female", "non-binary"}
VALID_INTERESTED_IN = {"male", "female", "non-binary", "everyone"}


def lambda_handler(event: Optional[Dict[str, Any]], context: Any) -> Dict[str, Any]:
    event = event or {}
    method = get_http_method(event)
    path = normalize_path(get_request_path(event))

    operation, route_params = resolve_route(method, path)
    if operation is None:
        return json_response(404, {"code": "NOT_FOUND", "message": f"No route matches {method} {path}."})

    if method in {"POST", "PUT"}:
        payload, error = parse_json_body(event)
        if error is not None:
            return error
    else:
        payload = None

    user_id = _get_user_id(event)

    try:
        if operation == "createProfile":
            if not user_id:
                return json_response(401, {"code": "UNAUTHORIZED", "message": "Authentication required."})
            return handle_create(user_id, payload or {})
        if operation == "getProfile":
            return handle_get(route_params["userId"])
        if operation == "updateProfile":
            if not user_id:
                return json_response(401, {"code": "UNAUTHORIZED", "message": "Authentication required."})
            return handle_update(user_id, route_params["userId"], payload or {})
        if operation == "deleteProfile":
            if not user_id:
                return json_response(401, {"code": "UNAUTHORIZED", "message": "Authentication required."})
            return handle_delete(user_id, route_params["userId"])
    except ClientError:
        logger.exception("AWS error in %s", operation)
        return json_response(500, {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."})
    except Exception:
        logger.exception("Unexpected error in %s", operation)
        return json_response(500, {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."})


def handle_create(user_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    name = (body.get("name") or "").strip()
    gender = (body.get("gender") or "").strip()
    interested_in = (body.get("interestedIn") or "").strip()
    birth_date = (body.get("birthDate") or "").strip()
    location = body.get("location")

    if not name:
        return json_response(400, {"code": "VALIDATION_ERROR", "message": "name is required."})
    if not gender or gender not in VALID_GENDERS:
        return json_response(400, {"code": "VALIDATION_ERROR", "message": f"gender is required and must be one of: {', '.join(sorted(VALID_GENDERS))}."})
    if not interested_in or interested_in not in VALID_INTERESTED_IN:
        return json_response(400, {"code": "VALIDATION_ERROR", "message": f"interestedIn is required and must be one of: {', '.join(sorted(VALID_INTERESTED_IN))}."})
    if not birth_date:
        return json_response(400, {"code": "VALIDATION_ERROR", "message": "birthDate is required."})
    if not location:
        return json_response(400, {"code": "VALIDATION_ERROR", "message": "location is required."})

    table = dynamodb.Table(PROFILES_TABLE_NAME)
    existing = table.get_item(Key={"PK": f"USER#{user_id}", "SK": "PROFILE"})
    if existing.get("Item"):
        return json_response(409, {"code": "CONFLICT", "message": "Profile already exists."})

    now = datetime.now(timezone.utc).isoformat()
    item: Dict[str, Any] = {
        "PK": f"USER#{user_id}",
        "SK": "PROFILE",
        "userId": user_id,
        "name": name,
        "gender": gender,
        "interestedIn": interested_in,
        "birthDate": birth_date,
        "location": location,
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
        "Detail": json.dumps(_build_event_detail(item)),
        "EventBusName": EVENT_BUS_NAME,
    }])

    profile = {k: v for k, v in item.items() if k not in ("PK", "SK")}
    return json_response(201, profile)


def handle_get(user_id: str) -> Dict[str, Any]:
    table = dynamodb.Table(PROFILES_TABLE_NAME)
    result = table.get_item(Key={"PK": f"USER#{user_id}", "SK": "PROFILE"})
    item = result.get("Item")

    if not item:
        return json_response(404, {"code": "NOT_FOUND", "message": "Profile not found."})

    profile = {k: v for k, v in item.items() if k not in ("PK", "SK")}
    return json_response(200, profile)


def handle_update(caller_id: str, user_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    if caller_id != user_id:
        return json_response(403, {"code": "FORBIDDEN", "message": "You can only update your own profile."})

    table = dynamodb.Table(PROFILES_TABLE_NAME)
    if not table.get_item(Key={"PK": f"USER#{user_id}", "SK": "PROFILE"}).get("Item"):
        return json_response(404, {"code": "NOT_FOUND", "message": "Profile not found."})

    updates = {k: v for k, v in body.items() if k in UPDATABLE_FIELDS}
    if not updates:
        return json_response(400, {"code": "VALIDATION_ERROR", "message": "No valid fields to update."})

    if "gender" in updates and updates["gender"] not in VALID_GENDERS:
        return json_response(400, {"code": "VALIDATION_ERROR", "message": f"gender must be one of: {', '.join(sorted(VALID_GENDERS))}."})
    if "interestedIn" in updates and updates["interestedIn"] not in VALID_INTERESTED_IN:
        return json_response(400, {"code": "VALIDATION_ERROR", "message": f"interestedIn must be one of: {', '.join(sorted(VALID_INTERESTED_IN))}."})


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
        "Detail": json.dumps(_build_event_detail(updated_item)),
        "EventBusName": EVENT_BUS_NAME,
    }])

    profile = {k: v for k, v in updated_item.items() if k not in ("PK", "SK")}
    return json_response(200, profile)


def handle_delete(caller_id: str, user_id: str) -> Dict[str, Any]:
    if caller_id != user_id:
        return json_response(403, {"code": "FORBIDDEN", "message": "You can only delete your own profile."})

    table = dynamodb.Table(PROFILES_TABLE_NAME)
    if not table.get_item(Key={"PK": f"USER#{user_id}", "SK": "PROFILE"}).get("Item"):
        return json_response(404, {"code": "NOT_FOUND", "message": "Profile not found."})

    table.delete_item(Key={"PK": f"USER#{user_id}", "SK": "PROFILE"})
    return json_response(200, {"message": "Profile deleted successfully"})


def _build_event_detail(item: Dict[str, Any]) -> Dict[str, Any]:
    """Build event payload with all fields D2 discovery-service needs."""
    return {
        "userId": item.get("userId", ""),
        "name": item.get("name", ""),
        "birthDate": item.get("birthDate", ""),
        "birthTime": item.get("birthTime", ""),
        "gender": item.get("gender", ""),
        "preferred_gender": item.get("interestedIn", ""),
        "location_coordinates": item.get("location", []),
        "city": item.get("city", ""),
        "avatarUrl": item.get("avatarUrl", ""),
        "bio": item.get("bio", ""),
        "interests": item.get("interests", []),
        "timestamp": item.get("updatedAt", "") or item.get("createdAt", ""),
    }


def resolve_route(method: str, path: str) -> Tuple[Optional[str], Dict[str, str]]:
    if method == "POST" and path == "/profiles":
        return "createProfile", {}

    match = PROFILE_DETAIL_PATTERN.match(path)
    if not match:
        return None, {}

    user_id = match.group("userId")
    if method == "GET":
        return "getProfile", {"userId": user_id}
    if method == "PUT":
        return "updateProfile", {"userId": user_id}
    if method == "DELETE":
        return "deleteProfile", {"userId": user_id}

    return None, {}


def _get_user_id(event: Dict[str, Any]) -> Optional[str]:
    claims = event.get("requestContext", {}).get("authorizer", {}).get("claims", {})
    return claims.get("sub") or claims.get("cognito:username")


def get_http_method(event: Dict[str, Any]) -> str:
    method = (
        event.get("requestContext", {}).get("http", {}).get("method")
        or event.get("httpMethod")
        or ""
    )
    return str(method).upper()


def get_request_path(event: Dict[str, Any]) -> str:
    return (
        event.get("rawPath")
        or event.get("path")
        or event.get("requestContext", {}).get("http", {}).get("path")
        or "/"
    )


def normalize_path(path: Any) -> str:
    if not path:
        return "/"
    normalized = str(path).strip()
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if normalized != "/" and normalized.endswith("/"):
        normalized = normalized.rstrip("/")
    return normalized


def parse_json_body(event: Dict[str, Any]):
    body = event.get("body")
    if body in (None, ""):
        return None, None
    if isinstance(body, dict):
        return body, None
    try:
        return json.loads(body), None
    except json.JSONDecodeError:
        return None, json_response(400, {"code": "VALIDATION_ERROR", "message": "Request body must be valid JSON."})


CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
}


def json_response(status_code: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(payload),
    }
