import json
import os
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

CONNECTIONS_TABLE = os.environ["CONNECTIONS_TABLE"]
MESSAGES_TABLE = os.environ["MESSAGES_TABLE"]
EVENT_BUS_NAME = os.environ.get("EVENT_BUS_NAME", "kismet-events")

dynamodb = boto3.resource("dynamodb")
connections = dynamodb.Table(CONNECTIONS_TABLE)
messages = dynamodb.Table(MESSAGES_TABLE)
events_client = boto3.client("events")


def handler(event, context):
    connection_id = event["requestContext"]["connectionId"]
    domain = event["requestContext"]["domainName"]
    stage = event["requestContext"]["stage"]

    body = json.loads(event.get("body") or "{}")
    match_id = body.get("matchId")
    content = body.get("content")
    sender_id = body.get("senderId", "")
    receiver_id = body.get("receiverId", "")

    if not match_id or not content:
        return {"statusCode": 400, "body": "Missing matchId or content"}

    # 1. Persist message to DynamoDB
    now = datetime.now(timezone.utc).isoformat()
    message_id = str(uuid.uuid4())
    item = {
        "PK": f"CONV#{match_id}",
        "SK": f"MSG#{now}#{message_id}",
        "messageId": message_id,
        "matchId": match_id,
        "senderId": sender_id,
        "recipientId": receiver_id,
        "content": content,
        "messageType": "text",
        "timestamp": now,
        "deleted": False,
    }
    messages.put_item(Item=item)

    # 2. Publish message.sent to EventBridge
    try:
        events_client.put_events(Entries=[{
            "Source": "kismet.message-service",
            "DetailType": "message.sent",
            "Detail": json.dumps({
                "messageId": message_id,
                "matchId": match_id,
                "senderId": sender_id,
                "recipientId": receiver_id,
                "content": content,
                "messageType": "text",
                "timestamp": now,
            }),
            "EventBusName": EVENT_BUS_NAME,
        }])
    except Exception as exc:
        print(f"[WARN] Failed to publish message.sent: {exc}")

    # 3. Find receiver's active connections via matchId GSI
    result = connections.query(
        IndexName="matchId-index",
        KeyConditionExpression=Key("matchId").eq(match_id),
    )
    receiver_conns = [
        c for c in result.get("Items", [])
        if c["connectionId"] != connection_id  # don't echo back to sender
    ]

    # 4. Push message to receiver(s) via WebSocket
    apigw = boto3.client(
        "apigatewaymanagementapi",
        endpoint_url=f"https://{domain}/{stage}",
    )
    payload = json.dumps({"type": "newMessage", **{k: item[k] for k in
                          ["messageId", "matchId", "senderId", "content", "timestamp"]}})

    for conn in receiver_conns:
        try:
            apigw.post_to_connection(
                ConnectionId=conn["connectionId"],
                Data=payload.encode(),
            )
        except apigw.exceptions.GoneException:
            # Stale connection — clean up
            connections.delete_item(Key={"PK": f"CONN#{conn['connectionId']}", "SK": "META"})

    return {"statusCode": 200, "body": "Message delivered"}
