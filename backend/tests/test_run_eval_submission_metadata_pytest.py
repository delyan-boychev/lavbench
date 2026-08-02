import json
import os
import tempfile
from unittest.mock import MagicMock

import pandas as pd
import pytest

from task_modules import submission_runner as sr


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
        "main_server_url": "http://localhost:5000",
    }
    metadata.update(overrides)
    return metadata


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
        mocker.patch.object(sr, "run_command_streaming", return_value=(0, "", "", False))
        mocker.patch.object(sr, "download_task_files_to_dir", return_value=None)
        mocker.patch.object(sr, "download_labels_parquet_to_dir", return_value=labels_path)
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
        assert kwargs["private_score"] == pytest.approx(0.0)
        assert kwargs["metrics_payload_pub"] == {"accuracy": 1.0}
        assert kwargs["metrics_payload_priv"] == {}
        statuses = {c.kwargs.get("status") for c in mock_report.call_args_list}
        assert "running" in statuses

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
        assert fallback["public_score"] == pytest.approx(1.0)
        assert fallback["execution_time_ms"] is not None
        assert mock_r.set.call_args.kwargs["ex"] == 7200

    def test_container_run_exception_reraises_and_reports_failed(self, mocker, tmp_path):
        mock_report = self._setup_happy(mocker, tmp_path)
        mocker.patch.object(
            sr, "run_command_streaming", side_effect=Exception("docker daemon unreachable")
        )
        with pytest.raises(Exception, match="docker daemon unreachable"):
            self._run(_base_metadata())
        failed = self._reports_with_status(mock_report, "failed")
        assert len(failed) >= 1

    def test_time_limit_exceeded_marks_failed(self, mocker, tmp_path):
        mock_report = self._setup_happy(mocker, tmp_path)
        mocker.patch.object(sr, "run_command_streaming", return_value=(0, "", "", True))
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
        mocker.patch("task_modules.image_builder.build_task_image", return_value=False)
        mocker.patch("task_modules.image_builder.ensure_task_image", return_value=False)
        result = self._run(_base_metadata())
        assert result is None
        failed = self._reports_with_status(mock_report, "failed")
        assert len(failed) >= 1
