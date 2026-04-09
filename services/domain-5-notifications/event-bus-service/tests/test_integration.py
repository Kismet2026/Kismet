"""
Event Bus Service — 本地集成测试（使用 moto 模拟 AWS）

完整流程：
  1. 创建 DynamoDB 表 + EventBridge bus
  2. catch_all_handler 接收事件 → 写入 DynamoDB
  3. GET /events/history → 查询刚写入的事件
  4. GET /events/rules → 列出 EventBridge 规则
  5. POST /events/replay → 重放一个事件
  6. 验证重放后的事件也被记录

不需要 AWS 账号，不花钱，全部在本地跑。
"""

import json
import os
import unittest

import boto3
from moto import mock_aws

# 设置环境变量（必须在 import lambda_function 之前）
os.environ["EVENT_LOG_TABLE"] = "kismet-event-log-test"
os.environ["EVENT_BUS_NAME"] = "kismet-events"
os.environ["ENVIRONMENT"] = "test"


def _create_dynamodb_table():
    """在 moto 模拟环境中创建 DynamoDB 表。"""
    client = boto3.client("dynamodb", region_name="us-east-1")
    client.create_table(
        TableName="kismet-event-log-test",
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "source", "AttributeType": "S"},
            {"AttributeName": "timestamp", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "source-timestamp-index",
                "KeySchema": [
                    {"AttributeName": "source", "KeyType": "HASH"},
                    {"AttributeName": "timestamp", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _create_event_bus():
    """在 moto 模拟环境中创建 EventBridge bus + 规则。"""
    client = boto3.client("events", region_name="us-east-1")
    client.create_event_bus(Name="kismet-events")

    # 添加 catch-all 规则
    client.put_rule(
        Name="kismet-catch-all-logger",
        EventBusName="kismet-events",
        EventPattern=json.dumps({"source": [{"prefix": "kismet."}]}),
        State="ENABLED",
        Description="Catch-all rule for logging",
    )
    client.put_targets(
        Rule="kismet-catch-all-logger",
        EventBusName="kismet-events",
        Targets=[
            {
                "Id": "catch-all-target",
                "Arn": "arn:aws:lambda:us-east-1:123456789:function:kismet-event-bus-logger-test",
            }
        ],
    )

    # 添加 match.created 路由规则
    client.put_rule(
        Name="kismet-notification-on-match-created",
        EventBusName="kismet-events",
        EventPattern=json.dumps({
            "source": ["kismet.match-service"],
            "detail-type": ["match.created"],
        }),
        State="ENABLED",
        Description="Route match.created to Push + Email",
    )
    client.put_targets(
        Rule="kismet-notification-on-match-created",
        EventBusName="kismet-events",
        Targets=[
            {
                "Id": "push-target",
                "Arn": "arn:aws:lambda:us-east-1:123456789:function:kismet-push-notification-test",
            },
            {
                "Id": "email-target",
                "Arn": "arn:aws:lambda:us-east-1:123456789:function:kismet-email-service-test",
            },
        ],
    )


@mock_aws
class TestEventBusIntegration(unittest.TestCase):
    """端到端集成测试：模拟完整的事件流。"""

    def setUp(self):
        """每个测试前创建模拟的 AWS 资源。"""
        # 设置 region
        os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
        os.environ["AWS_ACCESS_KEY_ID"] = "testing"
        os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"

        _create_dynamodb_table()
        _create_event_bus()

        # 重新初始化 lambda_function 中的 clients，让它们指向 moto
        import lambda_function

        lambda_function.dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        lambda_function.table = lambda_function.dynamodb.Table("kismet-event-log-test")
        lambda_function.events_client = boto3.client("events", region_name="us-east-1")

    # ─── 测试 1：事件写入 ─────────────────────────────────────
    def test_catch_all_logs_event(self):
        """验证 catch_all_handler 把事件写进 DynamoDB。"""
        from lambda_function import catch_all_handler

        event = {
            "id": "evt-integration-001",
            "source": "kismet.match-service",
            "detail-type": "match.created",
            "detail": {
                "matchId": "match-789",
                "userIds": ["user-123", "user-456"],
            },
            "time": "2026-04-01T12:00:00Z",
        }

        result = catch_all_handler(event, None)
        self.assertEqual(result["statusCode"], 200)

        # 直接查 DynamoDB 验证
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(
            "kismet-event-log-test"
        )
        item = table.get_item(Key={"PK": "EVENT#evt-integration-001", "SK": "META"})
        self.assertIn("Item", item)
        self.assertEqual(item["Item"]["source"], "kismet.match-service")
        self.assertEqual(item["Item"]["detailType"], "match.created")
        self.assertEqual(item["Item"]["status"], "delivered")

    # ─── 测试 2：写入多个事件后查询历史 ──────────────────────
    def test_history_returns_logged_events(self):
        """验证 GET /events/history 能查到刚写入的事件。"""
        from lambda_function import catch_all_handler, admin_api_handler

        # 写入 3 个事件
        events_data = [
            {
                "id": f"evt-hist-{i}",
                "source": src,
                "detail-type": dt,
                "detail": {"test": True},
                "time": f"2026-04-01T12:0{i}:00Z",
            }
            for i, (src, dt) in enumerate([
                ("kismet.match-service", "match.created"),
                ("kismet.auth-service", "user.created"),
                ("kismet.swipe-service", "swipe.created"),
            ])
        ]

        for ev in events_data:
            catch_all_handler(ev, None)

        # 不带过滤 — 查所有
        api_event = {
            "httpMethod": "GET",
            "path": "/events/history",
            "queryStringParameters": None,
        }
        result = admin_api_handler(api_event, None)
        body = json.loads(result["body"])

        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(body["count"], 3)

    # ─── 测试 3：按 source 过滤 ───────────────────────────────
    def test_history_filters_by_source(self):
        """验证 GET /events/history?source=xxx 只返回对应的事件。"""
        from lambda_function import catch_all_handler, admin_api_handler

        # 写入不同 source 的事件
        for i, src in enumerate(["kismet.match-service", "kismet.auth-service", "kismet.match-service"]):
            catch_all_handler(
                {
                    "id": f"evt-filter-{i}",
                    "source": src,
                    "detail-type": "test",
                    "detail": {},
                    "time": f"2026-04-01T13:0{i}:00Z",
                },
                None,
            )

        # 只查 match-service 的
        api_event = {
            "httpMethod": "GET",
            "path": "/events/history",
            "queryStringParameters": {"source": "kismet.match-service"},
        }
        result = admin_api_handler(api_event, None)
        body = json.loads(result["body"])

        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(body["count"], 2)
        for item in body["items"]:
            self.assertEqual(item["source"], "kismet.match-service")

    # ─── 测试 4：列出 EventBridge 规则 ────────────────────────
    def test_list_rules(self):
        """验证 GET /events/rules 能列出 EventBridge 上的规则和 targets。"""
        from lambda_function import admin_api_handler

        api_event = {"httpMethod": "GET", "path": "/events/rules"}
        result = admin_api_handler(api_event, None)
        body = json.loads(result["body"])

        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(body["count"], 2)

        rule_names = [r["ruleName"] for r in body["rules"]]
        self.assertIn("kismet-catch-all-logger", rule_names)
        self.assertIn("kismet-notification-on-match-created", rule_names)

        # 检查 match 规则有两个 target
        match_rule = next(r for r in body["rules"] if r["ruleName"] == "kismet-notification-on-match-created")
        self.assertEqual(len(match_rule["targets"]), 2)

    # ─── 测试 5 & 6 移到 TestReplayIntegration（无规则环境） ────


@mock_aws
class TestReplayIntegration(unittest.TestCase):
    """
    重放测试需要独立环境：只建 bus，不建规则。
    原因：moto 的 put_events 会尝试投递到 Lambda target，但 moto 不支持 Lambda target，会抛 NotImplementedError。
    重放功能只需要 bus 存在就够了。
    """

    def setUp(self):
        os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
        os.environ["AWS_ACCESS_KEY_ID"] = "testing"
        os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"

        _create_dynamodb_table()
        # 只建 bus，不建规则
        boto3.client("events", region_name="us-east-1").create_event_bus(Name="kismet-events")

        import lambda_function

        lambda_function.dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        lambda_function.table = lambda_function.dynamodb.Table("kismet-event-log-test")
        lambda_function.events_client = boto3.client("events", region_name="us-east-1")

    def test_replay_event_end_to_end(self):
        """
        完整流程：
        1. 写入一个事件
        2. 通过 replay 接口重放它
        3. 验证重放成功 + 新记录被写入
        """
        from lambda_function import catch_all_handler, admin_api_handler

        # Step 1: 写入原始事件
        original_event = {
            "id": "evt-replay-001",
            "source": "kismet.report-service",
            "detail-type": "user.reported",
            "detail": {
                "reportId": "report-001",
                "reporterId": "user-123",
                "reportedUserId": "user-456",
                "reason": "spam",
            },
            "time": "2026-04-01T14:00:00Z",
        }
        catch_all_handler(original_event, None)

        # Step 2: 重放
        replay_api_event = {
            "httpMethod": "POST",
            "path": "/events/replay",
            "body": json.dumps({"eventId": "evt-replay-001"}),
        }
        result = admin_api_handler(replay_api_event, None)
        body = json.loads(result["body"])

        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(body["eventId"], "evt-replay-001")
        self.assertEqual(body["status"], "replayed")
        self.assertIn("replayedAt", body)

        # Step 3: 验证 history 里现在有 2 条（原始 + 重放）
        history_event = {
            "httpMethod": "GET",
            "path": "/events/history",
            "queryStringParameters": {"source": "kismet.report-service"},
        }
        history_result = admin_api_handler(history_event, None)
        history_body = json.loads(history_result["body"])

        self.assertEqual(history_body["count"], 2)
        statuses = [item["status"] for item in history_body["items"]]
        self.assertIn("delivered", statuses)
        self.assertIn("replayed", statuses)

    def test_replay_nonexistent_event(self):
        """验证重放一个不存在的 eventId 返回 404。"""
        from lambda_function import admin_api_handler

        api_event = {
            "httpMethod": "POST",
            "path": "/events/replay",
            "body": json.dumps({"eventId": "does-not-exist"}),
        }
        result = admin_api_handler(api_event, None)

        self.assertEqual(result["statusCode"], 404)

    # ─── 测试 7：模拟多种事件类型的完整日志 ───────────────────
    def test_full_event_lifecycle(self):
        """
        模拟真实场景：
        user.created → profile.completed → swipe.created → match.created
        验证所有事件都被记录，且可以按 detailType 过滤。
        """
        from lambda_function import catch_all_handler, admin_api_handler

        lifecycle_events = [
            {
                "id": "evt-lifecycle-1",
                "source": "kismet.auth-service",
                "detail-type": "user.created",
                "detail": {"userId": "user-new", "email": "test@northeastern.edu"},
                "time": "2026-04-01T10:00:00Z",
            },
            {
                "id": "evt-lifecycle-2",
                "source": "kismet.profile-service",
                "detail-type": "profile.completed",
                "detail": {"userId": "user-new", "name": "Test User"},
                "time": "2026-04-01T10:30:00Z",
            },
            {
                "id": "evt-lifecycle-3",
                "source": "kismet.swipe-service",
                "detail-type": "swipe.created",
                "detail": {"userId": "user-new", "targetUserId": "user-456", "action": "like"},
                "time": "2026-04-01T11:00:00Z",
            },
            {
                "id": "evt-lifecycle-4",
                "source": "kismet.match-service",
                "detail-type": "match.created",
                "detail": {"matchId": "match-new", "userIds": ["user-new", "user-456"]},
                "time": "2026-04-01T11:01:00Z",
            },
        ]

        for ev in lifecycle_events:
            result = catch_all_handler(ev, None)
            self.assertEqual(result["statusCode"], 200)

        # 查所有 — 应该有 4 条
        all_result = admin_api_handler(
            {"httpMethod": "GET", "path": "/events/history", "queryStringParameters": {"limit": "10"}},
            None,
        )
        self.assertEqual(json.loads(all_result["body"])["count"], 4)

        # 只查 match.created
        match_result = admin_api_handler(
            {
                "httpMethod": "GET",
                "path": "/events/history",
                "queryStringParameters": {"source": "kismet.match-service", "detailType": "match.created"},
            },
            None,
        )
        match_body = json.loads(match_result["body"])
        self.assertEqual(match_body["count"], 1)
        self.assertEqual(match_body["items"][0]["detailType"], "match.created")


if __name__ == "__main__":
    unittest.main()
