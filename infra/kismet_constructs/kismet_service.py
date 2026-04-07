from typing import Optional, List, Dict
from constructs import Construct
import aws_cdk as cdk
from aws_cdk import (
    aws_lambda as lambda_,
    aws_dynamodb as dynamodb,
    aws_apigateway as apigateway,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_logs as logs,
)


def _get_attr_type(t: str) -> dynamodb.AttributeType:
    return {"S": dynamodb.AttributeType.STRING, "N": dynamodb.AttributeType.NUMBER}.get(
        t, dynamodb.AttributeType.STRING
    )


def _get_or_create_resource(
    parent: apigateway.IResource, parts: List[str]
) -> apigateway.IResource:
    """Recursively get or create nested API Gateway resources."""
    if not parts:
        return parent
    part = parts[0]
    existing = parent.get_resource(part)
    resource = existing if existing else parent.add_resource(part)
    return _get_or_create_resource(resource, parts[1:])


class KismetService(Construct):
    """
    Reusable construct for a Kismet microservice.
    Creates: Lambda, IAM Role, DynamoDB table(s), API Gateway routes,
             EventBridge rules, CloudWatch Log Group.

    Args:
        service_name:    Short name, e.g. "swipe". Used for Lambda/table naming.
        code_path:       Path to Lambda code directory (relative to infra/).
        handler:         Lambda handler string. Default: "lambda_function.handler"
        tables:          List of table configs:
                           [{"pk": {"name": "PK", "type": "S"},
                             "sk": {"name": "SK", "type": "S"},  # optional
                             "table_name": "kismet-foo",          # optional override
                             "gsi": [{"name": "...", "pk": {...}, "sk": {...}}]}]
        routes:          List of API route configs:
                           [{"method": "GET", "path": "/foo/{id}", "auth": True}]
        consume_events:  List of event detail-types to subscribe to, e.g. ["match.created"]
        publish_events:  Whether the Lambda needs events:PutEvents permission.
        extra_policies:  List of iam.PolicyStatement for special permissions.
        environment:     Extra Lambda environment variables.
        api:             Shared API Gateway RestApi.
        authorizer:      Shared Cognito authorizer.
        event_bus:       Shared EventBridge EventBus.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        service_name: str,
        code_path: str,
        handler: str = "lambda_function.handler",
        tables: Optional[List[Dict]] = None,
        routes: Optional[List[Dict]] = None,
        consume_events: Optional[List[str]] = None,
        publish_events: bool = False,
        extra_policies: Optional[List[iam.PolicyStatement]] = None,
        environment: Optional[Dict] = None,
        api: Optional[apigateway.RestApi] = None,
        authorizer: Optional[apigateway.IAuthorizer] = None,
        event_bus: Optional[events.EventBus] = None,
    ):
        super().__init__(scope, construct_id)

        fn_name = f"kismet-{service_name}"
        env_vars = environment or {}

        # ── Lambda ────────────────────────────────────────────────────────────
        self.function = lambda_.Function(
            self,
            "Function",
            function_name=fn_name,
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler=handler,
            code=lambda_.Code.from_asset(code_path),
            timeout=cdk.Duration.seconds(30),
            memory_size=256,
            environment=env_vars,
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        # ── DynamoDB tables ───────────────────────────────────────────────────
        self.tables: List[dynamodb.Table] = []
        for i, table_cfg in enumerate(tables or []):
            table_name = table_cfg.get(
                "table_name",
                f"kismet-{service_name}" if i == 0 else f"kismet-{service_name}-{i}",
            )
            pk_cfg = table_cfg["pk"]
            sk_cfg = table_cfg.get("sk")

            table = dynamodb.Table(
                self,
                f"Table{i}",
                table_name=table_name,
                partition_key=dynamodb.Attribute(
                    name=pk_cfg["name"],
                    type=_get_attr_type(pk_cfg.get("type", "S")),
                ),
                sort_key=(
                    dynamodb.Attribute(
                        name=sk_cfg["name"],
                        type=_get_attr_type(sk_cfg.get("type", "S")),
                    )
                    if sk_cfg
                    else None
                ),
                billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            )

            for gsi in table_cfg.get("gsi", []):
                table.add_global_secondary_index(
                    index_name=f"{gsi['name']}-index",
                    partition_key=dynamodb.Attribute(
                        name=gsi["pk"]["name"],
                        type=_get_attr_type(gsi["pk"].get("type", "S")),
                    ),
                    sort_key=(
                        dynamodb.Attribute(
                            name=gsi["sk"]["name"],
                            type=_get_attr_type(gsi["sk"].get("type", "S")),
                        )
                        if gsi.get("sk")
                        else None
                    ),
                )

            table.grant_read_write_data(self.function)
            self.tables.append(table)

        # ── API Gateway routes ────────────────────────────────────────────────
        if api and routes:
            integration = apigateway.LambdaIntegration(self.function)
            for route in routes:
                path_parts = [p for p in route["path"].split("/") if p]
                resource = _get_or_create_resource(api.root, path_parts)
                method_options = {}
                if route.get("auth", True) and authorizer:
                    method_options["authorizer"] = authorizer
                    method_options["authorization_type"] = (
                        apigateway.AuthorizationType.COGNITO
                    )
                resource.add_method(route["method"], integration, **method_options)

        # ── EventBridge: publish permission ──────────────────────────────────
        if publish_events and event_bus:
            event_bus.grant_put_events_to(self.function)

        # ── EventBridge: consume (subscribe) ─────────────────────────────────
        for event_type in consume_events or []:
            rule = events.Rule(
                self,
                f"Rule{event_type.replace('.', '-')}",
                event_bus=event_bus,
                event_pattern=events.EventPattern(
                    detail_type=[event_type],
                ),
            )
            rule.add_target(targets.LambdaFunction(self.function))

        # ── Extra IAM policies ────────────────────────────────────────────────
        for policy in extra_policies or []:
            self.function.add_to_role_policy(policy)
