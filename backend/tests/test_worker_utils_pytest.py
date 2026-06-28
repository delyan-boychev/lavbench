import base64
import os
import tempfile
from unittest.mock import patch

import pytest
from worker_utils import (
    MockModel,
    StreamingLogList,
    _sign_worker_token,
    download_labels_parquet_to_dir,
    download_task_files_to_dir,
    report_status_to_server,
    run_command_streaming,
)


class TestRunCommandStreaming:
    """Tests for docker-py-based run_command_streaming."""

    def _make_mock_container(self, mocker, exit_code=0):
        mock_container = mocker.MagicMock()
        mock_container.status = "exited"
        mock_container.wait.return_value = {"StatusCode": exit_code}
        mock_container.logs.return_value = [b"line 1\n", b"line 2\n"]
        return mock_container

    def test_successful_run(self, mocker):
        mock_client = mocker.MagicMock()
        mock_container = self._make_mock_container(mocker, exit_code=0)
        mock_client.containers.run.return_value = mock_container
        logs = []
        retcode, stdout, _stderr, is_timeout = run_command_streaming(
            mock_client,
            "test:latest",
            ["echo", "hello"],
            logs,
        )
        assert retcode == 0
        assert is_timeout is False
        assert "line 1" in stdout
        assert "line 1" in logs

    def test_failing_run(self, mocker):
        mock_client = mocker.MagicMock()
        mock_container = self._make_mock_container(mocker, exit_code=1)
        mock_client.containers.run.return_value = mock_container
        logs = []
        retcode, _stdout, _stderr, is_timeout = run_command_streaming(
            mock_client,
            "test:latest",
            ["bash", "-c", "exit 1"],
            logs,
        )
        assert retcode == 1
        assert is_timeout is False

    def test_container_start_failure(self, mocker):
        mock_client = mocker.MagicMock()
        mock_client.containers.run.side_effect = Exception("failed to create container")
        logs = []
        retcode, _stdout, stderr, _is_timeout = run_command_streaming(
            mock_client,
            "bad:latest",
            ["cmd"],
            logs,
        )
        assert retcode == -1
        assert "failed to create container" in stderr

    def test_timeout_exceeded(self, mocker):
        mock_client = mocker.MagicMock()
        mock_container = mocker.MagicMock()
        # Simulate the container still running until we kill it
        mock_container.status = "running"
        mock_container.wait.return_value = {"StatusCode": -1}
        mock_container.logs.return_value = []
        mock_client.containers.run.return_value = mock_container
        logs = []
        _retcode, _stdout, _stderr, is_timeout = run_command_streaming(
            mock_client,
            "test:latest",
            ["sleep", "10"],
            logs,
            time_limit=0.01,
        )
        assert is_timeout
        mock_container.kill.assert_called_once()

    def test_logs_populated(self, mocker):
        mock_client = mocker.MagicMock()
        mock_container = self._make_mock_container(mocker, exit_code=0)
        mock_client.containers.run.return_value = mock_container
        logs = []
        run_command_streaming(mock_client, "test:latest", ["echo", "hi"], logs)
        assert any("line 1" in log for log in logs)
        assert any("line 2" in log for log in logs)

    def test_gpu_device_request(self, mocker):

        mock_client = mocker.MagicMock()
        mock_container = self._make_mock_container(mocker, exit_code=0)
        mock_client.containers.run.return_value = mock_container
        logs = []
        run_command_streaming(
            mock_client,
            "test:latest",
            ["cmd"],
            logs,
            gpu_required=True,
            gpu_id="1",
        )
        call_kwargs = mock_client.containers.run.call_args[1]
        assert call_kwargs["device_requests"] is not None
        dr = call_kwargs["device_requests"][0]
        assert dr.device_ids == ["1"]
        assert ["gpu"] in dr.capabilities


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


class TestSignWorkerToken:
    """Tests for the _sign_worker_token function."""

    def test_missing_key_returns_empty(self, monkeypatch):
        monkeypatch.delenv("WORKER_PRIVATE_KEY", raising=False)
        assert _sign_worker_token(1) == ""

    def test_invalid_key_returns_empty(self, monkeypatch):
        monkeypatch.setenv("WORKER_PRIVATE_KEY", "not-valid-base64")
        assert _sign_worker_token(1) == ""

    def test_valid_key_returns_token(self, monkeypatch):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        priv = Ed25519PrivateKey.generate()
        priv_b64 = base64.b64encode(priv.private_bytes_raw()).decode()
        monkeypatch.setenv("WORKER_PRIVATE_KEY", priv_b64)

        token = _sign_worker_token(42)
        assert "." in token

        nonce, b64_sig = token.split(".", 1)
        assert nonce.startswith("42:")

        signature = base64.b64decode(b64_sig)
        pub = priv.public_key()
        pub.verify(signature, nonce.encode())

    def test_token_format(self, monkeypatch):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        priv = Ed25519PrivateKey.generate()
        monkeypatch.setenv(
            "WORKER_PRIVATE_KEY",
            base64.b64encode(priv.private_bytes_raw()).decode(),
        )
        token = _sign_worker_token(99)
        assert token.count(".") == 1

        nonce, _ = token.split(".")
        parts = nonce.split(":")
        assert len(parts) == 2
        assert parts[0] == "99"

    def test_different_submissions_different_tokens(self, monkeypatch):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        priv = Ed25519PrivateKey.generate()
        monkeypatch.setenv(
            "WORKER_PRIVATE_KEY",
            base64.b64encode(priv.private_bytes_raw()).decode(),
        )
        t1 = _sign_worker_token(1)
        t2 = _sign_worker_token(2)
        # Different submission_id → different nonce → different token
        assert t1.split(".")[0].split(":")[0] == "1"
        assert t2.split(".")[0].split(":")[0] == "2"


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
        assert any("404" in log for log in logs)

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
