import aws_cdk as cdk
from constructs import Construct
from aws_cdk import (
    Duration,
    RemovalPolicy,
    aws_dynamodb as dynamodb,
    aws_events as events,
    aws_events_targets as targets,
    aws_lambda as lambda_,
    aws_apigateway as apigateway,
    aws_iam as iam,
    aws_logs as logs,
    aws_scheduler as scheduler,
)

from stacks.shared_stack import SharedStack
from kismet_constructs.kismet_service import KismetService


class Domain5Stack(cdk.Stack):
    """
    Domain 5 — Notifications & Engagement
    Owners: Nili (Push Notification, Email), Xiaoyuan (Event Bus, Scheduler)
    """

    def __init__(self, scope: Construct, construct_id: str, *, shared: SharedStack, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        event_bus = events.EventBus.from_event_bus_name(
            self,
            "ImportedEventBus",
            "kismet-events",
        )

        imported_api = apigateway.RestApi.from_rest_api_attributes(
            self,
            "ImportedSharedApi",
            rest_api_id=shared.api.rest_api_id,
            root_resource_id=shared.api.rest_api_root_resource_id,
        )

        # ══════════════════════════════════════════════════════════════════════
        # Nili's services (standard KismetService pattern)
        # ══════════════════════════════════════════════════════════════════════

        # ── Push Notification Service ─────────────────────────────────────────
        KismetService(
            self,
            "PushNotificationService",
            service_name="push-notification",
            code_path="../services/domain-5-notifications/push-notification-service",
            handler="lambda_function.handler",
            tables=[
                {
                    "table_name": "kismet-notifications",
                    "pk": {"name": "PK", "type": "S"},
                    "sk": {"name": "SK", "type": "S"},
                },
                {
                    "table_name": "kismet-device-tokens",
                    "pk": {"name": "PK", "type": "S"},
                    "sk": {"name": "SK", "type": "S"},
                },
            ],
            routes=[
                {"method": "POST", "path": "/notifications/register", "auth": True},
                {"method": "GET", "path": "/notifications", "auth": True},
                {"method": "PUT", "path": "/notifications/{notificationId}/read", "auth": True},
                {"method": "GET", "path": "/notifications/unread-count", "auth": True},
            ],
            consume_events=["match.created", "message.sent"],
            publish_events=False,
            extra_policies=[
                iam.PolicyStatement(
                    actions=["sns:CreatePlatformEndpoint", "sns:Publish"],
                    resources=["*"],
                ),
            ],
            environment={
                "NOTIFICATIONS_TABLE": "kismet-notifications",
                "DEVICE_TOKENS_TABLE": "kismet-device-tokens",
            },
            api=imported_api,
            authorizer=shared.authorizer,
            event_bus=event_bus,
        )

        # ── Email Service ─────────────────────────────────────────────────────
        KismetService(
            self,
            "EmailService",
            service_name="email",
            code_path="../services/domain-5-notifications/email-service",
            handler="lambda_function.handler",
            tables=[
                {
                    "table_name": "kismet-email-preferences",
                    "pk": {"name": "PK", "type": "S"},
                    "sk": {"name": "SK", "type": "S"},
                },
            ],
            routes=[
                {"method": "GET", "path": "/email/preferences", "auth": True},
                {"method": "PUT", "path": "/email/preferences", "auth": True},
            ],
            consume_events=["user.created", "match.created", "user.reported", "scheduler.weekly_digest"],
            publish_events=False,
            extra_policies=[
                iam.PolicyStatement(
                    actions=["ses:SendEmail"],
                    resources=["*"],
                ),
            ],
            environment={
                "PREFERENCES_TABLE": "kismet-email-preferences",
                "SENDER_EMAIL": "noreply@kismet.app",
                "ADMIN_EMAIL": "admin@kismet.app",
            },
            api=imported_api,
            authorizer=shared.authorizer,
            event_bus=event_bus,
        )

        # ══════════════════════════════════════════════════════════════════════
        # Xiaoyuan's services (raw CDK — multiple Lambdas + special resources)
        # ══════════════════════════════════════════════════════════════════════

        # ── Event Bus Service ─────────────────────────────────────────────────
        # Central event routing: catch-all logger + admin API for debugging

        # DynamoDB: kismet-event-log
        event_log_table = dynamodb.Table(
            self,
            "EventLogTable",
            table_name="kismet-event-log",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        event_log_table.add_global_secondary_index(
            index_name="source-timestamp-index",
            partition_key=dynamodb.Attribute(name="source", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="timestamp", type=dynamodb.AttributeType.STRING),
        )

        event_bus_code = lambda_.Code.from_asset(
            "../services/domain-5-notifications/event-bus-service"
        )

        event_bus_env = {
            "EVENT_LOG_TABLE": event_log_table.table_name,
            "EVENT_BUS_NAME": event_bus.event_bus_name,
            "ENVIRONMENT": "dev",
        }

        # Lambda 1: Catch-All Logger (EventBridge → DynamoDB)
        catch_all_fn = lambda_.Function(
            self,
            "EventBusCatchAllFn",
            function_name="kismet-event-bus-logger",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda_function.catch_all_handler",
            code=event_bus_code,
            timeout=Duration.seconds(30),
            memory_size=256,
            environment=event_bus_env,
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        event_log_table.grant_read_write_data(catch_all_fn)

        # EventBridge catch-all rule: prefix match kismet.*
        events.Rule(
            self,
            "CatchAllRule",
            rule_name="kismet-catch-all-logger",
            event_bus=event_bus,
            event_pattern=events.EventPattern(
                source=events.Match.prefix("kismet."),
            ),
            targets=[targets.LambdaFunction(catch_all_fn)],
        )

        # Lambda 2: Admin API (API Gateway)
        admin_events_fn = lambda_.Function(
            self,
            "EventBusAdminFn",
            function_name="kismet-event-bus-admin",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda_function.admin_api_handler",
            code=event_bus_code,
            timeout=Duration.seconds(30),
            memory_size=256,
            environment=event_bus_env,
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        event_log_table.grant_read_write_data(admin_events_fn)
        event_bus.grant_put_events_to(admin_events_fn)  # for replay

        admin_events_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "events:ListRules",
                    "events:ListTargetsByRule",
                    "events:DescribeRule",
                ],
                resources=[
                    f"arn:aws:events:{self.region}:{self.account}:rule/{event_bus.event_bus_name}/*",
                    event_bus.event_bus_arn,
                ],
            )
        )

        # API Gateway: /events/*
        events_resource = imported_api.root.add_resource("events")
        events_integration = apigateway.LambdaIntegration(admin_events_fn)
        events_resource.add_resource("rules").add_method("GET", events_integration)
        events_resource.add_resource("history").add_method("GET", events_integration)
        events_resource.add_resource("replay").add_method("POST", events_integration)

        # ── Scheduler Service ─────────────────────────────────────────────────
        # Timed jobs: weekly digest, stale match cleanup, analytics, health check

        # DynamoDB: kismet-scheduler
        scheduler_table = dynamodb.Table(
            self,
            "SchedulerTable",
            table_name="kismet-scheduler",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        scheduler_code = lambda_.Code.from_asset(
            "../services/domain-5-notifications/scheduler-service"
        )

        # Lambda 3: Job Executor (EventBridge Scheduler → Lambda → EventBridge)
        executor_fn = lambda_.Function(
            self,
            "SchedulerExecutorFn",
            function_name="kismet-scheduler-executor",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda_function.job_executor_handler",
            code=scheduler_code,
            timeout=Duration.seconds(30),
            memory_size=256,
            environment={
                "SCHEDULER_TABLE": scheduler_table.table_name,
                "EVENT_BUS_NAME": event_bus.event_bus_name,
                "ENVIRONMENT": "dev",
            },
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        scheduler_table.grant_read_write_data(executor_fn)
        event_bus.grant_put_events_to(executor_fn)

        # IAM Role for EventBridge Scheduler to invoke executor Lambda
        scheduler_role = iam.Role(
            self,
            "SchedulerExecutionRole",
            role_name="kismet-scheduler-execution-role",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
        )

        executor_fn.grant_invoke(scheduler_role)

        # 4 built-in schedules
        built_in_schedules = [
            {
                "id": "WeeklyDigest",
                "name": "kismet-weekly-digest",
                "expression": "cron(0 9 ? * SUN *)",
                "description": "Send weekly digest email every Sunday at 9am UTC",
                "input": '{"jobType": "weekly_digest"}',
            },
            {
                "id": "StaleMatchCleanup",
                "name": "kismet-stale-match-cleanup",
                "expression": "rate(1 day)",
                "description": "Archive matches with no messages after 30 days",
                "input": '{"jobType": "stale_match_cleanup"}',
            },
            {
                "id": "AnalyticsAggregation",
                "name": "kismet-analytics-aggregation",
                "expression": "rate(1 hour)",
                "description": "Trigger Activity Logger to flush buffered analytics data",
                "input": '{"jobType": "analytics_aggregation"}',
            },
            {
                "id": "HealthCheck",
                "name": "kismet-health-check",
                "expression": "rate(5 minutes)",
                "description": "Trigger Health Monitor to check all services",
                "input": '{"jobType": "health_check"}',
            },
        ]

        for sched in built_in_schedules:
            scheduler.CfnSchedule(
                self,
                sched["id"],
                name=sched["name"],
                description=sched["description"],
                schedule_expression=sched["expression"],
                flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(
                    mode="OFF",
                ),
                state="ENABLED",
                target=scheduler.CfnSchedule.TargetProperty(
                    arn=executor_fn.function_arn,
                    role_arn=scheduler_role.role_arn,
                    input=sched["input"],
                ),
            )

        # Lambda 4: Scheduler Admin API (API Gateway)
        admin_sched_fn = lambda_.Function(
            self,
            "SchedulerAdminFn",
            function_name="kismet-scheduler-admin",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda_function.admin_api_handler",
            code=scheduler_code,
            timeout=Duration.seconds(30),
            memory_size=256,
            environment={
                "SCHEDULER_TABLE": scheduler_table.table_name,
                "EVENT_BUS_NAME": event_bus.event_bus_name,
                "ENVIRONMENT": "dev",
                "JOB_EXECUTOR_ARN": executor_fn.function_arn,
                "SCHEDULER_ROLE_ARN": scheduler_role.role_arn,
            },
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        scheduler_table.grant_read_write_data(admin_sched_fn)

        admin_sched_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "scheduler:CreateSchedule",
                    "scheduler:DeleteSchedule",
                    "scheduler:GetSchedule",
                    "scheduler:ListSchedules",
                    "scheduler:UpdateSchedule",
                ],
                resources=[f"arn:aws:scheduler:{self.region}:{self.account}:schedule/default/kismet-*"],
            )
        )

        admin_sched_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["iam:PassRole"],
                resources=[scheduler_role.role_arn],
            )
        )

        # API Gateway: /scheduler/jobs/*
        scheduler_resource = imported_api.root.add_resource("scheduler")
        jobs_resource = scheduler_resource.add_resource("jobs")
        sched_integration = apigateway.LambdaIntegration(admin_sched_fn)
        jobs_resource.add_method("GET", sched_integration)
        jobs_resource.add_method("POST", sched_integration)
        jobs_resource.add_resource("{jobId}").add_method("DELETE", sched_integration)

        # ── Outputs ───────────────────────────────────────────────────────────
        cdk.CfnOutput(self, "CatchAllLoggerArn", value=catch_all_fn.function_arn)
        cdk.CfnOutput(self, "EventLogTableName", value=event_log_table.table_name)
        cdk.CfnOutput(self, "SchedulerExecutorArn", value=executor_fn.function_arn)
        cdk.CfnOutput(self, "SchedulerTableName", value=scheduler_table.table_name)
