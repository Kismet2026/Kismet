import json
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3

dynamodb = boto3.resource("dynamodb")
kinesis = boto3.client("kinesis")

ACTIVITY_LOG_TABLE = os.environ.get("ACTIVITY_LOG_TABLE", "kismet-activity-log")
KINESIS_STREAM_NAME = os.environ.get("KINESIS_STREAM_NAME", "kismet-activity-stream")


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=_json_default),
    }


def _json_default(obj):
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def handler(event, context):
    if "detail-type" in event:
        return handle_eventbridge(event)

    method = event.get("httpMethod", "")
    resource = event.get("resource", "")

    if method == "POST" and resource == "/analytics/log":
        return handle_post_log(event)
    if method == "GET" and resource == "/analytics/log/recent":
        return handle_get_recent(event)

    return _response(404, {"error": "Not found"})


def _extract_user_id(detail_type, detail):
    """Extract the primary userId from an event based on its type."""
    if detail_type == "match.created":
        user_ids = detail.get("userIds", [])
        return user_ids[0] if user_ids else "unknown"
    if detail_type == "message.sent":
        return detail.get("senderId", "unknown")
    if detail_type == "user.reported":
        return detail.get("reporterId", "unknown")
    return detail.get("userId", "unknown")


# ── EventBridge handler ───────────────────────────────────────────────────────


def handle_eventbridge(event):
    detail_type = event["detail-type"]
    detail = event.get("detail", {})
    source = event.get("source", "")
    timestamp = detail.get(
        "timestamp", datetime.now(timezone.utc).isoformat()
    )
    user_id = _extract_user_id(detail_type, detail)
    log_id = f"log-{uuid.uuid4().hex[:12]}"

    record = {
        "logId": log_id,
        "eventType": detail_type,
        "userId": user_id,
        "eventData": detail,
        "source": source,
        "timestamp": timestamp,
    }

    records_to_write = [(record, user_id)]

    if detail_type == "match.created":
        user_ids = detail.get("userIds", [])
        if len(user_ids) > 1:
            second_record = {
                **record,
                "logId": f"log-{uuid.uuid4().hex[:12]}",
                "userId": user_ids[1],
            }
            records_to_write.append((second_record, user_ids[1]))

    try:
        for current_record, current_user_id in records_to_write:
            _write_to_kinesis(current_record, current_user_id)
    except Exception as e:
        print(f"Kinesis write failed for EventBridge event {detail_type}: {e}")
        raise

    for current_record, current_user_id in records_to_write:
        _write_to_dynamodb(current_record, current_user_id)

    return {"statusCode": 200}


# ── POST /analytics/log ──────────────────────────────────────────────────────


def handle_post_log(event):
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(
            400, {"error": "VALIDATION_ERROR", "message": "Invalid JSON body"}
        )

    event_type = body.get("eventType")
    event_data = body.get("eventData")
    user_id = body.get("userId")

    if not event_type or event_data is None or not user_id:
        return _response(
            400,
            {
                "error": "VALIDATION_ERROR",
                "message": "eventType, eventData, and userId are required",
            },
        )

    timestamp = datetime.now(timezone.utc).isoformat()
    log_id = f"log-{uuid.uuid4().hex[:12]}"

    record = {
        "logId": log_id,
        "eventType": event_type,
        "userId": user_id,
        "eventData": event_data,
        "timestamp": timestamp,
    }

    try:
        _write_to_kinesis(record, user_id)
    except Exception as e:
        return _response(
            502,
            {
                "error": "KINESIS_WRITE_FAILED",
                "message": str(e),
            },
        )

    _write_to_dynamodb(record, user_id)

    return _response(
        200,
        {
            "logId": log_id,
            "eventType": event_type,
            "userId": user_id,
            "timestamp": timestamp,
            "status": "accepted",
        },
    )


# ── GET /analytics/log/recent ────────────────────────────────────────────────


def handle_get_recent(event):
    params = event.get("queryStringParameters") or {}
    user_id = params.get("userId")
    event_type = params.get("eventType")
    limit = min(int(params.get("limit", 50)), 100)

    table = dynamodb.Table(ACTIVITY_LOG_TABLE)

    if user_id:
        query_kwargs = {
            "KeyConditionExpression": "PK = :pk",
            "ExpressionAttributeValues": {":pk": f"USER#{user_id}"},
            "ScanIndexForward": False,
            "Limit": limit,
        }
        if event_type:
            query_kwargs["FilterExpression"] = "eventType = :et"
            query_kwargs["ExpressionAttributeValues"][":et"] = event_type
        result = table.query(**query_kwargs)
    else:
        scan_kwargs = {"Limit": limit}
        if event_type:
            scan_kwargs["FilterExpression"] = "eventType = :et"
            scan_kwargs["ExpressionAttributeValues"] = {":et": event_type}
        result = table.scan(**scan_kwargs)

    items = []
    for item in result.get("Items", []):
        items.append(
            {
                "logId": item.get("logId"),
                "eventType": item.get("eventType"),
                "userId": item["PK"].replace("USER#", ""),
                "eventData": item.get("eventData", {}),
                "timestamp": item.get("timestamp"),
            }
        )

    return _response(200, {"items": items, "count": len(items)})


# ── Kinesis + DynamoDB writers ────────────────────────────────────────────────


def _write_to_kinesis(record, partition_key):
    # Athena's `activity_events` table declares `eventData STRING`, so the
    # JsonSerDe needs each record's `eventData` to be a JSON *string*, not a
    # nested object — otherwise dashboard queries that call
    # `json_extract_scalar(eventData, '$.matchId')` always get NULL.
    # Stringify it here (Kinesis/Firehose/Athena path only). The DDB path
    # below keeps the original dict so consumers of `kismet-activity-log`
    # still see `eventData` as a native map.
    kinesis_record = record
    if isinstance(record.get("eventData"), dict):
        kinesis_record = {**record, "eventData": json.dumps(record["eventData"])}
    try:
        # Append a newline so Firehose writes JSON Lines to S3. Kinesis records
        # are concatenated byte-for-byte into Firehose output objects with no
        # delimiter added, so without this trailing '\n' the S3 file is one
        # long line of back-to-back JSON objects and Athena's JsonSerDe reads
        # only the first record per object.
        kinesis.put_record(
            StreamName=KINESIS_STREAM_NAME,
            Data=(json.dumps(kinesis_record) + "\n").encode("utf-8"),
            PartitionKey=partition_key,
        )
    except Exception as e:
        raise RuntimeError(
            f"failed to write to Kinesis stream {KINESIS_STREAM_NAME}"
        ) from e


def _write_to_dynamodb(record, user_id):
    table = dynamodb.Table(ACTIVITY_LOG_TABLE)
    event_data = json.loads(
        json.dumps(record.get("eventData", {})), parse_float=Decimal
    )

    table.put_item(
        Item={
            "PK": f"USER#{user_id}",
            "SK": f"EVENT#{record['timestamp']}#{record['logId']}",
            "logId": record["logId"],
            "eventType": record["eventType"],
            "eventData": event_data,
            "timestamp": record["timestamp"],
        }
    )
