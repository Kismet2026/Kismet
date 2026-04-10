import json
import logging
import os
import secrets
import string
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SERVICE_NAME = "email-verification-service"
CODE_LENGTH = 6
CODE_EXPIRY_SECONDS = 600       # 10 minutes
VERIFIED_RECORD_TTL_SECONDS = 30 * 24 * 3600  # 30 days

COGNITO_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "")
VERIFICATIONS_TABLE_NAME = os.environ.get("VERIFICATIONS_TABLE_NAME", "")
SES_SOURCE_EMAIL = os.environ.get("SES_SOURCE_EMAIL", "")

dynamodb = boto3.resource("dynamodb")
cognito = boto3.client("cognito-idp")
ses = boto3.client("ses")

ROUTES = {
    ("POST", "/verify/send"): {"operation": "sendVerificationCode", "expects_body": True},
    ("POST", "/verify/confirm"): {"operation": "confirmVerificationCode", "expects_body": True},
    ("GET", "/verify/status"): {"operation": "getVerificationStatus", "expects_body": False},
}


def lambda_handler(event: Optional[Dict[str, Any]], context: Any) -> Dict[str, Any]:
    event = event or {}
    method = get_http_method(event)
    path = normalize_path(get_request_path(event))

    route = ROUTES.get((method, path))
    if route is None:
        return json_response(404, {"code": "NOT_FOUND", "message": f"No route matches {method} {path}."})

    payload = None
    if route["expects_body"]:
        payload, error = parse_json_body(event)
        if error is not None:
            return error

    try:
        if route["operation"] == "sendVerificationCode":
            return handle_send(payload or {})
        if route["operation"] == "confirmVerificationCode":
            return handle_confirm(payload or {})
        if route["operation"] == "getVerificationStatus":
            return handle_status(event)
    except ClientError:
        logger.exception("AWS error in %s", route["operation"])
        return json_response(500, {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."})
    except Exception:
        logger.exception("Unexpected error in %s", route["operation"])
        return json_response(500, {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."})


def handle_send(body: Dict[str, Any]) -> Dict[str, Any]:
    email = (body.get("email") or "").strip().lower()
    if not email:
        return json_response(400, {"code": "VALIDATION_ERROR", "message": "email is required."})
    if not email.endswith(".edu"):
        return json_response(400, {"code": "VALIDATION_ERROR", "message": "Only .edu email addresses are supported."})

    code = _generate_code()
    now = datetime.now(timezone.utc)
    ttl = int(now.timestamp()) + CODE_EXPIRY_SECONDS

    dynamodb.Table(VERIFICATIONS_TABLE_NAME).put_item(Item={
        "PK": f"EMAIL#{email}",
        "SK": "LATEST",
        "email": email,
        "code": code,
        "verified": False,
        "createdAt": now.isoformat(),
        "ttl": ttl,
    })

    ses.send_email(
        Source=SES_SOURCE_EMAIL,
        Destination={"ToAddresses": [email]},
        Message={
            "Subject": {"Data": "Your Kismet verification code"},
            "Body": {"Text": {"Data": (
                f"Your Kismet verification code is: {code}\n\n"
                f"This code expires in {CODE_EXPIRY_SECONDS // 60} minutes.\n\n"
                "If you did not request this code, you can safely ignore this email."
            )}},
        },
    )

    return json_response(200, {
        "message": "Verification code sent",
        "email": email,
        "expiresIn": CODE_EXPIRY_SECONDS,
    })


def handle_confirm(body: Dict[str, Any]) -> Dict[str, Any]:
    email = (body.get("email") or "").strip().lower()
    code = str(body.get("code") or "").strip()

    if not email or not code:
        return json_response(400, {"code": "VALIDATION_ERROR", "message": "email and code are required."})

    table = dynamodb.Table(VERIFICATIONS_TABLE_NAME)
    result = table.get_item(Key={"PK": f"EMAIL#{email}", "SK": "LATEST"})
    item = result.get("Item")

    if not item:
        return json_response(404, {"code": "NOT_FOUND", "message": "No verification code found for this email."})

    if item.get("verified"):
        return json_response(200, {"message": "Email already verified", "email": email, "verified": True})

    now_ts = int(datetime.now(timezone.utc).timestamp())
    if item.get("ttl", 0) < now_ts:
        return json_response(410, {"code": "EXPIRED", "message": "Verification code has expired. Please request a new code."})

    if item.get("code") != code:
        return json_response(400, {"code": "VALIDATION_ERROR", "message": "Invalid verification code."})

    verified_at = datetime.now(timezone.utc).isoformat()
    long_ttl = int(datetime.now(timezone.utc).timestamp()) + VERIFIED_RECORD_TTL_SECONDS

    table.update_item(
        Key={"PK": f"EMAIL#{email}", "SK": "LATEST"},
        UpdateExpression="SET verified = :v, verifiedAt = :va, #ttl = :ttl REMOVE #code",
        ExpressionAttributeNames={"#code": "code", "#ttl": "ttl"},
        ExpressionAttributeValues={":v": True, ":va": verified_at, ":ttl": long_ttl},
    )

    try:
        cognito.admin_update_user_attributes(
            UserPoolId=COGNITO_USER_POOL_ID,
            Username=email,
            UserAttributes=[{"Name": "email_verified", "Value": "true"}],
        )
    except ClientError:
        # DynamoDB is source of truth; Cognito sync failure is non-fatal
        logger.warning("Failed to sync email_verified to Cognito for %s", email)

    return json_response(200, {"message": "Email verified successfully", "email": email, "verified": True})


def handle_status(event: Dict[str, Any]) -> Dict[str, Any]:
    # Prefer JWT claims injected by Cognito authorizer; fall back to ?email= for local dev
    claims = event.get("requestContext", {}).get("authorizer", {}).get("claims", {})
    email = claims.get("email") or (event.get("queryStringParameters") or {}).get("email", "")
    email = email.strip().lower()

    if not email:
        return json_response(401, {"code": "UNAUTHORIZED", "message": "Authentication required."})

    table = dynamodb.Table(VERIFICATIONS_TABLE_NAME)
    result = table.get_item(Key={"PK": f"EMAIL#{email}", "SK": "LATEST"})
    item = result.get("Item")

    if not item:
        return json_response(200, {"email": email, "verified": False, "verifiedAt": None})

    return json_response(200, {
        "email": email,
        "verified": item.get("verified", False),
        "verifiedAt": item.get("verifiedAt"),
    })


def _generate_code() -> str:
    return "".join(secrets.choice(string.digits) for _ in range(CODE_LENGTH))


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
