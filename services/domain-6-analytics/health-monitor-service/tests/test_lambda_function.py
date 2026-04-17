import json
import os
import importlib

import boto3
import pytest
from moto import mock_aws

os.environ["HEALTH_HISTORY_TABLE"] = "kismet-health-history"
os.environ["HEALTH_ALERTS_TOPIC_ARN"] = "arn:aws:sns:us-east-1:123456789012:kismet-health-alerts"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_SECURITY_TOKEN"] = "testing"
os.environ["AWS_SESSION_TOKEN"] = "testing"

import lambda_function

HEALTHY_METRICS = {
    "errors": 0, "errorRate": 0.0, "avgDuration": 50,
    "p99Duration": 120, "invocations": 100, "throttles": 0,
}
UNHEALTHY_METRICS = {
    "errors": 10, "errorRate": 0.1, "avgDuration": 50,
    "p99Duration": 120, "invocations": 100, "throttles": 0,
}
DEGRADED_METRICS = {
    "errors": 0, "errorRate": 0.0, "avgDuration": 500,
    "p99Duration": 800, "invocations": 100, "throttles": 0,
}
UNKNOWN_METRICS = {
    "errors": 0, "errorRate": 0.0, "avgDuration": 0,
    "p99Duration": 0, "invocations": 0, "throttles": 0,
}


@pytest.fixture
def aws(monkeypatch):
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        dynamodb.create_table(
            TableName="kismet-health-history",
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

        sns = boto3.client("sns", region_name="us-east-1")
        sns.create_topic(Name="kismet-health-alerts")

        importlib.reload(lambda_function)
        yield dynamodb


def http_event(method, resource, path_params=None):
    return {
        "httpMethod": method,
        "resource": resource,
        "pathParameters": path_params,
        "queryStringParameters": None,
    }


def _mock_cw_healthy(monkeypatch):
    monkeypatch.setattr(
        lambda_function, "_get_cloudwatch_metrics",
        lambda service_name, period_minutes=5: HEALTHY_METRICS,
    )


def _mock_cw_unhealthy(monkeypatch):
    monkeypatch.setattr(
        lambda_function, "_get_cloudwatch_metrics",
        lambda service_name, period_minutes=5: UNHEALTHY_METRICS,
    )


def _mock_cw_degraded(monkeypatch):
    monkeypatch.setattr(
        lambda_function, "_get_cloudwatch_metrics",
        lambda service_name, period_minutes=5: DEGRADED_METRICS,
    )


def _mock_cw_unknown(monkeypatch):
    monkeypatch.setattr(
        lambda_function, "_get_cloudwatch_metrics",
        lambda service_name, period_minutes=5: UNKNOWN_METRICS,
    )


# ── GET /health ──────────────────────────────────────────────────────────────


class TestGetHealth:
    def test_all_healthy(self, aws, monkeypatch):
        _mock_cw_healthy(monkeypatch)
        r = lambda_function.handler(http_event("GET", "/health"), {})
        assert r["statusCode"] == 200
        body = json.loads(r["body"])
        assert body["status"] == "healthy"
        assert len(body["services"]) == len(lambda_function.KNOWN_SERVICES)
        assert "checkedAt" in body

    def test_degraded_rolls_up(self, aws, monkeypatch):
        _mock_cw_degraded(monkeypatch)
        r = lambda_function.handler(http_event("GET", "/health"), {})
        assert json.loads(r["body"])["status"] == "degraded"

    def test_unhealthy_rolls_up(self, aws, monkeypatch):
        _mock_cw_unhealthy(monkeypatch)
        r = lambda_function.handler(http_event("GET", "/health"), {})
        assert json.loads(r["body"])["status"] == "unhealthy"

    def test_unknown_rolls_up_when_no_recent_signal(self, aws, monkeypatch):
        _mock_cw_unknown(monkeypatch)
        r = lambda_function.handler(http_event("GET", "/health"), {})
        assert json.loads(r["body"])["status"] == "unknown"

    def test_cloudwatch_error_returns_500(self, aws, monkeypatch):
        monkeypatch.setattr(
            lambda_function, "_get_cloudwatch_metrics",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("cw down")),
        )
        r = lambda_function.handler(http_event("GET", "/health"), {})
        assert r["statusCode"] == 500


# ── GET /health/{serviceName} ────────────────────────────────────────────────


class TestGetServiceHealth:
    def test_known_service(self, aws, monkeypatch):
        _mock_cw_healthy(monkeypatch)
        svc = lambda_function.KNOWN_SERVICES[0]
        r = lambda_function.handler(
            http_event("GET", "/health/{serviceName}",
                       path_params={"serviceName": svc}), {},
        )
        assert r["statusCode"] == 200
        body = json.loads(r["body"])
        assert body["serviceName"] == svc
        assert body["status"] == "healthy"
        assert "metrics" in body

    def test_unknown_service_returns_404(self, aws, monkeypatch):
        r = lambda_function.handler(
            http_event("GET", "/health/{serviceName}",
                       path_params={"serviceName": "nonexistent"}), {},
        )
        assert r["statusCode"] == 404


# ── GET /health/alarms ───────────────────────────────────────────────────────


class TestGetAlarms:
    def test_no_alarms(self, aws, monkeypatch):
        monkeypatch.setattr(
            lambda_function.cloudwatch, "describe_alarms",
            lambda **kw: {"MetricAlarms": []},
        )
        r = lambda_function.handler(http_event("GET", "/health/alarms"), {})
        assert r["statusCode"] == 200
        body = json.loads(r["body"])
        assert body["activeCount"] == 0
        assert body["alarms"] == []

    def test_with_alarms(self, aws, monkeypatch):
        from datetime import datetime, timezone
        monkeypatch.setattr(
            lambda_function.cloudwatch, "describe_alarms",
            lambda **kw: {
                "MetricAlarms": [{
                    "AlarmName": "swipe-service-error-rate",
                    "StateValue": "ALARM",
                    "StateReason": "Threshold crossed",
                    "StateUpdatedTimestamp": datetime(2026, 4, 1, tzinfo=timezone.utc),
                }]
            },
        )
        r = lambda_function.handler(http_event("GET", "/health/alarms"), {})
        body = json.loads(r["body"])
        assert body["activeCount"] == 1
        assert body["alarms"][0]["serviceName"] == "swipe-service"


# ── POST /health/check ───────────────────────────────────────────────────────


class TestPostHealthCheck:
    def test_saves_history_and_returns_status(self, aws, monkeypatch):
        _mock_cw_healthy(monkeypatch)
        published = []
        monkeypatch.setattr(
            lambda_function.sns, "publish",
            lambda **kw: published.append(kw),
        )
        r = lambda_function.handler(http_event("POST", "/health/check"), {})
        assert r["statusCode"] == 200
        body = json.loads(r["body"])
        assert body["status"] == "healthy"

        items = aws.Table("kismet-health-history").scan()["Items"]
        assert len(items) == 1
        assert items[0]["status"] == "healthy"

        assert len(published) == 0

    def test_unhealthy_triggers_sns_alert(self, aws, monkeypatch):
        _mock_cw_unhealthy(monkeypatch)
        published = []
        monkeypatch.setattr(
            lambda_function.sns, "publish",
            lambda **kw: published.append(kw),
        )
        lambda_function.handler(http_event("POST", "/health/check"), {})
        assert len(published) == 1
        assert "unhealthy" in published[0]["Subject"]


# ── Status logic ─────────────────────────────────────────────────────────────


class TestStatusLogic:
    def test_derive_healthy(self):
        assert lambda_function._derive_status(HEALTHY_METRICS) == "healthy"

    def test_derive_degraded(self):
        assert lambda_function._derive_status(DEGRADED_METRICS) == "degraded"

    def test_derive_unhealthy(self):
        assert lambda_function._derive_status(UNHEALTHY_METRICS) == "unhealthy"

    def test_derive_unknown(self):
        assert lambda_function._derive_status(UNKNOWN_METRICS) == "unknown"

    def test_rollup_worst_wins(self):
        assert lambda_function._rollup_status("healthy", "unknown") == "healthy"
        assert lambda_function._rollup_status("unknown", "healthy") == "healthy"
        assert lambda_function._rollup_status("unknown", "degraded") == "degraded"
        assert lambda_function._rollup_status("healthy", "degraded") == "degraded"
        assert lambda_function._rollup_status("degraded", "unhealthy") == "unhealthy"
        assert lambda_function._rollup_status("unhealthy", "healthy") == "unhealthy"


# ── Routing ───────────────────────────────────────────────────────────────────


class TestRouting:
    def test_unknown_returns_404(self, aws, monkeypatch):
        r = lambda_function.handler(http_event("DELETE", "/health"), {})
        assert r["statusCode"] == 404
