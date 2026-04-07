import json
import re
from typing import Any, Dict, Optional, Tuple


SERVICE_NAME = "photo-service"
PHOTO_DETAIL_PATTERN = re.compile(r"^/photos/(?P<identifier>[^/]+)$")
PHOTO_PRIMARY_PATTERN = re.compile(r"^/photos/(?P<photoId>[^/]+)/primary$")


def lambda_handler(event: Optional[Dict[str, Any]], context: Any) -> Dict[str, Any]:
    event = event or {}
    method = get_http_method(event)
    path = normalize_path(get_request_path(event))

    operation, route_params, expects_body = resolve_route(method, path)
    if operation is None:
        return json_response(
            404,
            {
                "code": "NOT_FOUND",
                "message": f"No route matches {method} {path}.",
            },
        )

    payload = None
    if expects_body:
        payload, error = parse_json_body(event)
        if error is not None:
            return error

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


def resolve_route(method: str, path: str) -> Tuple[Optional[str], Dict[str, str], bool]:
    if method == "POST" and path == "/photos/upload":
        return "uploadPhoto", {}, True

    primary_match = PHOTO_PRIMARY_PATTERN.match(path)
    if primary_match and method == "PUT":
        return "setPrimaryPhoto", {"photoId": primary_match.group("photoId")}, False

    detail_match = PHOTO_DETAIL_PATTERN.match(path)
    if not detail_match:
        return None, {}, False

    identifier = detail_match.group("identifier")
    if method == "GET":
        return "listPhotos", {"userId": identifier}, False
    if method == "DELETE":
        return "deletePhoto", {"photoId": identifier}, False

    return None, {}, False


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
