import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import boto3
from boto3.dynamodb.conditions import Key

PRESENCE_TABLE = os.environ["PRESENCE_TABLE"]
TYPING_TABLE = os.environ["TYPING_TABLE"]
MATCHES_TABLE = os.environ["MATCHES_TABLE"]

ONLINE_TTL_SECONDS = 60
TYPING_TTL_SECONDS = 5

dynamodb = boto3.resource("dynamodb")
presence_table = dynamodb.Table(PRESENCE_TABLE)
typing_table = dynamodb.Table(TYPING_TABLE)
matches_table = dynamodb.Table(MATCHES_TABLE)


def lambda_handler(event: Optional[Dict[str, Any]], context: Any) -> Dict[str, Any]:
    event = event or {}
    method = get_http_method(event)
    path = normalize_path(get_request_path(event))
    path_params = event.get("pathParameters") or {}

    claims = event.get("requestContext", {}).get("authorizer", {}).get("claims", {})
    user_id = claims.get("sub") or claims.get("cognito:username", "")
    if not user_id:
        return json_response(401, {"code": "UNAUTHORIZED", "message": "Authentication required"})

    # POST /presence/heartbeat
    if method == "POST" and path.endswith("/heartbeat"):
        return handle_heartbeat(user_id)

    # POST /presence/{matchId}/typing  or  GET /presence/{matchId}/typing
    if "matchId" in path_params:
        match_id = path_params["matchId"]
        if method == "POST":
            return handle_typing_start(match_id, user_id)
        if method == "GET":
            return handle_typing_get(match_id, user_id)

    # GET /presence/{userId}
    if method == "GET" and "userId" in path_params:
        return handle_get_presence(path_params["userId"])

    return json_response(404, {"code": "NOT_FOUND", "message": f"No route matches {method} {path}"})


# ── Handlers ──────────────────────────────────────────────────────────────────

def handle_heartbeat(user_id: str) -> Dict[str, Any]:
    """POST /presence/heartbeat — Mark the caller as online. TTL auto-expires after 60s."""
    now = datetime.now(timezone.utc)
    expires_at = int(now.timestamp()) + ONLINE_TTL_SECONDS
    now_iso = now.isoformat()

    presence_table.put_item(Item={
        "PK": f"USER#{user_id}",
        "SK": "STATUS",
        "userId": user_id,
        "status": "online",
        "lastSeen": now_iso,
        "ttl": expires_at,
    })

    return json_response(200, {
        "userId": user_id,
        "status": "online",
        "expiresAt": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
    })


def handle_get_presence(target_user_id: str) -> Dict[str, Any]:
    """GET /presence/{userId} — Return online/offline status for any user."""
    result = presence_table.get_item(Key={"PK": f"USER#{target_user_id}", "SK": "STATUS"})
    item = result.get("Item")

    if not item:
        return json_response(404, {"code": "NOT_FOUND", "message": "User not found"})

    return json_response(200, {
        "userId": target_user_id,
        "status": item.get("status", "offline"),
        "lastSeen": item.get("lastSeen"),
    })


def handle_typing_start(match_id: str, user_id: str) -> Dict[str, Any]:
    """POST /presence/{matchId}/typing — Signal that the caller is typing. TTL auto-expires after 5s."""
    match_item, error = get_match_for_user(match_id, user_id)
    if error:
        return error

    now = datetime.now(timezone.utc)
    expires_at = int(now.timestamp()) + TYPING_TTL_SECONDS
    now_iso = now.isoformat()

    typing_table.put_item(Item={
        "PK": f"MATCH#{match_id}#USER#{user_id}",
        "SK": "TYPING",
        "matchId": match_id,
        "userId": user_id,
        "since": now_iso,
        "ttl": expires_at,
    })

    return json_response(200, {
        "matchId": match_id,
        "userId": user_id,
        "typing": True,
        "expiresAt": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
    })


def handle_typing_get(match_id: str, user_id: str) -> Dict[str, Any]:
    """GET /presence/{matchId}/typing — Return who (other than the caller) is currently typing."""
    match_item, error = get_match_for_user(match_id, user_id)
    if error:
        return error

    # Find the other participant and check if they have an active typing record.
    other_user_id = get_other_participant(match_item, user_id)
    result = typing_table.get_item(
        Key={"PK": f"MATCH#{match_id}#USER#{other_user_id}", "SK": "TYPING"}
    )
    item = result.get("Item")

    typing_users = []
    if item:
        typing_users.append({"userId": other_user_id, "since": item.get("since")})

    return json_response(200, {"matchId": match_id, "typingUsers": typing_users})


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_match_for_user(match_id: str, user_id: str) -> Tuple[Optional[dict], Optional[dict]]:
    """Look up a match and verify that user_id is a participant. Returns (item, error)."""
    result = matches_table.get_item(Key={"PK": f"MATCH#{match_id}", "SK": "META"})
    item = result.get("Item")

    if not item:
        return None, json_response(404, {"code": "NOT_FOUND", "message": "Match not found"})

    participants = {item.get("userAId"), item.get("userBId")}
    if user_id not in participants:
        return None, json_response(403, {"code": "FORBIDDEN", "message": "User is not a participant of this match"})

    return item, None


def get_other_participant(match_item: dict, user_id: str) -> str:
    if match_item.get("userAId") == user_id:
        return match_item.get("userBId", "")
    return match_item.get("userAId", "")


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
    p = str(path or "/").strip()
    if not p.startswith("/"):
        p = f"/{p}"
    if p != "/" and p.endswith("/"):
        p = p.rstrip("/")
    return p


def json_response(status_code: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }


handler = lambda_handler
