import aws_cdk as cdk
from constructs import Construct
from aws_cdk import aws_iam as iam

from stacks.shared_stack import SharedStack
from kismet_constructs.kismet_service import KismetService


class Domain2Stack(cdk.Stack):
    """
    Domain 2 — Discovery & Matching
    Owner: Qinyuan (Discovery, Swipe, Match, Recommendation, BaZi)
    """

    def __init__(self, scope: Construct, construct_id: str, *, shared: SharedStack, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        # ── Swipe Service ─────────────────────────────────────────────────────
        swipe_svc = KismetService(
            self,
            "SwipeService",
            service_name="swipe",
            code_path="../services/domain-2-discovery/swipe-service",
            tables=[
                {
                    "table_name": "kismet-swipes",
                    "pk": {"name": "userId", "type": "S"},
                    "sk": {"name": "targetUserId", "type": "S"},
                }
            ],
            routes=[
                {"method": "POST", "path": "/swipe", "auth": True},
                {"method": "GET", "path": "/swipe/history", "auth": True},
            ],
            publish_events=True,
            api=shared.api,
            authorizer=shared.authorizer,
            event_bus=shared.event_bus,
        )

        # ── Match Service ─────────────────────────────────────────────────────
        match_svc = KismetService(
            self,
            "MatchService",
            service_name="match",
            code_path="../services/domain-2-discovery/match-service",
            tables=[
                {
                    "table_name": "kismet-matches",
                    "pk": {"name": "PK", "type": "S"},
                    "sk": {"name": "SK", "type": "S"},
                }
            ],
            routes=[
                {"method": "GET", "path": "/matches", "auth": True},
                {"method": "GET", "path": "/matches/{matchId}", "auth": True},
                {"method": "DELETE", "path": "/matches/{matchId}", "auth": True},
            ],
            consume_events=["swipe.created"],
            publish_events=True,
            environment={
                "SWIPE_TABLE_NAME": "kismet-swipes",
            },
            extra_policies=[
                # Match Service needs to read the swipe table to check mutual likes
                iam.PolicyStatement(
                    actions=["dynamodb:GetItem", "dynamodb:Query"],
                    resources=[
                        f"arn:aws:dynamodb:{self.region}:{self.account}:table/kismet-swipes",
                    ],
                ),
            ],
            api=shared.api,
            authorizer=shared.authorizer,
            event_bus=shared.event_bus,
        )

        # ── Discovery Service ─────────────────────────────────────────────────
        KismetService(
            self,
            "DiscoveryService",
            service_name="discovery",
            code_path="../services/domain-2-discovery/discovery-service",
            tables=[
                {
                    "table_name": "kismet-discovery",
                    "pk": {"name": "PK", "type": "S"},
                    "sk": {"name": "SK", "type": "S"},
                }
            ],
            routes=[
                {"method": "GET", "path": "/discovery", "auth": True},
            ],
            consume_events=["profile.completed"],
            api=shared.api,
            authorizer=shared.authorizer,
            event_bus=shared.event_bus,
        )

        # ── Recommendation Service ────────────────────────────────────────────
        KismetService(
            self,
            "RecommendationService",
            service_name="recommendation",
            code_path="../services/domain-2-discovery/recommendation-service",
            tables=[
                {
                    "table_name": "kismet-recommendations",
                    "pk": {"name": "PK", "type": "S"},
                    "sk": {"name": "SK", "type": "S"},
                }
            ],
            routes=[
                {"method": "GET", "path": "/recommend", "auth": True},
                {"method": "POST", "path": "/recommend/refresh", "auth": True},
            ],
            consume_events=["profile.completed", "swipe.created"],
            environment={
                "DISCOVERY_TABLE_NAME": "kismet-discovery",
            },
            extra_policies=[
                # Recommendation needs to read discovery table for candidate profiles
                iam.PolicyStatement(
                    actions=["dynamodb:Scan", "dynamodb:Query", "dynamodb:GetItem"],
                    resources=[
                        f"arn:aws:dynamodb:{self.region}:{self.account}:table/kismet-discovery",
                    ],
                ),
            ],
            api=shared.api,
            authorizer=shared.authorizer,
            event_bus=shared.event_bus,
        )

        # ── BaZi Service ─────────────────────────────────────────────────────
        # Stateless service — no DynamoDB table, no events
        KismetService(
            self,
            "BaZiService",
            service_name="bazi",
            code_path="../services/domain-2-discovery/bazi-service",
            routes=[
                {"method": "POST", "path": "/bazi/compatibility", "auth": True},
                {"method": "GET", "path": "/bazi/profile/{userId}", "auth": True},
            ],
            api=shared.api,
            authorizer=shared.authorizer,
            event_bus=shared.event_bus,
        )
