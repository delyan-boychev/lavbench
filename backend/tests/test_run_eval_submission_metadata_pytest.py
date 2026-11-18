"""Tests for run-eval submission metadata."""

import json
import os
import tempfile
from unittest.mock import MagicMock

import pandas as pd
import pytest

from tasks.task_modules import submission_runner as sr


def _base_metadata(**overrides):
    metadata = {
        "task_id": 456,
        "time_limit": 30,
        "ram_limit": 4096,
        "gpu_required": False,
        "base_docker_image": "python:3.10-slim",
        "apt_packages": "",
        "pip_requirements": "",
        "metrics_config": {"accuracy": {"weight": 1.0}},
        "public_eval_percentage": 100,
        "hf_datasets": "[]",
        "hf_models": "[]",
        "custom_eval_code": None,
        "challenge_id": 789,
        "metric_name": "accuracy",
        "hf_dataset_split": "test",
        "user_code": "print('hello')",
        "submission_id": "sub_meta_1",
        "attempt_id": "attempt-meta-1",
        "main_server_url": "http://localhost:5000",
    }
    metadata.update(overrides)
    return metadata


@pytest.fixture(autouse=True)
def _mock_run_content_fetch(mocker):
    mocker.patch.object(sr, "fetch_submission_capabilities", return_value=None)
    mocker.patch(
        "utils.worker_utils.fetch_submission_run_content",
        side_effect=lambda metadata: (
            metadata.get("user_code"),
            metadata.get("custom_eval_code"),
        ),
    )


class TestRunEvalSubmissionMetadataMode:
    def _setup_happy(self, mocker, tmp_path, write_submission_parquet=True):
        labels_dir = tmp_path / "labels"
        labels_dir.mkdir()
        labels_path = str(labels_dir / "labels.parquet")
        pd.DataFrame({"id": [1, 2, 3, 4], "label": [0, 1, 0, 1]}).to_parquet(labels_path)

        if write_submission_parquet:
            original_mkdtemp = tempfile.mkdtemp

            def mock_mkdtemp(*args, **kwargs):
                td = original_mkdtemp(*args, **kwargs)
                pd.DataFrame({"id": [1, 2, 3, 4], "label": [0, 1, 0, 1]}).to_parquet(
                    os.path.join(td, "submission.parquet")
                )
                return td

            mocker.patch("tempfile.mkdtemp", side_effect=mock_mkdtemp)

        mocker.patch.object(sr, "check_docker_available", return_value=True)
        mocker.patch.object(sr, "_get_client", return_value=MagicMock())
        mocker.patch.object(sr, "_image_exists_docker", return_value=True)
        mocker.patch.object(sr, "run_sandbox", return_value=(0, "", "", False))
        mocker.patch.object(sr, "sync_task_files_to_assets_cache", return_value=True)
        mocker.patch.object(sr, "sync_labels_parquet_to_cache", return_value=labels_path)
        mocker.patch.object(sr, "_fetch_hf_key_from_server", return_value="hf_key_test")
        mock_report = mocker.patch.object(sr, "report_status_to_server", return_value=True)
        return mock_report

    def _run(self, metadata):
        return sr.run_eval_submission(
            self_task=None,
            submission_id="sub_meta_1",
            metadata=metadata,
            app=None,
            db=None,
            submission_cls=None,
            challenge_cls=None,
        )

    @staticmethod
    def _reports_with_status(mock_report, status):
        return [c for c in mock_report.call_args_list if c.kwargs.get("status") == status]

    def test_metadata_mode_full_flow(self, mocker, tmp_path):
        mock_report = self._setup_happy(mocker, tmp_path)
        result = self._run(_base_metadata())
        assert result == "Submission sub_meta_1 evaluated with status completed"
        final = self._reports_with_status(mock_report, "completed")
        assert len(final) == 1
        kwargs = final[0].kwargs
        assert kwargs["public_score"] == pytest.approx(1.0)
        assert kwargs["private_score"] is None
        assert kwargs["metrics_payload_pub"] == {"accuracy": 1.0}
        assert kwargs["metrics_payload_priv"] == {}
        statuses = {c.kwargs.get("status") for c in mock_report.call_args_list}
        assert "running" in statuses

    def test_metadata_mode_fetches_run_content_unconditionally(self, mocker, tmp_path):
        self._setup_happy(mocker, tmp_path)
        mock_fetch = mocker.patch(
            "utils.worker_utils.fetch_submission_run_content",
            return_value=("print('fresh')", "def evaluate(): pass"),
        )
        metadata = _base_metadata(
            user_code="print('stale')",
            custom_eval_code="print('stale-eval')",
        )
        result = self._run(metadata)
        assert result == "Submission sub_meta_1 evaluated with status completed"
        mock_fetch.assert_called_once()
        assert metadata["user_code"] == "print('fresh')"
        assert metadata["custom_eval_code"] == "def evaluate(): pass"

    def test_metadata_mode_fails_when_run_content_fetch_fails(self, mocker, tmp_path):
        self._setup_happy(mocker, tmp_path)
        mocker.patch(
            "utils.worker_utils.fetch_submission_run_content",
            side_effect=RuntimeError("server unreachable"),
        )
        metadata = _base_metadata()
        del metadata["user_code"]
        del metadata["custom_eval_code"]
        result = self._run(metadata)
        assert result.startswith("Failed to fetch submission run content")

    def test_fallback_key_written_when_report_fails(self, mocker, tmp_path):
        mock_report = self._setup_happy(mocker, tmp_path)
        mock_report.return_value = False
        mock_r = mocker.MagicMock()
        mocker.patch.object(sr, "get_coordination_client", return_value=mock_r)
        result = self._run(_base_metadata())
        assert "completed" in result
        mock_r.set.assert_called_once()
        key, payload = mock_r.set.call_args.args[0], mock_r.set.call_args.args[1]
        assert key == "submission:sub_meta_1:fallback"
        fallback = json.loads(payload)
        assert fallback["status"] == "completed"
        assert fallback["attempt_id"] == "attempt-meta-1"
        assert fallback["public_score"] == pytest.approx(1.0)
        assert fallback["execution_time_ms"] is not None
        assert mock_r.set.call_args.kwargs["ex"] == 7200

    def test_container_run_exception_reraises_and_reports_failed(self, mocker, tmp_path):
        mock_report = self._setup_happy(mocker, tmp_path)
        mocker.patch.object(sr, "run_sandbox", side_effect=Exception("docker daemon unreachable"))
        with pytest.raises(Exception, match="docker daemon unreachable"):
            self._run(_base_metadata())
        failed = self._reports_with_status(mock_report, "failed")
        assert len(failed) >= 1

    def test_time_limit_exceeded_marks_failed(self, mocker, tmp_path):
        mock_report = self._setup_happy(mocker, tmp_path)
        mocker.patch.object(sr, "run_sandbox", return_value=(0, "", "", True))
        result = self._run(_base_metadata())
        assert "evaluated with status failed" in result
        failed = self._reports_with_status(mock_report, "failed")
        assert len(failed) == 1
        assert "TIMEOUT EXPIRED" in failed[0].kwargs["logs"]

    def test_missing_submission_parquet_marks_failed(self, mocker, tmp_path):
        mock_report = self._setup_happy(mocker, tmp_path, write_submission_parquet=False)
        result = self._run(_base_metadata())
        assert "evaluated with status failed" in result
        failed = self._reports_with_status(mock_report, "failed")
        assert "did not generate 'submission.parquet'" in failed[0].kwargs["logs"]

    def test_build_failure_reports_failed_and_returns_none(self, mocker, tmp_path):
        mock_report = self._setup_happy(mocker, tmp_path)
        mocker.patch.object(sr, "_image_exists_docker", return_value=False)
        mocker.patch("tasks.task_modules.image_builder.build_task_image", return_value=False)
        mocker.patch("tasks.task_modules.image_builder.ensure_task_image", return_value=False)
        result = self._run(_base_metadata())
        assert result is None
        failed = self._reports_with_status(mock_report, "failed")
        assert len(failed) >= 1


class TestFileModeRunner:
    """A file task skips the image and the sandbox and scores the fetched Parquet."""

    def _setup(self, mocker, tmp_path, body):
        labels_path = str(tmp_path / "labels.parquet")
        pd.DataFrame({"id": [1, 2, 3, 4], "label": [0, 1, 0, 1]}).to_parquet(labels_path)
        mocker.patch.object(sr, "sync_labels_parquet_to_cache", return_value=labels_path)
        sandbox = mocker.patch.object(sr, "run_sandbox")
        docker = mocker.patch.object(sr, "check_docker_available")

        response = MagicMock(status_code=200)
        response.iter_content.return_value = [body]
        mocker.patch("utils.worker_utils.requests.get", return_value=response)
        mocker.patch("utils.worker_utils.worker_request_headers", return_value={})
        report = mocker.patch.object(sr, "report_status_to_server", return_value=True)
        return report, sandbox, docker

    def _metadata(self, body):
        import hashlib

        return _base_metadata(
            evaluation_mode="file",
            user_code=None,
            artifact_sha256=hashlib.sha256(body).hexdigest(),
            artifact_size=len(body),
        )

    def _parquet(self, tmp_path):
        path = tmp_path / "sub.parquet"
        pd.DataFrame({"id": [1, 2, 3, 4], "prediction": [0, 1, 0, 1]}).to_parquet(path)
        return path.read_bytes()

    def test_the_fetched_parquet_is_scored_without_a_sandbox(self, mocker, tmp_path):
        body = self._parquet(tmp_path)
        report, sandbox, docker = self._setup(mocker, tmp_path, body)
        sr.run_eval_submission(None, "sub_file_1", self._metadata(body), None, None, None, None)
        sandbox.assert_not_called()
        docker.assert_not_called()
        final = report.call_args_list[-1].kwargs
        assert final["status"] == "completed"
        assert final["public_score"] == 1.0
        assert isinstance(final["evaluation_time_ms"], int) and final["evaluation_time_ms"] >= 0

    def test_a_sha256_mismatch_fails_as_a_platform_failure(self, mocker, tmp_path):
        body = self._parquet(tmp_path)
        report, sandbox, _docker = self._setup(mocker, tmp_path, body[:-1] + b"X")
        sr.run_eval_submission(None, "sub_file_2", self._metadata(body), None, None, None, None)
        sandbox.assert_not_called()
        statuses = [
            (c.kwargs.get("status"), c.kwargs.get("detailed_status")) for c in report.call_args_list
        ]
        assert ("failed", sr.INFRA_FAILURE) in statuses
