import aws_cdk as cdk
from constructs import Construct
from aws_cdk import (
    aws_cognito as cognito,
    aws_apigateway as apigateway,
    aws_events as events,
    aws_s3 as s3,
    aws_kinesis as kinesis,
    aws_sns as sns,
)

class SharedStack(cdk.Stack):
    """
    Shared infrastructure deployed once by PM.
    All domain stacks receive this as a dependency via `shared=`.

    Resources:
        Cognito UserPool + App Client
        API Gateway (REST) + Cognito Authorizer
        EventBridge Bus (kismet-events)
        S3: photos, analytics, frontend
        Kinesis Data Stream (kismet-activity-stream)
        SNS Topic (kismet-health-alerts)
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        # ── Cognito ───────────────────────────────────────────────────────────
        self.user_pool = cognito.UserPool(
            self,
            "UserPool",
            user_pool_name="kismet-user-pool",
            self_sign_up_enabled=True,
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_uppercase=False,
                require_symbols=False,
            ),
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        self.user_pool_client = self.user_pool.add_client(
            "WebClient",
            user_pool_client_name="kismet-web-client",
            auth_flows=cognito.AuthFlow(
                user_password=True,
                user_srp=True,
            ),
        )

        # ── API Gateway ───────────────────────────────────────────────────────
        self.api = apigateway.RestApi(
            self,
            "Api",
            rest_api_name="kismet-api",
            deploy_options=apigateway.StageOptions(stage_name="dev"),
            default_cors_preflight_options=apigateway.CorsOptions(
                allow_origins=apigateway.Cors.ALL_ORIGINS,
                allow_methods=apigateway.Cors.ALL_METHODS,
                allow_headers=["Content-Type", "Authorization"],
            ),
        )

        self.authorizer = apigateway.CognitoUserPoolsAuthorizer(
            self,
            "CognitoAuthorizer",
            cognito_user_pools=[self.user_pool],
        )

        # ── EventBridge ───────────────────────────────────────────────────────
        self.event_bus = events.EventBus(
            self,
            "EventBus",
            event_bus_name="kismet-events",
        )

        # ── S3 ────────────────────────────────────────────────────────────────
        self.photos_bucket = s3.Bucket(
            self,
            "PhotosBucket",
            bucket_name=f"kismet-photos-{self.account}-dev",
            cors=[
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.GET, s3.HttpMethods.PUT],
                    allowed_origins=["*"],
                    allowed_headers=["*"],
                )
            ],
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        self.analytics_bucket = s3.Bucket(
            self,
            "AnalyticsBucket",
            bucket_name=f"kismet-analytics-{self.account}-dev",
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        self.frontend_bucket = s3.Bucket(
            self,
            "FrontendBucket",
            bucket_name=f"kismet-frontend-{self.account}-dev",
            website_index_document="index.html",
            public_read_access=True,
            block_public_access=s3.BlockPublicAccess(
                block_public_acls=False,
                ignore_public_acls=False,
                block_public_policy=False,
                restrict_public_buckets=False,
            ),
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # ── Kinesis Data Stream ───────────────────────────────────────────────
        # Activity Logger writes here; Analytics Pipeline reads via Firehose
        self.activity_stream = kinesis.Stream(
            self,
            "ActivityStream",
            stream_name="kismet-activity-stream",
            shard_count=1,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # ── SNS ───────────────────────────────────────────────────────────────
        # Health Monitor publishes alerts here
        self.health_alerts_topic = sns.Topic(
            self,
            "HealthAlertsTopic",
            topic_name="kismet-health-alerts",
        )

        # ── CloudFormation outputs ────────────────────────────────────────────
        cdk.CfnOutput(self, "UserPoolId", value=self.user_pool.user_pool_id)
        cdk.CfnOutput(
            self, "UserPoolClientId", value=self.user_pool_client.user_pool_client_id
        )
        cdk.CfnOutput(self, "ApiUrl", value=self.api.url)
        cdk.CfnOutput(self, "EventBusArn", value=self.event_bus.event_bus_arn)
        cdk.CfnOutput(self, "PhotosBucketName", value=self.photos_bucket.bucket_name)
        cdk.CfnOutput(self, "ActivityStreamArn", value=self.activity_stream.stream_arn)
