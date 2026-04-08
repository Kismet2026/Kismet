import aws_cdk as cdk
from constructs import Construct
from aws_cdk import (
    aws_iam as iam,
    aws_ec2 as ec2,
    aws_elasticache as elasticache,
    aws_apigateway as apigateway
)

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
            handler="lambda_function.handler",
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
            handler="lambda_function.handler",
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
            handler="lambda_function.handler",
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
        # Uses ElastiCache (Redis)
        vpc = ec2.Vpc(
            self,
            "RateLimiterVpc",
            max_azs=2,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Isolated",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
                )
            ]
        )

        redis_sg = ec2.SecurityGroup(
            self,
            "RedisSecurityGroup",
            vpc=vpc,
            description="Allow Lambda to access Redis"
        )
        
        lambda_sg = ec2.SecurityGroup(
            self,
            "RateLimiterLambdaSg",
            vpc=vpc,
            description="Security group for Rate Limiter Lambda"
        )
        
        redis_sg.add_ingress_rule(
            lambda_sg,
            ec2.Port.tcp(6379),
            "Allow Lambda to access Redis"
        )

        subnet_group = elasticache.CfnSubnetGroup(
            self,
            "RedisSubnetGroup",
            description="Subnet group for Redis",
            subnet_ids=vpc.select_subnets(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED).subnet_ids
        )

        redis_cluster = elasticache.CfnCacheCluster(
            self,
            "RateLimiterRedis",
            cache_node_type="cache.t3.micro",
            engine="redis",
            num_cache_nodes=1,
            vpc_security_group_ids=[redis_sg.security_group_id],
            cache_subnet_group_name=subnet_group.ref
        )
        redis_cluster.add_dependency(subnet_group)

        KismetService(
            self,
            "RateLimiterService",
            service_name="rate-limiter",
            code_path="../services/domain-4-moderation/rate-limiter-service",
            handler="lambda_function.handler",
            tables=[],  # Uses ElastiCache
            routes=[
                {"method": "GET", "path": "/ratelimit/status/{userId}", "auth": True},
                {"method": "POST", "path": "/ratelimit/reset/{userId}", "auth": True},
            ],
            consume_events=[],
            publish_events=False,
            api=imported_api,
            authorizer=shared.authorizer,
            event_bus=shared.event_bus,
            vpc=vpc,
            security_groups=[lambda_sg],
            environment={
                "REDIS_URL": f"redis://{redis_cluster.attr_redis_endpoint_address}:{redis_cluster.attr_redis_endpoint_port}"
            }
        )
