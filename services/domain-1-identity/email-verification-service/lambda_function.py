import json
import logging
import os
import secrets
import string
from datetime import datetime, timezone
from typing import Dict

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


def handler(event, context):
    event = event or {}
    method = _get_method(event)
    path = _get_path(event)
    operation = None

    try:
        if method == "POST" and path == "/verify/send":
            operation = "sendVerificationCode"
            payload, error = _parse_body(event)
            if error is not None:
                return error
            return handle_send(payload or {})
        elif method == "POST" and path == "/verify/confirm":
            operation = "confirmVerificationCode"
            payload, error = _parse_body(event)
            if error is not None:
                return error
            return handle_confirm(payload or {})
        elif method == "GET" and path == "/verify/status":
            operation = "getVerificationStatus"
            return handle_status(event)
        else:
            return _response(404, {"code": "NOT_FOUND", "message": f"No route matches {method} {path}."})
    except ClientError:
        logger.exception("AWS error in %s", operation or f"{method} {path}")
        return _response(500, {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."})
    except Exception:
        logger.exception("Unexpected error in %s", operation or f"{method} {path}")
        return _response(500, {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."})


def handle_send(body: Dict[str, str]) -> Dict[str, object]:
    email = (body.get("email") or "").strip().lower()
    if not email:
        return _response(400, {"code": "VALIDATION_ERROR", "message": "email is required."})
    if not email.endswith(".edu"):
        return _response(400, {"code": "VALIDATION_ERROR", "message": "Only .edu email addresses are supported."})

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

    return _response(200, {
        "message": "Verification code sent",
        "email": email,
        "expiresIn": CODE_EXPIRY_SECONDS,
    })


def handle_confirm(body: Dict[str, str]) -> Dict[str, object]:
    email = (body.get("email") or "").strip().lower()
    code = str(body.get("code") or "").strip()

    if not email or not code:
        return _response(400, {"code": "VALIDATION_ERROR", "message": "email and code are required."})

    table = dynamodb.Table(VERIFICATIONS_TABLE_NAME)
    result = table.get_item(Key={"PK": f"EMAIL#{email}", "SK": "LATEST"})
    item = result.get("Item")

    if not item:
        return _response(404, {"code": "NOT_FOUND", "message": "No verification code found for this email."})

    if item.get("verified"):
        return _response(200, {"message": "Email already verified", "email": email, "verified": True})

    now_ts = int(datetime.now(timezone.utc).timestamp())
    if item.get("ttl", 0) < now_ts:
        return _response(410, {"code": "EXPIRED", "message": "Verification code has expired. Please request a new code."})

    if item.get("code") != code:
        return _response(400, {"code": "VALIDATION_ERROR", "message": "Invalid verification code."})

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

    return _response(200, {"message": "Email verified successfully", "email": email, "verified": True})


def handle_status(event: Dict[str, object]) -> Dict[str, object]:
    # Prefer JWT claims injected by Cognito authorizer; fall back to ?email= for local dev
    claims = event.get("requestContext", {}).get("authorizer", {}).get("claims", {})
    email = claims.get("email") or (event.get("queryStringParameters") or {}).get("email", "")
    email = email.strip().lower()

    if not email:
        return _response(401, {"code": "UNAUTHORIZED", "message": "Authentication required."})

    table = dynamodb.Table(VERIFICATIONS_TABLE_NAME)
    result = table.get_item(Key={"PK": f"EMAIL#{email}", "SK": "LATEST"})
    item = result.get("Item")

    if not item:
        return _response(200, {"email": email, "verified": False, "verifiedAt": None})

    return _response(200, {
        "email": email,
        "verified": item.get("verified", False),
        "verifiedAt": item.get("verifiedAt"),
    })


def _generate_code() -> str:
    return "".join(secrets.choice(string.digits) for _ in range(CODE_LENGTH))


def _get_method(event: Dict[str, object]) -> str:
    method = (
        event.get("requestContext", {}).get("http", {}).get("method")
        or event.get("httpMethod")
        or ""
    )
    return str(method).upper()


def _get_path(event: Dict[str, object]) -> str:
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


def _parse_body(event: Dict[str, object]):
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


def _response(status_code: int, body: Dict[str, object]) -> Dict[str, object]:
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body),
    }
