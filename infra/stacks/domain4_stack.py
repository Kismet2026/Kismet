import aws_cdk as cdk
from constructs import Construct
from aws_cdk import aws_events as events, aws_iam as iam

from stacks.shared_stack import SharedStack
from kismet_constructs.kismet_service import KismetService


class Domain4Stack(cdk.Stack):
    """
    Domain 4 — Safety & Moderation
    Owners: Yue (Text Moderation), KS (Image Moderation), Amber (Report, Rate Limiter)
    """

    def __init__(self, scope: Construct, construct_id: str, *, shared: SharedStack, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        event_bus = events.EventBus.from_event_bus_name(
            self,
            "ImportedEventBus",
            "kismet-events",
        )

        # ── Text Moderation (Yue) ──────────────────────────────────────────────
        KismetService(
            self,
            "TextModerationService",
            service_name="text-moderation",
            code_path="../services/domain-4-moderation/text-moderation-service",
            tables=[],
            routes=[],
            consume_events=["message.sent"],
            publish_events=True,
            extra_policies=[
                iam.PolicyStatement(
                    actions=["comprehend:DetectToxicContent"],
                    resources=["*"]
                )
            ],
            api=shared.api,
            authorizer=shared.authorizer,
            event_bus=event_bus,
        )

        # ── Image Moderation (KS) ──────────────────────────────────────────────
        KismetService(
            self,
            "ImageModerationService",
            service_name="image-moderation",
            code_path="../services/domain-4-moderation/image-moderation-service",
            tables=[],
            routes=[],
            consume_events=["photo.uploaded"],
            publish_events=True,
            extra_policies=[
                iam.PolicyStatement(
                    actions=["rekognition:DetectModerationLabels"],
                    resources=["*"]
                )
            ],
            api=shared.api,
            authorizer=shared.authorizer,
            event_bus=event_bus,
        )

        # ── Report Service (Amber) ─────────────────────────────────────────────
        KismetService(
            self,
            "ReportService",
            service_name="report",
            code_path="../services/domain-4-moderation/report-service",
            handler="index.handler",
            tables=[
                {
                    "table_name": "kismet-reports",
                    "pk": {"name": "pk", "type": "S"},
                    "sk": {"name": "sk", "type": "S"},
                    "gsi": [
                        {
                            "name": "reportedUserId",
                            "pk": {"name": "reportedUserId", "type": "S"},
                            "sk": {"name": "createdAt", "type": "S"}
                        },
                        {
                            "name": "status",
                            "pk": {"name": "status", "type": "S"},
                            "sk": {"name": "createdAt", "type": "S"}
                        }
                    ]
                }
            ],
            routes=[
                {"method": "POST", "path": "/reports", "auth": True},
                {"method": "GET", "path": "/reports", "auth": True},
                {"method": "GET", "path": "/reports/{reportId}", "auth": True},
                {"method": "PUT", "path": "/reports/{reportId}/resolve", "auth": True},
            ],
            consume_events=[],
            publish_events=True,  # Publishes user.reported
            extra_policies=[
                iam.PolicyStatement(
                    actions=["ses:SendEmail"],
                    resources=["*"]
                )
            ],
            api=shared.api,
            authorizer=shared.authorizer,
            event_bus=event_bus,
        )

        # ── Rate Limiter Service (Amber) ───────────────────────────────────────
        # Note: Uses ElastiCache (Redis) for storage instead of DynamoDB.
        # Redis cluster provisioning is typically handled in shared infra, 
        # so no DynamoDB tables are created here.
        KismetService(
            self,
            "RateLimiterService",
            service_name="rate-limiter",
            code_path="../services/domain-4-moderation/rate-limiter-service",
            handler="index.handler",
            tables=[],  # Uses ElastiCache
            routes=[
                {"method": "GET", "path": "/ratelimit/status/{userId}", "auth": True},
                {"method": "POST", "path": "/ratelimit/reset/{userId}", "auth": True},
            ],
            consume_events=[],
            publish_events=False,
            api=shared.api,
            authorizer=shared.authorizer,
            event_bus=event_bus,
        )
