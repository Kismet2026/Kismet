import json
import os
import boto3
from datetime import datetime, timezone

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ.get("TABLE_NAME", "kismet-email-preferences"))

VALID_TEMPLATES = ["welcome", "match_notification", "message_notification", "weekly_digest", "report_alert"]


def handler(event, context):
    http_method = event.get("httpMethod", "")
    path = event.get("path", "")
    user_id = event.get("requestContext", {}).get("authorizer", {}).get("claims", {}).get("sub", "")

    if http_method == "POST" and path == "/email/send":
        return send_email(event)
    elif http_method == "GET" and path == "/email/preferences":
        return get_preferences(event, user_id)
    elif http_method == "PUT" and path == "/email/preferences":
        return update_preferences(event, user_id)
    else:
        return response(404, {"error": {"code": "NOT_FOUND", "message": "Route not found"}})


def send_email(event):
    body = json.loads(event.get("body", "{}"))
    template_name = body.get("templateName")
    recipient_user_id = body.get("recipientUserId")
    template_data = body.get("templateData", {})

    if template_name not in VALID_TEMPLATES:
        return response(400, {"error": {"code": "VALIDATION_ERROR", "message": f"Invalid templateName. Must be one of: {VALID_TEMPLATES}"}})

    if not recipient_user_id:
        return response(400, {"error": {"code": "VALIDATION_ERROR", "message": "Missing recipientUserId"}})

    # TODO: check email preferences, send via SES
    return response(200, {
        "emailId": "email-stub",
        "templateName": template_name,
        "recipientUserId": recipient_user_id,
        "status": "sent",
        "sentAt": datetime.now(timezone.utc).isoformat(),
    })


def get_preferences(event, user_id):
    # TODO: query DynamoDB PK=USER#{user_id}, SK=PREFS
    return response(200, {
        "userId": user_id,
        "matchNotifications": True,
        "messageNotifications": True,
        "weeklyDigest": True,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    })


def update_preferences(event, user_id):
    body = json.loads(event.get("body", "{}"))

    allowed_fields = ["matchNotifications", "messageNotifications", "weeklyDigest"]
    for key, value in body.items():
        if key in allowed_fields and not isinstance(value, bool):
            return response(400, {"error": {"code": "VALIDATION_ERROR", "message": f"{key} must be boolean"}})

    # TODO: update DynamoDB
    return response(200, {
        "userId": user_id,
        "matchNotifications": body.get("matchNotifications", True),
        "messageNotifications": body.get("messageNotifications", True),
        "weeklyDigest": body.get("weeklyDigest", True),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    })


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }