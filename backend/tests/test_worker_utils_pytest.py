"""Tests for the worker helpers."""

import base64
import fcntl
import hashlib
import io
import os
import threading
import time
from collections.abc import Iterator
from unittest.mock import patch

import pytest

from config import Config
from utils.files import file_sha256
from utils.worker_auth import sign_worker_token
from utils.worker_utils import (
    DOWNLOAD_TEMP_PREFIX,
    DownloadError,
    MockModel,
    StreamingLogList,
    copy_file_verified,
    download_file,
    fetch_submission_run_content,
    report_status_to_server,
    run_command_streaming,
    run_sandbox,
    run_stale_dir_sweep,
    sync_labels_parquet_to_cache,
    sync_task_files_to_assets_cache,
)


def _mock_response_body(mock_obj, body: bytes, chunk_size: int = 8) -> None:
    """Configure a mocked requests.get response to stream *body* via
    iter_content (matching worker_utils streaming downloads)."""
    mock_obj.status_code = 200
    mock_obj.content = body

    def _iter_content(chunk_size: int = 1024):
        for i in range(0, len(body), min(chunk_size, len(body) or 1)):
            yield body[i : i + chunk_size]

    mock_obj.iter_content.side_effect = _iter_content


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


class TestDownloadFile:
    URL = "http://test:5001/api/worker/tasks/42/files/data.csv"

    @pytest.fixture
    def dest(self, tmp_path):
        data_dir = tmp_path / "task_42" / "data"
        data_dir.mkdir(parents=True)
        return data_dir / "data.csv"

    @patch("utils.worker_utils.requests.get")
    def test_streams_and_verifies(self, mock_get, dest):
        body = b"a,b\n1,2\n" * 10
        _mock_response_body(mock_get.return_value, body, chunk_size=4)
        assert download_file(self.URL, {}, str(dest), size_bytes=len(body), sha256=_sha(body))
        assert dest.read_bytes() == body
        assert mock_get.call_args.kwargs["stream"] is True
        assert mock_get.call_args.kwargs["timeout"] == Config.WORKER_DOWNLOAD_TIMEOUT
        mock_get.return_value.close.assert_called_once()
        assert os.stat(dest).st_mode & 0o777 == 0o644

    @patch("utils.worker_utils.requests.get")
    def test_corrupted_body_keeps_destination(self, mock_get, dest):
        dest.write_bytes(b"old verified")
        _mock_response_body(mock_get.return_value, b"corrupted!")
        with pytest.raises(DownloadError, match="sha256 mismatch"):
            download_file(self.URL, {}, str(dest), size_bytes=10, sha256=_sha(b"expected!!"))
        assert dest.read_bytes() == b"old verified"
        assert os.listdir(dest.parent) == ["data.csv"]

    @patch("utils.worker_utils.requests.get")
    def test_truncated_body_fails_on_size(self, mock_get, dest):
        _mock_response_body(mock_get.return_value, b"short")
        with pytest.raises(DownloadError, match="size mismatch"):
            download_file(self.URL, {}, str(dest), size_bytes=50)
        assert not dest.exists()
        assert os.listdir(dest.parent) == []

    @patch("utils.worker_utils.requests.get")
    def test_partial_download_uses_the_reserved_prefix(self, mock_get, dest):
        seen: list[str] = []

        def _iter_content(chunk_size: int = 1024):
            seen.extend(os.listdir(dest.parent))
            yield b"x"

        mock_get.return_value.status_code = 200
        mock_get.return_value.iter_content.side_effect = _iter_content
        download_file(self.URL, {}, str(dest))
        (partial,) = seen
        assert partial.startswith(DOWNLOAD_TEMP_PREFIX)

    @patch("utils.worker_utils.requests.get")
    def test_http_error_leaves_no_temp_file(self, mock_get, dest):
        mock_get.return_value.status_code = 404
        with pytest.raises(DownloadError, match="HTTP 404"):
            download_file(self.URL, {}, str(dest))
        assert os.listdir(dest.parent) == []

    @patch("utils.worker_utils.requests.get")
    def test_replaces_atomically_from_the_same_directory(self, mock_get, dest):
        _mock_response_body(mock_get.return_value, b"new")
        with patch("utils.worker_utils.os.replace", wraps=os.replace) as spy:
            download_file(self.URL, {}, str(dest), sha256=_sha(b"new"))
        tmp_path, target = spy.call_args.args
        assert os.path.dirname(tmp_path) == str(dest.parent)
        assert target == str(dest)

    @patch("utils.worker_utils.requests.get")
    def test_locked_caller_waits_then_reuses_verified_file(self, mock_get, dest):
        body = b"shared content"
        lock_path = dest.parent.parent / ".locks" / "data-data.csv.lock"
        lock_path.parent.mkdir()
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        result: list[bool] = []
        waiter = threading.Thread(
            target=lambda: result.append(
                download_file(
                    self.URL, {}, str(dest), size_bytes=len(body), sha256=_sha(body), lock=True
                )
            )
        )
        try:
            waiter.start()
            waiter.join(timeout=0.3)
            assert waiter.is_alive(), "the second caller must wait for the lock"
            dest.write_bytes(body)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        waiter.join(timeout=5)
        assert result == [False]
        mock_get.assert_not_called()

    @patch("utils.worker_utils.requests.get")
    def test_lock_redownloads_a_stale_file(self, mock_get, dest):
        dest.write_bytes(b"stale")
        _mock_response_body(mock_get.return_value, b"fresh")
        assert download_file(self.URL, {}, str(dest), sha256=_sha(b"fresh"), lock=True)
        assert dest.read_bytes() == b"fresh"
        assert (dest.parent.parent / ".locks" / "data-data.csv.lock").exists()
        assert sorted(os.listdir(dest.parent)) == ["data.csv"]


class TestDownloadLocking:
    URL = "http://test:5001/api/worker/tasks/42/files/data.csv"

    @pytest.fixture
    def dest(self, tmp_path):
        data_dir = tmp_path / "task_42" / "data"
        data_dir.mkdir(parents=True)
        return data_dir / "data.csv"

    @staticmethod
    def _hold(lock_path):
        lock_path.parent.mkdir(exist_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    @patch("utils.worker_utils.DOWNLOAD_LOCK_MAX_WAIT", 0.2)
    @patch("utils.worker_utils.requests.get")
    def test_lock_wait_is_bounded(self, mock_get, dest):
        fd = self._hold(dest.parent.parent / ".locks" / "data-data.csv.lock")
        try:
            with pytest.raises(DownloadError, match="timed out"):
                download_file(self.URL, {}, str(dest), lock=True)
        finally:
            os.close(fd)
        mock_get.assert_not_called()

    @patch("utils.worker_utils._file_matches")
    @patch("utils.worker_utils.requests.get")
    def test_reuse_false_skips_hashing_a_known_stale_file(self, mock_get, mock_matches, dest):
        dest.write_bytes(b"stale")
        _mock_response_body(mock_get.return_value, b"fresh")
        assert download_file(self.URL, {}, str(dest), sha256=_sha(b"fresh"), lock=True, reuse=False)
        mock_matches.assert_not_called()
        assert dest.read_bytes() == b"fresh"

    def test_copy_file_verified_rejects_a_corrupted_source(self, tmp_path, dest):
        src = tmp_path / "upload.csv"
        src.write_bytes(b"changed")
        dest.write_bytes(b"previous")
        with pytest.raises(DownloadError, match="sha256 mismatch"):
            copy_file_verified(str(src), str(dest), sha256=_sha(b"original"))
        assert dest.read_bytes() == b"previous"
        assert os.listdir(dest.parent) == ["data.csv"]

    def test_copy_file_verified_reuses_a_matching_file(self, tmp_path, dest):
        src = tmp_path / "upload.csv"
        src.write_bytes(b"same")
        assert copy_file_verified(str(src), str(dest), sha256=_sha(b"same")) is True
        assert copy_file_verified(str(src), str(dest), sha256=_sha(b"same")) is False


def test_file_sha256_matches_hashlib(tmp_path):
    path = tmp_path / "blob"
    path.write_bytes(b"x" * (3 * 1024 * 1024 + 5))
    assert file_sha256(str(path)) == _sha(path.read_bytes())


class TestFetchSubmissionRunContent:
    @patch("utils.worker_utils.requests.get")
    @patch(
        "utils.worker_utils.worker_request_headers",
        return_value={
            "X-Worker-Token": "signed-token",
            "X-Worker-Capability": "scoped-capability",
        },
    )
    def test_returns_content_from_server(self, mock_headers, mock_get):
        mock_resp = mock_get.return_value
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "user_code": "print(1)",
            "custom_eval_code": "def evaluate(): pass",
        }
        metadata = {"submission_id": "sub-1", "main_server_url": "http://server:5000"}
        user_code, eval_code = fetch_submission_run_content(metadata)
        assert (user_code, eval_code) == ("print(1)", "def evaluate(): pass")
        url = mock_get.call_args[0][0]
        assert url == "http://server:5000/api/worker/submission-run-content/sub-1"
        assert mock_get.call_args[1]["headers"]["X-Worker-Token"] == "signed-token"
        assert mock_get.call_args[1]["headers"]["X-Worker-Capability"] == "scoped-capability"

    @patch("utils.worker_utils.requests.get")
    @patch(
        "utils.worker_utils.worker_request_headers",
        return_value={
            "X-Worker-Token": "signed-token",
            "X-Worker-Capability": "scoped-capability",
        },
    )
    def test_raises_on_non_200(self, mock_headers, mock_get):
        mock_get.return_value.status_code = 404
        with pytest.raises(RuntimeError, match="404"):
            fetch_submission_run_content(
                {"submission_id": "sub-1", "main_server_url": "http://server:5000"}
            )

    def test_raises_without_server_url(self):
        with pytest.raises(RuntimeError, match="no main_server_url"):
            fetch_submission_run_content({"submission_id": "sub-1"})


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
        monkeypatch.setattr("utils.worker_utils.Config.TASK_IMAGES_DIR", str(tmp_path))
        return tmp_path

    @patch("utils.worker_utils.requests.get")
    def test_first_run_downloads_and_writes_manifest(self, mock_get, cache_env):
        _mock_response_body(mock_get.return_value, b"file content")
        ok = sync_task_files_to_assets_cache(self._metadata(), [])
        assert ok is True
        dest = cache_env / "task_42" / "data" / "data.csv"
        assert dest.read_bytes() == b"file content"
        manifest = (cache_env / "task_42" / ".assets.json").read_text()
        assert '"saved_name": "abc.csv"' in manifest

    @patch("utils.worker_utils.requests.get")
    def test_each_file_download_signs_its_own_token(self, mock_get, cache_env):
        _mock_response_body(mock_get.return_value, b"file content")
        tokens = iter(["tok-1", "tok-2"])
        files = [
            {"filename": "a.csv", "saved_name": "a1.csv"},
            {"filename": "b.csv", "saved_name": "b1.csv"},
        ]
        with patch(
            "utils.worker_utils.worker_request_headers",
            side_effect=lambda *_: {"X-Worker-Token": next(tokens), "X-Worker-Capability": "c"},
        ):
            assert sync_task_files_to_assets_cache(self._metadata(task_files=files), []) is True
        sent = [call.kwargs["headers"]["X-Worker-Token"] for call in mock_get.call_args_list]
        assert sent == ["tok-1", "tok-2"]

    @patch("utils.worker_utils.requests.get")
    def test_unchanged_cache_skips_transfer(self, mock_get, cache_env):
        _mock_response_body(mock_get.return_value, b"file content")
        sync_task_files_to_assets_cache(self._metadata(), [])
        mock_get.reset_mock()
        ok = sync_task_files_to_assets_cache(self._metadata(), [])
        assert ok is True
        mock_get.assert_not_called()

    @patch("utils.worker_utils.requests.get")
    def test_changed_saved_name_redownloads(self, mock_get, cache_env):
        _mock_response_body(mock_get.return_value, b"new content")
        sync_task_files_to_assets_cache(self._metadata(), [])
        sync_task_files_to_assets_cache(
            self._metadata(task_files=[{"filename": "data.csv", "saved_name": "xyz.csv"}]),
            [],
        )
        assert mock_get.call_count == 2
        dest = cache_env / "task_42" / "data" / "data.csv"
        assert dest.read_bytes() == b"new content"

    @patch("utils.worker_utils.requests.get")
    def test_hidden_files_never_reach_the_sandbox_cache(self, mock_get, cache_env):
        _mock_response_body(mock_get.return_value, b"file content")
        files = [
            {"filename": "data.csv", "saved_name": "abc.csv"},
            {"filename": "baseline_submission.parquet", "saved_name": "b.parquet"},
            {"filename": "answers.csv", "saved_name": "c.csv", "visibility": "hidden"},
        ]
        assert sync_task_files_to_assets_cache(self._metadata(task_files=files), []) is True
        urls = [call.args[0] for call in mock_get.call_args_list]
        assert urls == ["http://test:5001/api/worker/tasks/42/files/data.csv"]

    @patch("utils.worker_utils.requests.get")
    def test_labels_parquet_never_in_data_cache(self, mock_get, cache_env):
        _mock_response_body(mock_get.return_value, b"file content")
        metadata = self._metadata(
            task_files=[
                {"filename": "data.csv", "saved_name": "abc.csv"},
                {"filename": "labels.parquet", "saved_name": "labels_1.parquet"},
            ]
        )
        ok = sync_task_files_to_assets_cache(metadata, [])
        assert ok is True
        assert not (cache_env / "task_42" / "data" / "labels.parquet").exists()

    @patch("utils.worker_utils.requests.get")
    def test_sha256_mismatch_fails_sync(self, mock_get, cache_env):
        _mock_response_body(mock_get.return_value, b"tampered")
        entry = {"filename": "data.csv", "saved_name": "abc.csv", "sha256": _sha(b"original")}
        logs: list[str] = []
        ok = sync_task_files_to_assets_cache(self._metadata(task_files=[entry]), logs)
        assert ok is False
        assert not (cache_env / "task_42" / "data" / "data.csv").exists()
        assert any("sha256 mismatch" in line for line in logs)

    @patch("utils.worker_utils.requests.get")
    def test_lock_files_stay_out_of_the_data_dir(self, mock_get, cache_env):
        _mock_response_body(mock_get.return_value, b"file content")
        entry = {"filename": "data.csv", "saved_name": "abc.csv", "sha256": _sha(b"file content")}
        assert sync_task_files_to_assets_cache(self._metadata(task_files=[entry]), [])
        assert os.listdir(cache_env / "task_42" / "data") == ["data.csv"]
        assert (cache_env / "task_42" / ".locks" / "data-data.csv.lock").exists()

    @patch("utils.worker_utils._file_matches")
    @patch("utils.worker_utils.requests.get")
    def test_changed_saved_name_skips_the_reuse_hash(self, mock_get, mock_matches, cache_env):
        mock_matches.return_value = False
        _mock_response_body(mock_get.return_value, b"v1 content")
        sync_task_files_to_assets_cache(self._metadata(), [])
        _mock_response_body(mock_get.return_value, b"v2 content")
        entry = {"filename": "data.csv", "saved_name": "new.csv"}
        assert sync_task_files_to_assets_cache(self._metadata(task_files=[entry]), [])
        assert mock_matches.call_count == 1, "only the first sync, with no manifest entry, checks"
        assert (cache_env / "task_42" / "data" / "data.csv").read_bytes() == b"v2 content"

    @patch("utils.worker_utils.requests.get")
    def test_concurrent_syncs_merge_the_manifest(self, mock_get, cache_env):
        import json as _json

        _mock_response_body(mock_get.return_value, b"same body")
        errors: list[BaseException] = []

        def sync(name):
            try:
                entry = {"filename": name, "saved_name": f"s-{name}"}
                assert sync_task_files_to_assets_cache(self._metadata(task_files=[entry]), [])
            except BaseException as e:
                errors.append(e)

        threads = [threading.Thread(target=sync, args=(f"f{i}.csv",)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        assert errors == []
        task_dir = cache_env / "task_42"
        assert not [n for n in os.listdir(task_dir) if n.endswith(".tmp")]
        assert _json.loads((task_dir / ".assets.json").read_text())["files"]

    @patch("utils.worker_utils.requests.get")
    def test_manifest_write_failure_does_not_fail_the_sync(self, mock_get, cache_env):
        _mock_response_body(mock_get.return_value, b"file content")
        with patch("utils.worker_utils.json.dump", side_effect=OSError("disk full")):
            assert sync_task_files_to_assets_cache(self._metadata(), []) is True
        assert (cache_env / "task_42" / "data" / "data.csv").read_bytes() == b"file content"
        assert not [n for n in os.listdir(cache_env / "task_42") if n.endswith(".tmp")]

    @patch("utils.worker_utils.DOWNLOAD_LOCK_MAX_WAIT", 0.2)
    @patch("utils.worker_utils.requests.get")
    def test_lock_timeout_fails_the_sync(self, mock_get, cache_env):
        lock_path = cache_env / "task_42" / ".locks" / "data-data.csv.lock"
        lock_path.parent.mkdir(parents=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        logs: list[str] = []
        try:
            assert sync_task_files_to_assets_cache(self._metadata(), logs) is False
        finally:
            os.close(fd)
        assert any("timed out" in line for line in logs)

    @patch("utils.worker_utils.requests.get")
    def test_download_failure_returns_false(self, mock_get, cache_env):
        mock_get.return_value.status_code = 404
        ok = sync_task_files_to_assets_cache(self._metadata(), [])
        assert ok is False

    @patch("utils.worker_utils.requests.get")
    def test_labels_0600_and_0700_dir(self, mock_get, cache_env):
        _mock_response_body(mock_get.return_value, b"labels data")
        path = sync_labels_parquet_to_cache(
            self._metadata(task_files=[{"filename": "labels.parquet", "saved_name": "l1.parquet"}]),
            [],
        )
        assert path is not None
        assert (cache_env / "task_42" / "labels" / "labels.parquet").read_bytes() == b"labels data"
        assert os.stat(path).st_mode & 0o777 == 0o600
        assert os.stat(cache_env / "task_42" / "labels").st_mode & 0o777 == 0o700

    def test_labels_unchanged_reuses_cache(self, cache_env):
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

        with patch("utils.worker_utils.requests.get") as mock_get:
            path = sync_labels_parquet_to_cache(metadata, [])
            assert path is not None
            mock_get.assert_not_called()


class TestRunCommandStreaming:
    """Tests for the hardened run_sandbox entry point."""

    def _make_mock_container(self, mocker, exit_code=0):
        mock_container = mocker.MagicMock()
        mock_container.status = "exited"
        mock_container.wait.return_value = {"StatusCode": exit_code}
        mock_container.logs.return_value = [b"line 1\n", b"line 2\n"]
        return mock_container

    def _make_mock_client(self, mocker, exit_code=0):
        mock_client = mocker.MagicMock()
        mock_container = self._make_mock_container(mocker, exit_code=exit_code)
        mock_client.containers.create.return_value = mock_container
        mock_volume = mocker.MagicMock()
        mock_volume.name = "lavbench_seed_vol"
        mock_client.volumes.create.return_value = mock_volume
        return mock_client, mock_container

    def test_successful_run_applies_hardened_policy(self, mocker, tmp_path):
        seed = tmp_path / "seed"
        seed.mkdir()
        (seed / "script.py").write_text("print(1)\n")
        mock_client, _mock_container = self._make_mock_client(mocker, exit_code=0)
        logs = []
        retcode, stdout, _stderr, is_timeout = run_sandbox(
            mock_client,
            "test:latest",
            ["echo", "hello"],
            seed_dir=str(seed),
            collect_files=[("/app/submission.parquet", str(tmp_path / "out.parquet"))],
            logs_list=logs,
        )
        assert retcode == 0
        assert is_timeout is False
        assert "line 1" in stdout
        assert "line 1" in logs
        create_kwargs = mock_client.containers.create.call_args[1]
        assert create_kwargs["network_mode"] == "none"
        assert create_kwargs["cap_drop"] == ["ALL"]
        assert create_kwargs["security_opt"] == ["no-new-privileges:true"]
        assert create_kwargs["pids_limit"] == 64
        assert create_kwargs["tmpfs"] == {"/tmp": "noexec,nosuid,size=128m"}
        assert create_kwargs["user"] == "65534:65534"
        assert create_kwargs["read_only"] is True
        assert create_kwargs["storage_opt"] == {"size": Config.WORKER_SANDBOX_STORAGE_OPT}
        # Per-run anonymous volume, never a host-path bind
        assert create_kwargs["volumes"] == {"lavbench_seed_vol": {"bind": "/app", "mode": "rw"}}

    def test_empty_config_omits_storage_opt(self, mocker, tmp_path):
        seed = tmp_path / "seed"
        seed.mkdir()
        mock_client, _mock_container = self._make_mock_client(mocker, exit_code=0)
        mocker.patch.object(Config, "WORKER_SANDBOX_STORAGE_OPT", "")

        retcode, _stdout, _stderr, _is_timeout = run_sandbox(
            mock_client,
            "test:latest",
            ["echo", "hello"],
            seed_dir=str(seed),
            collect_files=[],
            logs_list=[],
        )

        assert retcode == 0
        create_kwargs = mock_client.containers.create.call_args.kwargs
        assert "storage_opt" not in create_kwargs

    def test_explicit_empty_storage_opt_omits_option(self, mocker, tmp_path):
        seed = tmp_path / "seed"
        seed.mkdir()
        mock_client, _mock_container = self._make_mock_client(mocker, exit_code=0)

        retcode, _stdout, _stderr, _is_timeout = run_sandbox(
            mock_client,
            "test:latest",
            ["echo", "hello"],
            seed_dir=str(seed),
            collect_files=[],
            logs_list=[],
            storage_opt={},
        )

        assert retcode == 0
        create_kwargs = mock_client.containers.create.call_args.kwargs
        assert "storage_opt" not in create_kwargs

    def test_failing_run(self, mocker, tmp_path):
        seed = tmp_path / "seed"
        seed.mkdir()
        mock_client, _mock_container = self._make_mock_client(mocker, exit_code=1)
        logs = []
        retcode, _stdout, _stderr, is_timeout = run_sandbox(
            mock_client,
            "test:latest",
            ["bash", "-c", "exit 1"],
            seed_dir=str(seed),
            collect_files=[],
            logs_list=logs,
        )
        assert retcode == 1
        assert is_timeout is False

    def test_container_start_failure(self, mocker, tmp_path):
        seed = tmp_path / "seed"
        seed.mkdir()
        mock_client = mocker.MagicMock()
        mock_client.containers.create.side_effect = Exception("failed to create container")
        mock_volume = mocker.MagicMock()
        mock_volume.name = "lavbench_seed_vol"
        mock_client.volumes.create.return_value = mock_volume
        logs = []
        retcode, _stdout, stderr, _is_timeout = run_sandbox(
            mock_client,
            "bad:latest",
            ["cmd"],
            seed_dir=str(seed),
            collect_files=[],
            logs_list=logs,
        )
        assert retcode == -1
        assert "failed to create container" in stderr

    def test_storage_opt_failure_fails_closed_and_cleans_up(self, mocker, tmp_path):
        """Reject sandboxes when the daemon cannot enforce the storage quota."""
        seed = tmp_path / "seed"
        seed.mkdir()
        mock_client, _mock_container = self._make_mock_client(mocker, exit_code=0)
        mock_client.containers.create.side_effect = Exception(
            "Backing Filesystem: extfs is not supported for storage_opt"
        )
        logs = []
        retcode, _stdout, stderr, _is_timeout = run_sandbox(
            mock_client,
            "test:latest",
            ["echo", "hello"],
            seed_dir=str(seed),
            collect_files=[],
            logs_list=logs,
        )
        assert retcode == -1
        assert "storage_opt" in stderr
        assert mock_client.containers.create.call_count == 1
        mock_client.volumes.create.return_value.remove.assert_called_once_with()

    def test_timeout_exceeded(self, mocker, tmp_path):
        seed = tmp_path / "seed"
        seed.mkdir()
        mock_client = mocker.MagicMock()
        mock_container = mocker.MagicMock()
        # Simulate the container still running until we kill it
        mock_container.status = "running"
        mock_container.wait.return_value = {"StatusCode": -1}
        mock_container.logs.return_value = []
        mock_client.containers.create.return_value = mock_container
        mock_volume = mocker.MagicMock()
        mock_volume.name = "lavbench_seed_vol"
        mock_client.volumes.create.return_value = mock_volume
        logs = []
        _retcode, _stdout, _stderr, is_timeout = run_sandbox(
            mock_client,
            "test:latest",
            ["sleep", "10"],
            seed_dir=str(seed),
            collect_files=[],
            logs_list=logs,
            time_limit=0.01,
        )
        assert is_timeout
        assert mock_container.kill.call_count >= 1

    def test_logs_populated(self, mocker, tmp_path):
        seed = tmp_path / "seed"
        seed.mkdir()
        mock_client, _mock_container = self._make_mock_client(mocker, exit_code=0)
        logs = []
        run_sandbox(
            mock_client,
            "test:latest",
            ["echo", "hi"],
            seed_dir=str(seed),
            collect_files=[],
            logs_list=logs,
        )
        assert any("line 1" in log for log in logs)
        assert any("line 2" in log for log in logs)

    def test_gpu_device_request(self, mocker, tmp_path):
        seed = tmp_path / "seed"
        seed.mkdir()
        mock_client, _mock_container = self._make_mock_client(mocker, exit_code=0)
        logs = []
        run_sandbox(
            mock_client,
            "test:latest",
            ["cmd"],
            seed_dir=str(seed),
            collect_files=[],
            logs_list=logs,
            gpu_required=True,
            gpu_id="1",
        )
        call_kwargs = mock_client.containers.create.call_args[1]
        assert call_kwargs["device_requests"] is not None
        dr = call_kwargs["device_requests"][0]
        assert dr.device_ids == ["1"]
        assert ["gpu"] in dr.capabilities

    def test_gpu_ids_not_configured_falls_back_to_all(self, mocker, tmp_path):
        seed = tmp_path / "seed"
        seed.mkdir()
        mock_client, _mock_container = self._make_mock_client(mocker, exit_code=0)
        run_sandbox(
            mock_client,
            "test:latest",
            ["cmd"],
            seed_dir=str(seed),
            collect_files=[],
            logs_list=[],
            gpu_required=True,
        )
        dr = mock_client.containers.create.call_args[1]["device_requests"][0]
        assert dr.device_ids == []
        assert dr.count == -1


class TestSeedTarNormalization:
    def test_normalizes_ownership_and_modes(self):
        import tarfile

        from utils.worker_utils import SANDBOX_GID, SANDBOX_UID, _normalize_seed_tar_member

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
        """docker-py returns get_archive streams as byte-chunk generators."""
        import io
        import tarfile

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for name, content in files.items():
                info = tarfile.TarInfo(name=name)
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
        data = buf.getvalue()

        def _chunks() -> Iterator[bytes]:
            for i in range(0, len(data), 4096):
                yield data[i : i + 4096]

        return _chunks()

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

    def test_collect_archive_exceeding_buffer_cap_is_skipped(self, mocker, tmp_path):
        from config import Config

        original = Config.MAX_COLLECT_BUFFER_BYTES
        Config.MAX_COLLECT_BUFFER_BYTES = 64
        try:
            seed = tmp_path / "seed"
            seed.mkdir()
            mock_client = mocker.MagicMock()
            mock_container = self._make_mock_container(
                mocker, files={"submission.parquet": b"parquet"}
            )
            mock_client.containers.create.return_value = mock_container
            mock_volume = mocker.MagicMock()
            mock_volume.name = "lavbench_seed_vol"
            mock_client.volumes.create.return_value = mock_volume

            retcode, _stdout, _stderr, _ = run_command_streaming(
                mock_client,
                "test:latest",
                ["python", "-u", "script.py"],
                [],
                seed_dir=str(seed),
                collect_files=[("/app/submission.parquet", str(tmp_path / "out.parquet"))],
            )
            assert retcode == 0
            assert not (tmp_path / "out.parquet").exists()
        finally:
            Config.MAX_COLLECT_BUFFER_BYTES = original

    def test_collect_oversized_member_is_skipped(self, mocker, tmp_path):
        from config import Config

        original = Config.MAX_EXTRACT_MEMBER_BYTES
        Config.MAX_EXTRACT_MEMBER_BYTES = 2
        try:
            seed = tmp_path / "seed"
            seed.mkdir()
            mock_client = mocker.MagicMock()
            mock_container = self._make_mock_container(
                mocker, files={"submission.parquet": b"parquet"}
            )
            mock_client.containers.create.return_value = mock_container
            mock_volume = mocker.MagicMock()
            mock_volume.name = "lavbench_seed_vol"
            mock_client.volumes.create.return_value = mock_volume

            run_command_streaming(
                mock_client,
                "test:latest",
                ["python", "-u", "script.py"],
                [],
                seed_dir=str(seed),
                collect_files=[("/app/submission.parquet", str(tmp_path / "out.parquet"))],
            )
            assert not (tmp_path / "out.parquet").exists()
        finally:
            Config.MAX_EXTRACT_MEMBER_BYTES = original

    def test_seed_tar_has_writable_root_entry(self, mocker, tmp_path):
        """put_archive ignores '.' root metadata, so a leading '/' entry must
        chown/chmod the /app mount point itself (writable by the sandbox user)."""
        import tarfile

        from utils.worker_utils import SANDBOX_GID, SANDBOX_UID

        seed = tmp_path / "seed"
        seed.mkdir()
        (seed / "script.py").write_text("print(1)\n")

        mock_client = mocker.MagicMock()
        mock_container = self._make_mock_container(mocker)
        mock_client.containers.create.return_value = mock_container
        mock_volume = mocker.MagicMock()
        mock_volume.name = "lavbench_seed_vol"
        mock_client.volumes.create.return_value = mock_volume

        captured: dict[str, bytes] = {}

        def _capture(_path: str, fileobj) -> None:
            captured["tar"] = fileobj.read()

        mock_container.put_archive.side_effect = _capture

        run_command_streaming(
            mock_client,
            "test:latest",
            ["python", "-u", "script.py"],
            [],
            seed_dir=str(seed),
        )

        with tarfile.open(fileobj=io.BytesIO(captured["tar"]), mode="r") as tar:
            members = tar.getmembers()
        assert members[0].name in ("", "/")  # tarfile normalizes "/" to ""
        assert members[0].type == tarfile.DIRTYPE
        assert members[0].type == tarfile.DIRTYPE
        assert members[0].mode == 0o777
        assert members[0].uid == SANDBOX_UID
        assert members[0].gid == SANDBOX_GID

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
    def test_append_immediately_flushes_single_line(self):
        with patch("utils.sse_utils.publish_submission_log_batch") as mock_publish:
            stream = StreamingLogList(submission_id=123)
            stream.append("test line")
            mock_publish.assert_called_once_with(123, ["test line"])

    def test_append_batches_many_lines(self):
        with patch("utils.sse_utils.publish_submission_log_batch") as mock_publish:
            stream = StreamingLogList(submission_id=123)
            for i in range(100):
                stream.append(f"line {i}")
            stream.flush()
            batches = [call.args[1] for call in mock_publish.call_args_list]
            assert len(mock_publish.call_args_list) >= 2
            assert all(len(b) <= 50 for b in batches)
            assert [line for batch in batches for line in batch] == [
                f"line {i}" for i in range(100)
            ]

    def test_max_length_trims(self):
        with patch("utils.sse_utils.publish_submission_log_batch"):
            stream = StreamingLogList(submission_id=1)
            for i in range(10001):
                stream.append(f"line {i}")
        assert len(stream) <= 10000

    def test_publish_exception_caught(self):
        with patch(
            "utils.sse_utils.publish_submission_log_batch", side_effect=Exception("SSE error")
        ):
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
    """Tests for sign_worker_token."""

    def test_missing_key_returns_empty(self, monkeypatch):
        monkeypatch.delenv("WORKER_PRIVATE_KEY", raising=False)
        assert sign_worker_token() == ""

    def test_invalid_key_returns_empty(self, monkeypatch):
        monkeypatch.setenv("WORKER_PRIVATE_KEY", "not-valid-base64")
        assert sign_worker_token() == ""

    def test_valid_key_returns_token(self, monkeypatch):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        priv = Ed25519PrivateKey.generate()
        priv_b64 = base64.b64encode(priv.private_bytes_raw()).decode()
        monkeypatch.setenv("WORKER_ID", "test-worker")
        monkeypatch.setenv("WORKER_PRIVATE_KEY", priv_b64)

        token = sign_worker_token()
        assert "." in token

        version, worker_id, timestamp, nonce, b64_sig = token.split(".", 4)
        assert version == "v1"
        assert worker_id == "test-worker"

        signature = base64.urlsafe_b64decode(b64_sig + "=" * (-len(b64_sig) % 4))
        pub = priv.public_key()
        pub.verify(signature, f"{version}.{worker_id}.{timestamp}.{nonce}".encode())

    def test_token_format(self, monkeypatch):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        priv = Ed25519PrivateKey.generate()
        monkeypatch.setenv(
            "WORKER_PRIVATE_KEY",
            base64.b64encode(priv.private_bytes_raw()).decode(),
        )
        monkeypatch.setenv("WORKER_ID", "test-worker")
        token = sign_worker_token()
        assert token.count(".") == 4
        assert token.split(".", 2)[:2] == ["v1", "test-worker"]

    def test_each_call_gives_a_new_token(self, monkeypatch):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        priv = Ed25519PrivateKey.generate()
        monkeypatch.setenv(
            "WORKER_PRIVATE_KEY",
            base64.b64encode(priv.private_bytes_raw()).decode(),
        )
        monkeypatch.setenv("WORKER_ID", "test-worker")
        t1 = sign_worker_token()
        t2 = sign_worker_token()
        assert t1 != t2


class TestReportStatusToServer:
    @patch("utils.worker_utils.requests.post")
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

    @patch("utils.worker_utils.requests.post")
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

    @patch("utils.worker_utils.requests.post")
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

    @patch("utils.worker_utils.requests.post")
    def test_no_metadata_returns_false(self, mock_post):
        result = report_status_to_server({}, "completed", "done")
        assert result is False
        mock_post.assert_not_called()

    @patch("utils.worker_utils.requests.post")
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

    @patch("utils.worker_utils.requests.post")
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
