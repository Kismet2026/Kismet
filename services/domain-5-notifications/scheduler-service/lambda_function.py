"""
Kismet Scheduler Service — Lambda Handlers

Two entry points:
  1. admin_api_handler    — API Gateway; GET/POST/DELETE /scheduler/jobs
  2. job_executor_handler — Invoked by EventBridge Scheduler; publishes events to trigger target services
"""

import json
import os
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

# ─── Clients ──────────────────────────────────────────────────
dynamodb = boto3.resource("dynamodb")
events_client = boto3.client("events")
scheduler_client = boto3.client("scheduler")

SCHEDULER_TABLE = os.environ["SCHEDULER_TABLE"]
EVENT_BUS_NAME = os.environ["EVENT_BUS_NAME"]
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")

table = dynamodb.Table(SCHEDULER_TABLE)

# Job type → event detail-type mapping for EventBridge
JOB_EVENT_MAP = {
    "weekly_digest": {
        "source": "kismet.scheduler-service",
        "detail_type": "scheduler.weekly_digest",
        "description": "Send weekly digest email to all users",
    },
    "stale_match_cleanup": {
        "source": "kismet.scheduler-service",
        "detail_type": "scheduler.stale_match_cleanup",
        "description": "Archive matches with no messages after 30 days",
    },
    "analytics_aggregation": {
        "source": "kismet.scheduler-service",
        "detail_type": "scheduler.analytics_aggregation",
        "description": "Trigger Activity Logger to flush buffered analytics",
    },
    "health_check": {
        "source": "kismet.scheduler-service",
        "detail_type": "scheduler.health_check",
        "description": "Trigger Health Monitor to check all services",
    },
}

VALID_JOB_TYPES = set(JOB_EVENT_MAP.keys())


# ─── Helpers ──────────────────────────────────────────────────
def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }


def _error(status_code, code, message):
    return _response(status_code, {"error": {"code": code, "message": message}})


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. Admin API (API Gateway)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def admin_api_handler(event, context):
    """Routes API Gateway requests to the correct handler."""
    http_method = event.get("httpMethod", "")
    path = event.get("path", "")

    if path == "/scheduler/jobs" and http_method == "GET":
        return _list_jobs(event)
    elif path == "/scheduler/jobs" and http_method == "POST":
        return _create_job(event)
    elif path.startswith("/scheduler/jobs/") and http_method == "DELETE":
        job_id = event.get("pathParameters", {}).get("jobId")
        return _delete_job(job_id)
    else:
        return _error(404, "NOT_FOUND", f"No route for {http_method} {path}")


# ─── GET /scheduler/jobs ──────────────────────────────────────
def _list_jobs(event):
    """List all scheduled jobs from DynamoDB."""
    response = table.scan()
    items = response.get("Items", [])

    jobs = []
    for item in items:
        jobs.append(
            {
                "jobId": item["jobId"],
                "jobType": item["jobType"],
                "schedule": item.get("schedule", ""),
                "description": item.get("description", ""),
                "state": item.get("state", "ENABLED"),
                "lastRunAt": item.get("lastRunAt"),
                "nextRunAt": item.get("nextRunAt"),
                "params": item.get("params", {}),
            }
        )

    return _response(200, {"jobs": jobs, "count": len(jobs)})


# ─── POST /scheduler/jobs ─────────────────────────────────────
def _create_job(event):
    """Create a new scheduled job: DynamoDB record + EventBridge Scheduler schedule."""
    body = json.loads(event.get("body") or "{}")
    job_type = body.get("jobType")
    schedule = body.get("schedule")
    params = body.get("params", {})

    if not job_type or not schedule:
        return _error(400, "VALIDATION_ERROR", "jobType and schedule are required")

    if job_type not in VALID_JOB_TYPES:
        return _error(
            400,
            "VALIDATION_ERROR",
            f"Invalid jobType. Must be one of: {', '.join(VALID_JOB_TYPES)}",
        )

    job_id = f"job-{uuid.uuid4().hex[:8]}"
    now = _now_iso()
    description = JOB_EVENT_MAP[job_type]["description"]

    # Check for duplicate job type + schedule
    existing = table.scan(
        FilterExpression=Key("jobType").eq(job_type)
        & Key("schedule").eq(schedule)
    )
    if existing.get("Items"):
        return _error(
            409, "CONFLICT", f"A job with type '{job_type}' and schedule '{schedule}' already exists"
        )

    # Get the executor Lambda ARN from environment
    executor_arn = os.environ.get("JOB_EXECUTOR_ARN", "")
    role_arn = os.environ.get("SCHEDULER_ROLE_ARN", "")

    # Create EventBridge Scheduler schedule
    schedule_name = f"kismet-{job_type.replace('_', '-')}-{job_id}-{ENVIRONMENT}"
    try:
        scheduler_client.create_schedule(
            Name=schedule_name,
            ScheduleExpression=schedule,
            FlexibleTimeWindow={"Mode": "OFF"},
            State="ENABLED",
            Target={
                "Arn": executor_arn,
                "RoleArn": role_arn,
                "Input": json.dumps({"jobType": job_type, "jobId": job_id, "params": params}),
            },
        )
    except Exception as e:
        return _error(500, "INTERNAL_ERROR", f"Failed to create schedule: {str(e)}")

    # Write job metadata to DynamoDB
    item = {
        "PK": f"JOB#{job_id}",
        "SK": "META",
        "jobId": job_id,
        "jobType": job_type,
        "schedule": schedule,
        "scheduleName": schedule_name,
        "description": description,
        "params": params,
        "state": "ENABLED",
        "createdAt": now,
        "nextRunAt": now,  # Approximate; real next-run is managed by EventBridge Scheduler
    }
    table.put_item(Item=item)

    return _response(
        201,
        {
            "jobId": job_id,
            "jobType": job_type,
            "schedule": schedule,
            "params": params,
            "state": "ENABLED",
            "createdAt": now,
            "nextRunAt": now,
        },
    )


# ─── DELETE /scheduler/jobs/{jobId} ───────────────────────────
def _delete_job(job_id):
    """Delete a scheduled job: remove DynamoDB record + EventBridge Scheduler schedule."""
    if not job_id:
        return _error(400, "VALIDATION_ERROR", "jobId is required")

    # Look up the job
    result = table.get_item(Key={"PK": f"JOB#{job_id}", "SK": "META"})
    item = result.get("Item")

    if not item:
        return _error(404, "NOT_FOUND", f"Job {job_id} not found")

    # Delete EventBridge Scheduler schedule
    schedule_name = item.get("scheduleName", "")
    if schedule_name:
        try:
            scheduler_client.delete_schedule(Name=schedule_name)
        except scheduler_client.exceptions.ResourceNotFoundException:
            pass  # Already deleted

    # Delete from DynamoDB
    table.delete_item(Key={"PK": f"JOB#{job_id}", "SK": "META"})

    return _response(
        200,
        {
            "jobId": job_id,
            "deleted": True,
            "deletedAt": _now_iso(),
        },
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. Job Executor (EventBridge Scheduler → Lambda)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def job_executor_handler(event, context):
    """
    Invoked by EventBridge Scheduler. Publishes the appropriate event
    to the kismet-events bus so target services can react.
    """
    job_type = event.get("jobType", "unknown")
    job_id = event.get("jobId")
    params = event.get("params", {})

    job_config = JOB_EVENT_MAP.get(job_type)
    if not job_config:
        print(f"Unknown job type: {job_type}")
        return {"statusCode": 400, "body": f"Unknown job type: {job_type}"}

    now = _now_iso()

    # Publish event to EventBridge for downstream consumers
    events_client.put_events(
        Entries=[
            {
                "Source": job_config["source"],
                "DetailType": job_config["detail_type"],
                "Detail": json.dumps(
                    {
                        "jobType": job_type,
                        "jobId": job_id or "built-in",
                        "params": params,
                        "triggeredAt": now,
                    }
                ),
                "EventBusName": EVENT_BUS_NAME,
            }
        ]
    )

    # Update lastRunAt in DynamoDB if we have a job ID
    if job_id:
        try:
            table.update_item(
                Key={"PK": f"JOB#{job_id}", "SK": "META"},
                UpdateExpression="SET lastRunAt = :ts",
                ExpressionAttributeValues={":ts": now},
            )
        except Exception as e:
            print(f"Failed to update lastRunAt for {job_id}: {e}")

    print(f"Executed job: {job_type} at {now}")
    return {"statusCode": 200}
