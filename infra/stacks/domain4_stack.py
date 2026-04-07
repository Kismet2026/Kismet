import aws_cdk as cdk
from constructs import Construct
from aws_cdk import (
    aws_iam as iam,
    aws_ec2 as ec2,
    aws_elasticache as elasticache
)

from stacks.shared_stack import SharedStack
from kismet_constructs.kismet_service import KismetService


class Domain4Stack(cdk.Stack):
    """
    Domain 4 — Safety & Moderation
    Owners: Yue (Text Moderation), KS (Image Moderation), Amber (Report, Rate Limiter)
    """

    def __init__(self, scope: Construct, construct_id: str, *, shared: SharedStack, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

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
            event_bus=shared.event_bus,
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
            event_bus=shared.event_bus,
        )

        # ── Rate Limiter Service (Amber) ───────────────────────────────────────
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
            api=shared.api,
            authorizer=shared.authorizer,
            event_bus=shared.event_bus,
            vpc=vpc,
            security_groups=[lambda_sg],
            environment={
                "REDIS_URL": f"redis://{redis_cluster.attr_redis_endpoint_address}:{redis_cluster.attr_redis_endpoint_port}"
            }
        )
