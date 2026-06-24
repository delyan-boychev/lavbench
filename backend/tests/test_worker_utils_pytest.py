import os
import time
import tempfile
from unittest.mock import patch

import pytest

from worker_utils import (
    run_command_streaming,
    StreamingLogList,
    MockModel,
    report_status_to_server,
    download_task_files_to_dir,
    download_labels_parquet_to_dir,
)


class TestRunCommandStreaming:
    def test_echo_command_success(self):
        logs = []
        retcode, stdout, stderr, is_timeout = run_command_streaming(["echo", "hello world"], logs)
        assert retcode == 0
        assert "hello world" in stdout
        assert is_timeout is False

    def test_command_fails(self):
        logs = []
        retcode, stdout, stderr, is_timeout = run_command_streaming(["bash", "-c", "exit 1"], logs)
        assert retcode != 0
        assert is_timeout is False

    def test_command_not_found(self):
        logs = []
        retcode, stdout, stderr, is_timeout = run_command_streaming(
            ["nonexistent_command_xyz"], logs
        )
        assert retcode != 0

    def test_timeout_exceeded(self):
        logs = []
        retcode, stdout, stderr, is_timeout = run_command_streaming(
            ["sleep", "10"], logs, time_limit=0.5
        )
        assert is_timeout

    def test_logs_populated_on_stdout(self):
        logs = []
        run_command_streaming(["echo", "line1"], logs)
        assert any("line1" in l for l in logs)

    def test_logs_populated_on_stderr(self):
        logs = []
        run_command_streaming(["bash", "-c", "echo errmsg >&2"], logs)
        assert any("errmsg" in l for l in logs)

    def test_timeout_triggers_kill(self):
        logs = []
        start = time.time()
        run_command_streaming(["sleep", "30"], logs, time_limit=0.3)
        elapsed = time.time() - start
        assert elapsed < 10


class TestStreamingLogList:
    @patch("sse_utils.publish_submission_log")
    def test_append_publishes_log(self, mock_publish):
        stream = StreamingLogList(submission_id=123)
        stream.append("test line")
        mock_publish.assert_called_once_with(123, "test line")

    @patch("sse_utils.publish_submission_log")
    def test_max_length_trims(self, mock_publish):
        stream = StreamingLogList(submission_id=1)
        for i in range(10001):
            stream.append(f"line {i}")
        assert len(stream) <= 10000

    @patch("sse_utils.publish_submission_log")
    def test_publish_exception_caught(self, mock_publish):
        mock_publish.side_effect = Exception("SSE error")
        stream = StreamingLogList(submission_id=1)
        stream.append("test")

    def test_inherits_from_list(self):
        stream = StreamingLogList(submission_id=1)
        stream.append("a")
        stream.append("b")
        assert list(stream) == ["a", "b"]
        assert len(stream) == 2


class TestMockModel:
    def test_creates_attributes_from_kwargs(self):
        m = MockModel(foo="bar", num=42)
        assert m.foo == "bar"
        assert m.num == 42

    def test_missing_attribute_raises(self):
        m = MockModel()
        with pytest.raises(AttributeError):
            _ = m.nonexistent

    def test_default_works(self):
        m = MockModel(x=1)
        assert m.x == 1


class TestReportStatusToServer:
    @patch("worker_utils.requests.post")
    def test_successful_report(self, mock_post):
        mock_post.return_value.status_code = 200
        result = report_status_to_server(
            {
                "main_server_url": "http://test:5001",
                "submission_id": 1,
            },
            "completed",
            "done",
        )
        assert result

    @patch("worker_utils.requests.post")
    def test_retry_on_failure(self, mock_post):
        mock_post.return_value.status_code = 500
        result = report_status_to_server(
            {
                "main_server_url": "http://test:5001",
                "submission_id": 1,
            },
            "completed",
            "done",
            max_retries=2,
        )
        assert result is False
        assert mock_post.call_count == 2

    @patch("worker_utils.requests.post")
    def test_retry_on_exception(self, mock_post):
        mock_post.side_effect = Exception("connection error")
        result = report_status_to_server(
            {
                "main_server_url": "http://test:5001",
                "submission_id": 1,
            },
            "completed",
            "done",
            max_retries=3,
        )
        assert result is False

    @patch("worker_utils.requests.post")
    def test_no_metadata_returns_false(self, mock_post):
        result = report_status_to_server({}, "completed", "done")
        assert result is False
        mock_post.assert_not_called()

    @patch("worker_utils.requests.post")
    def test_includes_logs_in_payload(self, mock_post):
        mock_post.return_value.status_code = 200
        report_status_to_server(
            {
                "main_server_url": "http://test:5001",
                "submission_id": 1,
            },
            "completed",
            "done",
            logs=["line1", "line2"],
        )
        payload = mock_post.call_args[1]["json"]
        assert payload["logs"] == "line1\nline2"

    @patch("worker_utils.requests.post")
    def test_includes_scores_in_payload(self, mock_post):
        mock_post.return_value.status_code = 200
        report_status_to_server(
            {
                "main_server_url": "http://test:5001",
                "submission_id": 1,
            },
            "completed",
            "done",
            public_score=0.85,
            private_score=0.75,
            execution_time_ms=1234,
        )
        payload = mock_post.call_args[1]["json"]
        assert payload["public_score"] == 0.85
        assert payload["private_score"] == 0.75
        assert payload["execution_time_ms"] == 1234


class TestDownloadTaskFilesToDir:
    @patch("worker_utils.requests.get")
    def test_downloads_files(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = b"file content"
        metadata = {
            "main_server_url": "http://test:5001",
            "task_files": [{"filename": "data.csv"}],
            "task_id": 5,
        }
        with tempfile.TemporaryDirectory() as tmp:
            download_task_files_to_dir(metadata, tmp, [])
            filepath = os.path.join(tmp, "data.csv")
            assert os.path.exists(filepath)
            with open(filepath, "rb") as f:
                assert f.read() == b"file content"

    @patch("worker_utils.requests.get")
    def test_skips_labels_parquet(self, mock_get):
        metadata = {
            "main_server_url": "http://test:5001",
            "task_files": [{"filename": "labels.parquet"}],
            "task_id": 5,
        }
        with tempfile.TemporaryDirectory() as tmp:
            download_task_files_to_dir(metadata, tmp, [])
            mock_get.assert_not_called()

    @patch("worker_utils.requests.get")
    def test_no_metadata_does_nothing(self, mock_get):
        with tempfile.TemporaryDirectory() as tmp:
            download_task_files_to_dir({}, tmp, [])
            mock_get.assert_not_called()

    @patch("worker_utils.requests.get")
    def test_handles_download_failure(self, mock_get):
        mock_get.return_value.status_code = 404
        logs = []
        metadata = {
            "main_server_url": "http://test:5001",
            "task_files": [{"filename": "data.csv"}],
            "task_id": 5,
        }
        with tempfile.TemporaryDirectory() as tmp:
            download_task_files_to_dir(metadata, tmp, logs)
        assert any("404" in l for l in logs)

    @patch("worker_utils.requests.get")
    def test_empty_files_list(self, mock_get):
        metadata = {
            "main_server_url": "http://test:5001",
            "task_files": [],
            "task_id": 5,
        }
        with tempfile.TemporaryDirectory() as tmp:
            download_task_files_to_dir(metadata, tmp, [])
            mock_get.assert_not_called()


class TestDownloadLabelsParquetToDir:
    @patch("worker_utils.requests.get")
    def test_downloads_labels_parquet(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = b"labels data"
        metadata = {
            "main_server_url": "http://test:5001",
            "task_files": [{"filename": "labels.parquet"}],
            "task_id": 5,
        }
        with tempfile.TemporaryDirectory() as tmp:
            result = download_labels_parquet_to_dir(metadata, tmp, [])
            assert result is not None
            assert os.path.exists(result)
            with open(result, "rb") as f:
                assert f.read() == b"labels data"

    @patch("worker_utils.requests.get")
    def test_no_labels_file_returns_none(self, mock_get):
        metadata = {
            "main_server_url": "http://test:5001",
            "task_files": [{"filename": "data.csv"}],
            "task_id": 5,
        }
        with tempfile.TemporaryDirectory() as tmp:
            result = download_labels_parquet_to_dir(metadata, tmp, [])
            assert result is None
            mock_get.assert_not_called()

    @patch("worker_utils.requests.get")
    def test_no_metadata_returns_none(self, mock_get):
        with tempfile.TemporaryDirectory() as tmp:
            result = download_labels_parquet_to_dir({}, tmp, [])
            assert result is None
