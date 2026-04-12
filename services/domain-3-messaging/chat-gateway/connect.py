import os
from datetime import datetime, timezone

import boto3

TABLE = os.environ["CONNECTIONS_TABLE"]
MATCHES_TABLE = os.environ["MATCHES_TABLE"]

dynamodb = boto3.resource("dynamodb")
db = dynamodb.Table(TABLE)
matches = dynamodb.Table(MATCHES_TABLE)


def handler(event, context):
    connection_id = event["requestContext"]["connectionId"]
    params = event.get("queryStringParameters") or {}

    # userId passed as query param: wss://...?userId=<sub>&matchId=<id>
    user_id = params.get("userId", "")
    match_id = params.get("matchId", "")

    if not user_id or not match_id:
        return {"statusCode": 400, "body": "userId and matchId are required"}

    # Verify the match exists and the user is a participant
    match_error = _verify_match_participant(match_id, user_id)
    if match_error:
        return match_error

    db.put_item(Item={
        "PK": f"CONN#{connection_id}",
        "SK": "META",
        "connectionId": connection_id,
        "userId": user_id,
        "matchId": match_id,
        "connectedAt": datetime.now(timezone.utc).isoformat(),
        # TTL: 24 hours — auto-clean stale connections
        "ttl": int(datetime.now(timezone.utc).timestamp()) + 86400,
    })

    print(f"Connected: {connection_id} -> userId={user_id} matchId={match_id}")
    return {"statusCode": 200, "body": "Connected"}


def _verify_match_participant(match_id: str, user_id: str):
    """Return an error response if the match doesn't exist or user isn't a participant."""
    result = matches.get_item(Key={"PK": f"MATCH#{match_id}", "SK": "META"})
    item = result.get("Item")
    if not item:
        return {"statusCode": 404, "body": "Match not found"}
    participants = {item.get("userAId"), item.get("userBId")}
    if user_id not in participants:
        return {"statusCode": 403, "body": "User is not a participant of this match"}
    return None
