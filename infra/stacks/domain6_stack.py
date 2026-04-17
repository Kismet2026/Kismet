import aws_cdk as cdk
from constructs import Construct
from aws_cdk import (
    aws_apigateway as apigateway,
    aws_events as events,
    aws_iam as iam,
    aws_kinesisfirehose as firehose,
    aws_s3 as s3,
    aws_sns as sns,
)

from stacks.shared_stack import SharedStack
from kismet_constructs.kismet_service import KismetService, synth_stage_redeploy


class Domain6Stack(cdk.Stack):
    """
    Domain 6 — Analytics & Admin
    Owners: Jessica (Activity Logger, Analytics Pipeline), Lingyun (Admin Dashboard, Health Monitor)
    """

    def __init__(self, scope: Construct, construct_id: str, *, shared: SharedStack, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        event_bus = events.EventBus.from_event_bus_name(
            self,
            "ImportedEventBus",
            "kismet-events",
        )
        activity_stream = shared.activity_stream
        analytics_bucket = shared.analytics_bucket
        health_alerts_topic = sns.Topic.from_topic_arn(
            self,
            "ImportedHealthAlertsTopic",
            f"arn:aws:sns:{self.region}:{self.account}:kismet-health-alerts",
        )
        # Import the API into this stack so that API Gateway resources (methods,
        # integrations) live here rather than in KismetShared.  This prevents
        # the circular cross-stack reference that would otherwise arise from
        # SharedStack's deployment referencing Domain 6 Lambda ARNs.
        imported_api = apigateway.RestApi.from_rest_api_attributes(
            self,
            "ImportedSharedApi",
            rest_api_id=shared.api.rest_api_id,
            root_resource_id=shared.api.rest_api_root_resource_id,
        )

        # ── Kinesis Firehose → S3 ─────────────────────────────────────────────
        if activity_stream is not None:
            firehose_role = iam.Role(
                self,
                "FirehoseRole",
                assumed_by=iam.ServicePrincipal("firehose.amazonaws.com"),
                inline_policies={
                    "FirehosePolicy": iam.PolicyDocument(
                        statements=[
                            iam.PolicyStatement(
                                actions=[
                                    "s3:GetBucketLocation",
                                    "s3:ListBucket",
                                    "s3:ListBucketMultipartUploads",
                                ],
                                resources=[analytics_bucket.bucket_arn],
                            ),
                            iam.PolicyStatement(
                                actions=[
                                    "s3:PutObject",
                                    "s3:PutObjectAcl",
                                    "s3:AbortMultipartUpload",
                                    "s3:GetObject",
                                ],
                                resources=[f"{analytics_bucket.bucket_arn}/*"],
                            ),
                            iam.PolicyStatement(
                                actions=[
                                    "kinesis:GetRecords",
                                    "kinesis:GetShardIterator",
                                    "kinesis:DescribeStream",
                                    "kinesis:ListShards",
                                ],
                                resources=[activity_stream.stream_arn],
                            ),
                        ]
                    )
                },
            )

            firehose.CfnDeliveryStream(
                self,
                "ActivityFirehose",
                delivery_stream_name="kismet-activity-firehose",
                delivery_stream_type="KinesisStreamAsSource",
                kinesis_stream_source_configuration=firehose.CfnDeliveryStream.KinesisStreamSourceConfigurationProperty(
                    kinesis_stream_arn=activity_stream.stream_arn,
                    role_arn=firehose_role.role_arn,
                ),
                s3_destination_configuration=firehose.CfnDeliveryStream.S3DestinationConfigurationProperty(
                    bucket_arn=analytics_bucket.bucket_arn,
                    role_arn=firehose_role.role_arn,
                    prefix="events/",
                    buffering_hints=firehose.CfnDeliveryStream.BufferingHintsProperty(
                        interval_in_seconds=60,
                        size_in_m_bs=5,
                    ),
                ),
            )

        # ── Activity Logger (Jessica) ─────────────────────────────────────────
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
            extra_policies=[],
            environment=(
                {"ACTIVITY_LOG_TABLE": "kismet-activity-log", "KINESIS_STREAM_NAME": activity_stream.stream_name}
                if activity_stream is not None
                else {"ACTIVITY_LOG_TABLE": "kismet-activity-log"}
            ),
            api=imported_api,
            authorizer=shared.authorizer,
            event_bus=event_bus,
        )

        # ── Analytics Pipeline (Jessica) ──────────────────────────────────────
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
                        analytics_bucket.bucket_arn,
                        f"{analytics_bucket.bucket_arn}/*",
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
                "ANALYTICS_BUCKET": analytics_bucket.bucket_name,
                "ATHENA_DATABASE": "kismet_analytics",
                "S3_DATA_PREFIX": "events",
            },
            api=imported_api,
            authorizer=shared.authorizer,
            event_bus=event_bus,
        )

        # ── Admin Dashboard (Lingyun) ──────────────────────────────────────────
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
            api=imported_api,
            authorizer=shared.authorizer,
            event_bus=event_bus,
        )

        # ── Health Monitor (Lingyun) ───────────────────────────────────────────
        KismetService(
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
                {"method": "GET", "path": "/health", "auth": False},
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
                    resources=[health_alerts_topic.topic_arn],
                ),
            ],
            environment={
                "HEALTH_ALERTS_TOPIC_ARN": health_alerts_topic.topic_arn,
            },
            api=imported_api,
            authorizer=shared.authorizer,
            event_bus=event_bus,
        )

        # Force API Gateway dev stage to redeploy when routes change (issue #118)
        synth_stage_redeploy(self, api=imported_api)
