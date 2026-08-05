"""Tests for the Celery tasks."""

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
        result = tasks.evaluate_submission("sub_soft", metadata)
        assert result is None
        mock_report.assert_called_once()
        assert mock_report.call_args.kwargs["status"] == "failed"
