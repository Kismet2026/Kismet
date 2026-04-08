import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SERVICE_NAME = "auth-service"

COGNITO_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "")
COGNITO_APP_CLIENT_ID = os.environ.get("COGNITO_APP_CLIENT_ID", "")
USERS_TABLE_NAME = os.environ.get("USERS_TABLE_NAME", "")
EVENT_BUS_NAME = os.environ.get("EVENT_BUS_NAME", "")

cognito = boto3.client("cognito-idp")
dynamodb = boto3.resource("dynamodb")
events = boto3.client("events")

ROUTES = {
    ("POST", "/auth/signup"): "signup",
    ("POST", "/auth/login"): "login",
    ("POST", "/auth/refresh"): "refresh",
    ("POST", "/auth/logout"): "logout",
}


def lambda_handler(event: Optional[Dict[str, Any]], context: Any) -> Dict[str, Any]:
    event = event or {}
    method = get_http_method(event)
    path = normalize_path(get_request_path(event))

    operation = ROUTES.get((method, path))
    if operation is None:
        return json_response(404, {"code": "NOT_FOUND", "message": f"No route matches {method} {path}."})

    payload, error = parse_json_body(event)
    if error is not None:
        return error

    try:
        if operation == "signup":
            return handle_signup(payload or {})
        if operation == "login":
            return handle_login(payload or {})
        if operation == "refresh":
            return handle_refresh(payload or {})
        if operation == "logout":
            return handle_logout(payload or {})
    except ClientError as exc:
        return _handle_cognito_error(exc)
    except Exception:
        logger.exception("Unexpected error in %s", operation)
        return json_response(500, {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."})


def handle_signup(body: Dict[str, Any]) -> Dict[str, Any]:
    email = (body.get("email") or "").strip()
    password = body.get("password") or ""

    if not email or not password:
        return json_response(400, {"code": "VALIDATION_ERROR", "message": "email and password are required."})

    response = cognito.sign_up(
        ClientId=COGNITO_APP_CLIENT_ID,
        Username=email,
        Password=password,
        UserAttributes=[{"Name": "email", "Value": email}],
    )

    user_id = response["UserSub"]
    created_at = datetime.now(timezone.utc).isoformat()

    item: Dict[str, Any] = {
        "PK": f"USER#{user_id}",
        "SK": "METADATA",
        "userId": user_id,
        "email": email,
        "createdAt": created_at,
    }
    if body.get("birthDate"):
        item["birthDate"] = body["birthDate"]
    if body.get("birthTime"):
        item["birthTime"] = body["birthTime"]

    dynamodb.Table(USERS_TABLE_NAME).put_item(Item=item)

    events.put_events(Entries=[{
        "Source": "kismet.auth-service",
        "DetailType": "user.created",
        "Detail": json.dumps({"userId": user_id, "email": email, "createdAt": created_at}),
        "EventBusName": EVENT_BUS_NAME,
    }])

    return json_response(201, {"userId": user_id, "email": email, "createdAt": created_at})


def handle_login(body: Dict[str, Any]) -> Dict[str, Any]:
    email = (body.get("email") or "").strip()
    password = body.get("password") or ""

    if not email or not password:
        return json_response(400, {"code": "VALIDATION_ERROR", "message": "email and password are required."})

    response = cognito.initiate_auth(
        ClientId=COGNITO_APP_CLIENT_ID,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": email, "PASSWORD": password},
    )

    auth = response["AuthenticationResult"]
    return json_response(200, {
        "accessToken": auth["AccessToken"],
        "refreshToken": auth.get("RefreshToken"),
        "idToken": auth["IdToken"],
        "expiresIn": auth["ExpiresIn"],
    })


def handle_refresh(body: Dict[str, Any]) -> Dict[str, Any]:
    refresh_token = body.get("refreshToken") or ""
    if not refresh_token:
        return json_response(400, {"code": "VALIDATION_ERROR", "message": "refreshToken is required."})

    response = cognito.initiate_auth(
        ClientId=COGNITO_APP_CLIENT_ID,
        AuthFlow="REFRESH_TOKEN_AUTH",
        AuthParameters={"REFRESH_TOKEN": refresh_token},
    )

    auth = response["AuthenticationResult"]
    return json_response(200, {"accessToken": auth["AccessToken"], "expiresIn": auth["ExpiresIn"]})


def handle_logout(body: Dict[str, Any]) -> Dict[str, Any]:
    refresh_token = body.get("refreshToken") or ""
    if not refresh_token:
        return json_response(400, {"code": "VALIDATION_ERROR", "message": "refreshToken is required."})

    cognito.revoke_token(Token=refresh_token, ClientId=COGNITO_APP_CLIENT_ID)
    return json_response(200, {"message": "Successfully logged out"})


def _handle_cognito_error(exc: ClientError) -> Dict[str, Any]:
    code = exc.response["Error"]["Code"]
    message = exc.response["Error"]["Message"]

    mapping = {
        "UsernameExistsException": (409, "CONFLICT", "An account with this email already exists."),
        "UserNotFoundException": (404, "NOT_FOUND", "No account found with this email."),
        "NotAuthorizedException": (401, "UNAUTHORIZED", "Invalid credentials."),
        "UserNotConfirmedException": (403, "FORBIDDEN", "Account email is not yet confirmed."),
        "InvalidPasswordException": (400, "VALIDATION_ERROR", message),
        "InvalidParameterException": (400, "VALIDATION_ERROR", message),
        "TooManyRequestsException": (429, "RATE_LIMITED", "Too many requests. Please try again later."),
    }

    if code in mapping:
        status, error_code, error_message = mapping[code]
        return json_response(status, {"code": error_code, "message": error_message})

    logger.error("Unhandled Cognito error %s: %s", code, message)
    return json_response(500, {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."})


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


def json_response(status_code: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }
