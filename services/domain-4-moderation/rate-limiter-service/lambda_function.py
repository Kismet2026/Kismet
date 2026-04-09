import json
import os
import math
from datetime import datetime, timezone, timedelta
import redis

# Global connection to reuse across invocations
redis_client = None

LIMITS = {
    "swipes": {"limit": 100, "windowSeconds": 86400},
    "messages": {"limit": 50, "windowSeconds": 3600},
    "reports": {"limit": 5, "windowSeconds": 86400}
}

def get_redis():
    global redis_client
    if not redis_client:
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        redis_client = redis.from_url(redis_url)
    return redis_client

def get_window_info(action):
    now = datetime.now(timezone.utc)
    conf = LIMITS.get(action)
    if not conf: raise ValueError("Invalid action")
    
    if conf["windowSeconds"] == 86400:
        window_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        resets_at = window_start + timedelta(days=1)
    elif conf["windowSeconds"] == 3600:
        window_start = datetime(now.year, now.month, now.day, now.hour, tzinfo=timezone.utc)
        resets_at = window_start + timedelta(hours=1)
        
    timestamp = int(window_start.timestamp() * 1000)
    ttl_seconds = math.floor((resets_at - now).total_seconds())
    return timestamp, resets_at.isoformat().replace('+00:00', 'Z'), ttl_seconds

def check_rate_limit(user_id, action):
    """
    Middleware function that can be imported to check limits before other actions.
    """
    if action not in LIMITS: return {"allowed": True}
    
    r = get_redis()
    timestamp, resets_at, ttl_seconds = get_window_info(action)
    key = f"ratelimit:{user_id}:{action}:{timestamp}"
    
    try:
        current_count = r.incr(key)
        if current_count == 1:
            r.expire(key, ttl_seconds + 60)
            
        limit = LIMITS[action]["limit"]
        if current_count > limit:
            return {
                "allowed": False,
                "statusCode": 429,
                "error": "RATE_LIMIT_EXCEEDED",
                "message": f"You have exceeded the limit of {limit} {action} per {'day' if LIMITS[action]['windowSeconds'] == 86400 else 'hour'}.",
                "retryAfter": resets_at
            }
        return {"allowed": True, "remaining": limit - current_count}
    except Exception as e:
        print(f"Rate limit check failed: {e}")
        return {"allowed": True}

def handler(event, context):
    method = event.get('httpMethod')
    path = event.get('resource', event.get('path', ''))
    
    claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
    headers = event.get('headers', {}) or {}
    
    is_admin = claims.get('custom:role') == 'admin' or headers.get('x-is-admin') == 'true'

    if not is_admin:
        return {"statusCode": 403, "body": json.dumps({"error": "FORBIDDEN"})}

    try:
        if method == "GET" and "/ratelimit/status/" in path:
            return get_status(event)
        elif method == "POST" and "/ratelimit/reset/" in path:
            return reset_limit(event)
            
        return {"statusCode": 404, "body": json.dumps({"error": "Not Found"})}
    except Exception as e:
        print(f"Error: {e}")
        return {"statusCode": 500, "body": json.dumps({"error": "Internal Server Error"})}

def get_status(event):
    user_id = event.get('pathParameters', {}).get('userId')
    if not user_id: return {"statusCode": 404, "body": json.dumps({"error": "NOT_FOUND"})}
    
    r = get_redis()
    status_limits = {}
    found_any = False
    
    for action, conf in LIMITS.items():
        timestamp, resets_at, _ = get_window_info(action)
        key = f"ratelimit:{user_id}:{action}:{timestamp}"
        
        value = r.get(key)
        used = int(value) if value else 0
        if used > 0: found_any = True
        
        status_limits[action] = {
            "used": used,
            "limit": conf["limit"],
            "remaining": max(0, conf["limit"] - used),
            "resetsAt": resets_at
        }
        
    if not found_any:
        return {"statusCode": 404, "body": json.dumps({"error": "NOT_FOUND"})}
        
    return {"statusCode": 200, "body": json.dumps({"userId": user_id, "limits": status_limits})}

def reset_limit(event):
    user_id = event.get('pathParameters', {}).get('userId')
    if not user_id: return {"statusCode": 404, "body": json.dumps({"error": "NOT_FOUND"})}
    
    r = get_redis()
    for action in LIMITS.keys():
        timestamp, _, _ = get_window_info(action)
        key = f"ratelimit:{user_id}:{action}:{timestamp}"
        r.delete(key)
        
    return {
        "statusCode": 200,
        "body": json.dumps({
            "userId": user_id,
            "message": "Rate limit counters have been reset.",
            "resetAt": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        })
    }