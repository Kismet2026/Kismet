import aws_cdk as cdk
from constructs import Construct
from aws_cdk import aws_events as events, aws_iam as iam, aws_apigateway as apigateway

from stacks.shared_stack import SharedStack
from kismet_constructs.kismet_service import KismetService


class Domain1Stack(cdk.Stack):
    """
    Domain 1 — Identity & Profile
    Owners: Quinn (Profile, Email Verification), KS (Auth, Photo)
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

        # ── Auth Service (KS) ─────────────────────────────────────────────────
        # signup, login, refresh, logout via Cognito
        auth_svc = KismetService(
            self,
            "AuthService",
            service_name="auth",
            code_path="../services/domain-1-identity/auth-service",
            tables=[
                {
                    "table_name": "kismet-users",
                    "pk": {"name": "PK", "type": "S"},
                    "sk": {"name": "SK", "type": "S"},
                }
            ],
            routes=[
                {"method": "POST", "path": "/auth/signup", "auth": False},
                {"method": "POST", "path": "/auth/login", "auth": False},
                {"method": "POST", "path": "/auth/refresh", "auth": False},
                {"method": "POST", "path": "/auth/logout", "auth": False},
            ],
            publish_events=True,
            environment={
                "COGNITO_USER_POOL_ID": shared.user_pool.user_pool_id,
                "COGNITO_APP_CLIENT_ID": shared.user_pool_client.user_pool_client_id,
                "USERS_TABLE_NAME": "kismet-users",
            },
            extra_policies=[
                # Auth needs Cognito admin operations for signup/login/refresh/logout
                iam.PolicyStatement(
                    actions=[
                        "cognito-idp:SignUp",
                        "cognito-idp:InitiateAuth",
                        "cognito-idp:RevokeToken",
                        "cognito-idp:AdminGetUser",
                    ],
                    resources=[shared.user_pool.user_pool_arn],
                ),
            ],
            api=imported_api,
            authorizer=shared.authorizer,
            event_bus=event_bus,
        )

        # ── Profile Service (Quinn) ───────────────────────────────────────────
        # CRUD for user profiles, publishes profile.completed
        profile_svc = KismetService(
            self,
            "ProfileService",
            service_name="profile",
            code_path="../services/domain-1-identity/profile-service",
            tables=[
                {
                    "table_name": "kismet-profiles",
                    "pk": {"name": "PK", "type": "S"},
                    "sk": {"name": "SK", "type": "S"},
                }
            ],
            routes=[
                {"method": "POST", "path": "/profiles", "auth": True},
                {"method": "GET", "path": "/profiles/{userId}", "auth": True},
                {"method": "PUT", "path": "/profiles/{userId}", "auth": True},
                {"method": "DELETE", "path": "/profiles/{userId}", "auth": True},
            ],
            publish_events=True,
            environment={
                "PROFILES_TABLE_NAME": "kismet-profiles",
                "DISCOVERY_TABLE_NAME": "kismet-discovery",
            },
            extra_policies=[
                iam.PolicyStatement(
                    actions=["dynamodb:DeleteItem", "dynamodb:UpdateItem"],
                    resources=["arn:aws:dynamodb:*:*:table/kismet-discovery"],
                ),
            ],
            api=imported_api,
            authorizer=shared.authorizer,
            event_bus=event_bus,
        )
        # ── Photo Service (KS) ───────────────────────────────────────────────
        # Upload (presigned URL), list, delete, set primary photo
        photo_svc = KismetService(
            self,
            "PhotoService",
            service_name="photo",
            code_path="../services/domain-1-identity/photo-service",
            tables=[
                {
                    "table_name": "kismet-photos",
                    "pk": {"name": "PK", "type": "S"},
                    "sk": {"name": "SK", "type": "S"},
                }
            ],
            routes=[
                {"method": "POST", "path": "/photos/upload", "auth": True},
                {"method": "GET", "path": "/users/{userId}/photos", "auth": True},
                {"method": "DELETE", "path": "/photos/{photoId}", "auth": True},
                {"method": "PUT", "path": "/photos/{photoId}/primary", "auth": True},
            ],
            publish_events=True,
            environment={
                "PHOTOS_TABLE_NAME": "kismet-photos",
                "PHOTOS_BUCKET_NAME": shared.photos_bucket.bucket_name,
                "PHOTOS_CDN_BASE_URL": f"https://{shared.photos_bucket.bucket_name}.s3.{self.region}.amazonaws.com",  # TODO: add CloudFront URL when available
            },
            extra_policies=[
                # S3 for presigned URL generation and object deletion
                iam.PolicyStatement(
                    actions=["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
                    resources=[f"{shared.photos_bucket.bucket_arn}/*"],
                ),
            ],
            api=imported_api,
            authorizer=shared.authorizer,
            event_bus=event_bus,
        )


