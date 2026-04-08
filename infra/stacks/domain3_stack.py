import aws_cdk as cdk
from constructs import Construct
from aws_cdk import aws_iam as iam

from stacks.shared_stack import SharedStack
from kismet_constructs.kismet_service import KismetService


class Domain3Stack(cdk.Stack):
    """
    Domain 3 — Messaging
    Owners: Parker (Chat Gateway, Message Service), QX (Presence Service), Jiaxin (Icebreaker Service)

    Implemented here: Message Service + Chat Gateway
    """

    def __init__(self, scope: Construct, construct_id: str, *, shared: SharedStack, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

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
                {"method": "GET", "path": "/messages/{matchId}", "auth": True},
                {"method": "DELETE", "path": "/messages/{messageId}", "auth": True},
            ],
            consume_events=[],   # no incoming events; other services call via HTTP
            publish_events=True, # publishes message.sent
            environment={
                "EVENT_BUS_NAME": shared.event_bus.event_bus_name,
            },
            api=shared.api,
            authorizer=shared.authorizer,
            event_bus=shared.event_bus,
        )

        # ── Chat Gateway (Parker) ─────────────────────────────────────────────
        # HTTP-polling frontend interface for messaging.
        # Shares the kismet-messages DynamoDB table with Message Service.
        # Routes:
        #   POST /chat/{matchId}/send      — send a message
        #   GET  /chat/{matchId}/messages  — poll for new messages (supports ?since=<ISO>)
        #   GET  /chat/{matchId}/status    — last message + unread count
        chat_gateway = KismetService(
            self,
            "ChatGateway",
            service_name="chat-gateway",
            code_path="../services/domain-3-messaging/chat-gateway",
            tables=[],  # no table of its own; reads/writes kismet-messages directly
            routes=[
                {"method": "POST", "path": "/chat/{matchId}/send", "auth": True},
                {"method": "GET", "path": "/chat/{matchId}/messages", "auth": True},
                {"method": "GET", "path": "/chat/{matchId}/status", "auth": True},
            ],
            consume_events=[],
            publish_events=True,  # also publishes message.sent on send
            environment={
                "MESSAGES_TABLE": "kismet-messages",
                "EVENT_BUS_NAME": shared.event_bus.event_bus_name,
            },
            api=shared.api,
            authorizer=shared.authorizer,
            event_bus=shared.event_bus,
        )

        # Grant Chat Gateway read/write access to the Message Service's DynamoDB table
        message_service.tables[0].grant_read_write_data(chat_gateway.function)

        # ── Message Service env: inject TABLE_NAME after table is created ─────
        message_service.function.add_environment(
            "TABLE_NAME", message_service.tables[0].table_name
        )

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
                "TABLE_NAME": "kismet-icebreakers",
            },
            api=shared.api,
            authorizer=shared.authorizer,
            event_bus=shared.event_bus,
        )
