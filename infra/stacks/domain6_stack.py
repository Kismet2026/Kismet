import aws_cdk as cdk
from constructs import Construct
from aws_cdk import aws_iam as iam

from stacks.shared_stack import SharedStack
from kismet_constructs.kismet_service import KismetService


class Domain6Stack(cdk.Stack):
    """
    Domain 6 — Analytics & Admin
    Owners: Jessica (Activity Logger, Analytics Pipeline), Lingyun (Admin Dashboard, Health Monitor)
    """

    def __init__(self, scope: Construct, construct_id: str, *, shared: SharedStack, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        # ── Activity Logger (Jessica) ─────────────────────────────────────────
        # Catch-all EventBridge subscriber → writes every event to Kinesis stream
        KismetService(
            self,
            "ActivityLoggerService",
            service_name="activity-logger",
            code_path="../services/domain-6-analytics/activity-logger-service",
            tables=[
                {
                    "table_name": "kismet-activity-log",
                    "pk": {"name": "PK", "type": "S"},
                    "sk": {"name": "SK", "type": "S"},
                }
            ],
            routes=[
                {
                    "method": "POST",
                    "path": "/analytics/log",
                    "auth": False,
                },
                {"method": "GET", "path": "/analytics/log/recent", "auth": True},
            ],
            consume_events=[
                "swipe.created",
                "match.created",
                "message.sent",
                "user.created",
                "profile.completed",
                "photo.uploaded",
                "content.flagged",
                "user.reported",
            ],
            publish_events=False,
            extra_policies=[
                iam.PolicyStatement(
                    actions=["kinesis:PutRecord", "kinesis:PutRecords"],
                    resources=[shared.activity_stream.stream_arn],
                )
            ],
            environment={
                "ACTIVITY_LOG_TABLE": "kismet-activity-log",
                "KINESIS_STREAM_NAME": shared.activity_stream.stream_name,
            },
            api=shared.api,
            authorizer=shared.authorizer,
            event_bus=shared.event_bus,
        )

        # ── Analytics Pipeline (Jessica) ──────────────────────────────────────
        # Reads from Kinesis Firehose → S3 → Athena
        # Note: Kinesis Firehose delivery stream is not created here —
        #       it is configured separately to read from kismet-activity-stream
        #       and deliver to the analytics S3 bucket.
        KismetService(
            self,
            "AnalyticsPipelineService",
            service_name="analytics-pipeline",
            code_path="../services/domain-6-analytics/analytics-pipeline-service",
            tables=[],
            routes=[
                {"method": "POST", "path": "/analytics/query", "auth": True},
                {"method": "GET", "path": "/analytics/query/{queryId}", "auth": True},
                {"method": "GET", "path": "/analytics/dashboard", "auth": True},
            ],
            consume_events=[],
            publish_events=False,
            extra_policies=[
                iam.PolicyStatement(
                    actions=[
                        "athena:StartQueryExecution",
                        "athena:GetQueryExecution",
                        "athena:GetQueryResults",
                    ],
                    resources=["*"],
                ),
                iam.PolicyStatement(
                    actions=[
                        "s3:GetObject",
                        "s3:PutObject",
                        "s3:ListBucket",
                        "s3:GetBucketLocation",
                    ],
                    resources=[
                        shared.analytics_bucket.bucket_arn,
                        f"{shared.analytics_bucket.bucket_arn}/*",
                    ],
                ),
                iam.PolicyStatement(
                    actions=[
                        "glue:GetDatabase",
                        "glue:GetTable",
                        "glue:CreateDatabase",
                        "glue:CreateTable",
                    ],
                    resources=["*"],
                ),
            ],
            environment={
                "ANALYTICS_BUCKET": shared.analytics_bucket.bucket_name,
                "ATHENA_DATABASE": "kismet_analytics",
                "S3_DATA_PREFIX": "events",
            },
            api=shared.api,
            authorizer=shared.authorizer,
            event_bus=shared.event_bus,
        )

        # ── Admin Dashboard (Lingyun) ──────────────────────────────────────────
        # Two DynamoDB tables: kismet-admin-stats and kismet-flagged-content
        # Also reads/writes kismet-profiles (domain-1) for user ban/unban/list
        KismetService(
            self,
            "AdminDashboardService",
            service_name="admin-dashboard",
            code_path="../services/domain-6-analytics/admin-dashboard-service",
            tables=[
                {
                    "table_name": "kismet-admin-stats",
                    "pk": {"name": "PK", "type": "S"},
                    "sk": {"name": "SK", "type": "S"},
                },
                {
                    "table_name": "kismet-flagged-content",
                    "pk": {"name": "PK", "type": "S"},
                    "sk": {"name": "SK", "type": "S"},
                },
            ],
            routes=[
                {"method": "GET", "path": "/admin/stats", "auth": True},
                {"method": "GET", "path": "/admin/flagged-content", "auth": True},
                {
                    "method": "PUT",
                    "path": "/admin/flagged-content/{contentId}/resolve",
                    "auth": True,
                },
                {"method": "GET", "path": "/admin/users", "auth": True},
                {"method": "PUT", "path": "/admin/users/{userId}/ban", "auth": True},
                {"method": "PUT", "path": "/admin/users/{userId}/unban", "auth": True},
            ],
            consume_events=["content.flagged", "user.reported"],
            publish_events=False,
            extra_policies=[
                iam.PolicyStatement(
                    actions=[
                        "dynamodb:GetItem",
                        "dynamodb:UpdateItem",
                        "dynamodb:Scan",
                    ],
                    resources=[
                        f"arn:aws:dynamodb:{self.region}:{self.account}:table/kismet-profiles",
                    ],
                )
            ],
            api=shared.api,
            authorizer=shared.authorizer,
            event_bus=shared.event_bus,
        )

        # ── Health Monitor (Lingyun) ───────────────────────────────────────────
        health_monitor = KismetService(
            self,
            "HealthMonitorService",
            service_name="health-monitor",
            code_path="../services/domain-6-analytics/health-monitor-service",
            tables=[
                {
                    "table_name": "kismet-health-history",
                    "pk": {"name": "PK", "type": "S"},
                    "sk": {"name": "SK", "type": "S"},
                }
            ],
            routes=[
                {"method": "GET", "path": "/health", "auth": False},  # public
                {"method": "GET", "path": "/health/{serviceName}", "auth": True},
                {"method": "GET", "path": "/health/alarms", "auth": True},
                {"method": "POST", "path": "/health/check", "auth": True},
            ],
            consume_events=[],
            publish_events=False,
            extra_policies=[
                iam.PolicyStatement(
                    actions=["cloudwatch:GetMetricData", "cloudwatch:DescribeAlarms"],
                    resources=["*"],
                ),
                iam.PolicyStatement(
                    actions=["sns:Publish"],
                    resources=[shared.health_alerts_topic.topic_arn],
                ),
            ],
            environment={
                "HEALTH_ALERTS_TOPIC_ARN": shared.health_alerts_topic.topic_arn,
            },
            api=shared.api,
            authorizer=shared.authorizer,
            event_bus=shared.event_bus,
        )
