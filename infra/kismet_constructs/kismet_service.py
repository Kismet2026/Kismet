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
        vpc: Optional[cdk.aws_ec2.IVpc] = None,
        security_groups: Optional[List[cdk.aws_ec2.ISecurityGroup]] = None,
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
            vpc=vpc,
            security_groups=security_groups,
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
        # We also track each Method so that callers can force the shared REST
        # API stage to redeploy when routes change (issue #118).
        self.api_methods: List[apigateway.Method] = []
        self.route_specs: List[str] = []
        if api and routes:
            integration = apigateway.LambdaIntegration(self.function)
            cors_added: set[str] = set()
            for route in routes:
                path_parts = [p for p in route["path"].split("/") if p]
                resource = _get_or_create_resource(api.root, path_parts)
                method_options = {}
                if route.get("auth", True) and authorizer:
                    method_options["authorizer"] = authorizer
                    method_options["authorization_type"] = (
                        apigateway.AuthorizationType.COGNITO
                    )
                method = resource.add_method(
                    route["method"], integration, **method_options
                )
                self.api_methods.append(method)
                self.route_specs.append(f"{route['method']} {route['path']}")
                # Add CORS OPTIONS method (needed for cross-stack imported APIs)
                resource_path = resource.path
                if resource_path not in cors_added:
                    try:
                        resource.add_cors_preflight(
                            allow_origins=["*"],
                            allow_methods=apigateway.Cors.ALL_METHODS,
                            allow_headers=["Content-Type", "Authorization"],
                        )
                    except Exception:
                        pass  # OPTIONS already exists on this resource
                    cors_added.add(resource_path)

        # ── EventBridge: always expose bus name if event_bus is provided ─────
        if event_bus:
            self.function.add_environment("EVENT_BUS_NAME", event_bus.event_bus_name)

        # ── EventBridge: publish permission ──────────────────────────────────
        if publish_events and event_bus:
            event_bus.grant_put_events_to(self.function)
            self.function.add_environment("EVENT_BUS_NAME", event_bus.event_bus_name)

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


def synth_stage_redeploy(
    scope: Construct,
    *,
    api: apigateway.IRestApi,
    services: Optional[List[KismetService]] = None,
    stage_name: str = "dev",
) -> Optional[apigateway.Deployment]:
    """Force the shared REST API stage to redeploy when any domain route changes.

    CDK bug / footgun (issue #118): when a domain stack uses
    `apigateway.RestApi.from_rest_api_attributes(...)` to import the shared API
    and adds new Resources/Methods to it, CloudFormation creates the resources
    but does NOT create a new Deployment for the stage. The result is that the
    new routes exist in the API definition but return 403/404 to clients
    because the `dev` stage is still serving the old deployment.

    This helper creates an `apigateway.Deployment` whose logical ID is a hash
    of every service's route specs. When a domain stack adds, removes, or
    renames a route the hash changes, the logical ID changes, CFN synthesises
    a new Deployment, and the stage is updated to serve the new one.

    `depends_on` is wired to every route Method so that CFN cannot create
    the Deployment before the methods it needs to capture exist.

    Intended usage (one call per domain stack, after all services are built)::

        KismetService(self, "A", ...)
        KismetService(self, "B", ...)
        synth_stage_redeploy(self, api=imported_api)

    If `services` is omitted, every `KismetService` in `scope`'s subtree is
    auto-discovered. Pass an explicit list to scope down.
    """
    import hashlib

    if services is None:
        services = [
            node for node in scope.node.find_all() if isinstance(node, KismetService)
        ]

    all_routes: List[str] = []
    all_methods: List[apigateway.Method] = []
    for svc in services:
        all_routes.extend(svc.route_specs)
        all_methods.extend(svc.api_methods)

    # Also pick up any apigateway.Method added directly in `scope` (e.g. a
    # domain stack that calls imported_api.root.add_resource(...).add_method(...)
    # without going through KismetService, like D5's /events/* routes).
    for node in scope.node.find_all():
        if isinstance(node, apigateway.Method) and node not in all_methods:
            all_methods.append(node)
            # Best-effort fingerprint entry — we don't know the path, but the
            # Method's construct id changes when the route set changes.
            all_routes.append(f"loose:{node.node.path}")

    if not all_routes:
        return None

    digest = hashlib.sha256(",".join(sorted(all_routes)).encode()).hexdigest()[:12]

    deployment = apigateway.Deployment(
        scope,
        f"StageRedeploy{digest}",
        api=api,
        description=f"Routes fingerprint: {digest} (see issue #118)",
        retain_deployments=False,
    )
    # Direct the deployment at the existing shared stage instead of creating
    # a new stage. The CFN property is `StageName` on AWS::ApiGateway::Deployment.
    cfn_deployment = deployment.node.default_child  # type: ignore[attr-defined]
    cfn_deployment.add_override("Properties.StageName", stage_name)

    # Ensure every route method is created before the deployment is synthesised.
    for method in all_methods:
        deployment.node.add_dependency(method)

    return deployment
