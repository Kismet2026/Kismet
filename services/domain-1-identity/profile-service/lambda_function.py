import json
import re
from typing import Any, Dict, Optional, Tuple


SERVICE_NAME = "profile-service"
PROFILE_DETAIL_PATTERN = re.compile(r"^/profiles/(?P<userId>[^/]+)$")


def lambda_handler(event: Optional[Dict[str, Any]], context: Any) -> Dict[str, Any]:
    event = event or {}
    method = get_http_method(event)
    path = normalize_path(get_request_path(event))

    operation, route_params = resolve_route(method, path)
    if operation is None:
        return json_response(
            404,
            {
                "code": "NOT_FOUND",
                "message": f"No route matches {method} {path}.",
            },
        )

    if method in {"POST", "PUT"}:
        payload, error = parse_json_body(event)
        if error is not None:
            return error
    else:
        payload = None

    request_id = getattr(context, "aws_request_id", None)
    return json_response(
        501,
        {
            "code": "NOT_IMPLEMENTED",
            "message": f"{operation} is scaffolded but not implemented yet.",
            "service": SERVICE_NAME,
            "operation": operation,
            "path": path,
            "pathParameters": route_params,
            "requestId": request_id,
            "receivedBody": payload,
        },
    )


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
        return None, json_response(
            400,
            {
                "code": "VALIDATION_ERROR",
                "message": "Request body must be valid JSON.",
            },
        )


def json_response(status_code: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }
