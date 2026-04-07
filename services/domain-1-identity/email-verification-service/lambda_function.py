import json
from typing import Any, Dict, Optional


SERVICE_NAME = "email-verification-service"

ROUTES = {
    ("POST", "/verify/send"): {
        "operation": "sendVerificationCode",
        "expects_body": True,
    },
    ("POST", "/verify/confirm"): {
        "operation": "confirmVerificationCode",
        "expects_body": True,
    },
    ("GET", "/verify/status"): {
        "operation": "getVerificationStatus",
        "expects_body": False,
    },
}


def lambda_handler(event: Optional[Dict[str, Any]], context: Any) -> Dict[str, Any]:
    event = event or {}
    method = get_http_method(event)
    path = normalize_path(get_request_path(event))

    route = ROUTES.get((method, path))
    if route is None:
        return json_response(
            404,
            {
                "code": "NOT_FOUND",
                "message": f"No route matches {method} {path}.",
            },
        )

    payload = None
    if route["expects_body"]:
        payload, error = parse_json_body(event)
        if error is not None:
            return error

    request_id = getattr(context, "aws_request_id", None)
    return json_response(
        501,
        {
            "code": "NOT_IMPLEMENTED",
            "message": f'{route["operation"]} is scaffolded but not implemented yet.',
            "service": SERVICE_NAME,
            "operation": route["operation"],
            "path": path,
            "requestId": request_id,
            "receivedBody": payload,
        },
    )


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
