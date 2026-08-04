import base64
import os
import tempfile
import time
from unittest.mock import patch

import pytest

from config import Config
from worker_utils import (
    MockModel,
    StreamingLogList,
    _sign_worker_token,
    download_labels_parquet_to_dir,
    download_task_files_to_dir,
    report_status_to_server,
    run_command_streaming,
    run_stale_dir_sweep,
    sync_labels_parquet_to_cache,
    sync_task_files_to_assets_cache,
)


class TestAssetsCache:
    def _metadata(self, **overrides):
        metadata = {
            "main_server_url": "http://test:5001",
            "submission_id": "sub_1",
            "task_id": 42,
            "task_files": [{"filename": "data.csv", "saved_name": "abc.csv"}],
        }
        metadata.update(overrides)
        return metadata

    @pytest.fixture
    def cache_env(self, monkeypatch, tmp_path):
        monkeypatch.setattr("worker_utils.Config.TASK_IMAGES_DIR", str(tmp_path))
        return tmp_path

    @patch("worker_utils._sign_worker_token", return_value="tok")
    @patch("worker_utils.requests.get")
    def test_first_run_downloads_and_writes_manifest(self, mock_get, _tk, cache_env):
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = b"file content"
        ok = sync_task_files_to_assets_cache(self._metadata(), [])
        assert ok is True
        dest = cache_env / "task_42" / "data" / "data.csv"
        assert dest.read_bytes() == b"file content"
        manifest = (cache_env / "task_42" / ".assets.json").read_text()
        assert '"saved_name": "abc.csv"' in manifest

    @patch("worker_utils._sign_worker_token", return_value="tok")
    @patch("worker_utils.requests.get")
    def test_unchanged_cache_skips_transfer(self, mock_get, _tk, cache_env):
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = b"file content"
        sync_task_files_to_assets_cache(self._metadata(), [])
        mock_get.reset_mock()
        ok = sync_task_files_to_assets_cache(self._metadata(), [])
        assert ok is True
        mock_get.assert_not_called()

    @patch("worker_utils._sign_worker_token", return_value="tok")
    @patch("worker_utils.requests.get")
    def test_changed_saved_name_redownloads(self, mock_get, _tk, cache_env):
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = b"new content"
        sync_task_files_to_assets_cache(self._metadata(), [])
        sync_task_files_to_assets_cache(
            self._metadata(task_files=[{"filename": "data.csv", "saved_name": "xyz.csv"}]),
            [],
        )
        assert mock_get.call_count == 2
        dest = cache_env / "task_42" / "data" / "data.csv"
        assert dest.read_bytes() == b"new content"

    @patch("worker_utils._sign_worker_token", return_value="tok")
    @patch("worker_utils.requests.get")
    def test_labels_parquet_never_in_data_cache(self, mock_get, _tk, cache_env):
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = b"file content"
        metadata = self._metadata(
            task_files=[
                {"filename": "data.csv", "saved_name": "abc.csv"},
                {"filename": "labels.parquet", "saved_name": "labels_1.parquet"},
            ]
        )
        ok = sync_task_files_to_assets_cache(metadata, [])
        assert ok is True
        assert not (cache_env / "task_42" / "data" / "labels.parquet").exists()

    @patch("worker_utils._sign_worker_token", return_value="tok")
    @patch("worker_utils.requests.get")
    def test_download_failure_returns_false(self, mock_get, _tk, cache_env):
        mock_get.return_value.status_code = 404
        ok = sync_task_files_to_assets_cache(self._metadata(), [])
        assert ok is False

    @patch("worker_utils._sign_worker_token", return_value="tok")
    @patch("worker_utils.requests.get")
    def test_labels_0600_and_0700_dir(self, mock_get, _tk, cache_env):
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = b"labels data"
        path = sync_labels_parquet_to_cache(
            self._metadata(task_files=[{"filename": "labels.parquet", "saved_name": "l1.parquet"}]),
            [],
        )
        assert path is not None
        assert (cache_env / "task_42" / "labels" / "labels.parquet").read_bytes() == b"labels data"
        assert os.stat(path).st_mode & 0o777 == 0o600
        assert os.stat(cache_env / "task_42" / "labels").st_mode & 0o777 == 0o700

    @patch("worker_utils._sign_worker_token", return_value="tok")
    def test_labels_unchanged_reuses_cache(self, _tk, cache_env):
        import json as _json

        metadata = {
            "main_server_url": "http://test:5001",
            "submission_id": "sub_1",
            "task_id": 42,
            "task_files": [{"filename": "labels.parquet", "saved_name": "l1.parquet"}],
        }
        labels_dir = cache_env / "task_42" / "labels"
        labels_dir.mkdir(parents=True, exist_ok=True)
        (labels_dir / "labels.parquet").write_bytes(b"cached")
        os.chmod(labels_dir, 0o700)
        (cache_env / "task_42" / ".assets.json").write_text(
            _json.dumps({"labels": {"saved_name": "l1.parquet", "size": 6}})
        )

        with patch("worker_utils.requests.get") as mock_get:
            path = sync_labels_parquet_to_cache(metadata, [])
            assert path is not None
            mock_get.assert_not_called()


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
        assert mock_container.kill.call_count >= 1

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


class TestSeedTarNormalization:
    def test_normalizes_ownership_and_modes(self):
        import tarfile

        from worker_utils import SANDBOX_GID, SANDBOX_UID, _normalize_seed_tar_member

        dir_member = tarfile.TarInfo(name=".")
        dir_member.type = tarfile.DIRTYPE
        dir_member.mode = 0o700
        dir_member.uid = 501
        dir_member.gid = 20
        normalized_dir = _normalize_seed_tar_member(dir_member)
        assert normalized_dir.uid == SANDBOX_UID
        assert normalized_dir.gid == SANDBOX_GID
        assert normalized_dir.mode == 0o777

        file_member = tarfile.TarInfo(name="script.py")
        file_member.type = tarfile.REGTYPE
        file_member.mode = 0o600
        file_member.uid = 501
        file_member.gid = 20
        normalized_file = _normalize_seed_tar_member(file_member)
        assert normalized_file.uid == SANDBOX_UID
        assert normalized_file.gid == SANDBOX_GID
        assert normalized_file.mode == 0o644

        exec_member = tarfile.TarInfo(name="harness.py")
        exec_member.type = tarfile.REGTYPE
        exec_member.mode = 0o755
        normalized_exec = _normalize_seed_tar_member(exec_member)
        assert normalized_exec.mode == 0o755


class TestSeededRunCommandStreaming:
    """Sandboxes seeded via put_archive instead of host-path bind mounts."""

    def _tar_stream(self, files: dict[str, bytes]):
        import io
        import tarfile

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for name, content in files.items():
                info = tarfile.TarInfo(name=name)
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
        buf.seek(0)
        return buf

    def _make_mock_container(self, mocker, exit_code=0, files: dict[str, bytes] | None = None):
        mock_container = mocker.MagicMock()
        mock_container.status = "exited"
        mock_container.wait.return_value = {"StatusCode": exit_code}
        mock_container.logs.return_value = [b"seeded run\n"]
        if files:
            mock_container.get_archive.return_value = (self._tar_stream(files), None)
        else:
            mock_container.get_archive.side_effect = Exception("not found")
        return mock_container

    def test_seed_dir_streams_via_put_archive(self, mocker, tmp_path):
        seed = tmp_path / "seed"
        seed.mkdir()
        (seed / "submission_sub_1.py").write_text("print(1)\n")
        (seed / "data").mkdir()
        (seed / "data" / "features.csv").write_text("x,y\n")

        mock_client = mocker.MagicMock()
        mock_container = self._make_mock_container(mocker, files={"submission.parquet": b"parquet"})
        mock_client.containers.create.return_value = mock_container
        mock_volume = mocker.MagicMock()
        mock_volume.name = "lavbench_seed_vol"
        mock_client.volumes.create.return_value = mock_volume

        retcode, _stdout, _stderr, is_timeout = run_command_streaming(
            mock_client,
            "test:latest",
            ["python", "-u", "submission_sub_1.py"],
            [],
            seed_dir=str(seed),
            collect_files=[("/app/submission.parquet", str(tmp_path / "out.parquet"))],
        )

        assert retcode == 0
        assert is_timeout is False
        mock_client.containers.run.assert_not_called()
        mock_client.containers.create.assert_called_once()
        create_kwargs = mock_client.containers.create.call_args[1]
        assert create_kwargs["volumes"] == {"lavbench_seed_vol": {"bind": "/app", "mode": "rw"}}
        mock_container.put_archive.assert_called_once()
        call = mock_container.put_archive.call_args
        assert call.args[0] == "/app"
        mock_container.start.assert_called_once()
        assert (tmp_path / "out.parquet").read_bytes() == b"parquet"
        mock_container.remove.assert_called()
        mock_volume.remove.assert_called()

    def test_put_archive_failure_removes_container(self, mocker, tmp_path):
        seed = tmp_path / "seed"
        seed.mkdir()
        (seed / "script.py").write_text("print(1)\n")

        mock_client = mocker.MagicMock()
        mock_container = mocker.MagicMock()
        mock_container.put_archive.side_effect = Exception("archive failed")
        mock_client.containers.create.return_value = mock_container
        mock_volume = mocker.MagicMock()
        mock_volume.name = "lavbench_seed_vol"
        mock_client.volumes.create.return_value = mock_volume

        retcode, _stdout, stderr, _is_timeout = run_command_streaming(
            mock_client,
            "test:latest",
            ["python", "-u", "script.py"],
            [],
            seed_dir=str(seed),
        )

        assert retcode == -1
        assert "archive failed" in stderr
        mock_container.remove.assert_called_once_with(force=True)
        mock_volume.remove.assert_called_once()

    def test_collect_missing_file_is_ignored(self, mocker, tmp_path):
        seed = tmp_path / "seed"
        seed.mkdir()
        (seed / "script.py").write_text("print(1)\n")

        mock_client = mocker.MagicMock()
        mock_container = self._make_mock_container(mocker)
        mock_client.containers.create.return_value = mock_container
        mock_volume = mocker.MagicMock()
        mock_volume.name = "lavbench_seed_vol"
        mock_client.volumes.create.return_value = mock_volume

        retcode, _stdout, _stderr, _is_timeout = run_command_streaming(
            mock_client,
            "test:latest",
            ["python", "-u", "script.py"],
            [],
            seed_dir=str(seed),
            collect_files=[("/app/submission.parquet", str(tmp_path / "none.parquet"))],
        )

        assert retcode == 0
        assert not (tmp_path / "none.parquet").exists()
        mock_container.remove.assert_called()
        mock_volume.remove.assert_called()


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


class TestRunStaleDirSweep:
    def test_removes_old_dirs_keeps_fresh(self, mocker, tmp_path):
        mocker.patch.object(Config, "LAVBENCH_WORKSPACE_DIR", str(tmp_path))
        old_dir = tmp_path / "task_old"
        old_dir.mkdir()
        old = time.time() - 30 * 3600
        os.utime(old_dir, (old, old))
        fresh_dir = tmp_path / "task_fresh"
        fresh_dir.mkdir()
        loose_file = tmp_path / "loose.txt"
        loose_file.write_text("keep me")

        logs = []
        removed = run_stale_dir_sweep(max_age_hours=24, logs=logs)

        assert removed == 1
        assert not old_dir.exists()
        assert fresh_dir.exists()
        assert loose_file.exists()
        assert any("task_old" in line for line in logs)

    def test_missing_workspace_returns_zero(self, mocker, tmp_path):
        mocker.patch.object(Config, "LAVBENCH_WORKSPACE_DIR", str(tmp_path / "does-not-exist"))
        assert run_stale_dir_sweep() == 0

    def test_recent_dir_not_removed(self, mocker, tmp_path):
        mocker.patch.object(Config, "LAVBENCH_WORKSPACE_DIR", str(tmp_path))
        recent_dir = tmp_path / "task_recent"
        recent_dir.mkdir()
        os.utime(recent_dir, (time.time() - 3600, time.time() - 3600))
        assert run_stale_dir_sweep(max_age_hours=24) == 0
        assert recent_dir.exists()
