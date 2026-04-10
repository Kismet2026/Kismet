import json
import os
from io import BytesIO

import boto3
from boto3.dynamodb.conditions import Key

CONNECTIONS_TABLE = os.environ["CONNECTIONS_TABLE"]
MATCHES_TABLE = os.environ["MATCHES_TABLE"]
MESSAGE_SERVICE_FUNCTION_NAME = os.environ["MESSAGE_SERVICE_FUNCTION_NAME"]
ALLOWED_MESSAGE_TYPES = {"text"}

dynamodb = boto3.resource("dynamodb")
connections = dynamodb.Table(CONNECTIONS_TABLE)
matches = dynamodb.Table(MATCHES_TABLE)
lambda_client = boto3.client("lambda")


def handler(event, context):
    connection_id = event["requestContext"]["connectionId"]
    domain = event["requestContext"]["domainName"]
    stage = event["requestContext"]["stage"]

    body = json.loads(event.get("body") or "{}")
    content = body.get("content")
    message_type = body.get("messageType", "text")

    connection = get_connection(connection_id)
    if not connection:
        return json_response(401, {"code": "UNAUTHORIZED", "message": "Connection not registered"})

    sender_id = connection.get("userId", "")
    match_id = connection.get("matchId", "")

    if not sender_id:
        return json_response(401, {"code": "UNAUTHORIZED", "message": "Authentication required"})
    if not match_id or not content:
        return json_response(
            400,
            {"code": "VALIDATION_ERROR", "message": "matchId and content are required"},
        )
    if message_type not in ALLOWED_MESSAGE_TYPES:
        return json_response(
            400,
            {"code": "VALIDATION_ERROR", "message": "messageType must be 'text'"},
        )

    match_item, match_error = get_match_for_user(match_id, sender_id)
    if match_error:
        return match_error

    message_response = invoke_message_service(match_id, content, message_type, sender_id)
    if message_response["statusCode"] != 200:
        return message_response

    message = json.loads(message_response["body"])
    recipient_id = get_other_participant(match_item, sender_id)

    # Push message to other active connections in the same match.
    connection_query = connections.query(
        IndexName="matchId-index",
        KeyConditionExpression=Key("matchId").eq(match_id),
    )
    receiver_conns = [
        c for c in connection_query.get("Items", [])
        if c["connectionId"] != connection_id and c.get("userId") == recipient_id
    ]

    apigw = boto3.client(
        "apigatewaymanagementapi",
        endpoint_url=f"https://{domain}/{stage}",
    )
    payload = json.dumps({"type": "newMessage", **message})

    for conn in receiver_conns:
        post_to_connection(apigw, conn["connectionId"], payload)

    return message_response


def invoke_message_service(match_id, content, message_type, sender_id):
    invocation_event = {
        "httpMethod": "POST",
        "path": "/messages",
        "body": json.dumps(
            {
                "matchId": match_id,
                "content": content,
                "messageType": message_type,
            }
        ),
        "requestContext": {"authorizer": {"claims": {"sub": sender_id}}},
    }

    try:
        response = lambda_client.invoke(
            FunctionName=MESSAGE_SERVICE_FUNCTION_NAME,
            InvocationType="RequestResponse",
            Payload=json.dumps(invocation_event).encode(),
        )
        payload = response.get("Payload", BytesIO(b"{}")).read()
        result = json.loads(payload or b"{}")
    except Exception as exc:
        print(f"[ERROR] Failed to invoke Message Service: {exc}")
        return json_response(
            502,
            {"code": "UPSTREAM_ERROR", "message": "Message Service invocation failed"},
        )

    if not isinstance(result, dict) or "statusCode" not in result or "body" not in result:
        return json_response(
            502,
            {"code": "UPSTREAM_ERROR", "message": "Message Service returned an invalid response"},
        )

    return {
        "statusCode": result["statusCode"],
        "body": result["body"],
    }


def get_connection(connection_id):
    result = connections.get_item(Key={"PK": f"CONN#{connection_id}", "SK": "META"})
    return result.get("Item")


def get_match_for_user(match_id, user_id):
    result = matches.get_item(Key={"PK": f"MATCH#{match_id}", "SK": "META"})
    item = result.get("Item")

    if not item:
        return None, json_response(404, {"code": "NOT_FOUND", "message": "Match not found"})

    participants = {item.get("userAId"), item.get("userBId")}
    if user_id not in participants:
        return None, json_response(
            403,
            {"code": "FORBIDDEN", "message": "User is not a participant of this match"},
        )

    return item, None


def get_other_participant(match_item, user_id):
    if match_item.get("userAId") == user_id:
        return match_item.get("userBId", "")
    return match_item.get("userAId", "")


def post_to_connection(apigw, connection_id, payload):
    try:
        apigw.post_to_connection(
            ConnectionId=connection_id,
            Data=payload.encode(),
        )
    except apigw.exceptions.GoneException:
        connections.delete_item(Key={"PK": f"CONN#{connection_id}", "SK": "META"})


def json_response(status_code, payload):
    return {"statusCode": status_code, "body": json.dumps(payload)}
