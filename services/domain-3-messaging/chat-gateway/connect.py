import os
from datetime import datetime, timezone

import boto3

TABLE = os.environ["CONNECTIONS_TABLE"]
db = boto3.resource("dynamodb").Table(TABLE)


def handler(event, context):
    connection_id = event["requestContext"]["connectionId"]
    params = event.get("queryStringParameters") or {}

    # JWT validation is handled by API Gateway authorizer;
    # userId passed as query param: wss://...?userId=<sub>&matchId=<id>
    user_id = params.get("userId", "anonymous")
    match_id = params.get("matchId", "")

    if not user_id or user_id == "anonymous" or not match_id:
        return {"statusCode": 400, "body": "userId and matchId are required"}

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
