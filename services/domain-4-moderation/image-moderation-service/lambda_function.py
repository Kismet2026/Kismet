"""
Image Moderation — single Lambda module (API + EventBridge).
Contract: docs/api-contracts/domain-4-image-moderation-service.md
"""

import base64
import json
import os
import re
import time
import traceback
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

os.environ.setdefault(
    "AWS_DEFAULT_REGION",
    os.environ.get("AWS_REGION", "us-east-1"),
)

dynamodb = boto3.resource("dynamodb")
rekognition = boto3.client("rekognition")
events = boto3.client("events")

TABLE_NAME = os.environ.get(
    "IMAGE_MODERATION_TABLE_NAME", "kismet-image-moderation-dev"
)
PHOTO_S3_BUCKET = os.environ.get("PHOTO_S3_BUCKET", "")
PHOTOS_TABLE_NAME = os.environ.get("PHOTOS_TABLE_NAME", "")
EVENT_BUS_NAME = os.environ.get("EVENT_BUS_NAME", "kismet-events")
# Rekognition label confidence is 0–100; flag if max(label) >= this
MODERATION_FLAG_CONFIDENCE = float(
    os.environ.get("MODERATION_FLAG_CONFIDENCE", "60")
)
# Minimum confidence for labels returned by Rekognition (broader capture)
REKOGNITION_MIN_CONFIDENCE = float(
    os.environ.get("REKOGNITION_MIN_CONFIDENCE", "5")
)
ADMIN_GROUP_NAMES = frozenset(
    x.strip()
    for x in os.environ.get("ADMIN_GROUP_NAMES", "admin").split(",")
    if x.strip()
)
HISTORY_DEFAULT_LIMIT = int(os.environ.get("HISTORY_DEFAULT_LIMIT", "20"))
HISTORY_MAX_LIMIT = int(os.environ.get("HISTORY_MAX_LIMIT", "50"))

_img_table = None


def _resolve_rekognition_bucket(*, s3_bucket_override: Optional[str]) -> str:
    """
    Rekognition S3Object bucket: EventBridge photo.uploaded should pass
    detail.s3Bucket (event-schema.json). HTTP POST uses env PHOTO_S3_BUCKET only.
    """
    if isinstance(s3_bucket_override, str):
        o = s3_bucket_override.strip()
        if o:
            return o
    base = (PHOTO_S3_BUCKET or "").strip()
    return base


def _table():
    global _img_table
    if _img_table is None:
        _img_table = dynamodb.Table(TABLE_NAME)
    return _img_table


def lambda_handler(event: Optional[Dict[str, Any]], context: Any) -> Dict[str, Any]:
    event = event or {}
    if _is_eventbridge(event):
        return handle_eventbridge(event, context)
    return handle_http(event, context)


def _is_eventbridge(event: Dict[str, Any]) -> bool:
    if event.get("httpMethod") or event.get("requestContext", {}).get("http"):
        return False
    return "source" in event and "detail-type" in event


def handle_eventbridge(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    if event.get("source") != "kismet.photo-service":
        return _eb_ok({"skipped": True, "reason": "source"})
    if event.get("detail-type") != "photo.uploaded":
        return _eb_ok({"skipped": True, "reason": "detail-type"})

    detail = event.get("detail") or {}
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except json.JSONDecodeError:
            return _eb_ok({"skipped": True, "reason": "detail-json"})

    pid = detail.get("photoId")
    uid = detail.get("userId")
    s3_key = detail.get("s3Key")
    s3_bucket = detail.get("s3Bucket")
    if (
        not pid
        or not isinstance(s3_key, str)
        or not s3_key.strip()
        or not uid
        or not isinstance(uid, str)
        or not uid.strip()
    ):
        return _eb_ok({"skipped": True, "reason": "missing-fields"})
    if not isinstance(s3_bucket, str) or not s3_bucket.strip():
        return _eb_ok({"skipped": True, "reason": "missing-s3-bucket"})

    bucket = s3_bucket.strip()
    if PHOTO_S3_BUCKET and bucket != PHOTO_S3_BUCKET.strip():
        print(
            "[image-moderation] detail.s3Bucket "
            f"({bucket!r}) != PHOTO_S3_BUCKET ({PHOTO_S3_BUCKET!r}); "
            "using detail.s3Bucket per event-schema."
        )

    try:
        run_image_moderation(
            s3_key=s3_key.strip(),
            photo_id=str(pid),
            user_id=uid.strip(),
            s3_bucket=bucket,
        )
    except RuntimeError as e:
        print(f"[image-moderation] {e}\n{traceback.format_exc()}")
        raise
    return _eb_ok({"ok": True, "photoId": pid})


def _eb_ok(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"statusCode": 200, "body": json.dumps(payload)}


def handle_http(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    method = _http_method(event)
    path = _normalize_path(_http_path(event))

    if method == "POST" and path == "/moderate/image":
        return post_moderate_image(event)
    if method == "GET" and path == "/moderate/image/history":
        return get_moderation_history(event)

    if path.startswith("/moderate/image"):
        return error_response(
            404, "NOT_FOUND", f"No route matches {method} {path}."
        )
    return error_response(
        404, "NOT_FOUND", f"No route matches {method} {path}."
    )


def post_moderate_image(event: Dict[str, Any]) -> Dict[str, Any]:
    body, err = _parse_json_body(event)
    if err:
        return err
    code, data = validate_post_body(body or {})
    if code:
        return error_response(
            400,
            "VALIDATION_ERROR",
            "s3Key, photoId, and userId are required.",
        )
    assert data is not None
    try:
        result = run_image_moderation(
            s3_key=data["s3Key"],
            photo_id=data["photoId"],
            user_id=data["userId"],
        )
    except RuntimeError as e:
        msg = str(e)
        if msg.startswith("IMAGE_NOT_FOUND"):
            return error_response(
                404, "IMAGE_NOT_FOUND", "S3 object not found for the given s3Key."
            )
        if msg.startswith("REKOGNITION:MISSING_BUCKET"):
            return error_response(
                500,
                "REKOGNITION_ERROR",
                "Server misconfiguration: PHOTO_S3_BUCKET is not set.",
            )
        if msg.startswith("REKOGNITION:"):
            return error_response(
                500, "REKOGNITION_ERROR", "AWS Rekognition call failed."
            )
        raise
    return response(200, result)


def get_moderation_history(event: Dict[str, Any]) -> Dict[str, Any]:
    if not extract_claims(event):
        return error_response(401, "UNAUTHORIZED", "Authentication required.")
    if not is_admin(event):
        return error_response(403, "FORBIDDEN", "Admin access required.")

    params = event.get("queryStringParameters") or {}
    try:
        limit = int(params.get("limit", _default_history_limit()))
    except (TypeError, ValueError):
        limit = _default_history_limit()
    cursor = params.get("cursor")

    try:
        items, next_cursor = query_history_page(limit=limit, cursor=cursor)
    except ValueError:
        return error_response(400, "VALIDATION_ERROR", "Invalid cursor.")
    except RuntimeError:
        return error_response(
            500, "INTERNAL_ERROR", "Failed to read moderation history."
        )

    return response(200, {"items": items, "nextCursor": next_cursor, "count": len(items)})


def validate_post_body(body: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    if not isinstance(body, dict):
        return "VALIDATION_ERROR", None
    s3_key = body.get("s3Key")
    pid = body.get("photoId")
    uid = body.get("userId")
    if not s3_key or not isinstance(s3_key, str) or not s3_key.strip():
        return "VALIDATION_ERROR", None
    if not pid or not isinstance(pid, str) or not str(pid).strip():
        return "VALIDATION_ERROR", None
    if not uid or not isinstance(uid, str) or not uid.strip():
        return "VALIDATION_ERROR", None
    return None, {
        "s3Key": s3_key.strip(),
        "photoId": str(pid).strip(),
        "userId": uid.strip(),
    }


def run_image_moderation(
    *,
    s3_key: str,
    photo_id: str,
    user_id: str,
    s3_bucket: Optional[str] = None,
) -> Dict[str, Any]:
    bucket = _resolve_rekognition_bucket(s3_bucket_override=s3_bucket)
    if not bucket:
        raise RuntimeError("REKOGNITION:MISSING_BUCKET")
    labels_out, max_conf, flagged, top_name = detect_moderation_labels(
        s3_key, bucket=bucket
    )
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    put_moderation_row(
        photo_id=photo_id,
        user_id=user_id,
        s3_key=s3_key,
        flagged=flagged,
        labels=labels_out,
        confidence=max_conf,
        timestamp_iso=ts,
    )

    if flagged:
        reason = _reason_slug(top_name) if top_name else "moderation_detected"
        score = round(max_conf / 100.0, 4)
        try:
            publish_content_flagged(
                content_id=photo_id,
                user_id=user_id,
                score=score,
                reason=reason,
            )
        except RuntimeError as e:
            print(f"[image-moderation] content.flagged failed: {e}")
        try:
            mark_photo_rejected(user_id=user_id, photo_id=photo_id)
        except RuntimeError as e:
            print(f"[image-moderation] photo status update failed: {e}")

    return {
        "photoId": photo_id,
        "userId": user_id,
        "flagged": flagged,
        "labels": labels_out,
        "confidence": round(max_conf, 1) if flagged else 0.0,
        "timestamp": ts,
    }


def detect_moderation_labels(
    s3_key: str,
    *,
    bucket: str,
) -> Tuple[List[Dict[str, Any]], float, bool, Optional[str]]:
    try:
        resp = rekognition.detect_moderation_labels(
            Image={
                "S3Object": {
                    "Bucket": bucket,
                    "Name": s3_key,
                }
            },
            MinConfidence=REKOGNITION_MIN_CONFIDENCE,
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "RekognitionError")
        if code in ("InvalidS3ObjectException", "S3ObjectNotFoundException"):
            raise RuntimeError(f"IMAGE_NOT_FOUND:{code}") from e
        raise RuntimeError(f"REKOGNITION:{code}") from e

    labels_out: List[Dict[str, Any]] = []
    max_conf = 0.0
    top_name: Optional[str] = None

    for lab in resp.get("ModerationLabels") or []:
        name = lab.get("Name") or ""
        conf = float(lab.get("Confidence") or 0.0)
        if conf > max_conf:
            max_conf = conf
            top_name = name if name else top_name
        elif conf == max_conf and name and not top_name:
            top_name = name
        if name:
            labels_out.append({"name": name, "confidence": round(conf, 1)})

    flagged = max_conf >= MODERATION_FLAG_CONFIDENCE
    if flagged and not top_name and labels_out:
        top_name = labels_out[0]["name"]

    return labels_out, max_conf, flagged, top_name


def _reason_slug(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_") or "moderation_detected"


def _labels_for_dynamo(labels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for lb in labels:
        if not isinstance(lb, dict):
            continue
        d = dict(lb)
        if "confidence" in d:
            d["confidence"] = Decimal(str(round(float(d["confidence"]), 2)))
        out.append(d)
    return out


def put_moderation_row(
    *,
    photo_id: str,
    user_id: str,
    s3_key: str,
    flagged: bool,
    labels: List[Dict[str, Any]],
    confidence: float,
    timestamp_iso: str,
) -> None:
    sort_ts = int(time.time() * 1000)
    item: Dict[str, Any] = {
        "photoId": f"PHOTO#{photo_id}",
        "sk": "RESULT",
        "rawPhotoId": photo_id,
        "userId": user_id,
        "s3Key": s3_key,
        "flagged": flagged,
        "labels": _labels_for_dynamo(labels),
        "confidence": Decimal(str(round(confidence, 2))),
        "timestamp": timestamp_iso,
        "gsi1pk": "IMAGE_MODERATION_HISTORY",
        "gsi1sk": sort_ts,
    }
    _table().put_item(Item=item)


def query_history_page(
    limit: int, cursor: Optional[str]
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    lim = max(1, min(limit, HISTORY_MAX_LIMIT))
    kwargs: Dict[str, Any] = {
        "IndexName": "gsi1",
        "KeyConditionExpression": "gsi1pk = :p",
        "ExpressionAttributeValues": {":p": "IMAGE_MODERATION_HISTORY"},
        "ScanIndexForward": False,
        "Limit": lim,
    }
    if cursor:
        try:
            raw = base64.urlsafe_b64decode(cursor.encode("utf-8") + b"===")
            kwargs["ExclusiveStartKey"] = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, ValueError) as e:
            raise ValueError("INVALID_CURSOR") from e

    try:
        resp = _table().query(**kwargs)
    except ClientError as e:
        raise RuntimeError(str(e)) from e

    items: List[Dict[str, Any]] = []
    for row in resp.get("Items", []):
        pid = row.get("rawPhotoId") or str(row.get("photoId", "")).replace(
            "PHOTO#", "", 1
        )
        conf = float(row.get("confidence", 0))
        flagged = bool(row.get("flagged", False))
        labels = list(row.get("labels") or [])
        for lb in labels:
            if isinstance(lb, dict) and "confidence" in lb:
                try:
                    lb["confidence"] = float(lb["confidence"])
                except (TypeError, ValueError):
                    pass
        items.append(
            {
                "photoId": pid,
                "userId": row.get("userId", ""),
                "flagged": flagged,
                "labels": labels,
                "confidence": round(conf, 1) if flagged else 0.0,
                "timestamp": row.get("timestamp", ""),
            }
        )

    next_c = None
    lek = resp.get("LastEvaluatedKey")
    if lek:
        next_c = (
            base64.urlsafe_b64encode(
                json.dumps(lek, default=_dynamo_json).encode("utf-8")
            )
            .decode("utf-8")
            .rstrip("=")
        )
    return items, next_c


def _dynamo_json(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    raise TypeError(type(obj))


def publish_content_flagged(
    *,
    content_id: str,
    user_id: str,
    score: float,
    reason: str,
) -> None:
    detail = {
        "contentId": content_id,
        "contentType": "image",
        "userId": user_id,
        "reason": reason,
        "score": score,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    try:
        events.put_events(
            Entries=[
                {
                    "Source": "kismet.moderation",
                    "DetailType": "content.flagged",
                    "Detail": json.dumps(detail),
                    "EventBusName": EVENT_BUS_NAME,
                }
            ]
        )
    except ClientError as e:
        raise RuntimeError(str(e)) from e


def mark_photo_rejected(*, user_id: str, photo_id: str) -> None:
    if not PHOTOS_TABLE_NAME:
        return
    tbl = dynamodb.Table(PHOTOS_TABLE_NAME)
    try:
        tbl.update_item(
            Key={"PK": f"USER#{user_id}", "SK": f"PHOTO#{photo_id}"},
            UpdateExpression="SET #st = :rej",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={":rej": "rejected"},
        )
    except ClientError as e:
        raise RuntimeError(str(e)) from e


def extract_claims(event: Dict[str, Any]) -> Dict[str, Any]:
    rc = event.get("requestContext") or {}
    auth = rc.get("authorizer")
    if not isinstance(auth, dict):
        return {}
    claims = auth.get("claims")
    if isinstance(claims, dict):
        return claims
    jwt = auth.get("jwt")
    if isinstance(jwt, dict) and isinstance(jwt.get("claims"), dict):
        return jwt["claims"]
    return {}


def _parse_groups(raw: Any) -> set:
    if raw is None:
        return set()
    if isinstance(raw, list):
        return {str(g).strip() for g in raw if str(g).strip()}
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return set()
        if s.startswith("["):
            try:
                data = json.loads(s)
                if isinstance(data, list):
                    return {str(g).strip() for g in data if str(g).strip()}
            except json.JSONDecodeError:
                pass
        return {p.strip() for p in s.replace(",", " ").split() if p.strip()}
    return set()


def is_admin(event: Dict[str, Any]) -> bool:
    return bool(
        _parse_groups(extract_claims(event).get("cognito:groups"))
        & ADMIN_GROUP_NAMES
    )


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


def _parse_json_body(
    event: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    body = event.get("body")
    if body in (None, ""):
        return None, error_response(400, "VALIDATION_ERROR", "Request body is required.")
    if isinstance(body, dict):
        return body, None
    try:
        return json.loads(body), None
    except json.JSONDecodeError:
        return None, error_response(
            400, "VALIDATION_ERROR", "Request body must be valid JSON."
        )


def _default_history_limit() -> int:
    return min(HISTORY_DEFAULT_LIMIT, HISTORY_MAX_LIMIT)


def response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def error_response(status_code: int, code: str, message: str) -> Dict[str, Any]:
    return response(status_code, {"error": {"code": code, "message": message}})
