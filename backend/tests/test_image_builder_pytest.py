"""Tests for the Docker image builder."""

import json
import os
from collections import namedtuple

import pytest

from tasks.task_modules import image_builder as ib
from tasks.task_modules.image_builder import (
    _build_lock_key,
    _check_build_disk_space,
    _clear_stale_build_locks,
    _config_hash,
    _eval_code_hash,
    _release_build_lock,
    _task_files_hash,
    _try_acquire_build_lock,
    build_task_image,
    clear_build_lock,
)


def _metadata(**overrides):
    metadata = {
        "task_id": 42,
        "base_docker_image": "python:3.10-slim",
        "pip_requirements": "",
        "hf_datasets": [],
        "hf_models": [],
        "hf_api_key": "",
        "task_files": [],
        "custom_eval_code": "",
        "_main_server_url": "",
        "_worker_token": "",
    }
    metadata.update(overrides)
    return metadata


class TestHashes:
    def test_config_hash_deterministic(self):
        h1 = _config_hash("img", "pip", "apt", ["ds"], ["m"], "tfh", "ech")
        h2 = _config_hash("img", "pip", "apt", ["ds"], ["m"], "tfh", "ech")
        assert h1 == h2

    def test_config_hash_sensitive_to_each_input(self):
        base = ("img", "pip", "apt", ["ds"], ["m"], "tfh", "ech")
        base_hash = _config_hash(*base)
        variations = (
            ("img2", "pip", "apt", ["ds"], ["m"], "tfh", "ech"),
            ("img", "pip2", "apt", ["ds"], ["m"], "tfh", "ech"),
            ("img", "pip", "apt2", ["ds"], ["m"], "tfh", "ech"),
            ("img", "pip", "apt", ["ds2"], ["m"], "tfh", "ech"),
            ("img", "pip", "apt", ["ds"], ["m2"], "tfh", "ech"),
            ("img", "pip", "apt", ["ds"], ["m"], "tfh2", "ech"),
            ("img", "pip", "apt", ["ds"], ["m"], "tfh", "ech2"),
        )
        for variation in variations:
            assert _config_hash(*variation) != base_hash

    def test_config_hash_sensitive_to_hf_key_presence(self):
        base_hash = _config_hash("img", "pip", "apt", ["ds"], ["m"], "tfh", "ech")
        keyed = _config_hash("img", "pip", "apt", ["ds"], ["m"], "tfh", "ech", hf_key_present=True)
        assert keyed != base_hash

    def test_config_hash_ignores_dataset_order(self):
        h1 = _config_hash("img", "pip", "apt", ["a", "b"], [], "", "")
        h2 = _config_hash("img", "pip", "apt", ["b", "a"], [], "", "")
        assert h1 == h2

    def test_task_files_hash_empty(self):
        assert _task_files_hash([]) == ""
        assert _task_files_hash(None) == ""

    def test_task_files_hash_deterministic_and_sensitive(self):
        files = [
            {"filename": "a.txt", "size_bytes": 10},
            {"filename": "b.txt", "size_bytes": 20},
        ]
        assert _task_files_hash(files) == _task_files_hash(files)
        changed = [
            {"filename": "a.txt", "size_bytes": 11},
            {"filename": "b.txt", "size_bytes": 20},
        ]
        assert _task_files_hash(files) != _task_files_hash(changed)

    def test_eval_code_hash_none_and_empty_same(self):
        assert _eval_code_hash(None) == _eval_code_hash("")
        assert _eval_code_hash("code") != _eval_code_hash("")


class TestBuildLockKey:
    def test_lock_key_format(self):
        assert _build_lock_key(42) == f"docker_build:lock:{ib._WORKER_HOSTNAME}:42"


class TestTryAcquireBuildLock:
    def test_acquired_when_setnx_truthy(self, mocker):
        mock_r = mocker.MagicMock()
        mock_r.set.return_value = True
        mocker.patch.object(ib, "get_coordination_client", return_value=mock_r)
        assert _try_acquire_build_lock(42) is True
        mock_r.set.assert_called_once_with(
            _build_lock_key(42), ib._WORKER_HOSTNAME, nx=True, ex=ib.BUILD_LOCK_TTL
        )

    def test_failed_when_setnx_falsy(self, mocker):
        mock_r = mocker.MagicMock()
        mock_r.set.return_value = None
        mocker.patch.object(ib, "get_coordination_client", return_value=mock_r)
        assert _try_acquire_build_lock(42) is False

    def test_failed_without_client(self, mocker):
        mocker.patch.object(ib, "get_coordination_client", return_value=None)
        assert _try_acquire_build_lock(42) is False

    def test_failed_when_set_raises(self, mocker):
        mock_r = mocker.MagicMock()
        mock_r.set.side_effect = Exception("redis down")
        mocker.patch.object(ib, "get_coordination_client", return_value=mock_r)
        assert _try_acquire_build_lock(42) is False


class TestReleaseBuildLock:
    def test_deletes_lock_key(self, mocker):
        mock_r = mocker.MagicMock()
        mocker.patch.object(ib, "get_coordination_client", return_value=mock_r)
        _release_build_lock(42)
        mock_r.delete.assert_called_once_with(_build_lock_key(42))

    def test_no_client_is_noop(self, mocker):
        mocker.patch.object(ib, "get_coordination_client", return_value=None)
        _release_build_lock(42)


class TestCheckBuildDiskSpace:
    Usage = namedtuple("Usage", "total used free")

    @pytest.fixture(autouse=True)
    def _tmp_images_dir(self, tmp_path, mocker):
        mocker.patch.object(ib, "TASK_IMAGES_DIR", str(tmp_path))
        yield tmp_path

    def test_enough_space_returns_true(self, mocker):
        usage = self.Usage(100, 50, 10 * 1024**3)
        mocker.patch("tasks.task_modules.image_builder.shutil.disk_usage", return_value=usage)
        assert _check_build_disk_space() is True

    def test_insufficient_space_returns_false(self, mocker):
        usage = self.Usage(100, 99, 4 * 1024**3)
        mocker.patch("tasks.task_modules.image_builder.shutil.disk_usage", return_value=usage)
        assert _check_build_disk_space() is False

    def test_boundary_exact_minimum_passes(self, mocker):
        usage = self.Usage(100, 50, ib.MIN_BUILD_DISK_GB * 1024**3)
        mocker.patch("tasks.task_modules.image_builder.shutil.disk_usage", return_value=usage)
        assert _check_build_disk_space() is True

    def test_oserror_fails_open(self, mocker):
        mocker.patch(
            "tasks.task_modules.image_builder.shutil.disk_usage",
            side_effect=OSError("no such dir"),
        )
        assert _check_build_disk_space() is True


class TestBuildTaskImage:
    @pytest.fixture(autouse=True)
    def _tmp_images_dir(self, tmp_path, mocker):
        mocker.patch.object(ib, "TASK_IMAGES_DIR", str(tmp_path))
        yield tmp_path

    def test_cache_hit_skips_build(self, mocker, _tmp_images_dir):
        metadata = _metadata()
        expected = _config_hash(
            "python:3.10-slim", "", "", [], [], _task_files_hash([]), _eval_code_hash("")
        )
        task_dir = _tmp_images_dir / "task_42"
        task_dir.mkdir()
        (task_dir / "hf_meta.json").write_text(json.dumps({"hash": expected}))
        mocker.patch.object(ib, "_image_exists", return_value=True)
        mock_acquire = mocker.patch.object(ib, "_try_acquire_build_lock")
        mock_do_build = mocker.patch.object(ib, "_do_build")
        assert build_task_image(metadata) is True
        mock_acquire.assert_not_called()
        mock_do_build.assert_not_called()

    def test_rebuild_path_when_hash_changed(self, mocker, _tmp_images_dir):
        metadata = _metadata()
        task_dir = _tmp_images_dir / "task_42"
        task_dir.mkdir()
        (task_dir / "hf_meta.json").write_text(json.dumps({"hash": "stale-hash"}))
        mocker.patch.object(ib, "_image_exists", return_value=True)
        mock_acquire = mocker.patch.object(ib, "_try_acquire_build_lock", return_value=True)
        mock_do_build = mocker.patch.object(ib, "_do_build", return_value=True)
        assert build_task_image(metadata) is True
        mock_acquire.assert_called_once_with(42, timeout=ib.BUILD_LOCK_MAX_WAIT)
        mock_do_build.assert_called_once_with(metadata, log_callback=None, force_rebuild=False)

    def test_force_rebuild_bypasses_fast_path(self, mocker, _tmp_images_dir):
        metadata = _metadata()
        expected = _config_hash(
            "python:3.10-slim", "", "", [], [], _task_files_hash([]), _eval_code_hash("")
        )
        task_dir = _tmp_images_dir / "task_42"
        task_dir.mkdir()
        (task_dir / "hf_meta.json").write_text(json.dumps({"hash": expected}))
        mocker.patch.object(ib, "_image_exists", return_value=True)
        mock_acquire = mocker.patch.object(ib, "_try_acquire_build_lock", return_value=True)
        mock_do_build = mocker.patch.object(ib, "_do_build", return_value=True)
        assert build_task_image(metadata, force_rebuild=True) is True
        mock_acquire.assert_called_once_with(42, timeout=ib.BUILD_LOCK_MAX_WAIT)
        mock_do_build.assert_called_once_with(metadata, log_callback=None, force_rebuild=True)

    def test_do_build_force_rebuild_skips_hash_short_circuit(self, mocker, _tmp_images_dir):
        metadata = _metadata()
        expected = _config_hash(
            "python:3.10-slim", "", "", [], [], _task_files_hash([]), _eval_code_hash("")
        )
        task_dir = _tmp_images_dir / "task_42"
        task_dir.mkdir()
        (task_dir / "hf_meta.json").write_text(json.dumps({"hash": expected}))
        mocker.patch.object(ib, "_image_exists", return_value=True)
        mocker.patch.object(ib, "_check_build_disk_space", return_value=True)
        mock_build = mocker.patch.object(ib, "_run_docker_build", return_value=(0, "", "", False))
        mock_report = mocker.patch.object(ib, "_report_build_error")
        assert ib._do_build(metadata, force_rebuild=True) is True
        mock_build.assert_called_once()
        mock_report.assert_any_call(42, "", "", None)

    def test_image_missing_triggers_build(self, mocker, _tmp_images_dir):
        metadata = _metadata()
        mocker.patch.object(ib, "_image_exists", return_value=False)
        mocker.patch.object(ib, "_try_acquire_build_lock", return_value=True)
        mock_do_build = mocker.patch.object(ib, "_do_build", return_value=True)
        assert build_task_image(metadata) is True
        mock_do_build.assert_called_once()

    def test_lock_failure_returns_existing_image(self, mocker, _tmp_images_dir):
        metadata = _metadata()
        mocker.patch.object(ib, "_try_acquire_build_lock", return_value=False)
        mocker.patch.object(ib, "_image_exists", side_effect=[False, True])
        assert build_task_image(metadata) is True

    def test_lock_failure_without_image_returns_false(self, mocker, _tmp_images_dir):
        metadata = _metadata()
        mocker.patch.object(ib, "_try_acquire_build_lock", return_value=False)
        mocker.patch.object(ib, "_image_exists", return_value=False)
        assert build_task_image(metadata) is False

    def test_do_build_failure_returns_false_and_releases_lock(self, mocker, _tmp_images_dir):
        metadata = _metadata()
        mocker.patch.object(ib, "_image_exists", return_value=False)
        mocker.patch.object(ib, "_try_acquire_build_lock", return_value=True)
        mock_do_build = mocker.patch.object(ib, "_do_build", return_value=False)
        mock_release = mocker.patch.object(ib, "_release_build_lock")
        assert build_task_image(metadata) is False
        mock_do_build.assert_called_once()
        mock_release.assert_called_once_with(42)

    def test_missing_task_id_returns_false(self, mocker):
        assert build_task_image({}) is False


class TestEnsureTaskImage:
    @pytest.fixture(autouse=True)
    def _tmp_images_dir(self, tmp_path, mocker):
        mocker.patch.object(ib, "TASK_IMAGES_DIR", str(tmp_path))
        yield tmp_path

    def test_returns_true_when_build_succeeds(self, mocker):
        mocker.patch.object(ib, "build_task_image", return_value=True)
        assert ib.ensure_task_image(_metadata()) is True

    def test_returns_true_when_image_appears(self, mocker):
        mocker.patch.object(ib, "build_task_image", return_value=False)
        mocker.patch.object(ib, "_image_exists", side_effect=[False, True])
        assert ib.ensure_task_image(_metadata()) is True

    def test_returns_false_after_retries(self, mocker):
        mock_build = mocker.patch.object(ib, "build_task_image", return_value=False)
        mocker.patch.object(ib, "_image_exists", return_value=False)
        mocker.patch.object(ib.time, "sleep")
        assert ib.ensure_task_image(_metadata()) is False
        assert mock_build.call_count == 3


class TestDoBuild:
    @pytest.fixture(autouse=True)
    def _tmp_images_dir(self, tmp_path, mocker):
        mocker.patch.object(ib, "TASK_IMAGES_DIR", str(tmp_path))
        yield tmp_path

    def test_success_writes_meta_and_dockerfile(self, mocker, _tmp_images_dir):
        mocker.patch.object(ib, "_image_exists", return_value=False)
        mocker.patch.object(ib, "_check_build_disk_space", return_value=True)
        mocker.patch.object(ib, "_download_dataset")
        mocker.patch.object(ib, "_download_model")
        mocker.patch.object(ib, "_download_task_file_for_build")
        mocker.patch.object(ib, "_run_docker_build", return_value=(0, "", "", False))
        mock_report = mocker.patch.object(ib, "_report_build_error")
        metadata = _metadata(
            pip_requirements="numpy",
            hf_datasets='["ds1"]',
            hf_models='["m1"]',
            custom_eval_code="def evaluate(): pass",
            task_files=[{"filename": "data.csv", "saved_name": "data.csv"}],
        )
        assert ib._do_build(metadata) is True
        task_dir = _tmp_images_dir / "task_42"
        assert (task_dir / "Dockerfile").exists()
        assert (task_dir / "requirements.txt").exists()
        assert not (task_dir / "evaluator_script.py").exists()
        assert "evaluator_script.py" not in (task_dir / "Dockerfile").read_text()
        # Sandbox working dirs must be owned by the sandbox user so per-run volumes are writable
        last_line = (task_dir / "Dockerfile").read_text().strip().splitlines()[-1]
        assert last_line == (
            "RUN mkdir -p /app /work && chown 65534:65534 /app /work && chmod 0755 /app /work"
        )
        meta = json.loads((task_dir / "hf_meta.json").read_text())
        assert meta["hash"]
        mock_report.assert_called_once_with(42, "", "", None)

    def test_build_rc_failure_reports_error(self, mocker, _tmp_images_dir):
        mocker.patch.object(ib, "_image_exists", return_value=False)
        mocker.patch.object(ib, "_check_build_disk_space", return_value=True)
        mocker.patch.object(ib, "_download_dataset")
        mocker.patch.object(ib, "_download_model")

        def fake_run_docker_build(tag, build_dir, logs, log_callback=None):
            logs.append("compile error line")
            return (1, "", "compile error", False)

        mocker.patch.object(ib, "_run_docker_build", side_effect=fake_run_docker_build)
        mock_report = mocker.patch.object(ib, "_report_build_error")
        assert ib._do_build(_metadata()) is False
        mock_report.assert_called_once()
        assert "compile error line" in mock_report.call_args[0][1]

    def test_disk_space_failure_reports_and_returns_false(self, mocker, _tmp_images_dir):
        mocker.patch.object(ib, "_image_exists", return_value=False)
        mocker.patch.object(ib, "_check_build_disk_space", return_value=False)
        mock_report = mocker.patch.object(ib, "_report_build_error")
        assert ib._do_build(_metadata()) is False
        mock_report.assert_called_once_with(42, "Insufficient disk space for build", "", None)


class TestDownloadTaskFileForBuild:
    def test_uses_the_verified_locked_download(self, mocker, tmp_path):
        mocker.patch.object(ib, "worker_request_headers", return_value={"X-Worker-Token": "t"})
        mock_download = mocker.patch.object(ib, "download_file")
        entry = {"filename": "data.csv", "saved_name": "x.csv", "size_bytes": 3, "sha256": "ab"}
        metadata = {"_main_server_url": "http://server/", "_worker_metadata": {"worker": 1}}
        ib._download_task_file_for_build(42, entry, str(tmp_path), metadata)
        args, kwargs = mock_download.call_args
        assert args[0] == "http://server/api/worker/tasks/42/files/data.csv"
        assert args[2] == str(tmp_path / "data.csv")
        assert kwargs == {"size_bytes": 3, "sha256": "ab", "lock": True}

    def test_mismatch_becomes_a_build_sync_error(self, mocker, tmp_path):
        from utils.worker_utils import DownloadError

        mocker.patch.object(ib, "worker_request_headers", return_value={})
        mocker.patch.object(ib, "download_file", side_effect=DownloadError("sha256 mismatch"))
        metadata = {"_main_server_url": "http://server", "_worker_metadata": {"worker": 1}}
        with pytest.raises(RuntimeError, match="sha256 mismatch"):
            ib._download_task_file_for_build(42, {"filename": "a.csv"}, str(tmp_path), metadata)


class TestBuildContextIgnore:
    def test_locks_and_partial_downloads_stay_out_of_the_context(self, mocker, tmp_path):
        from docker.utils.build import exclude_paths

        mocker.patch.object(ib, "TASK_IMAGES_DIR", str(tmp_path))
        mocker.patch.object(ib, "_image_exists", return_value=False)
        mocker.patch.object(ib, "_check_build_disk_space", return_value=True)
        mocker.patch.object(ib, "_download_task_file_for_build")
        contexts = []

        def fake_build(tag, build_dir, logs, log_callback=None):
            with open(os.path.join(build_dir, ".dockerignore")) as fh:
                patterns = [line for line in fh.read().splitlines() if line]
            contexts.append(set(exclude_paths(build_dir, patterns)))
            return 0, "", "", False

        mocker.patch.object(ib, "_run_docker_build", side_effect=fake_build)
        mocker.patch.object(ib, "_report_build_error")
        task_dir = tmp_path / "task_42"
        (task_dir / "data").mkdir(parents=True)
        (task_dir / "data" / "data.csv").write_bytes(b"ok")
        (task_dir / "data" / ".download-data.csv.abc.tmp").write_bytes(b"partial")
        (task_dir / ".locks").mkdir()
        (task_dir / ".locks" / "data-data.csv.lock").write_bytes(b"")
        (task_dir / "labels").mkdir()
        (task_dir / "labels" / "labels.parquet").write_bytes(b"ground truth")
        metadata = _metadata(task_files=[{"filename": "data.csv", "saved_name": "data.csv"}])
        assert ib._do_build(metadata) is True
        (context,) = contexts
        assert "data/data.csv" in context
        assert "Dockerfile" in context
        assert not any(".download-" in path or ".locks" in path for path in context)
        assert not any(path.startswith("labels") for path in context)


class TestLocalTaskFileCopy:
    """The build copies local uploads through the locked, verified path."""

    @pytest.fixture
    def env(self, mocker, tmp_path):
        import hashlib

        mocker.patch.object(ib, "TASK_IMAGES_DIR", str(tmp_path / "images"))
        uploads = tmp_path / "uploads"
        (uploads / "task_42").mkdir(parents=True)
        (uploads / "task_42" / "x-data.csv").write_bytes(b"local bytes")
        mocker.patch.object(ib.Config, "UPLOAD_FOLDER", str(uploads), create=True)
        mocker.patch.object(ib, "_image_exists", return_value=False)
        mocker.patch.object(ib, "_check_build_disk_space", return_value=True)
        mocker.patch.object(ib, "_run_docker_build", return_value=(0, "", "", False))
        mock_download = mocker.patch.object(ib, "_download_task_file_for_build")
        report = mocker.patch.object(ib, "_report_build_error")
        entry = {
            "filename": "data.csv",
            "saved_name": "x-data.csv",
            "size_bytes": 11,
            "sha256": hashlib.sha256(b"local bytes").hexdigest(),
        }
        return tmp_path / "images" / "task_42", entry, mock_download, report

    def test_copies_atomically_under_the_file_lock(self, env):
        task_dir, entry, mock_download, _ = env
        assert ib._do_build(_metadata(task_files=[entry])) is True
        assert (task_dir / "data" / "data.csv").read_bytes() == b"local bytes"
        assert (task_dir / ".locks" / "data-data.csv.lock").exists()
        assert os.listdir(task_dir / "data") == ["data.csv"]
        mock_download.assert_not_called()

    def test_corrupted_local_file_fails_the_build(self, env):
        task_dir, entry, _, report = env
        entry["sha256"] = "0" * 64
        assert ib._do_build(_metadata(task_files=[entry])) is False
        assert not (task_dir / "data" / "data.csv").exists()
        assert report.call_args.kwargs["problem_codes"] == ["ERR_TASK_FILE_SYNC_FAILED"]


class TestReportBuildError:
    def test_missing_params_returns_early(self, mocker):
        mock_post = mocker.patch("requests.post")
        ib._report_build_error(None, "err", "http://server:5000", "tok")
        ib._report_build_error(1, "err", None, "tok")
        ib._report_build_error(1, "err", "http://server:5000", None)
        mock_post.assert_not_called()

    def test_posts_error_to_server(self, mocker):
        mock_post = mocker.patch("requests.post")
        mocker.patch.object(
            ib,
            "worker_request_headers",
            return_value={
                "X-Worker-Token": "tok123",
                "X-Worker-Capability": "scoped-capability",
            },
        )
        ib._report_build_error(42, "build exploded", "http://server:5000/", {"task_id": 42})
        mock_post.assert_called_once()
        url, kwargs = mock_post.call_args[0][0], mock_post.call_args[1]
        assert url == "http://server:5000/api/worker/tasks/42/report-build-error"
        assert kwargs["json"] == {"error": "build exploded"}
        assert kwargs["headers"] == {
            "X-Worker-Token": "tok123",
            "X-Worker-Capability": "scoped-capability",
        }
        assert kwargs["timeout"] == 10

    def test_exception_is_swallowed(self, mocker):
        mocker.patch("requests.post", side_effect=Exception("network down"))
        ib._report_build_error(42, "err", "http://server:5000", "tok")


class TestClearBuildLock:
    def test_cleared_returns_true(self, mocker):
        mock_r = mocker.MagicMock()
        mock_r.delete.return_value = 1
        mocker.patch.object(ib, "get_coordination_client", return_value=mock_r)
        assert clear_build_lock(42) is True
        mock_r.delete.assert_called_once_with(_build_lock_key(42))

    def test_no_lock_returns_false(self, mocker):
        mock_r = mocker.MagicMock()
        mock_r.delete.return_value = 0
        mocker.patch.object(ib, "get_coordination_client", return_value=mock_r)
        assert clear_build_lock(42) is False

    def test_no_client_returns_false(self, mocker):
        mocker.patch.object(ib, "get_coordination_client", return_value=None)
        assert clear_build_lock(42) is False

    def test_exception_returns_false(self, mocker):
        mock_r = mocker.MagicMock()
        mock_r.delete.side_effect = Exception("redis down")
        mocker.patch.object(ib, "get_coordination_client", return_value=mock_r)
        assert clear_build_lock(42) is False


class TestClearStaleBuildLocks:
    def test_deletes_all_matching_keys(self, mocker):
        mock_r = mocker.MagicMock()
        mock_r.scan_iter.return_value = [
            b"docker_build:lock:host:1",
            b"docker_build:lock:host:2",
        ]
        mocker.patch.object(ib, "get_coordination_client", return_value=mock_r)
        _clear_stale_build_locks()
        assert mock_r.delete.call_count == 2

    def test_no_client_is_noop(self, mocker):
        mocker.patch.object(ib, "get_coordination_client", return_value=None)
        _clear_stale_build_locks()

    def test_exception_is_swallowed(self, mocker):
        mock_r = mocker.MagicMock()
        mock_r.scan_iter.side_effect = Exception("redis down")
        mocker.patch.object(ib, "get_coordination_client", return_value=mock_r)
        _clear_stale_build_locks()
