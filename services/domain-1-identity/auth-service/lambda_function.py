import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict

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


def handler(event, context):
    event = event or {}
    method = _get_method(event)
    path = _get_path(event)
    operation = None

    try:
        if method == "POST" and path == "/auth/signup":
            operation = "signup"
            payload, error = _parse_body(event)
            if error is not None:
                return error
            return handle_signup(payload or {})
        elif method == "POST" and path == "/auth/login":
            operation = "login"
            payload, error = _parse_body(event)
            if error is not None:
                return error
            return handle_login(payload or {})
        elif method == "POST" and path == "/auth/refresh":
            operation = "refresh"
            payload, error = _parse_body(event)
            if error is not None:
                return error
            return handle_refresh(payload or {})
        elif method == "POST" and path == "/auth/logout":
            operation = "logout"
            payload, error = _parse_body(event)
            if error is not None:
                return error
            return handle_logout(payload or {})
        else:
            return _response(404, {"code": "NOT_FOUND", "message": f"No route matches {method} {path}."})
    except ClientError as exc:
        return _handle_cognito_error(exc)
    except Exception:
        logger.exception("Unexpected error in %s", operation or f"{method} {path}")
        return _response(500, {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."})


def handle_signup(body: Dict[str, Any]) -> Dict[str, Any]:
    email = (body.get("email") or "").strip()
    password = body.get("password") or ""

    if not email or not password:
        return _response(400, {"code": "VALIDATION_ERROR", "message": "email and password are required."})

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
        "Detail": json.dumps({"userId": user_id, "email": email, "timestamp": created_at}),
        "EventBusName": EVENT_BUS_NAME,
    }])

    return _response(201, {"userId": user_id, "email": email, "createdAt": created_at})


def handle_login(body: Dict[str, Any]) -> Dict[str, Any]:
    email = (body.get("email") or "").strip()
    password = body.get("password") or ""

    if not email or not password:
        return _response(400, {"code": "VALIDATION_ERROR", "message": "email and password are required."})

    response = cognito.initiate_auth(
        ClientId=COGNITO_APP_CLIENT_ID,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": email, "PASSWORD": password},
    )

    auth = response["AuthenticationResult"]
    return _response(200, {
        "accessToken": auth["AccessToken"],
        "refreshToken": auth.get("RefreshToken"),
        "idToken": auth["IdToken"],
        "expiresIn": auth["ExpiresIn"],
    })


def handle_refresh(body: Dict[str, Any]) -> Dict[str, Any]:
    refresh_token = body.get("refreshToken") or ""
    if not refresh_token:
        return _response(400, {"code": "VALIDATION_ERROR", "message": "refreshToken is required."})

    response = cognito.initiate_auth(
        ClientId=COGNITO_APP_CLIENT_ID,
        AuthFlow="REFRESH_TOKEN_AUTH",
        AuthParameters={"REFRESH_TOKEN": refresh_token},
    )

    auth = response["AuthenticationResult"]
    return _response(200, {"accessToken": auth["AccessToken"], "expiresIn": auth["ExpiresIn"]})


def handle_logout(body: Dict[str, Any]) -> Dict[str, Any]:
    refresh_token = body.get("refreshToken") or ""
    if not refresh_token:
        return _response(400, {"code": "VALIDATION_ERROR", "message": "refreshToken is required."})

    cognito.revoke_token(Token=refresh_token, ClientId=COGNITO_APP_CLIENT_ID)
    return _response(200, {"message": "Successfully logged out"})


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
        return _response(status, {"code": error_code, "message": error_message})

    logger.error("Unhandled Cognito error %s: %s", code, message)
    return _response(500, {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."})


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
        "body": json.dumps(body),
    }


lambda_handler = handler
