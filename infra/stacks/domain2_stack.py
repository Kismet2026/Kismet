import aws_cdk as cdk
from constructs import Construct
from aws_cdk import aws_events as events, aws_iam as iam, aws_apigateway as apigateway

from stacks.shared_stack import SharedStack
from kismet_constructs.kismet_service import KismetService


class Domain2Stack(cdk.Stack):
    """
    Domain 2 — Discovery & Matching
    Owner: Qinyuan (Discovery, Swipe, Match, Recommendation, BaZi)
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
            api=imported_api,
            authorizer=shared.authorizer,
            event_bus=event_bus,
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
                "SWIPE_TABLE_NAME": swipe_svc.tables[0].table_name,
            },
            extra_policies=[
                # Match Service needs to read the swipe table to check mutual likes
                iam.PolicyStatement(
                    actions=["dynamodb:GetItem", "dynamodb:Query"],
                    resources=[swipe_svc.tables[0].table_arn],
                ),
            ],
            api=imported_api,
            authorizer=shared.authorizer,
            event_bus=event_bus,
        )

        # ── Discovery Service ─────────────────────────────────────────────────
        discovery_svc = KismetService(
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
            consume_events=["profile.completed", "profile.banned"],
            environment={
                "SWIPE_TABLE_NAME": swipe_svc.tables[0].table_name,
                "BAZI_API_URL": "https://match-date-nu.vercel.app/api/match",
                "BAZI_API_KEY": "ABC",  # TODO: replace with real key before deploy
            },
            extra_policies=[
                # Discovery needs to read swipe table to filter already-swiped candidates
                iam.PolicyStatement(
                    actions=["dynamodb:Query"],
                    resources=[swipe_svc.tables[0].table_arn],
                ),
            ],
            api=imported_api,
            authorizer=shared.authorizer,
            event_bus=event_bus,
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
                "DISCOVERY_TABLE_NAME": discovery_svc.tables[0].table_name,
                "SWIPE_TABLE_NAME": swipe_svc.tables[0].table_name,
            },
            extra_policies=[
                # Recommendation needs to read discovery table for candidate profiles + BaZi cache
                iam.PolicyStatement(
                    actions=["dynamodb:Scan", "dynamodb:Query", "dynamodb:GetItem", "dynamodb:BatchGetItem"],
                    resources=[discovery_svc.tables[0].table_arn],
                ),
                # Recommendation needs to read swipe table to exclude already-swiped candidates
                iam.PolicyStatement(
                    actions=["dynamodb:Query"],
                    resources=[swipe_svc.tables[0].table_arn],
                ),
            ],
            api=imported_api,
            authorizer=shared.authorizer,
            event_bus=event_bus,
        )

        # ── BaZi Service ─────────────────────────────────────────────────────
        # Stateless service — proxies to external BaZi API, no DynamoDB table
        KismetService(
            self,
            "BaZiService",
            service_name="bazi",
            code_path="../services/domain-2-discovery/bazi-service",
            routes=[
                {"method": "POST", "path": "/bazi/top-matches", "auth": True},
            ],
            environment={
                "BAZI_API_URL": "https://match-date-nu.vercel.app/api/match",
                "BAZI_API_KEY": "ABC",
            },
            api=imported_api,
            authorizer=shared.authorizer,
            event_bus=event_bus,
        )
