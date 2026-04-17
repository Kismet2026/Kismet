import json
import os
import boto3
from boto3.dynamodb.conditions import Attr
from datetime import datetime, timezone

dynamodb = boto3.resource("dynamodb")
ses = boto3.client("ses")

prefs_table = dynamodb.Table(os.environ.get("PREFERENCES_TABLE", "kismet-email-preferences"))

SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "noreply@kismet.app")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@kismet.app")

# IAM least-privilege: In CDK stack, scope SES permissions to verified identities:
#   ses:SendEmail → arn:aws:ses:{region}:{account}:identity/*
# Do NOT use Resource: "*" for SES — restrict to verified sender domain/identity.

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

    if http_method == "GET" and path == "/email/preferences":
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
    elif detail_type == "user.deleted":
        return on_user_deleted(detail)
    elif detail_type == "scheduler.weekly_digest":
        return on_weekly_digest(detail)
    elif detail_type == "message.sent":
        return on_message_sent(detail)
    elif detail_type == "profile.banned":
        return on_profile_banned(detail)
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
        subject=get_subject_for_template("welcome"),
        body_text="Welcome to Kismet! We're excited to have you. Start by completing your profile to get discovered.",
        body_html=render_template("welcome", {"email": email}),
    )

    return {"statusCode": 200}


def on_user_deleted(detail):
    """Delete email preferences when a user deletes their account."""
    user_id = detail.get("userId", "")
    if not user_id:
        print("[WARN] user.deleted event missing userId")
        return {"statusCode": 400}

    prefs_table.delete_item(Key={"PK": f"USER#{user_id}", "SK": "PREFS"})
    print(f"[INFO] Deleted email preferences for user {user_id}")
    return {"statusCode": 200}


def on_match_created(detail):
    """Send match notification email to both users (if opted in)."""
    match_id = detail.get("matchId", "")
    user_ids = detail.get("userIds", [])

    for user_id in user_ids:
        # Single read for both preference check and email lookup
        prefs = prefs_table.get_item(
            Key={"PK": f"USER#{user_id}", "SK": "PREFS"}
        ).get("Item", {})
        if not prefs.get("matchNotifications", True):
            continue
        email = prefs.get("email", "")
        if not email:
            print(f"No email on record for {user_id}, skipping match email")
            continue
        send_ses_email(
            recipient=email,
            subject=get_subject_for_template("match_notification"),
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
        subject=get_subject_for_template("report_alert"),
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


def on_message_sent(detail):
    """Send message notification email to recipient (if opted in)."""
    recipient_id = detail.get("recipientId", "")
    if not recipient_id:
        print("message.sent event missing recipientId, skipping email")
        return {"statusCode": 200}

    prefs = prefs_table.get_item(
        Key={"PK": f"USER#{recipient_id}", "SK": "PREFS"}
    ).get("Item", {})

    if not prefs.get("messageNotifications", True):
        return {"statusCode": 200}

    email = prefs.get("email", "")
    if not email:
        print(f"No email on record for {recipient_id}, skipping message email")
        return {"statusCode": 200}

    send_ses_email(
        recipient=email,
        subject=get_subject_for_template("message_notification"),
        body_text="Someone sent you a message on Kismet. Open the app to reply.",
        body_html=render_template("message_notification", {}),
    )

    return {"statusCode": 200}


def on_profile_banned(detail):
    """Send suspension notice to banned user and audit email to admin."""
    user_id = detail.get("userId", "")
    reason = detail.get("reason", "unknown")
    report_id = detail.get("reportId", "")
    timestamp = detail.get("timestamp", datetime.now(timezone.utc).isoformat())

    prefs = prefs_table.get_item(
        Key={"PK": f"USER#{user_id}", "SK": "PREFS"}
    ).get("Item", {})

    email = prefs.get("email", "")
    if email:
        send_ses_email(
            recipient=email,
            subject=get_subject_for_template("ban_notice"),
            body_text="Your Kismet account has been suspended following review of community reports. If you believe this is a mistake, contact support@kismet.app.",
            body_html=render_template("ban_notice", {}),
        )
    else:
        print(f"No email on record for banned user {user_id}, skipping suspension notice")

    send_ses_email(
        recipient=ADMIN_EMAIL,
        subject=get_subject_for_template("ban_audit"),
        body_text=(
            f"User ID: {user_id}\n"
            f"Reason: {reason}\n"
            f"Report ID: {report_id}\n"
            f"Timestamp: {timestamp}"
        ),
        body_html=render_template("ban_audit", {
            "userId": user_id,
            "reason": reason,
            "reportId": report_id,
            "timestamp": timestamp,
        }),
    )

    return {"statusCode": 200}


def on_weekly_digest(detail):
    """Send weekly digest email to all users with weeklyDigest enabled."""
    result = prefs_table.scan(
        FilterExpression=Attr("weeklyDigest").eq(True)
    )
    items = result.get("Items", [])
    while "LastEvaluatedKey" in result:
        result = prefs_table.scan(
            FilterExpression=Attr("weeklyDigest").eq(True),
            ExclusiveStartKey=result["LastEvaluatedKey"],
        )
        items.extend(result.get("Items", []))

    sent = 0
    for item in items:
        email = item.get("email", "")
        if not email:
            continue
        send_ses_email(
            recipient=email,
            subject=get_subject_for_template("weekly_digest"),
            body_text="This week on Kismet. Matches made, messages exchanged, and conversations worth returning to.",
            body_html=render_template("weekly_digest", {}),
        )
        sent += 1

    print(f"Weekly digest sent to {sent} users")
    return {"statusCode": 200}


# ---------------------------------------------------------------------------
# REST API handlers
# ---------------------------------------------------------------------------


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

def send_ses_email(recipient, subject, body_text, body_html=None):
    """Send an email via SES."""
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
            '<div style="background:#1a0e15;padding:48px 20px;font-family:Georgia,\'Times New Roman\',serif;">'
            '<div style="max-width:560px;margin:0 auto;background:#2d1824;border:1px solid #3d2030;border-radius:8px;overflow:hidden;">'
            '<div style="padding:56px 40px 36px;text-align:center;">'
            '<div style="font-family:\'Allura\',\'Brush Script MT\',cursive;font-size:62px;color:#d9a74a;line-height:1;">Kismet</div>'
            '<div style="margin:22px auto 0;padding-top:18px;border-top:1px solid #3d2030;max-width:320px;">'
            '<div style="color:#b89b6e;font-size:14px;font-family:Georgia,serif;font-style:italic;">a meeting meant to happen</div>'
            '</div></div>'
            '<div style="padding:8px 48px 44px;color:#e8d9b8;font-size:16px;line-height:1.75;font-family:Georgia,serif;">'
            '<p style="margin:0 0 20px;">Welcome.</p>'
            '<p style="margin:0 0 20px;">We can\'t promise fate &mdash; but we can give it somewhere to show up.</p>'
            '<p style="margin:0 0 36px;">Your profile is where it starts.</p>'
            '<div style="text-align:center;margin:36px 0 8px;">'
            '<a href="#" style="display:inline-block;background:#d9a74a;color:#1f1018;padding:15px 48px;border-radius:2px;text-decoration:none;font-family:Georgia,serif;font-size:13px;letter-spacing:3px;text-transform:uppercase;font-weight:bold;">Complete Profile</a>'
            '</div></div>'
            '<div style="padding:22px 40px;border-top:1px solid #3d2030;text-align:center;font-size:11px;color:#6e5538;line-height:1.7;font-family:Georgia,serif;">'
            'You received this because you joined <span style="color:#a88959;">Kismet</span>.<br>'
            '<a href="#" style="color:#8a6d45;text-decoration:underline;">Manage preferences</a>'
            '</div></div></div>'
        ),
        "match_notification": (
            '<div style="background:#1a0e15;padding:48px 20px;font-family:Georgia,\'Times New Roman\',serif;">'
            '<div style="max-width:560px;margin:0 auto;background:#2d1824;border:1px solid #3d2030;border-radius:8px;overflow:hidden;">'
            '<div style="padding:44px 40px 28px;text-align:center;border-bottom:1px solid #3d2030;">'
            '<div style="font-family:\'Allura\',\'Brush Script MT\',cursive;font-size:52px;color:#d9a74a;line-height:1;">Kismet</div>'
            '</div>'
            '<div style="padding:40px 48px;color:#e8d9b8;font-size:16px;line-height:1.75;font-family:Georgia,serif;">'
            '<p style="margin:0 0 24px;font-size:20px;color:#d9a74a;font-style:italic;">The feeling is mutual.</p>'
            '<p style="margin:0 0 36px;">Someone you liked liked you back. Whenever you\'re ready, the first word is yours.</p>'
            '<div style="text-align:center;margin:36px 0 8px;">'
            '<a href="#" style="display:inline-block;background:#d9a74a;color:#1f1018;padding:15px 48px;border-radius:2px;text-decoration:none;font-family:Georgia,serif;font-size:13px;letter-spacing:3px;text-transform:uppercase;font-weight:bold;">Start a conversation</a>'
            '</div></div>'
            '<div style="padding:22px 40px;border-top:1px solid #3d2030;text-align:center;font-size:11px;color:#6e5538;line-height:1.7;font-family:Georgia,serif;">'
            'You\'re getting this because <span style="color:#a88959;">match notifications</span> are enabled.<br>'
            '<a href="#" style="color:#8a6d45;text-decoration:underline;">Manage preferences</a>'
            '</div></div></div>'
        ),
        "message_notification": (
            '<div style="background:#1a0e15;padding:48px 20px;font-family:Georgia,\'Times New Roman\',serif;">'
            '<div style="max-width:560px;margin:0 auto;background:#2d1824;border:1px solid #3d2030;border-radius:8px;overflow:hidden;">'
            '<div style="padding:44px 40px 28px;text-align:center;border-bottom:1px solid #3d2030;">'
            '<div style="font-family:\'Allura\',\'Brush Script MT\',cursive;font-size:52px;color:#d9a74a;line-height:1;">Kismet</div>'
            '</div>'
            '<div style="padding:40px 48px;color:#e8d9b8;font-size:16px;line-height:1.75;font-family:Georgia,serif;">'
            '<p style="margin:0 0 24px;font-size:20px;color:#d9a74a;font-style:italic;">A message is waiting.</p>'
            '<p style="margin:0 0 36px;">Someone wrote to you on Kismet.</p>'
            '<div style="text-align:center;margin:36px 0 8px;">'
            '<a href="#" style="display:inline-block;background:#d9a74a;color:#1f1018;padding:15px 48px;border-radius:2px;text-decoration:none;font-family:Georgia,serif;font-size:13px;letter-spacing:3px;text-transform:uppercase;font-weight:bold;">Read message</a>'
            '</div></div>'
            '<div style="padding:22px 40px;border-top:1px solid #3d2030;text-align:center;font-size:11px;color:#6e5538;line-height:1.7;font-family:Georgia,serif;">'
            'You\'re getting this because <span style="color:#a88959;">message notifications</span> are enabled.<br>'
            '<a href="#" style="color:#8a6d45;text-decoration:underline;">Manage preferences</a>'
            '</div></div></div>'
        ),
        "weekly_digest": (
            '<div style="background:#1a0e15;padding:48px 20px;font-family:Georgia,\'Times New Roman\',serif;">'
            '<div style="max-width:560px;margin:0 auto;background:#2d1824;border:1px solid #3d2030;border-radius:8px;overflow:hidden;">'
            '<div style="padding:44px 40px 28px;text-align:center;border-bottom:1px solid #3d2030;">'
            '<div style="font-family:\'Allura\',\'Brush Script MT\',cursive;font-size:52px;color:#d9a74a;line-height:1;">Kismet</div>'
            '</div>'
            '<div style="padding:40px 48px;color:#e8d9b8;font-size:16px;line-height:1.75;font-family:Georgia,serif;">'
            '<p style="margin:0 0 24px;font-size:20px;color:#d9a74a;font-style:italic;">This week on Kismet.</p>'
            '<p style="margin:0 0 36px;">Matches made, messages exchanged, and conversations worth returning to.</p>'
            '<div style="text-align:center;margin:36px 0 8px;">'
            '<a href="#" style="display:inline-block;background:#d9a74a;color:#1f1018;padding:15px 48px;border-radius:2px;text-decoration:none;font-family:Georgia,serif;font-size:13px;letter-spacing:3px;text-transform:uppercase;font-weight:bold;">Return to Kismet</a>'
            '</div></div>'
            '<div style="padding:22px 40px;border-top:1px solid #3d2030;text-align:center;font-size:11px;color:#6e5538;line-height:1.7;font-family:Georgia,serif;">'
            'You\'re getting this because the <span style="color:#a88959;">weekly digest</span> is enabled.<br>'
            '<a href="#" style="color:#8a6d45;text-decoration:underline;">Manage preferences</a>'
            '</div></div></div>'
        ),
        "ban_notice": (
            '<div style="background:#1a0e15;padding:48px 20px;font-family:Georgia,\'Times New Roman\',serif;">'
            '<div style="max-width:560px;margin:0 auto;background:#2d1824;border:1px solid #3d2030;border-radius:8px;overflow:hidden;">'
            '<div style="padding:44px 40px 28px;text-align:center;border-bottom:1px solid #3d2030;">'
            '<div style="font-family:\'Allura\',\'Brush Script MT\',cursive;font-size:52px;color:#d9a74a;line-height:1;">Kismet</div>'
            '</div>'
            '<div style="padding:40px 48px;color:#e8d9b8;font-size:16px;line-height:1.75;font-family:Georgia,serif;">'
            '<p style="margin:0 0 24px;font-size:20px;color:#d9a74a;font-style:italic;">Your account has been suspended.</p>'
            '<p style="margin:0 0 36px;">Following a review of community reports, your Kismet account has been suspended. If you believe this is a mistake, contact <a href="mailto:support@kismet.app" style="color:#d9a74a;">support@kismet.app</a>.</p>'
            '</div>'
            '<div style="padding:22px 40px;border-top:1px solid #3d2030;text-align:center;font-size:11px;color:#6e5538;line-height:1.7;font-family:Georgia,serif;">'
            'This is an automated notice from <span style="color:#a88959;">Kismet</span>.'
            '</div></div></div>'
        ),
        "ban_audit": (
            '<div style="background:#e8d9b8;padding:48px 20px;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif;">'
            '<div style="max-width:560px;margin:0 auto;background:#f5ebd4;border:1px solid #d4c4a5;border-radius:2px;overflow:hidden;">'
            '<div style="background:#2d1824;padding:14px 20px;">'
            '<div style="color:#d9a74a;font-family:Georgia,serif;font-size:12px;letter-spacing:3px;text-transform:uppercase;">Kismet Admin</div>'
            '</div>'
            '<div style="padding:28px 24px;color:#22182a;font-size:13px;line-height:1.5;">'
            '<div style="font-size:16px;font-weight:600;color:#22182a;letter-spacing:-0.2px;margin:0 0 4px;">Account Banned</div>'
            '<div style="color:#6e5538;font-size:12px;margin:0 0 20px;">A user account has been suspended following community reports.</div>'
            '<div style="border-left:3px solid #2d1824;padding:12px 16px;background:#ede0c2;">'
            '<table style="width:100%;border-collapse:collapse;">'
            f'<tr><td style="padding:4px 0;color:#6e5538;font-size:11px;text-transform:uppercase;letter-spacing:1.5px;width:36%;">User ID</td><td style="padding:4px 0;color:#22182a;font-family:\'SF Mono\',Menlo,Consolas,monospace;font-size:12px;">{data.get("userId", "")}</td></tr>'
            f'<tr><td style="padding:4px 0;color:#6e5538;font-size:11px;text-transform:uppercase;letter-spacing:1.5px;">Reason</td><td style="padding:4px 0;color:#22182a;font-size:12px;">{data.get("reason", "")}</td></tr>'
            f'<tr><td style="padding:4px 0;color:#6e5538;font-size:11px;text-transform:uppercase;letter-spacing:1.5px;">Report ID</td><td style="padding:4px 0;color:#22182a;font-family:\'SF Mono\',Menlo,Consolas,monospace;font-size:12px;">{data.get("reportId", "")}</td></tr>'
            f'<tr><td style="padding:4px 0;color:#6e5538;font-size:11px;text-transform:uppercase;letter-spacing:1.5px;">Timestamp</td><td style="padding:4px 0;color:#22182a;font-family:\'SF Mono\',Menlo,Consolas,monospace;font-size:12px;">{data.get("timestamp", "")}</td></tr>'
            '</table>'
            '</div>'
            '</div></div></div>'
        ),
        "report_alert": (
            '<div style="background:#e8d9b8;padding:48px 20px;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif;">'
            '<div style="max-width:560px;margin:0 auto;background:#f5ebd4;border:1px solid #d4c4a5;border-radius:2px;overflow:hidden;">'
            '<div style="background:#2d1824;padding:14px 20px;">'
            '<div style="color:#d9a74a;font-family:Georgia,serif;font-size:12px;letter-spacing:3px;text-transform:uppercase;">Kismet Admin</div>'
            '</div>'
            '<div style="padding:28px 24px;color:#22182a;font-size:13px;line-height:1.5;">'
            '<div style="font-size:16px;font-weight:600;color:#22182a;letter-spacing:-0.2px;margin:0 0 4px;">User Report Submitted</div>'
            '<div style="color:#6e5538;font-size:12px;margin:0 0 20px;">A user has been reported and awaits admin review.</div>'
            '<div style="border-left:3px solid #2d1824;padding:12px 16px;background:#ede0c2;">'
            '<table style="width:100%;border-collapse:collapse;">'
            f'<tr><td style="padding:4px 0;color:#6e5538;font-size:11px;text-transform:uppercase;letter-spacing:1.5px;width:36%;">Report ID</td><td style="padding:4px 0;color:#22182a;font-family:\'SF Mono\',Menlo,Consolas,monospace;font-size:12px;">{data.get("reportId", "")}</td></tr>'
            f'<tr><td style="padding:4px 0;color:#6e5538;font-size:11px;text-transform:uppercase;letter-spacing:1.5px;">Reporter</td><td style="padding:4px 0;color:#22182a;font-family:\'SF Mono\',Menlo,Consolas,monospace;font-size:12px;">{data.get("reporterId", "")}</td></tr>'
            f'<tr><td style="padding:4px 0;color:#6e5538;font-size:11px;text-transform:uppercase;letter-spacing:1.5px;">Reported User</td><td style="padding:4px 0;color:#22182a;font-family:\'SF Mono\',Menlo,Consolas,monospace;font-size:12px;">{data.get("reportedUserId", "")}</td></tr>'
            f'<tr><td style="padding:4px 0;color:#6e5538;font-size:11px;text-transform:uppercase;letter-spacing:1.5px;">Reason</td><td style="padding:4px 0;color:#22182a;font-size:12px;">{data.get("reason", "")}</td></tr>'
            '</table>'
            '</div>'
            '<div style="margin-top:22px;">'
            '<a href="#" style="display:inline-block;background:#2d1824;color:#f5ebd4;padding:10px 20px;border-radius:2px;text-decoration:none;font-size:11px;letter-spacing:1.5px;text-transform:uppercase;font-weight:600;">Review Report</a>'
            '</div></div></div></div>'
        ),
    }
    return templates.get(template_name, "<p>Email content</p>")


def get_subject_for_template(template_name):
    subjects = {
        "welcome": "Welcome to Kismet",
        "match_notification": "The feeling is mutual — a new match on Kismet",
        "message_notification": "A message is waiting on Kismet",
        "weekly_digest": "This week on Kismet",
        "report_alert": "[Kismet Admin] New user report — action required",
        "ban_notice": "Your Kismet account has been suspended",
        "ban_audit": "[Kismet Admin] Account banned — action log",
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
