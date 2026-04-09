"""
Scheduler Service — 本地集成测试（使用 moto 模拟 AWS）

完整流程：
  1. 创建 DynamoDB 表 + EventBridge bus
  2. POST /scheduler/jobs → 创建定时任务
  3. GET /scheduler/jobs → 列出所有任务
  4. job_executor_handler → 执行任务，验证事件发到 EventBridge
  5. DELETE /scheduler/jobs/{jobId} → 删除任务
  6. 验证删除后 GET 不再返回该任务

不需要 AWS 账号，不花钱，全部在本地跑。
"""

import json
import os
import unittest

import boto3
from moto import mock_aws

# 设置环境变量（必须在 import lambda_function 之前）
os.environ["SCHEDULER_TABLE"] = "kismet-scheduler-test"
os.environ["EVENT_BUS_NAME"] = "kismet-events"
os.environ["ENVIRONMENT"] = "test"
os.environ["JOB_EXECUTOR_ARN"] = "arn:aws:lambda:us-east-1:123456789:function:kismet-scheduler-executor-test"
os.environ["SCHEDULER_ROLE_ARN"] = "arn:aws:iam::123456789:role/kismet-scheduler-role-test"


def _create_dynamodb_table():
    """在 moto 模拟环境中创建 scheduler DynamoDB 表。"""
    client = boto3.client("dynamodb", region_name="us-east-1")
    client.create_table(
        TableName="kismet-scheduler-test",
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _create_event_bus():
    """在 moto 模拟环境中创建 EventBridge bus。"""
    client = boto3.client("events", region_name="us-east-1")
    client.create_event_bus(Name="kismet-events")


@mock_aws
class TestSchedulerIntegration(unittest.TestCase):
    """端到端集成测试：模拟完整的 Scheduler 流程。"""

    def setUp(self):
        """每个测试前创建模拟的 AWS 资源。"""
        os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
        os.environ["AWS_ACCESS_KEY_ID"] = "testing"
        os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"

        _create_dynamodb_table()
        _create_event_bus()

        # 重新初始化 lambda_function 中的 clients
        import lambda_function

        lambda_function.dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        lambda_function.table = lambda_function.dynamodb.Table("kismet-scheduler-test")
        lambda_function.events_client = boto3.client("events", region_name="us-east-1")
        lambda_function.scheduler_client = boto3.client("scheduler", region_name="us-east-1")

    # ─── 测试 1：创建任务 → 列出 → 验证存在 ──────────────────
    def test_create_and_list_job(self):
        """创建一个 weekly_digest 任务，然后验证 list 能返回它。"""
        from lambda_function import admin_api_handler

        # 创建
        create_event = {
            "httpMethod": "POST",
            "path": "/scheduler/jobs",
            "body": json.dumps({
                "jobType": "weekly_digest",
                "schedule": "cron(0 9 ? * SUN *)",
                "params": {"templateName": "weekly_digest"},
            }),
        }
        create_result = admin_api_handler(create_event, None)
        create_body = json.loads(create_result["body"])

        self.assertEqual(create_result["statusCode"], 201)
        self.assertEqual(create_body["jobType"], "weekly_digest")
        self.assertEqual(create_body["state"], "ENABLED")
        job_id = create_body["jobId"]

        # 列出
        list_event = {"httpMethod": "GET", "path": "/scheduler/jobs"}
        list_result = admin_api_handler(list_event, None)
        list_body = json.loads(list_result["body"])

        self.assertEqual(list_body["count"], 1)
        self.assertEqual(list_body["jobs"][0]["jobId"], job_id)
        self.assertEqual(list_body["jobs"][0]["jobType"], "weekly_digest")

    # ─── 测试 2：创建 → 删除 → 验证消失 ──────────────────────
    def test_create_and_delete_job(self):
        """创建一个任务然后删除，验证 list 为空。"""
        from lambda_function import admin_api_handler

        # 创建
        create_event = {
            "httpMethod": "POST",
            "path": "/scheduler/jobs",
            "body": json.dumps({
                "jobType": "health_check",
                "schedule": "rate(5 minutes)",
            }),
        }
        create_result = admin_api_handler(create_event, None)
        job_id = json.loads(create_result["body"])["jobId"]

        # 删除
        delete_event = {
            "httpMethod": "DELETE",
            "path": f"/scheduler/jobs/{job_id}",
            "pathParameters": {"jobId": job_id},
        }
        delete_result = admin_api_handler(delete_event, None)
        delete_body = json.loads(delete_result["body"])

        self.assertEqual(delete_result["statusCode"], 200)
        self.assertTrue(delete_body["deleted"])

        # 列出 — 应为空
        list_event = {"httpMethod": "GET", "path": "/scheduler/jobs"}
        list_result = admin_api_handler(list_event, None)
        list_body = json.loads(list_result["body"])

        self.assertEqual(list_body["count"], 0)

    # ─── 测试 3：重复创建同类型+同 schedule → 409 ─────────────
    def test_duplicate_job_returns_conflict(self):
        """同 jobType + 同 schedule 创建两次应该返回 409。"""
        from lambda_function import admin_api_handler

        create_event = {
            "httpMethod": "POST",
            "path": "/scheduler/jobs",
            "body": json.dumps({
                "jobType": "stale_match_cleanup",
                "schedule": "rate(1 day)",
            }),
        }

        # 第一次 — 成功
        result1 = admin_api_handler(create_event, None)
        self.assertEqual(result1["statusCode"], 201)

        # 第二次 — 冲突
        result2 = admin_api_handler(create_event, None)
        self.assertEqual(result2["statusCode"], 409)
        body = json.loads(result2["body"])
        self.assertEqual(body["error"]["code"], "CONFLICT")

    # ─── 测试 4：job executor 发布事件到 EventBridge ──────────
    def test_job_executor_publishes_event(self):
        """验证 job_executor_handler 成功发事件到 EventBridge。"""
        from lambda_function import job_executor_handler

        event = {
            "jobType": "weekly_digest",
            "jobId": "job-test-001",
            "params": {"templateName": "weekly_digest"},
        }

        result = job_executor_handler(event, None)
        self.assertEqual(result["statusCode"], 200)

        # moto 不提供直接查询"已发事件"的 API，
        # 但如果 put_events 失败会抛异常，走到这里说明成功了

    # ─── 测试 5：executor 更新 lastRunAt ──────────────────────
    def test_job_executor_updates_last_run(self):
        """验证 executor 执行后更新 DynamoDB 中的 lastRunAt。"""
        from lambda_function import admin_api_handler, job_executor_handler

        # 先创建一个任务
        create_event = {
            "httpMethod": "POST",
            "path": "/scheduler/jobs",
            "body": json.dumps({
                "jobType": "analytics_aggregation",
                "schedule": "rate(1 hour)",
            }),
        }
        create_result = admin_api_handler(create_event, None)
        job_id = json.loads(create_result["body"])["jobId"]

        # 执行
        executor_event = {
            "jobType": "analytics_aggregation",
            "jobId": job_id,
            "params": {},
        }
        job_executor_handler(executor_event, None)

        # 查 DynamoDB 验证 lastRunAt 被更新
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(
            "kismet-scheduler-test"
        )
        item = table.get_item(Key={"PK": f"JOB#{job_id}", "SK": "META"})
        self.assertIn("lastRunAt", item["Item"])

    # ─── 测试 6：创建多个不同类型的任务 ──────────────────────
    def test_create_multiple_job_types(self):
        """创建所有 4 种内置任务类型，验证 list 返回全部。"""
        from lambda_function import admin_api_handler

        jobs = [
            ("weekly_digest", "cron(0 9 ? * SUN *)"),
            ("stale_match_cleanup", "rate(1 day)"),
            ("analytics_aggregation", "rate(1 hour)"),
            ("health_check", "rate(5 minutes)"),
        ]

        for job_type, schedule in jobs:
            create_event = {
                "httpMethod": "POST",
                "path": "/scheduler/jobs",
                "body": json.dumps({"jobType": job_type, "schedule": schedule}),
            }
            result = admin_api_handler(create_event, None)
            self.assertEqual(result["statusCode"], 201, f"Failed to create {job_type}")

        # 列出所有
        list_event = {"httpMethod": "GET", "path": "/scheduler/jobs"}
        list_result = admin_api_handler(list_event, None)
        list_body = json.loads(list_result["body"])

        self.assertEqual(list_body["count"], 4)
        types = {j["jobType"] for j in list_body["jobs"]}
        self.assertEqual(types, {"weekly_digest", "stale_match_cleanup", "analytics_aggregation", "health_check"})

    # ─── 测试 7：无效 jobType → 400 ──────────────────────────
    def test_invalid_job_type(self):
        """验证创建不支持的 jobType 返回 400。"""
        from lambda_function import admin_api_handler

        create_event = {
            "httpMethod": "POST",
            "path": "/scheduler/jobs",
            "body": json.dumps({
                "jobType": "send_spam",
                "schedule": "rate(1 minute)",
            }),
        }
        result = admin_api_handler(create_event, None)

        self.assertEqual(result["statusCode"], 400)
        body = json.loads(result["body"])
        self.assertIn("Invalid jobType", body["error"]["message"])

    # ─── 测试 8：删除不存在的任务 → 404 ──────────────────────
    def test_delete_nonexistent_job(self):
        """验证删除不存在的 jobId 返回 404。"""
        from lambda_function import admin_api_handler

        delete_event = {
            "httpMethod": "DELETE",
            "path": "/scheduler/jobs/ghost-job",
            "pathParameters": {"jobId": "ghost-job"},
        }
        result = admin_api_handler(delete_event, None)

        self.assertEqual(result["statusCode"], 404)


if __name__ == "__main__":
    unittest.main()
