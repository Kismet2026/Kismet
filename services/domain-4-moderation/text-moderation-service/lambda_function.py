import json
from typing import Any, Dict, Optional, Tuple

SERVICE_NAME = "text-moderation-service"


def lambda_handler(event: Optional[Dict[str, Any]], context: Any) -> Dict[str, Any]:
    event = event or {}
    if _is_eventbridge_event(event):
        return handle_eventbridge(event, context)
    return handle_http(event, context)


def _is_eventbridge_event(event: Dict[str, Any]) -> bool:
    if event.get("httpMethod") or event.get("requestContext", {}).get("http"):
        return False
    return "detail" in event and "detail-type" in event


def handle_eventbridge(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    request_id = getattr(context, "aws_request_id", None)
    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "error": {
                    "code": "NOT_IMPLEMENTED",
                    "message": "message.sent consumer is scaffolded for Week 1; implement in Week 2.",
                },
                "service": SERVICE_NAME,
                "source": event.get("source"),
                "detailType": event.get("detail-type"),
                "requestId": request_id,
            }
        ),
    }


def resolve_route_with_event(
    method: str, path: str, event: Dict[str, Any]
) -> Tuple[Optional[str], Dict[str, Any]]:
    if method == "POST" and path == "/moderate/text":
        extras: Dict[str, Any] = {}
        body, err = _try_parse_json_body_for_debug(event)
        if err:
            extras["bodyParseNote"] = "invalid JSON on scaffold (Week 2 will validate)"
        elif body is not None:
            extras["receivedBodyKeys"] = list(body.keys())
        return "moderateText", extras

    if method == "GET" and path == "/moderate/text/history":
        params = event.get("queryStringParameters") or {}
        return "moderateTextHistory", {"queryKeys": list(params.keys())}

    return None, {}


def handle_http(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    method = _http_method(event)
    path = _normalize_path(_http_path(event))

    operation, extras = resolve_route_with_event(method, path, event)
    if operation is None:
        if path.startswith("/moderate/text"):
            return error_response(
                404,
                "NOT_FOUND",
                f"No route matches {method} {path}.",
            )
        return error_response(
            404,
            "NOT_FOUND",
            f"No route matches {method} {path}.",
        )

    request_id = getattr(context, "aws_request_id", None)
    return error_response(
        501,
        "NOT_IMPLEMENTED",
        f"{operation} is scaffolded for Week 1; implement in Week 2.",
        extra={
            "service": SERVICE_NAME,
            "operation": operation,
            "path": path,
            "requestId": request_id,
            **extras,
        },
    )


def _try_parse_json_body_for_debug(event: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], bool]:
    body = event.get("body")
    if body in (None, ""):
        return None, False
    if isinstance(body, dict):
        return body, False
    try:
        return json.loads(body), False
    except json.JSONDecodeError:
        return None, True


def _http_method(event: Dict[str, Any]) -> str:
    m = (
        event.get("requestContext", {}).get("http", {}).get("method")
        or event.get("httpMethod")
        or ""
    )
    return str(m).upper()


def _http_path(event: Dict[str, Any]) -> str:
    return (
        event.get("rawPath")
        or event.get("path")
        or event.get("requestContext", {}).get("http", {}).get("path")
        or "/"
    )


def _normalize_path(path: Any) -> str:
    if not path:
        return "/"
    p = str(path).strip()
    if not p.startswith("/"):
        p = f"/{p}"
    if p != "/" and p.endswith("/"):
        p = p.rstrip("/")
    return p


def error_response(
    status_code: int,
    code: str,
    message: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"error": {"code": code, "message": message}}
    if extra:
        payload.update(extra)
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }
