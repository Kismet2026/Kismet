import aws_cdk as cdk
from constructs import Construct
from aws_cdk import aws_apigateway as apigateway, aws_iam as iam

from stacks.shared_stack import SharedStack
from kismet_constructs.kismet_service import KismetService


class Domain4Stack(cdk.Stack):
    """
    Domain 4 — Safety & Moderation
    Owners: Yue (Text Moderation, Image Moderation), Amber (Report, Rate Limiter)
    """

    def __init__(self, scope: Construct, construct_id: str, *, shared: SharedStack, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        text_moderation_table = "kismet-text-moderation-dev"
        image_moderation_table = "kismet-image-moderation-dev"
        photos_table_name = "kismet-photos-dev"
        imported_api = apigateway.RestApi.from_rest_api_attributes(
            self,
            "ImportedSharedApiForModeration",
            rest_api_id=shared.api.rest_api_id,
            root_resource_id=shared.api.rest_api_root_resource_id,
        )

        # ── Text Moderation (Yue) ──────────────────────────────────────────────
        KismetService(
            self,
            "TextModerationService",
            service_name="text-moderation",
            code_path="../services/domain-4-moderation/text-moderation-service",
            tables=[
                {
                    "table_name": text_moderation_table,
                    "pk": {"name": "contentId", "type": "S"},
                    "sk": {"name": "sk", "type": "S"},
                    "gsi": [
                        {
                            "name": "gsi1",
                            "pk": {"name": "gsi1pk", "type": "S"},
                            "sk": {"name": "gsi1sk", "type": "N"},
                        }
                    ],
                }
            ],
            routes=[
                {"method": "POST", "path": "/moderate/text", "auth": True},
                {"method": "GET", "path": "/moderate/text/history", "auth": True},
            ],
            consume_events=["message.sent"],
            publish_events=True,
            environment={
                "TEXT_MODERATION_TABLE_NAME": text_moderation_table,
                "EVENT_BUS_NAME": shared.event_bus.event_bus_name,
            },
            extra_policies=[
                iam.PolicyStatement(
                    actions=["comprehend:DetectToxicContent"],
                    resources=["*"],
                )
            ],
            api=imported_api,
            authorizer=shared.authorizer,
            event_bus=shared.event_bus,
        )

        # ── Image Moderation (Yue) ──────────────────────────────────────────────
        KismetService(
            self,
            "ImageModerationService",
            service_name="image-moderation",
            code_path="../services/domain-4-moderation/image-moderation-service",
            tables=[
                {
                    "table_name": image_moderation_table,
                    "pk": {"name": "photoId", "type": "S"},
                    "sk": {"name": "sk", "type": "S"},
                    "gsi": [
                        {
                            "name": "gsi1",
                            "pk": {"name": "gsi1pk", "type": "S"},
                            "sk": {"name": "gsi1sk", "type": "N"},
                        }
                    ],
                }
            ],
            routes=[
                {"method": "POST", "path": "/moderate/image", "auth": True},
                {"method": "GET", "path": "/moderate/image/history", "auth": True},
            ],
            consume_events=["photo.uploaded"],
            publish_events=True,
            environment={
                "IMAGE_MODERATION_TABLE_NAME": image_moderation_table,
                "PHOTO_S3_BUCKET": shared.photos_bucket.bucket_name,
                "EVENT_BUS_NAME": shared.event_bus.event_bus_name,
                "PHOTOS_TABLE_NAME": photos_table_name,
            },
            extra_policies=[
                iam.PolicyStatement(
                    actions=["rekognition:DetectModerationLabels"],
                    resources=["*"],
                ),
                iam.PolicyStatement(
                    actions=["s3:GetObject", "s3:HeadObject"],
                    resources=[
                        shared.photos_bucket.bucket_arn,
                        f"{shared.photos_bucket.bucket_arn}/*",
                    ],
                ),
                iam.PolicyStatement(
                    actions=["dynamodb:UpdateItem"],
                    resources=[
                        f"arn:aws:dynamodb:{self.region}:{self.account}:table/{photos_table_name}",
                        f"arn:aws:dynamodb:{self.region}:{self.account}:table/{photos_table_name}/index/*",
                    ],
                ),
            ],
            api=imported_api,
            authorizer=shared.authorizer,
            event_bus=shared.event_bus,
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
                            "sk": {"name": "createdAt", "type": "S"},
                        },
                        {
                            "name": "status",
                            "pk": {"name": "status", "type": "S"},
                            "sk": {"name": "createdAt", "type": "S"},
                        },
                    ],
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
                    resources=["*"],
                )
            ],
            api=imported_api,
            authorizer=shared.authorizer,
            event_bus=shared.event_bus,
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
            api=imported_api,
            authorizer=shared.authorizer,
        )
