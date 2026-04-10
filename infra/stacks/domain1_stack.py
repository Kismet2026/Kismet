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
            handler="lambda_function.lambda_handler",
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
            handler="lambda_function.lambda_handler",
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
            },
            api=imported_api,
            authorizer=shared.authorizer,
            event_bus=event_bus,
        )

        # ── Email Verification Service (Quinn/KS) ────────────────────────────
        # Send verification code via SES, confirm code, update Cognito
        email_verify_svc = KismetService(
            self,
            "EmailVerificationService",
            service_name="email-verification",
            code_path="../services/domain-1-identity/email-verification-service",
            handler="lambda_function.lambda_handler",
            tables=[
                {
                    "table_name": "kismet-verifications",
                    "pk": {"name": "PK", "type": "S"},
                    "sk": {"name": "SK", "type": "S"},
                }
            ],
            routes=[
                {"method": "POST", "path": "/verify/send", "auth": True},
                {"method": "POST", "path": "/verify/confirm", "auth": True},
                {"method": "GET", "path": "/verify/status", "auth": True},
            ],
            environment={
                "COGNITO_USER_POOL_ID": shared.user_pool.user_pool_id,
                "VERIFICATIONS_TABLE_NAME": "kismet-verifications",
                "SES_SOURCE_EMAIL": "noreply@university.edu",  # TODO: update before deploy
            },
            extra_policies=[
                # SES for sending verification emails
                iam.PolicyStatement(
                    actions=["ses:SendEmail", "ses:SendRawEmail"],
                    resources=["*"],
                ),
                # Cognito for updating email_verified attribute
                iam.PolicyStatement(
                    actions=[
                        "cognito-idp:AdminGetUser",
                        "cognito-idp:AdminUpdateUserAttributes",
                    ],
                    resources=[shared.user_pool.user_pool_arn],
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
            handler="lambda_function.lambda_handler",
            tables=[
                {
                    "table_name": "kismet-photos",
                    "pk": {"name": "PK", "type": "S"},
                    "sk": {"name": "SK", "type": "S"},
                }
            ],
            routes=[
                {"method": "POST", "path": "/photos/upload", "auth": True},
                {"method": "GET", "path": "/photos/{identifier}", "auth": True},
                {"method": "DELETE", "path": "/photos/{identifier}", "auth": True},
                {"method": "PUT", "path": "/photos/{photoId}/primary", "auth": True},
            ],
            publish_events=True,
            environment={
                "PHOTOS_TABLE_NAME": "kismet-photos",
                "PHOTOS_BUCKET_NAME": shared.photos_bucket.bucket_name,
                "PHOTOS_CDN_BASE_URL": "",  # TODO: add CloudFront URL when available
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
