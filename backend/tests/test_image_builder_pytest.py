import json
from collections import namedtuple

import pytest

from task_modules import image_builder as ib
from task_modules.image_builder import (
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
        h1 = _config_hash("img", "pip", ["ds"], ["m"], "tfh", "ech")
        h2 = _config_hash("img", "pip", ["ds"], ["m"], "tfh", "ech")
        assert h1 == h2

    def test_config_hash_sensitive_to_each_input(self):
        base = ("img", "pip", ["ds"], ["m"], "tfh", "ech")
        base_hash = _config_hash(*base)
        variations = (
            ("img2", "pip", ["ds"], ["m"], "tfh", "ech"),
            ("img", "pip2", ["ds"], ["m"], "tfh", "ech"),
            ("img", "pip", ["ds2"], ["m"], "tfh", "ech"),
            ("img", "pip", ["ds"], ["m2"], "tfh", "ech"),
            ("img", "pip", ["ds"], ["m"], "tfh2", "ech"),
            ("img", "pip", ["ds"], ["m"], "tfh", "ech2"),
        )
        for variation in variations:
            assert _config_hash(*variation) != base_hash

    def test_config_hash_ignores_dataset_order(self):
        h1 = _config_hash("img", "pip", ["a", "b"], [], "", "")
        h2 = _config_hash("img", "pip", ["b", "a"], [], "", "")
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
        mocker.patch("task_modules.image_builder.shutil.disk_usage", return_value=usage)
        assert _check_build_disk_space() is True

    def test_insufficient_space_returns_false(self, mocker):
        usage = self.Usage(100, 99, 4 * 1024**3)
        mocker.patch("task_modules.image_builder.shutil.disk_usage", return_value=usage)
        assert _check_build_disk_space() is False

    def test_boundary_exact_minimum_passes(self, mocker):
        usage = self.Usage(100, 50, ib.MIN_BUILD_DISK_GB * 1024**3)
        mocker.patch("task_modules.image_builder.shutil.disk_usage", return_value=usage)
        assert _check_build_disk_space() is True

    def test_oserror_fails_open(self, mocker):
        mocker.patch(
            "task_modules.image_builder.shutil.disk_usage",
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
            "python:3.10-slim", "", [], [], _task_files_hash([]), _eval_code_hash("")
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
        mock_do_build.assert_called_once_with(metadata, log_callback=None)

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
        assert (task_dir / "evaluator_script.py").exists()
        meta = json.loads((task_dir / "hf_meta.json").read_text())
        assert meta["hash"]
        mock_report.assert_called_once_with(42, "", "", "")

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
        mock_report.assert_called_once_with(42, "Insufficient disk space for build", "", "")


class TestReportBuildError:
    def test_missing_params_returns_early(self, mocker):
        mock_post = mocker.patch("requests.post")
        ib._report_build_error(None, "err", "http://server:5000", "tok")
        ib._report_build_error(1, "err", None, "tok")
        ib._report_build_error(1, "err", "http://server:5000", None)
        mock_post.assert_not_called()

    def test_posts_error_to_server(self, mocker):
        mock_post = mocker.patch("requests.post")
        ib._report_build_error(42, "build exploded", "http://server:5000/", "tok123")
        mock_post.assert_called_once()
        url, kwargs = mock_post.call_args[0][0], mock_post.call_args[1]
        assert url == "http://server:5000/api/worker/tasks/42/report-build-error"
        assert kwargs["json"] == {"error": "build exploded"}
        assert kwargs["headers"] == {"X-Worker-Token": "tok123"}
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


class TestRebuildListener:
    def _mock_client(self, mocker, messages):
        mock_r = mocker.MagicMock()
        pubsub = mocker.MagicMock()
        mock_r.pubsub.return_value = pubsub
        mocker.patch.object(ib, "get_coordination_client", return_value=mock_r)

        def get_message(**kwargs):
            if messages:
                return messages.pop(0)
            raise RuntimeError("stop loop")

        pubsub.get_message.side_effect = get_message
        return pubsub

    def test_processes_rebuild_message(self, mocker):
        pubsub = self._mock_client(mocker, [{"type": "message", "data": b"task-42"}])
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "tasks": [
                {
                    "id": "task-42",
                    "base_docker_image": "python:3.10-slim",
                    "pip_requirements": "numpy",
                    "hf_datasets": "[]",
                    "hf_models": "[]",
                    "hf_api_key": "",
                    "task_files": [],
                    "custom_eval_code": "",
                }
            ]
        }
        mocker.patch("requests.get", return_value=mock_resp)
        mock_build = mocker.patch.object(ib, "build_task_image")
        ib._rebuild_listener("http://server:5000", "tok")
        pubsub.subscribe.assert_called_once_with(ib.CHANNEL_TASK_REBUILD)
        mock_build.assert_called_once()
        assert mock_build.call_args[0][0]["task_id"] == "task-42"
        pubsub.unsubscribe.assert_called_once()
        pubsub.close.assert_called_once()

    def test_message_for_unknown_task_is_ignored(self, mocker):
        pubsub = self._mock_client(mocker, [{"type": "message", "data": b"task-99"}])
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"tasks": [{"id": "task-42", "custom_eval_code": ""}]}
        mocker.patch("requests.get", return_value=mock_resp)
        mock_build = mocker.patch.object(ib, "build_task_image")
        ib._rebuild_listener("http://server:5000", "tok")
        mock_build.assert_not_called()
        pubsub.unsubscribe.assert_called_once()

    def test_no_redis_client_returns_early(self, mocker):
        mocker.patch.object(ib, "get_coordination_client", return_value=None)
        ib._rebuild_listener("http://server:5000", "tok")
