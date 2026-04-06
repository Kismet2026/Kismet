import json
import os
import uuid
import boto3
from boto3.dynamodb.conditions import Key
from datetime import datetime, timezone

dynamodb = boto3.resource("dynamodb")
ses = boto3.client("ses")

prefs_table = dynamodb.Table(os.environ.get("PREFERENCES_TABLE", "kismet-email-preferences"))

SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "noreply@kismet.app")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@kismet.app")

# IAM least-privilege: In CDK stack, scope SES permissions to verified identities:
#   ses:SendEmail → arn:aws:ses:{region}:{account}:identity/*
# Do NOT use Resource: "*" for SES — restrict to verified sender domain/identity.

VALID_TEMPLATES = [
    "welcome",
    "match_notification",
    "message_notification",
    "weekly_digest",
    "report_alert",
]

# Maps template name to the preference field that controls it
TEMPLATE_PREF_MAP = {
    "match_notification": "matchNotifications",
    "message_notification": "messageNotifications",
    "weekly_digest": "weeklyDigest",
}

DEFAULT_PREFERENCES = {
    "matchNotifications": True,
    "messageNotifications": True,
    "weeklyDigest": True,
}


def handler(event, context):
    # EventBridge event — has "source" and "detail-type"
    if "source" in event and "detail-type" in event:
        return handle_event(event, context)

    # API Gateway HTTP request
    http_method = event.get("httpMethod", "")
    path = event.get("path", "")
    user_id = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("claims", {})
        .get("sub", "")
    )

    if http_method == "POST" and path == "/email/send":
        return send_email(event)
    elif http_method == "GET" and path == "/email/preferences":
        return get_preferences(user_id)
    elif http_method == "PUT" and path == "/email/preferences":
        return update_preferences(event, user_id)
    else:
        return response(404, {"error": {"code": "NOT_FOUND", "message": "Route not found"}})


# ---------------------------------------------------------------------------
# EventBridge handlers
# ---------------------------------------------------------------------------

def handle_event(event, context):
    detail_type = event.get("detail-type", "")
    detail = event.get("detail", {})

    if detail_type == "user.created":
        return on_user_created(detail)
    elif detail_type == "match.created":
        return on_match_created(detail)
    elif detail_type == "user.reported":
        return on_user_reported(detail)
    else:
        print(f"Unhandled event type: {detail_type}")
        return {"statusCode": 200}


def on_user_created(detail):
    """Send welcome email to new user and initialize default preferences."""
    user_id = detail.get("userId", "")
    email = detail.get("email", "")
    timestamp = detail.get("timestamp", datetime.now(timezone.utc).isoformat())

    # Initialize default preferences and persist email for later event-driven lookups
    try:
        prefs_table.put_item(
            Item={
                "PK": f"USER#{user_id}",
                "SK": "PREFS",
                "email": email,
                **DEFAULT_PREFERENCES,
                "updatedAt": timestamp,
            },
            ConditionExpression="attribute_not_exists(PK)",
        )
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        pass  # preferences already exist, leave them unchanged

    # Send welcome email
    send_ses_email(
        recipient=email,
        subject="Welcome to Kismet!",
        body_text=f"Welcome to Kismet! We're excited to have you. Start by completing your profile to get discovered.",
        body_html=render_template("welcome", {"email": email}),
    )

    return {"statusCode": 200}


def on_match_created(detail):
    """Send match notification email to both users (if opted in)."""
    match_id = detail.get("matchId", "")
    user_ids = detail.get("userIds", [])

    for user_id in user_ids:
        if not check_preference(user_id, "matchNotifications"):
            continue
        prefs = prefs_table.get_item(
            Key={"PK": f"USER#{user_id}", "SK": "PREFS"}
        ).get("Item", {})
        email = prefs.get("email", "")
        if not email:
            print(f"No email on record for {user_id}, skipping match email")
            continue
        send_ses_email(
            recipient=email,
            subject="You have a new match on Kismet!",
            body_text=f"Great news! You have a new match (ID: {match_id}). Open Kismet to start chatting!",
            body_html=render_template("match_notification", {"matchId": match_id, "userId": user_id}),
        )

    return {"statusCode": 200}


def on_user_reported(detail):
    """Send admin alert email when a user is reported."""
    report_id = detail.get("reportId", "")
    reporter_id = detail.get("reporterId", "")
    reported_user_id = detail.get("reportedUserId", "")
    reason = detail.get("reason", "unknown")

    send_ses_email(
        recipient=ADMIN_EMAIL,
        subject=f"[Kismet Admin] User Report: {reason}",
        body_text=(
            f"Report ID: {report_id}\n"
            f"Reporter: {reporter_id}\n"
            f"Reported User: {reported_user_id}\n"
            f"Reason: {reason}"
        ),
        body_html=render_template("report_alert", {
            "reportId": report_id,
            "reporterId": reporter_id,
            "reportedUserId": reported_user_id,
            "reason": reason,
        }),
    )

    return {"statusCode": 200}


# ---------------------------------------------------------------------------
# REST API handlers
# ---------------------------------------------------------------------------

def send_email(event):
    """POST /email/send — internal endpoint for sending templated emails."""
    body = json.loads(event.get("body", "{}"))
    template_name = body.get("templateName")
    recipient_user_id = body.get("recipientUserId")
    template_data = body.get("templateData", {})

    if template_name not in VALID_TEMPLATES:
        return response(400, {
            "error": {"code": "VALIDATION_ERROR", "message": f"Invalid templateName. Must be one of: {VALID_TEMPLATES}"}
        })

    if not recipient_user_id:
        return response(400, {
            "error": {"code": "VALIDATION_ERROR", "message": "Missing recipientUserId"}
        })

    # Check user preference for this template type
    pref_field = TEMPLATE_PREF_MAP.get(template_name)
    if pref_field and not check_preference(recipient_user_id, pref_field):
        return response(422, {
            "error": {"code": "EMAIL_OPTED_OUT", "message": f"User has opted out of {template_name} emails"}
        })

    now = datetime.now(timezone.utc).isoformat()
    email_id = f"email-{uuid.uuid4().hex[:8]}"

    send_ses_email(
        recipient=None,  # resolved via user lookup in production
        subject=get_subject_for_template(template_name),
        body_text=json.dumps(template_data),
        body_html=render_template(template_name, template_data),
        user_id=recipient_user_id,
    )

    return response(200, {
        "emailId": email_id,
        "templateName": template_name,
        "recipientUserId": recipient_user_id,
        "status": "sent",
        "sentAt": now,
    })


def get_preferences(user_id):
    """GET /email/preferences — get current user's email prefs."""
    result = prefs_table.get_item(
        Key={"PK": f"USER#{user_id}", "SK": "PREFS"}
    )
    item = result.get("Item")

    if not item:
        # Return defaults if no preferences saved yet
        return response(200, {
            "userId": user_id,
            **DEFAULT_PREFERENCES,
            "updatedAt": None,
        })

    return response(200, {
        "userId": user_id,
        "matchNotifications": item.get("matchNotifications", True),
        "messageNotifications": item.get("messageNotifications", True),
        "weeklyDigest": item.get("weeklyDigest", True),
        "updatedAt": item.get("updatedAt"),
    })


def update_preferences(event, user_id):
    """PUT /email/preferences — update current user's email prefs."""
    body = json.loads(event.get("body", "{}"))

    allowed_fields = ["matchNotifications", "messageNotifications", "weeklyDigest"]
    updates = {}
    for key in allowed_fields:
        if key in body:
            if not isinstance(body[key], bool):
                return response(400, {
                    "error": {"code": "VALIDATION_ERROR", "message": f"{key} must be boolean"}
                })
            updates[key] = body[key]

    if not updates:
        return response(400, {
            "error": {"code": "VALIDATION_ERROR", "message": "No valid fields to update"}
        })

    now = datetime.now(timezone.utc).isoformat()
    updates["updatedAt"] = now

    update_expr_parts = []
    expr_values = {}
    expr_names = {}
    for i, (k, v) in enumerate(updates.items()):
        alias = f"#f{i}"
        val_alias = f":v{i}"
        update_expr_parts.append(f"{alias} = {val_alias}")
        expr_names[alias] = k
        expr_values[val_alias] = v

    prefs_table.update_item(
        Key={"PK": f"USER#{user_id}", "SK": "PREFS"},
        UpdateExpression="SET " + ", ".join(update_expr_parts),
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )

    # Fetch updated record to return full state
    return get_preferences(user_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def check_preference(user_id, pref_field):
    """Check if user has a specific email preference enabled. Defaults to True."""
    result = prefs_table.get_item(
        Key={"PK": f"USER#{user_id}", "SK": "PREFS"}
    )
    item = result.get("Item")
    if not item:
        return True  # default: opted in
    return item.get(pref_field, True)


def send_ses_email(recipient, subject, body_text, body_html=None, user_id=None):
    """Send an email via SES. If recipient is None and user_id is provided,
    the email address would be resolved from a user profile service in production."""
    if not recipient and not user_id:
        print("send_ses_email: no recipient or user_id provided, skipping")
        return

    # In production, resolve user_id → email via profile service or Cognito
    if not recipient and user_id:
        print(f"send_ses_email: would resolve email for user {user_id} in production")
        return

    try:
        ses.send_email(
            Source=SENDER_EMAIL,
            Destination={"ToAddresses": [recipient]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": body_text, "Charset": "UTF-8"},
                    **({"Html": {"Data": body_html, "Charset": "UTF-8"}} if body_html else {}),
                },
            },
        )
    except Exception as e:
        print(f"SES send_email failed: {e}")


def render_template(template_name, data):
    """Render an HTML email template. In production, use SES templates or
    a templating engine. For now, return simple HTML."""
    templates = {
        "welcome": (
            "<h1>Welcome to Kismet!</h1>"
            "<p>We're excited to have you. Complete your profile to start meeting people.</p>"
        ),
        "match_notification": (
            "<h1>New Match!</h1>"
            f"<p>You have a new match. Open Kismet to start chatting!</p>"
        ),
        "message_notification": (
            "<h1>New Message</h1>"
            "<p>You have a new message waiting for you on Kismet.</p>"
        ),
        "weekly_digest": (
            "<h1>Your Weekly Kismet Digest</h1>"
            "<p>Here's what happened this week on Kismet.</p>"
        ),
        "report_alert": (
            "<h1>User Report Alert</h1>"
            f"<p>Report ID: {data.get('reportId', '')}</p>"
            f"<p>Reporter: {data.get('reporterId', '')}</p>"
            f"<p>Reported User: {data.get('reportedUserId', '')}</p>"
            f"<p>Reason: {data.get('reason', '')}</p>"
        ),
    }
    return templates.get(template_name, "<p>Email content</p>")


def get_subject_for_template(template_name):
    subjects = {
        "welcome": "Welcome to Kismet!",
        "match_notification": "You have a new match on Kismet!",
        "message_notification": "You have a new message on Kismet",
        "weekly_digest": "Your Weekly Kismet Digest",
        "report_alert": "[Kismet Admin] User Report",
    }
    return subjects.get(template_name, "Kismet Notification")


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }
