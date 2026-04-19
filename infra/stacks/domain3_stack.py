import aws_cdk as cdk
from constructs import Construct
from aws_cdk import (
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_dynamodb as dynamodb,
    aws_logs as logs,
    aws_events as events,
    aws_apigateway as apigateway,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as integrations,
)

from stacks.shared_stack import SharedStack
from kismet_constructs.kismet_service import KismetService, synth_stage_redeploy


class Domain3Stack(cdk.Stack):
    """
    Domain 3 — Messaging
    Owners: Parker (Chat Gateway, Message Service), QX (Presence Service), Jiaxin (Icebreaker Service)

    Implemented here: Message Service + Chat Gateway
    """

    def __init__(self, scope: Construct, construct_id: str, *, shared: SharedStack, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        imported_api = apigateway.RestApi.from_rest_api_attributes(
            self,
            "ImportedSharedApi",
            rest_api_id=shared.api.rest_api_id,
            root_resource_id=shared.api.rest_api_root_resource_id,
        )

        matches_table = dynamodb.Table.from_table_name(
            self,
            "MatchesTable",
            "kismet-matches",
        )
        event_bus = events.EventBus.from_event_bus_name(
            self,
            "ImportedEventBus",
            "kismet-events",
        )

        # ── Message Service (Parker) ──────────────────────────────────────────
        # Persists messages in DynamoDB and publishes message.sent to EventBridge.
        # Table schema:
        #   PK = CONV#{matchId}   SK = MSG#{timestamp}#{messageId}
        #   GSI: messageId-index (PK = messageId)  — used by DELETE /messages/{messageId}
        message_service = KismetService(
            self,
            "MessageService",
            service_name="message-service",
            code_path="../services/domain-3-messaging/message-service",
            tables=[
                {
                    "table_name": "kismet-messages",
                    "pk": {"name": "PK", "type": "S"},
                    "sk": {"name": "SK", "type": "S"},
                    "gsi": [
                        {
                            "name": "messageId",
                            "pk": {"name": "messageId", "type": "S"},
                        }
                    ],
                }
            ],
            routes=[
                {"method": "POST", "path": "/messages", "auth": True},
                {"method": "GET", "path": "/messages/match/{matchId}", "auth": True},
                {"method": "DELETE", "path": "/messages/{messageId}", "auth": True},
            ],
            consume_events=["user.deleted", "profile.banned"],   # cleans up messages for deleted/banned users
            publish_events=True, # publishes message.sent
            environment={
                "EVENT_BUS_NAME": event_bus.event_bus_name,
                "MATCHES_TABLE": matches_table.table_name,
            },
            api=imported_api,
            authorizer=shared.authorizer,
            event_bus=event_bus,
        )

        # ── Message Service env: inject TABLE_NAME after table is created ─────
        message_service.function.add_environment(
            "TABLE_NAME", message_service.tables[0].table_name
        )
        matches_table.grant_read_data(message_service.function)

        # ── Chat Gateway — WebSocket (Parker) ─────────────────────────────────
        # Real-time chat via API Gateway WebSocket.
        # connections table: PK=CONN#{connectionId} SK=META
        #   GSI matchId-index: find all connections for a conversation
        connections_table = dynamodb.Table(
            self,
            "ConnectionsTable",
            table_name="kismet-connections",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        connections_table.add_global_secondary_index(
            index_name="matchId-index",
            partition_key=dynamodb.Attribute(name="matchId", type=dynamodb.AttributeType.STRING),
        )

        code_path = "../services/domain-3-messaging/chat-gateway"

        connect_fn = lambda_.Function(
            self, "WsConnectFn",
            function_name="kismet-ws-connect",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="connect.handler",
            code=lambda_.Code.from_asset(code_path),
            timeout=cdk.Duration.seconds(30),
            memory_size=256,
            environment={
                "CONNECTIONS_TABLE": connections_table.table_name,
                "MATCHES_TABLE": matches_table.table_name,
            },
            log_retention=logs.RetentionDays.ONE_WEEK,
        )
        connections_table.grant_read_write_data(connect_fn)
        matches_table.grant_read_data(connect_fn)

        disconnect_fn = lambda_.Function(
            self, "WsDisconnectFn",
            function_name="kismet-ws-disconnect",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="disconnect.handler",
            code=lambda_.Code.from_asset(code_path),
            timeout=cdk.Duration.seconds(30),
            memory_size=256,
            environment={"CONNECTIONS_TABLE": connections_table.table_name},
            log_retention=logs.RetentionDays.ONE_WEEK,
        )
        connections_table.grant_read_write_data(disconnect_fn)

        send_message_fn = lambda_.Function(
            self, "WsSendMessageFn",
            function_name="kismet-ws-send-message",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="send_message.handler",
            code=lambda_.Code.from_asset(code_path),
            timeout=cdk.Duration.seconds(30),
            memory_size=256,
            environment={
                "CONNECTIONS_TABLE": connections_table.table_name,
                "MATCHES_TABLE": matches_table.table_name,
                "MESSAGE_SERVICE_FUNCTION_NAME": message_service.function.function_name,
            },
            log_retention=logs.RetentionDays.ONE_WEEK,
        )
        connections_table.grant_read_write_data(send_message_fn)
        matches_table.grant_read_data(send_message_fn)
        message_service.function.grant_invoke(send_message_fn)

        # WebSocket API
        ws_api = apigwv2.WebSocketApi(
            self, "ChatWebSocketApi",
            api_name="kismet-chat-ws",
            connect_route_options=apigwv2.WebSocketRouteOptions(
                integration=integrations.WebSocketLambdaIntegration("ConnectInt", connect_fn),
            ),
            disconnect_route_options=apigwv2.WebSocketRouteOptions(
                integration=integrations.WebSocketLambdaIntegration("DisconnectInt", disconnect_fn),
            ),
            default_route_options=apigwv2.WebSocketRouteOptions(
                integration=integrations.WebSocketLambdaIntegration("SendMessageInt", send_message_fn),
            ),
        )

        ws_stage = apigwv2.WebSocketStage(
            self, "ChatWsStage",
            web_socket_api=ws_api,
            stage_name="dev",
            auto_deploy=True,
        )

        # Allow send_message Lambda to push messages back to WebSocket clients
        send_message_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["execute-api:ManageConnections"],
            resources=[f"arn:aws:execute-api:{self.region}:{self.account}:{ws_api.api_id}/*"],
        ))

        cdk.CfnOutput(self, "ChatWebSocketUrl", value=ws_stage.url, description="WebSocket chat URL")

        # Allow message-service to push read receipts via WebSocket
        message_service.function.add_environment("CONNECTIONS_TABLE", connections_table.table_name)
        message_service.function.add_environment("WEBSOCKET_ENDPOINT", ws_stage.callback_url)
        connections_table.grant_read_write_data(message_service.function)
        message_service.function.add_to_role_policy(iam.PolicyStatement(
            actions=["execute-api:ManageConnections"],
            resources=[f"arn:aws:execute-api:{self.region}:{self.account}:{ws_api.api_id}/*"],
        ))

        # ── Presence Service (QX) ────────────────────────────────────────────
        # Tracks online/offline status (heartbeat TTL=60s) and typing indicators (TTL=5s).
        # Tables created manually to support DynamoDB TTL — KismetService doesn't expose that.
        presence_table = dynamodb.Table(
            self,
            "PresenceTable",
            table_name="kismet-presence",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        typing_table = dynamodb.Table(
            self,
            "TypingTable",
            table_name="kismet-typing",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        presence_service = KismetService(
            self,
            "PresenceService",
            service_name="presence-service",
            code_path="../services/domain-3-messaging/presence-service",
            tables=[],  # created manually above to support TTL
            routes=[
                {"method": "POST", "path": "/presence/heartbeat",         "auth": True},
                {"method": "GET",  "path": "/presence/user/{userId}",     "auth": True},
                {"method": "POST", "path": "/presence/{matchId}/typing",  "auth": True},
                {"method": "GET",  "path": "/presence/{matchId}/typing",  "auth": True},
            ],
            environment={
                "PRESENCE_TABLE": presence_table.table_name,
                "TYPING_TABLE":   typing_table.table_name,
                "MATCHES_TABLE":  matches_table.table_name,
            },
            api=imported_api,
            authorizer=shared.authorizer,
            event_bus=event_bus,
        )

        presence_table.grant_read_write_data(presence_service.function)
        typing_table.grant_read_write_data(presence_service.function)
        matches_table.grant_read_data(presence_service.function)

        # ── Icebreaker Service (Jiaxin) ───────────────────────────────────────
        # Generates AI conversation starters via Bedrock when a match is created.
        # Caches results in DynamoDB so suggestions are ready before users open chat.
        # Routes:
        #   POST /icebreaker/generate   — generate (or return cached) icebreakers
        #   GET  /icebreaker/{matchId}  — retrieve previously generated icebreakers
        icebreaker_service = KismetService(
            self,
            "IcebreakerService",
            service_name="icebreaker",
            code_path="../services/domain-3-messaging/icebreaker-service",
            tables=[
                {
                    "table_name": "kismet-icebreakers",
                    "pk": {"name": "PK", "type": "S"},
                    "sk": {"name": "SK", "type": "S"},
                }
            ],
            routes=[
                {"method": "POST", "path": "/icebreaker/generate", "auth": True},
                {"method": "GET", "path": "/icebreaker/{matchId}", "auth": True},
            ],
            consume_events=["match.created"],  # auto-generate when a match is created
            publish_events=False,
            extra_policies=[
                iam.PolicyStatement(
                    actions=["bedrock:InvokeModel"],
                    resources=[
                        f"arn:aws:bedrock:{self.region}::foundation-model/anthropic.claude-3-haiku-20240307-v1:0"
                    ],
                )
            ],
            environment={
                "MATCHES_TABLE": matches_table.table_name,
            },
            api=imported_api,
            authorizer=shared.authorizer,
            event_bus=event_bus,
        )
        # Inject TABLE_NAME via CDK token (same pattern as message-service)
        icebreaker_service.function.add_environment(
            "TABLE_NAME", icebreaker_service.tables[0].table_name
        )
        matches_table.grant_read_data(icebreaker_service.function)

        # Force API Gateway dev stage to redeploy when routes change (issue #118)
        synth_stage_redeploy(self, api=imported_api)
