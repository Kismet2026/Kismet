import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SERVICE_NAME = "photo-service"
USER_PHOTOS_PATTERN = re.compile(r"^/users/(?P<userId>[^/]+)/photos$")
PHOTO_DETAIL_PATTERN = re.compile(r"^/photos/(?P<photoId>[^/]+)$")
PHOTO_PRIMARY_PATTERN = re.compile(r"^/photos/(?P<photoId>[^/]+)/primary$")
PHOTO_CONFIRM_PATTERN = re.compile(r"^/photos/(?P<photoId>[^/]+)/confirm$")

PHOTOS_TABLE_NAME = os.environ.get("PHOTOS_TABLE_NAME", "")
PHOTOS_BUCKET_NAME = os.environ.get("PHOTOS_BUCKET_NAME", "")
PHOTOS_CDN_BASE_URL = os.environ.get("PHOTOS_CDN_BASE_URL", "").rstrip("/")
PROFILES_TABLE_NAME = os.environ.get("PROFILES_TABLE_NAME", "kismet-profiles")
EVENT_BUS_NAME = os.environ.get("EVENT_BUS_NAME", "")

PRESIGNED_URL_EXPIRY = 300  # seconds
MAX_PHOTOS_PER_USER = 6
ALLOWED_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})

dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")
events = boto3.client("events")


def handler(event, context):
    event = event or {}
    method = _get_method(event)
    path = _get_path(event)
    user_id = _get_user_id(event)
    operation = None
    user_photos_match = USER_PHOTOS_PATTERN.match(path)
    primary_match = PHOTO_PRIMARY_PATTERN.match(path)
    confirm_match = PHOTO_CONFIRM_PATTERN.match(path)
    detail_match = PHOTO_DETAIL_PATTERN.match(path)

    try:
        if event.get("source") == "kismet.profile-service" and (
            event.get("detail-type") or event.get("detailType")
        ) == "user.deleted":
            operation = "handleUserDeleted"
            return handle_user_deleted(_get_event_detail(event))
        elif path == "/photos/upload":
            if method != "POST":
                return _response(404, {"code": "NOT_FOUND", "message": f"No route matches {method} {path}."})
            operation = "uploadPhoto"
            payload, error = _parse_body(event)
            if error is not None:
                return error
            if not user_id:
                return _response(401, {"code": "UNAUTHORIZED", "message": "Authentication required."})
            return handle_upload(user_id, payload or {})
        elif confirm_match and method == "POST":
            operation = "confirmPhoto"
            if not user_id:
                return _response(401, {"code": "UNAUTHORIZED", "message": "Authentication required."})
            return handle_confirm(user_id, confirm_match.group("photoId"))
        elif primary_match and method == "PUT":
            operation = "setPrimaryPhoto"
            if not user_id:
                return _response(401, {"code": "UNAUTHORIZED", "message": "Authentication required."})
            return handle_set_primary(user_id, primary_match.group("photoId"))
        elif user_photos_match and method == "GET":
            operation = "listPhotos"
            return handle_list(user_photos_match.group("userId"))
        elif detail_match and method == "DELETE":
            operation = "deletePhoto"
            if not user_id:
                return _response(401, {"code": "UNAUTHORIZED", "message": "Authentication required."})
            return handle_delete(user_id, detail_match.group("photoId"))
        else:
            return _response(404, {"code": "NOT_FOUND", "message": f"No route matches {method} {path}."})
    except ClientError:
        logger.exception("AWS error in %s", operation or f"{method} {path}")
        return _response(500, {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."})
    except Exception:
        logger.exception("Unexpected error in %s", operation or f"{method} {path}")
        return _response(500, {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."})


def handle_user_deleted(detail: Dict[str, Any]) -> Dict[str, Any]:
    """Delete all photos for a deleted user from DynamoDB and S3."""
    user_id = (detail.get("userId") or "").strip()
    if not user_id:
        logger.warning("user.deleted received without userId")
        return {"statusCode": 400, "body": "Missing userId"}

    table = dynamodb.Table(PHOTOS_TABLE_NAME)
    from boto3.dynamodb.conditions import Key as BotoKey
    result = table.query(KeyConditionExpression=BotoKey("PK").eq(f"USER#{user_id}"))

    deleted_count = 0
    for item in result.get("Items", []):
        try:
            s3.delete_object(Bucket=PHOTOS_BUCKET_NAME, Key=item["s3Key"])
        except ClientError:
            logger.warning("Failed to delete S3 object %s for user %s", item.get("s3Key"), user_id)
        table.delete_item(Key={"PK": f"USER#{user_id}", "SK": f"PHOTO#{item['photoId']}"})
        deleted_count += 1

    logger.info("Deleted %d photos for user %s", deleted_count, user_id)
    return {"statusCode": 200, "body": f"Deleted {deleted_count} photos"}


def handle_upload(user_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    content_type = (body.get("contentType") or "").strip().lower()
    filename = (body.get("filename") or "").strip()

    if not content_type:
        return _response(400, {"code": "VALIDATION_ERROR", "message": "contentType is required."})
    if content_type not in ALLOWED_CONTENT_TYPES:
        allowed = ", ".join(sorted(ALLOWED_CONTENT_TYPES))
        return _response(400, {"code": "VALIDATION_ERROR", "message": f"Unsupported content type. Allowed: {allowed}"})

    table = dynamodb.Table(PHOTOS_TABLE_NAME)
    existing = table.query(KeyConditionExpression=Key("PK").eq(f"USER#{user_id}"))
    if existing.get("Count", 0) >= MAX_PHOTOS_PER_USER:
        return _response(422, {"code": "LIMIT_EXCEEDED", "message": f"Maximum {MAX_PHOTOS_PER_USER} photos allowed per user."})

    photo_id = str(uuid.uuid4())
    ext = "jpg" if content_type == "image/jpeg" else content_type.split("/")[-1]
    s3_key = f"{user_id}/{photo_id}.{ext}"
    uploaded_at = datetime.now(timezone.utc).isoformat()
    is_primary = existing.get("Count", 0) == 0

    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": PHOTOS_BUCKET_NAME, "Key": s3_key, "ContentType": content_type},
        ExpiresIn=PRESIGNED_URL_EXPIRY,
    )

    table.put_item(Item={
        "PK": f"USER#{user_id}",
        "SK": f"PHOTO#{photo_id}",
        "photoId": photo_id,
        "userId": user_id,
        "s3Key": s3_key,
        "contentType": content_type,
        "filename": filename,
        "isPrimary": is_primary,
        "status": "pending",
        "uploadedAt": uploaded_at,
    })

    return _response(200, {"photoId": photo_id, "uploadUrl": upload_url, "expiresIn": PRESIGNED_URL_EXPIRY})


def handle_confirm(user_id: str, photo_id: str) -> Dict[str, Any]:
    table = dynamodb.Table(PHOTOS_TABLE_NAME)
    result = table.get_item(Key={"PK": f"USER#{user_id}", "SK": f"PHOTO#{photo_id}"})
    item = result.get("Item")

    if not item:
        return _response(404, {"code": "NOT_FOUND", "message": "Photo not found."})
    if item.get("status") != "pending":
        return _response(409, {"code": "CONFLICT", "message": "Photo already confirmed."})

    table.update_item(
        Key={"PK": f"USER#{user_id}", "SK": f"PHOTO#{photo_id}"},
        UpdateExpression="SET #st = :active",
        ExpressionAttributeNames={"#st": "status"},
        ExpressionAttributeValues={":active": "active"},
    )

    s3_key = item["s3Key"]
    is_primary = item.get("isPrimary", False)

    events.put_events(Entries=[{
        "Source": "kismet.photo-service",
        "DetailType": "photo.uploaded",
        "Detail": json.dumps({
            "photoId": photo_id,
            "userId": user_id,
            "s3Key": s3_key,
            "s3Bucket": PHOTOS_BUCKET_NAME,
            "contentType": item.get("contentType", ""),
            "cdnUrl": f"{PHOTOS_CDN_BASE_URL}/{s3_key}" if PHOTOS_CDN_BASE_URL else "",
            "isPrimary": is_primary,
            "timestamp": item.get("uploadedAt", ""),
        }),
        "EventBusName": EVENT_BUS_NAME,
    }])

    if is_primary:
        cdn_url = f"{PHOTOS_CDN_BASE_URL}/{s3_key}" if PHOTOS_CDN_BASE_URL else ""
        _update_profile_avatar(user_id, cdn_url)

    return _response(200, {"photoId": photo_id, "status": "active"})


def handle_list(user_id: str) -> Dict[str, Any]:
    table = dynamodb.Table(PHOTOS_TABLE_NAME)
    result = table.query(KeyConditionExpression=Key("PK").eq(f"USER#{user_id}"))

    photos = []
    for item in result.get("Items", []):
        status = item.get("status", "active")
        if status in ("rejected", "pending"):
            continue
        photos.append({
            "photoId": item["photoId"],
            "url": f"{PHOTOS_CDN_BASE_URL}/{item['s3Key']}",
            "isPrimary": item.get("isPrimary", False),
            "uploadedAt": item.get("uploadedAt"),
        })

    photos.sort(key=lambda p: p["uploadedAt"] or "", reverse=True)
    return _response(200, {"photos": photos, "count": len(photos)})


def handle_delete(user_id: str, photo_id: str) -> Dict[str, Any]:
    table = dynamodb.Table(PHOTOS_TABLE_NAME)
    result = table.get_item(Key={"PK": f"USER#{user_id}", "SK": f"PHOTO#{photo_id}"})
    item = result.get("Item")

    if not item:
        return _response(404, {"code": "NOT_FOUND", "message": "Photo not found."})

    s3.delete_object(Bucket=PHOTOS_BUCKET_NAME, Key=item["s3Key"])
    table.delete_item(Key={"PK": f"USER#{user_id}", "SK": f"PHOTO#{photo_id}"})

    # Promote most recent remaining photo to primary if the deleted one was primary
    if item.get("isPrimary"):
        remaining = table.query(KeyConditionExpression=Key("PK").eq(f"USER#{user_id}"))
        items = remaining.get("Items", [])
        if items:
            items.sort(key=lambda x: x.get("uploadedAt", ""), reverse=True)
            new_primary = items[0]
            table.update_item(
                Key={"PK": f"USER#{user_id}", "SK": f"PHOTO#{new_primary['photoId']}"},
                UpdateExpression="SET isPrimary = :t",
                ExpressionAttributeValues={":t": True},
            )

    return _response(200, {"message": "Photo deleted successfully"})


def handle_set_primary(user_id: str, photo_id: str) -> Dict[str, Any]:
    table = dynamodb.Table(PHOTOS_TABLE_NAME)

    result = table.get_item(Key={"PK": f"USER#{user_id}", "SK": f"PHOTO#{photo_id}"})
    if not result.get("Item"):
        return _response(404, {"code": "NOT_FOUND", "message": "Photo not found."})

    # Unset any existing primary photo
    existing = table.query(
        KeyConditionExpression=Key("PK").eq(f"USER#{user_id}"),
        FilterExpression=Attr("isPrimary").eq(True),
    )
    for item in existing.get("Items", []):
        if item["photoId"] != photo_id:
            table.update_item(
                Key={"PK": f"USER#{user_id}", "SK": f"PHOTO#{item['photoId']}"},
                UpdateExpression="SET isPrimary = :f",
                ExpressionAttributeValues={":f": False},
            )

    table.update_item(
        Key={"PK": f"USER#{user_id}", "SK": f"PHOTO#{photo_id}"},
        UpdateExpression="SET isPrimary = :t",
        ExpressionAttributeValues={":t": True},
    )

    # Update profile avatarUrl with new primary photo
    item = result["Item"]
    s3_key = item.get("s3Key", "")
    cdn_url = f"{PHOTOS_CDN_BASE_URL}/{s3_key}" if PHOTOS_CDN_BASE_URL and s3_key else ""
    _update_profile_avatar(user_id, cdn_url)

    return _response(200, {"photoId": photo_id, "isPrimary": True})


def _update_profile_avatar(user_id: str, avatar_url: str) -> None:
    """Update avatarUrl in profiles table and discovery table."""
    try:
        profiles_table = dynamodb.Table(PROFILES_TABLE_NAME)
        profiles_table.update_item(
            Key={"PK": f"USER#{user_id}", "SK": "PROFILE"},
            UpdateExpression="SET avatarUrl = :url",
            ExpressionAttributeValues={":url": avatar_url},
            ConditionExpression="attribute_exists(PK)",
        )
        logger.info("Updated profile avatarUrl for user %s", user_id)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            logger.info("No profile found for user %s, skipping avatar update", user_id)
        else:
            logger.warning("Failed to update profile avatarUrl: %s", e)

    # Also update discovery table
    try:
        discovery_table = dynamodb.Table("kismet-discovery")
        discovery_table.update_item(
            Key={"PK": f"PROFILE#{user_id}", "SK": "META"},
            UpdateExpression="SET avatarUrl = :url",
            ExpressionAttributeValues={":url": avatar_url},
            ConditionExpression="attribute_exists(PK)",
        )
        logger.info("Updated discovery avatarUrl for user %s", user_id)
    except ClientError:
        logger.info("No discovery entry for user %s, skipping", user_id)


def _get_user_id(event: Dict[str, Any]) -> Optional[str]:
    claims = event.get("requestContext", {}).get("authorizer", {}).get("claims", {})
    return claims.get("sub") or claims.get("cognito:username")


def _get_event_detail(event: Dict[str, Any]) -> Dict[str, Any]:
    detail = event.get("detail") or {}
    if isinstance(detail, dict):
        return detail
    if isinstance(detail, str):
        try:
            parsed = json.loads(detail)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


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
