import json
import os
import importlib
from datetime import datetime, timezone

import pytest

os.environ["ANALYTICS_BUCKET"] = "kismet-analytics-test"
os.environ["ATHENA_DATABASE"] = "kismet_analytics"
os.environ["S3_DATA_PREFIX"] = "events"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_SECURITY_TOKEN"] = "testing"
os.environ["AWS_SESSION_TOKEN"] = "testing"

import lambda_function


@pytest.fixture(autouse=True)
def reset_catalog():
    lambda_function._catalog_ready = True
    yield
    lambda_function._catalog_ready = False


def http_event(method, resource, body=None, path_params=None):
    return {
        "httpMethod": method,
        "resource": resource,
        "body": json.dumps(body) if body else None,
        "pathParameters": path_params,
        "queryStringParameters": None,
    }


def _mock_athena_start(monkeypatch, exec_id="qe-test-123"):
    monkeypatch.setattr(
        lambda_function.athena, "start_query_execution",
        lambda **kw: {"QueryExecutionId": exec_id},
    )


def _mock_athena_get_succeeded(monkeypatch, exec_id="qe-test-123"):
    monkeypatch.setattr(
        lambda_function.athena, "get_query_execution",
        lambda **kw: {
            "QueryExecution": {
                "Status": {
                    "State": "SUCCEEDED",
                    "SubmissionDateTime": datetime(2026, 4, 1, tzinfo=timezone.utc),
                    "CompletionDateTime": datetime(2026, 4, 1, 0, 0, 5, tzinfo=timezone.utc),
                },
            }
        },
    )


def _mock_athena_get_running(monkeypatch):
    monkeypatch.setattr(
        lambda_function.athena, "get_query_execution",
        lambda **kw: {
            "QueryExecution": {
                "Status": {
                    "State": "RUNNING",
                    "SubmissionDateTime": datetime(2026, 4, 1, tzinfo=timezone.utc),
                },
            }
        },
    )


def _mock_athena_get_failed(monkeypatch):
    monkeypatch.setattr(
        lambda_function.athena, "get_query_execution",
        lambda **kw: {
            "QueryExecution": {
                "Status": {
                    "State": "FAILED",
                    "SubmissionDateTime": datetime(2026, 4, 1, tzinfo=timezone.utc),
                    "StateChangeReason": "Table not found",
                },
            }
        },
    )


def _mock_athena_results(monkeypatch, rows=None):
    if rows is None:
        rows = [
            {"Data": [{"VarCharValue": "eventType"}, {"VarCharValue": "count"}]},
            {"Data": [{"VarCharValue": "swipe.created"}, {"VarCharValue": "42"}]},
        ]
    monkeypatch.setattr(
        lambda_function.athena, "get_query_results",
        lambda **kw: {"ResultSet": {"Rows": rows}},
    )


# ── POST /analytics/query ────────────────────────────────────────────────────


class TestPostQuery:
    def test_submits_query(self, monkeypatch):
        _mock_athena_start(monkeypatch)
        r = lambda_function.handler(
            http_event("POST", "/analytics/query", body={"sql": "SELECT 1"}), {},
        )
        assert r["statusCode"] == 200
        body = json.loads(r["body"])
        assert body["queryExecutionId"] == "qe-test-123"
        assert body["status"] == "QUEUED"

    def test_missing_sql_returns_400(self, monkeypatch):
        r = lambda_function.handler(
            http_event("POST", "/analytics/query", body={}), {},
        )
        assert r["statusCode"] == 400
        assert json.loads(r["body"])["error"] == "VALIDATION_ERROR"

    def test_empty_sql_returns_400(self, monkeypatch):
        r = lambda_function.handler(
            http_event("POST", "/analytics/query", body={"sql": "   "}), {},
        )
        assert r["statusCode"] == 400

    def test_invalid_json_returns_400(self, monkeypatch):
        r = lambda_function.handler({
            "httpMethod": "POST", "resource": "/analytics/query",
            "body": "broken{", "pathParameters": None, "queryStringParameters": None,
        }, {})
        assert r["statusCode"] == 400

    def test_athena_error_returns_500(self, monkeypatch):
        monkeypatch.setattr(
            lambda_function.athena, "start_query_execution",
            lambda **kw: (_ for _ in ()).throw(RuntimeError("athena down")),
        )
        r = lambda_function.handler(
            http_event("POST", "/analytics/query", body={"sql": "SELECT 1"}), {},
        )
        assert r["statusCode"] == 500
        assert json.loads(r["body"])["error"] == "ATHENA_ERROR"


# ── GET /analytics/query/{queryId} ───────────────────────────────────────────


class TestGetQueryResults:
    def test_succeeded_returns_results(self, monkeypatch):
        _mock_athena_get_succeeded(monkeypatch)
        _mock_athena_results(monkeypatch)
        r = lambda_function.handler(
            http_event("GET", "/analytics/query/{queryId}",
                       path_params={"queryId": "qe-test-123"}), {},
        )
        assert r["statusCode"] == 200
        body = json.loads(r["body"])
        assert body["status"] == "SUCCEEDED"
        assert body["results"][0]["eventType"] == "swipe.created"
        assert body["completedAt"] is not None

    def test_running_returns_status_only(self, monkeypatch):
        _mock_athena_get_running(monkeypatch)
        r = lambda_function.handler(
            http_event("GET", "/analytics/query/{queryId}",
                       path_params={"queryId": "qe-test-123"}), {},
        )
        body = json.loads(r["body"])
        assert body["status"] == "RUNNING"
        assert "results" not in body

    def test_failed_returns_error(self, monkeypatch):
        _mock_athena_get_failed(monkeypatch)
        r = lambda_function.handler(
            http_event("GET", "/analytics/query/{queryId}",
                       path_params={"queryId": "qe-test-123"}), {},
        )
        body = json.loads(r["body"])
        assert body["status"] == "FAILED"
        assert "Table not found" in body["error"]

    def test_not_found_returns_404(self, monkeypatch):
        from botocore.exceptions import ClientError
        monkeypatch.setattr(
            lambda_function.athena, "get_query_execution",
            lambda **kw: (_ for _ in ()).throw(
                lambda_function.athena.exceptions.InvalidRequestException(
                    {"Error": {"Code": "InvalidRequestException", "Message": "not found"}},
                    "GetQueryExecution",
                )
            ),
        )
        r = lambda_function.handler(
            http_event("GET", "/analytics/query/{queryId}",
                       path_params={"queryId": "qe-missing"}), {},
        )
        assert r["statusCode"] == 404


# ── GET /analytics/dashboard ─────────────────────────────────────────────────


class TestGetDashboard:
    def test_returns_metrics(self, monkeypatch):
        _mock_athena_start(monkeypatch)
        call_count = {"n": 0}
        orig = lambda_function.athena.get_query_execution

        def mock_get(**kw):
            call_count["n"] += 1
            return {
                "QueryExecution": {
                    "Status": {
                        "State": "SUCCEEDED",
                        "SubmissionDateTime": datetime(2026, 4, 1, tzinfo=timezone.utc),
                        "CompletionDateTime": datetime(2026, 4, 1, tzinfo=timezone.utc),
                    }
                }
            }

        monkeypatch.setattr(lambda_function.athena, "get_query_execution", mock_get)
        monkeypatch.setattr(
            lambda_function.athena, "get_query_results",
            lambda **kw: {
                "ResultSet": {
                    "Rows": [
                        {"Data": [
                            {"VarCharValue": "dau"}, {"VarCharValue": "totalUsers"},
                            {"VarCharValue": "matchesToday"}, {"VarCharValue": "messagesToday"},
                        ]},
                        {"Data": [
                            {"VarCharValue": "50"}, {"VarCharValue": "200"},
                            {"VarCharValue": "10"}, {"VarCharValue": "80"},
                        ]},
                    ]
                }
            },
        )
        r = lambda_function.handler(
            http_event("GET", "/analytics/dashboard"), {},
        )
        assert r["statusCode"] == 200
        body = json.loads(r["body"])
        assert body["dau"] == 50
        assert body["totalUsers"] == 200
        assert body["matchesToday"] == 10
        assert body["messagesToday"] == 80
        assert "generatedAt" in body

    def test_returns_503_on_failure(self, monkeypatch):
        monkeypatch.setattr(
            lambda_function.athena, "start_query_execution",
            lambda **kw: (_ for _ in ()).throw(RuntimeError("fail")),
        )
        r = lambda_function.handler(
            http_event("GET", "/analytics/dashboard"), {},
        )
        assert r["statusCode"] == 503
        body = json.loads(r["body"])
        assert body["error"] == "ANALYTICS_UNAVAILABLE"

    def test_returns_503_when_query_has_no_rows(self, monkeypatch):
        _mock_athena_start(monkeypatch)
        _mock_athena_get_succeeded(monkeypatch)
        monkeypatch.setattr(
            lambda_function.athena, "get_query_results",
            lambda **kw: {"ResultSet": {"Rows": []}},
        )
        r = lambda_function.handler(
            http_event("GET", "/analytics/dashboard"), {},
        )
        assert r["statusCode"] == 503
        body = json.loads(r["body"])
        assert body["error"] == "ANALYTICS_UNAVAILABLE"


# ── Routing ───────────────────────────────────────────────────────────────────


class TestRouting:
    def test_unknown_route_returns_404(self):
        r = lambda_function.handler(http_event("GET", "/unknown"), {})
        assert r["statusCode"] == 404
