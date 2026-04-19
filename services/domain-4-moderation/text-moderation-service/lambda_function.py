import base64
import json
import os
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

# AWS clients & config
dynamodb = boto3.resource("dynamodb")
comprehend = boto3.client("comprehend")
events = boto3.client("events")

TABLE_NAME = os.environ.get("TEXT_MODERATION_TABLE_NAME", "kismet-text-moderation-dev")
EVENT_BUS_NAME = os.environ.get("EVENT_BUS_NAME", "kismet-events")
TOXICITY_THRESHOLD = float(os.environ.get("TOXICITY_THRESHOLD", "0.65"))
CATEGORY_SCORE_FLOOR = float(os.environ.get("CATEGORY_SCORE_FLOOR", "0.35"))
COMPREHEND_LANGUAGE = os.environ.get("COMPREHEND_LANGUAGE", "en")
ADMIN_GROUP_NAMES = frozenset(
    x.strip()
    for x in os.environ.get("ADMIN_GROUP_NAMES", "admin").split(",")
    if x.strip()
)
HISTORY_DEFAULT_LIMIT = int(os.environ.get("HISTORY_DEFAULT_LIMIT", "20"))
HISTORY_MAX_LIMIT = int(os.environ.get("HISTORY_MAX_LIMIT", "50"))
CONTENT_MAX_BYTES = 4500

_mod_table = None


def _table():
    global _mod_table
    if _mod_table is None:
        _mod_table = dynamodb.Table(TABLE_NAME)
    return _mod_table


def handler(event: Optional[Dict[str, Any]], context: Any) -> Dict[str, Any]:
    event = event or {}
    if _is_eventbridge(event):
        return handle_eventbridge(event, context)
    return handle_http(event, context)


def _is_eventbridge(event: Dict[str, Any]) -> bool:
    if event.get("httpMethod") or event.get("requestContext", {}).get("http"):
        return False
    return "source" in event and "detail-type" in event


# EventBridge — message.sent
def handle_eventbridge(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    if event.get("source") != "kismet.message-service":
        return _eb_ok({"skipped": True, "reason": "source"})
    if event.get("detail-type") != "message.sent":
        return _eb_ok({"skipped": True, "reason": "detail-type"})

    detail = event.get("detail") or {}
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except json.JSONDecodeError:
            return _eb_ok({"skipped": True, "reason": "detail-json"})

    mid = detail.get("messageId")
    text = detail.get("content")
    sender = detail.get("senderId")
    if not mid or not isinstance(text, str) or not text.strip():
        return _eb_ok({"skipped": True, "reason": "missing-fields"})

    try:
        run_moderation(
            content=text.strip(),
            content_id=str(mid),
            content_type="message",
            user_id=str(sender) if sender else None,
        )
    except RuntimeError as e:
        print(f"[text-moderation] {e}\n{traceback.format_exc()}")
        raise
    return _eb_ok({"ok": True, "contentId": mid})


def _eb_ok(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"statusCode": 200, "body": json.dumps(payload)}

# HTTP — API Gateway
def handle_http(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    method = _http_method(event)
    path = _normalize_path(_http_path(event))

    if method == "POST" and path == "/moderate/text":
        return post_moderate_text(event)
    if method == "GET" and path == "/moderate/text/history":
        return get_moderation_history(event)

    if path.startswith("/moderate/text"):
        return error_response(
            404, "NOT_FOUND", f"No route matches {method} {path}."
        )
    return error_response(
        404, "NOT_FOUND", f"No route matches {method} {path}."
    )


def post_moderate_text(event: Dict[str, Any]) -> Dict[str, Any]:
    body, err = _parse_json_body(event)
    if err:
        return err
    code, data = validate_post_body(body or {})
    if code:
        return error_response(
            400,
            "VALIDATION_ERROR",
            "content, contentId, and contentType (message|bio) are required.",
        )
    assert data is not None
    try:
        result = run_moderation(
            content=data["content"],
            content_id=data["contentId"],
            content_type=data["contentType"],
            user_id=data.get("userId"),
        )
    except RuntimeError as e:
        if str(e).startswith("COMPREHEND:"):
            return error_response(500, "COMPREHEND_ERROR", "AWS Comprehend call failed.")
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


# Core moderation (Comprehend + DynamoDB + EventBridge)
def validate_post_body(body: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    if not isinstance(body, dict):
        return "VALIDATION_ERROR", None
    content = body.get("content")
    cid = body.get("contentId")
    ctype = body.get("contentType")
    if not content or not isinstance(content, str) or not content.strip():
        return "VALIDATION_ERROR", None
    if not cid or not isinstance(cid, str):
        return "VALIDATION_ERROR", None
    if ctype not in ("message", "bio"):
        return "VALIDATION_ERROR", None
    if len(content.strip().encode("utf-8")) > CONTENT_MAX_BYTES:
        return "VALIDATION_ERROR", None

    uid = body.get("userId")
    user_id = uid.strip() if isinstance(uid, str) and uid.strip() else None
    return None, {
        "content": content.strip(),
        "contentId": cid.strip(),
        "contentType": ctype,
        "userId": user_id,
    }


def run_moderation(
    *,
    content: str,
    content_type: str,
    content_id: str,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    toxicity_score, categories = detect_toxicity(content)
    flagged = toxicity_score >= TOXICITY_THRESHOLD
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    put_moderation_row(
        content_id=content_id,
        content_type=content_type,
        flagged=flagged,
        toxicity_score=toxicity_score,
        categories=categories,
        timestamp_iso=ts,
        user_id=user_id,
    )

    if flagged:
        if content_type == "bio":
            event_uid = user_id or content_id
        else:
            event_uid = user_id
            if not event_uid:
                print(
                    f"[text-moderation] flagged message {content_id} has no userId, "
                    "skipping content.flagged event — check message-service senderId"
                )

        if event_uid:
            try:
                publish_content_flagged(
                    content_id=content_id,
                    user_id=event_uid,
                    score=toxicity_score,
                )
            except RuntimeError as e:
                print(f"[text-moderation] content.flagged failed: {e}")

    return {
        "contentId": content_id,
        "contentType": content_type,
        "flagged": flagged,
        "toxicityScore": round(toxicity_score, 4),
        "categories": categories,
        "timestamp": ts,
    }


def detect_toxicity(text: str) -> Tuple[float, List[str]]:
    try:
        resp = comprehend.detect_toxic_content(
            TextSegments=[{"Text": text}],
            LanguageCode=COMPREHEND_LANGUAGE,
        )
    except ClientError as e:
        c = e.response.get("Error", {}).get("Code", "ComprehendError")
        raise RuntimeError(f"COMPREHEND:{c}") from e

    max_score = 0.0
    names: List[str] = []
    seen = set()
    for seg in resp.get("ResultList") or []:
        for lab in seg.get("Labels") or []:
            name = lab.get("Name") or ""
            score = float(lab.get("Score") or 0.0)
            max_score = max(max_score, score)
            if name and score >= CATEGORY_SCORE_FLOOR and name not in seen:
                seen.add(name)
                names.append(name)
    return max_score, names


def put_moderation_row(
    *,
    content_id: str,
    content_type: str,
    flagged: bool,
    toxicity_score: float,
    categories: List[str],
    timestamp_iso: str,
    user_id: Optional[str] = None,
) -> None:
    sort_ts = int(time.time() * 1000)
    item: Dict[str, Any] = {
        "contentId": f"CONTENT#{content_id}",
        "sk": "RESULT",
        "rawContentId": content_id,
        "contentType": content_type,
        "flagged": flagged,
        "toxicityScore": Decimal(str(round(toxicity_score, 4))),
        "categories": categories,
        "timestamp": timestamp_iso,
        "gsi1pk": "TEXT_MODERATION_HISTORY",
        "gsi1sk": sort_ts,
    }
    if user_id:
        item["userId"] = user_id
    _table().put_item(Item=item)


def query_history_page(
    limit: int, cursor: Optional[str]
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    lim = max(1, min(limit, HISTORY_MAX_LIMIT))
    kwargs: Dict[str, Any] = {
        "IndexName": "gsi1",
        "KeyConditionExpression": "gsi1pk = :p",
        "ExpressionAttributeValues": {":p": "TEXT_MODERATION_HISTORY"},
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
        items.append(
            {
                "contentId": row.get("rawContentId")
                or str(row.get("contentId", "")).replace("CONTENT#", "", 1),
                "contentType": row.get("contentType", ""),
                "flagged": bool(row.get("flagged", False)),
                "toxicityScore": float(row.get("toxicityScore", 0)),
                "categories": list(row.get("categories") or []),
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
    *, content_id: str, user_id: str, score: float, reason: str = "toxicity_detected"
) -> None:
    detail = {
        "contentId": content_id,
        "contentType": "text",
        "userId": user_id,
        "reason": reason,
        "score": round(score, 4),
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

# Auth
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
    return bool(_parse_groups(extract_claims(event).get("cognito:groups")) & ADMIN_GROUP_NAMES)


# HTTP helpers
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


def _parse_json_body(event: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
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