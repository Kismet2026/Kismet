import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import boto3
from boto3.dynamodb.conditions import Key

SERVICE_NAME = "icebreaker-service"
TABLE_NAME = os.environ["TABLE_NAME"]
MATCHES_TABLE = os.environ["MATCHES_TABLE"]
MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
matches_table = dynamodb.Table(MATCHES_TABLE)
bedrock = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))

# Fallback icebreakers if Bedrock is unavailable
FALLBACK_ICEBREAKERS = [
    "What's something you've been really into lately?",
    "If you could travel anywhere right now, where would you go?",
    "What's the best thing that happened to you this week?",
]


def lambda_handler(event: Optional[Dict[str, Any]], context: Any) -> Dict[str, Any]:
    event = event or {}

    # ── EventBridge trigger: match.created ───────────────────────────────────
    # Check both source AND detail-type to avoid acting on unrelated events
    if (event.get("source") == "kismet.match-service"
            and event.get("detail-type") == "match.created"):
        detail = event.get("detail", {})
        match_id = detail.get("matchId")
        if match_id:
            _generate_and_cache(match_id, user_a={}, user_b={})
            print(f"[INFO] Auto-generated icebreakers for match {match_id}")
        return {}

    # ── HTTP routes ───────────────────────────────────────────────────────────
    method = get_http_method(event)
    path = get_request_path(event)
    path_params = event.get("pathParameters") or {}

    user_id = _get_user_id(event)
    if not user_id:
        return json_response(401, {"code": "UNAUTHORIZED", "message": "Authentication required"})

    # POST /icebreaker/generate
    if method == "POST" and path.endswith("/generate"):
        payload, error = parse_json_body(event)
        if error:
            return error
        return handle_generate(payload, user_id)

    # GET /icebreaker/{matchId}
    if method == "GET" and "matchId" in path_params:
        return handle_get(path_params["matchId"], user_id)

    return json_response(404, {"code": "NOT_FOUND", "message": f"No route matches {method} {path}"})


# ── Handlers ──────────────────────────────────────────────────────────────────

def handle_generate(body: dict, user_id: str) -> Dict[str, Any]:
    """POST /icebreaker/generate — Generate (or return cached) conversation starters."""
    match_id = (body or {}).get("matchId")
    if not match_id:
        return json_response(400, {"code": "VALIDATION_ERROR", "message": "matchId is required"})

    # Verify the user is a participant of this match
    _, error = get_match_for_user(match_id, user_id)
    if error:
        return error

    # Return cached result if already generated
    cached = _get_cached(match_id)
    if cached:
        return json_response(200, cached)

    user_a = body.get("userA", {})
    user_b = body.get("userB", {})

    result = _generate_and_cache(match_id, user_a, user_b)
    return json_response(200, result)


def handle_get(match_id: str, user_id: str) -> Dict[str, Any]:
    """GET /icebreaker/{matchId} — Return previously generated icebreakers."""
    # Verify the user is a participant of this match
    _, error = get_match_for_user(match_id, user_id)
    if error:
        return error

    cached = _get_cached(match_id)
    if cached:
        return json_response(200, cached)
    return json_response(200, {"matchId": match_id, "suggestions": None})


# ── Core logic ────────────────────────────────────────────────────────────────

def _get_cached(match_id: str) -> Optional[dict]:
    result = table.get_item(Key={"PK": f"MATCH#{match_id}", "SK": "META"})
    item = result.get("Item")
    if not item:
        return None
    return {
        "matchId": match_id,
        "suggestions": item.get("suggestions", []),
        "source": item.get("source", "bedrock"),
        "generatedAt": item.get("generatedAt"),
    }


def _generate_and_cache(match_id: str, user_a: dict, user_b: dict) -> dict:
    suggestions, source = _call_bedrock(user_a, user_b)

    now = datetime.now(timezone.utc).isoformat()
    formatted = [{"id": f"ice-{i+1:03d}", "text": s, "source": source} for i, s in enumerate(suggestions)]

    table.put_item(Item={
        "PK": f"MATCH#{match_id}",
        "SK": "META",
        "matchId": match_id,
        "suggestions": formatted,
        "source": source,
        "generatedAt": now,
    })

    return {"matchId": match_id, "suggestions": formatted, "generatedAt": now}


def _call_bedrock(user_a: dict, user_b: dict) -> tuple:
    """Call Claude via Bedrock. Returns (suggestions_list, source_str)."""
    prompt = f"""You are a witty dating app assistant. Generate 3 fun and personalized conversation starters for two people who just matched.

Person A: {json.dumps(user_a) if user_a else "a college student"}
Person B: {json.dumps(user_b) if user_b else "a college student"}

Requirements:
- Each opener should be playful and feel personal
- Keep each one under 2 sentences
- Output ONLY a JSON array of strings, nothing else

Example: ["opener 1", "opener 2", "opener 3"]"""

    try:
        response = bedrock.invoke_model(
            modelId=MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 512,
                "messages": [{"role": "user", "content": prompt}],
            }),
        )
        body = json.loads(response["body"].read())
        text = body["content"][0]["text"].strip()
        suggestions = json.loads(text)
        return suggestions[:3], "bedrock"

    except Exception as exc:
        print(f"[WARN] Bedrock unavailable, using fallback: {exc}")
        return FALLBACK_ICEBREAKERS, "template"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_user_id(event: Dict[str, Any]) -> str:
    """Extract the authenticated user ID from Cognito JWT claims."""
    claims = event.get("requestContext", {}).get("authorizer", {}).get("claims", {})
    return claims.get("sub") or claims.get("cognito:username", "")


def get_match_for_user(match_id: str, user_id: str) -> Tuple[Optional[dict], Optional[dict]]:
    """Look up a match and verify user_id is a participant. Returns (item, error)."""
    result = matches_table.get_item(Key={"PK": f"MATCH#{match_id}", "SK": "META"})
    item = result.get("Item")
    if not item:
        return None, json_response(404, {"code": "NOT_FOUND", "message": "Match not found"})
    participants = {item.get("userAId"), item.get("userBId")}
    if user_id not in participants:
        return None, json_response(403, {"code": "FORBIDDEN", "message": "User is not a participant of this match"})
    return item, None


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


def parse_json_body(event: Dict[str, Any]):
    body = event.get("body")
    if body in (None, ""):
        return {}, None
    if isinstance(body, dict):
        return body, None
    try:
        return json.loads(body), None
    except json.JSONDecodeError:
        return None, json_response(
            400, {"code": "VALIDATION_ERROR", "message": "Request body must be valid JSON"}
        )


def json_response(status_code: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }


handler = lambda_handler
