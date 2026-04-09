"""Unit tests for Scheduler Service Lambda handlers."""

import json
import os
import unittest
from unittest.mock import MagicMock, patch

# Set env vars before importing the module
os.environ["SCHEDULER_TABLE"] = "kismet-scheduler-test"
os.environ["EVENT_BUS_NAME"] = "kismet-events"
os.environ["ENVIRONMENT"] = "test"
os.environ["JOB_EXECUTOR_ARN"] = "arn:aws:lambda:us-east-1:123:function:kismet-scheduler-executor"
os.environ["SCHEDULER_ROLE_ARN"] = "arn:aws:iam::123:role/kismet-scheduler-role"


class TestAdminApiHandler(unittest.TestCase):
    """Tests for the admin_api_handler (API Gateway router)."""

    @patch("lambda_function._list_jobs")
    def test_routes_get_jobs(self, mock_list):
        from lambda_function import admin_api_handler

        mock_list.return_value = {"statusCode": 200}
        event = {"httpMethod": "GET", "path": "/scheduler/jobs"}

        admin_api_handler(event, None)
        mock_list.assert_called_once()

    @patch("lambda_function._create_job")
    def test_routes_post_jobs(self, mock_create):
        from lambda_function import admin_api_handler

        mock_create.return_value = {"statusCode": 201}
        event = {"httpMethod": "POST", "path": "/scheduler/jobs"}

        admin_api_handler(event, None)
        mock_create.assert_called_once()

    @patch("lambda_function._delete_job")
    def test_routes_delete_job(self, mock_delete):
        from lambda_function import admin_api_handler

        mock_delete.return_value = {"statusCode": 200}
        event = {
            "httpMethod": "DELETE",
            "path": "/scheduler/jobs/job-001",
            "pathParameters": {"jobId": "job-001"},
        }

        admin_api_handler(event, None)
        mock_delete.assert_called_once_with("job-001")

    def test_returns_404_for_unknown_route(self):
        from lambda_function import admin_api_handler

        event = {"httpMethod": "GET", "path": "/scheduler/unknown"}
        result = admin_api_handler(event, None)

        assert result["statusCode"] == 404


class TestListJobs(unittest.TestCase):
    """Tests for GET /scheduler/jobs."""

    @patch("lambda_function.table")
    def test_returns_all_jobs(self, mock_table):
        from lambda_function import _list_jobs

        mock_table.scan.return_value = {
            "Items": [
                {
                    "jobId": "job-001",
                    "jobType": "weekly_digest",
                    "schedule": "cron(0 9 ? * SUN *)",
                    "description": "Send weekly digest",
                    "state": "ENABLED",
                }
            ]
        }

        result = _list_jobs({})

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["count"] == 1
        assert body["jobs"][0]["jobType"] == "weekly_digest"


class TestCreateJob(unittest.TestCase):
    """Tests for POST /scheduler/jobs."""

    @patch("lambda_function.scheduler_client")
    @patch("lambda_function.table")
    def test_creates_job_successfully(self, mock_table, mock_scheduler):
        from lambda_function import _create_job

        mock_table.scan.return_value = {"Items": []}

        event = {
            "body": json.dumps(
                {
                    "jobType": "weekly_digest",
                    "schedule": "cron(0 9 ? * SUN *)",
                    "params": {"templateName": "weekly_digest"},
                }
            )
        }

        result = _create_job(event)

        assert result["statusCode"] == 201
        body = json.loads(result["body"])
        assert body["jobType"] == "weekly_digest"
        assert body["state"] == "ENABLED"
        mock_table.put_item.assert_called_once()
        mock_scheduler.create_schedule.assert_called_once()

    def test_returns_400_for_missing_fields(self):
        from lambda_function import _create_job

        event = {"body": json.dumps({"jobType": "weekly_digest"})}
        result = _create_job(event)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error"]["code"] == "VALIDATION_ERROR"

    def test_returns_400_for_invalid_job_type(self):
        from lambda_function import _create_job

        event = {
            "body": json.dumps(
                {"jobType": "invalid_type", "schedule": "rate(1 hour)"}
            )
        }
        result = _create_job(event)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert "Invalid jobType" in body["error"]["message"]

    @patch("lambda_function.table")
    def test_returns_409_for_duplicate(self, mock_table):
        from lambda_function import _create_job

        mock_table.scan.return_value = {
            "Items": [{"jobId": "job-existing", "jobType": "weekly_digest"}]
        }

        event = {
            "body": json.dumps(
                {"jobType": "weekly_digest", "schedule": "cron(0 9 ? * SUN *)"}
            )
        }
        result = _create_job(event)

        assert result["statusCode"] == 409
        body = json.loads(result["body"])
        assert body["error"]["code"] == "CONFLICT"


class TestDeleteJob(unittest.TestCase):
    """Tests for DELETE /scheduler/jobs/{jobId}."""

    @patch("lambda_function.scheduler_client")
    @patch("lambda_function.table")
    def test_deletes_job_successfully(self, mock_table, mock_scheduler):
        from lambda_function import _delete_job

        mock_table.get_item.return_value = {
            "Item": {
                "PK": "JOB#job-001",
                "SK": "META",
                "jobId": "job-001",
                "scheduleName": "kismet-weekly-digest-job-001-test",
            }
        }

        result = _delete_job("job-001")

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["deleted"] is True
        mock_scheduler.delete_schedule.assert_called_once()
        mock_table.delete_item.assert_called_once()

    @patch("lambda_function.table")
    def test_returns_404_for_nonexistent_job(self, mock_table):
        from lambda_function import _delete_job

        mock_table.get_item.return_value = {}

        result = _delete_job("job-nonexistent")

        assert result["statusCode"] == 404

    def test_returns_400_for_missing_job_id(self):
        from lambda_function import _delete_job

        result = _delete_job(None)

        assert result["statusCode"] == 400


class TestJobExecutor(unittest.TestCase):
    """Tests for the job_executor_handler (EventBridge Scheduler → Lambda)."""

    @patch("lambda_function.table")
    @patch("lambda_function.events_client")
    def test_publishes_event_for_known_job(self, mock_events, mock_table):
        from lambda_function import job_executor_handler

        event = {"jobType": "weekly_digest", "jobId": "job-001", "params": {}}
        result = job_executor_handler(event, None)

        assert result["statusCode"] == 200
        mock_events.put_events.assert_called_once()
        call_args = mock_events.put_events.call_args[1]["Entries"][0]
        assert call_args["Source"] == "kismet.scheduler-service"
        assert call_args["DetailType"] == "scheduler.weekly_digest"

    @patch("lambda_function.events_client")
    def test_returns_400_for_unknown_job_type(self, mock_events):
        from lambda_function import job_executor_handler

        event = {"jobType": "unknown_type"}
        result = job_executor_handler(event, None)

        assert result["statusCode"] == 400
        mock_events.put_events.assert_not_called()

    @patch("lambda_function.table")
    @patch("lambda_function.events_client")
    def test_updates_last_run_at(self, mock_events, mock_table):
        from lambda_function import job_executor_handler

        event = {"jobType": "health_check", "jobId": "job-004", "params": {}}
        job_executor_handler(event, None)

        mock_table.update_item.assert_called_once()
        call_kwargs = mock_table.update_item.call_args[1]
        assert call_kwargs["Key"] == {"PK": "JOB#job-004", "SK": "META"}


if __name__ == "__main__":
    unittest.main()
