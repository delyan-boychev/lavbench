"""Tests for the Celery tasks."""

from typing import ClassVar

import pytest
from celery.exceptions import SoftTimeLimitExceeded

import tasks


class TestEvaluateSubmissionDispatch:
    def test_metadata_mode_dispatches_to_run_eval_submission(self, mocker):
        metadata = {"task_id": 5, "challenge_id": 9}
        mocker.patch.object(tasks, "app", None)
        mock_run = mocker.patch.object(tasks, "run_eval_submission", return_value="done")
        result = tasks.evaluate_submission("sub_dispatch", metadata)
        assert result == "done"
        args = mock_run.call_args[0]
        assert args[1] == "sub_dispatch"
        assert args[2] == metadata
        assert args[3] is None

    def test_non_metadata_mode_passes_app_and_models(self, mocker):
        mocker.patch.object(tasks, "app", "fake-app")
        mocker.patch.object(tasks, "Submission", "fake-submission")
        mocker.patch.object(tasks, "Challenge", "fake-challenge")
        mock_run = mocker.patch.object(tasks, "run_eval_submission", return_value="done")
        result = tasks.evaluate_submission("sub_db")
        assert result == "done"
        args = mock_run.call_args[0]
        assert args[1] == "sub_db"
        assert args[2] is None
        assert args[3] == "fake-app"
        assert args[5] == "fake-submission"
        assert args[6] == "fake-challenge"

    def test_exception_logs_dead_letter_and_reraises(self, mocker):
        metadata = {"task_id": 7, "challenge_id": 3}
        mocker.patch.object(tasks, "run_eval_submission", side_effect=ValueError("boom"))
        mock_dead = mocker.patch("utils.cache_utils.log_dead_letter")
        with pytest.raises(ValueError, match="boom"):
            tasks.evaluate_submission("sub_dead", metadata)
        mock_dead.assert_called_once()
        args, kwargs = mock_dead.call_args
        assert args[0] == "sub_dead"
        assert kwargs["task_id"] == 7
        assert kwargs["challenge_id"] == 3
        assert isinstance(kwargs["error"], ValueError)

    def test_soft_timeout_in_worker_mode_reports_failed(self, mocker):
        metadata = {"task_id": 7, "challenge_id": 3, "main_server_url": "http://localhost:5000"}
        mocker.patch.object(tasks, "IS_EVAL_WORKER", True)
        mocker.patch.object(tasks, "app", None)
        mocker.patch.object(tasks, "run_eval_submission", side_effect=SoftTimeLimitExceeded())
        mock_report = mocker.patch("utils.worker_utils.report_status_to_server", return_value=True)
        mocker.patch("utils.worker_auth.fetch_submission_capabilities")
        result = tasks.evaluate_submission("sub_soft", metadata)
        assert result is None
        mock_report.assert_called_once()
        assert mock_report.call_args.kwargs["status"] == "failed"
        # The sandbox enforces the task limit itself, so this time went to the platform
        assert mock_report.call_args.kwargs["detailed_status"] == "failed_infra"


class TestDeliveryBound:
    """A run whose worker process keeps dying (out of memory) is not redelivered for ever."""

    METADATA: ClassVar[dict[str, object]] = {
        "task_id": 7,
        "challenge_id": 3,
        "main_server_url": "http://localhost:5000",
    }

    @pytest.fixture(autouse=True)
    def _worker_mode(self, mocker, redis_flush):
        mocker.patch.object(tasks, "IS_EVAL_WORKER", True)
        mocker.patch.object(tasks, "app", None)
        mocker.patch("utils.worker_auth.fetch_submission_capabilities")
        self.report = mocker.patch("utils.worker_utils.report_status_to_server", return_value=True)
        self.run = mocker.patch.object(tasks, "run_eval_submission", return_value="done")

    def _deliveries_that_died(self, attempt, count):
        from utils.cache_utils import get_coordination_client

        get_coordination_client().set(tasks._delivery_key(attempt), count)

    def _deliver(self, attempt):
        return tasks.evaluate_submission.apply(
            args=["sub_oom", dict(self.METADATA)], task_id=attempt
        )

    def test_a_normal_delivery_runs_and_clears_its_count(self):
        from utils.cache_utils import get_coordination_client

        assert self._deliver("attempt-ok").result == "done"
        assert get_coordination_client().get(tasks._delivery_key("attempt-ok")) is None

    def test_redeliveries_after_lost_workers_still_run_up_to_the_bound(self):
        from config import Config

        self._deliveries_that_died("attempt-retry", Config.EVALUATION_MAX_DELIVERIES - 1)
        assert self._deliver("attempt-retry").result == "done"
        self.run.assert_called_once()
        self.report.assert_not_called()

    def test_past_the_bound_the_run_ends_as_a_platform_failure(self):
        from config import Config
        from utils.cache_utils import get_coordination_client

        self._deliveries_that_died("attempt-oom", Config.EVALUATION_MAX_DELIVERIES)
        assert self._deliver("attempt-oom").result is None
        self.run.assert_not_called()
        self.report.assert_called_once()
        assert self.report.call_args.kwargs["status"] == "failed"
        assert self.report.call_args.kwargs["detailed_status"] == "failed_infra"
        assert "[WORKER LOST]" in self.report.call_args.kwargs["logs"]
        assert get_coordination_client().get(tasks._delivery_key("attempt-oom")) is None

    def test_a_run_that_ends_with_an_error_is_not_counted_as_a_lost_worker(self, mocker):
        from utils.cache_utils import get_coordination_client

        self.run.side_effect = ValueError("capability claim failed")
        mocker.patch("utils.cache_utils.log_dead_letter")
        self._deliver("attempt-error")
        assert get_coordination_client().get(tasks._delivery_key("attempt-error")) is None

    def test_a_retry_keeps_the_count_of_lost_deliveries(self, mocker):
        """A capability retry is the same run again: earlier worker losses still count."""
        from celery.exceptions import Retry

        from utils.cache_utils import get_coordination_client

        self._deliveries_that_died("attempt-retry-keep", 1)
        self.run.side_effect = Retry("claim refused")
        self._deliver("attempt-retry-keep")
        assert int(get_coordination_client().get(tasks._delivery_key("attempt-retry-keep"))) == 2

    def test_the_failure_report_goes_to_the_workers_own_server_url(self, monkeypatch):
        from config import Config

        monkeypatch.setenv("MAIN_SERVER_URL", "https://lavbench.example.org")
        self._deliveries_that_died("attempt-url", Config.EVALUATION_MAX_DELIVERIES)
        self._deliver("attempt-url")
        reported = self.report.call_args.kwargs["metadata"]
        assert reported["main_server_url"] == "https://lavbench.example.org"


class TestBuildWaitBudget:
    def test_the_wait_leaves_room_for_the_run_and_its_scoring(self):
        from tasks.task_modules.submission_runner import build_wait_budget
        from utils.metadata import SCORING_BASE_SECONDS

        assert build_wait_budget(1200, 0, 300) == min(900, 1200 - 300 - SCORING_BASE_SECONDS)
        # A long task gets only what is left of the soft limit
        assert build_wait_budget(1200, 100, 1000) == 0
        assert build_wait_budget(5000, 0, 60) == 900

    def test_the_runner_passes_the_budget_from_the_dispatched_soft_limit(self):
        from tasks.task_modules.submission_runner import _soft_time_limit

        request = type("R", (), {"timelimit": (1700, 1400)})()
        assert _soft_time_limit(type("T", (), {"request": request})()) == 1400
        assert _soft_time_limit(None) > 0

    def test_a_build_wait_longer_than_the_soft_limit_is_bounded(self, capsys):
        from config import _bounded_build_wait

        assert _bounded_build_wait(900, 1200) == 900
        assert _bounded_build_wait(3000, 1200) == 1140
        assert "IMAGE_BUILD_WAIT_SECONDS" in capsys.readouterr().err
