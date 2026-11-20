"""Tests for the Docker image builder."""

import os
from collections import namedtuple

import pytest

from tasks.task_modules import image_builder as ib
from tasks.task_modules.image_builder import (
    _build_lock_key,
    _check_build_disk_space,
    _config_hash,
    _eval_code_hash,
    _task_files_hash,
    build_task_image,
)


def _metadata(**overrides):
    metadata = {
        "task_id": 42,
        "base_docker_image": "python:3.10-slim",
        "pip_requirements": "",
        "task_files": [],
        "custom_eval_code": "",
        "_main_server_url": "",
        "_worker_token": "",
    }
    metadata.update(overrides)
    return metadata


class TestHashes:
    def test_config_hash_deterministic(self):
        h1 = _config_hash("img", "pip", "apt", "tfh", "ech")
        h2 = _config_hash("img", "pip", "apt", "tfh", "ech")
        assert h1 == h2

    def test_config_hash_sensitive_to_each_input(self):
        base = ("img", "pip", "apt", "tfh", "ech")
        base_hash = _config_hash(*base)
        variations = (
            ("img2", "pip", "apt", "tfh", "ech"),
            ("img", "pip2", "apt", "tfh", "ech"),
            ("img", "pip", "apt2", "tfh", "ech"),
            ("img", "pip", "apt", "tfh2", "ech"),
            ("img", "pip", "apt", "tfh", "ech2"),
        )
        for variation in variations:
            assert _config_hash(*variation) != base_hash

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


class TestImageTags:
    def test_each_configuration_has_its_own_tag(self):
        base = ib.task_image_tag(_metadata())
        assert base.startswith("lavbench_task_42_") and len(base) == len("lavbench_task_42_") + 12
        assert ib.task_image_tag(_metadata(pip_requirements="numpy")) != base
        assert ib.task_image_tag(_metadata(base_docker_image="python:3.12-slim")) != base
        assert ib.task_image_tag(_metadata(apt_packages="git")) != base
        public = {"filename": "train.csv", "saved_name": "1_train.csv", "visibility": "public"}
        assert ib.task_image_tag(_metadata(task_files=[public])) != base

    def test_hidden_files_never_change_the_image(self):
        public = {"filename": "train.csv", "saved_name": "1_train.csv", "visibility": "public"}
        labels = {
            "filename": "labels.parquet",
            "saved_name": "2_labels.parquet",
            "visibility": "hidden",
        }
        new_labels = dict(labels, saved_name="3_labels.parquet")
        assert ib.task_image_tag(_metadata(task_files=[public, labels])) == ib.task_image_tag(
            _metadata(task_files=[public, new_labels])
        )
        assert ib.task_image_tag(_metadata(task_files=[labels])) == ib.task_image_tag(_metadata())

    def test_prune_keeps_the_current_image_and_survives_a_used_one(self, mocker):
        keep = "lavbench_task_42_aaaaaaaaaaaa"
        images = [
            mocker.Mock(tags=[f"{keep}:latest"]),
            mocker.Mock(tags=["lavbench_task_42_bbbbbbbbbbbb:latest"]),
            mocker.Mock(tags=["lavbench_task_42:latest"]),
            mocker.Mock(tags=["lavbench_task_421_cccccccccccc:latest"]),
        ]
        client = mocker.Mock()
        client.images.list.return_value = images
        client.images.remove.side_effect = [None, RuntimeError("image is in use")]
        mocker.patch.object(ib, "_get_client", return_value=client)
        assert ib.prune_task_images(42, keep=keep) == 1
        removed = [call.args[0] for call in client.images.remove.call_args_list]
        assert removed == ["lavbench_task_42_bbbbbbbbbbbb:latest", "lavbench_task_42:latest"]


class TestBuildTaskImage:
    @pytest.fixture(autouse=True)
    def _tmp_images_dir(self, tmp_path, mocker):
        mocker.patch.object(ib, "TASK_IMAGES_DIR", str(tmp_path))
        yield tmp_path

    def _existing(self, mocker, *metadatas):
        tags = {ib.task_image_tag(m) for m in metadatas}
        return mocker.patch.object(ib, "_image_exists", side_effect=lambda tag: tag in tags)

    def test_an_existing_image_of_the_configuration_skips_build(self, mocker):
        self._existing(mocker, _metadata())
        mock_lock = mocker.patch.object(ib, "renewing_lock")
        mock_do_build = mocker.patch.object(ib, "_do_build")
        assert build_task_image(_metadata()) is True
        mock_lock.assert_not_called()
        mock_do_build.assert_not_called()

    def test_changed_packages_build_a_new_image(self, mocker, redis_flush):
        """The bug this guards: an existing tag used to skip the build after a pip edit."""
        self._existing(mocker, _metadata())
        mock_do_build = mocker.patch.object(ib, "_do_build", return_value=True)
        metadata = _metadata(pip_requirements="numpy==2.0", apt_packages="git")
        assert build_task_image(metadata) is True
        mock_do_build.assert_called_once_with(metadata, log_callback=None, force_rebuild=False)

    def test_two_configurations_never_rebuild_each_other(self, mocker, redis_flush):
        """Runs dispatched before and after an edit alternate on a worker without a rebuild."""
        old, new = _metadata(), _metadata(pip_requirements="numpy")
        self._existing(mocker, old, new)
        mock_do_build = mocker.patch.object(ib, "_do_build")
        for metadata in (old, new, old, new):
            assert build_task_image(metadata) is True
        mock_do_build.assert_not_called()

    def test_force_rebuild_bypasses_fast_path(self, mocker, redis_flush):
        self._existing(mocker, _metadata())
        mock_do_build = mocker.patch.object(ib, "_do_build", return_value=True)
        metadata = _metadata()
        assert build_task_image(metadata, force_rebuild=True) is True
        mock_do_build.assert_called_once_with(metadata, log_callback=None, force_rebuild=True)

    def test_image_missing_triggers_build_and_frees_the_lock(self, mocker, redis_flush):
        from utils.cache_utils import get_coordination_client

        mocker.patch.object(ib, "_image_exists", return_value=False)
        mock_do_build = mocker.patch.object(ib, "_do_build", return_value=True)
        assert build_task_image(_metadata()) is True
        mock_do_build.assert_called_once()
        assert get_coordination_client().get(_build_lock_key(42)) is None

    def test_a_run_waits_for_another_runs_build_instead_of_failing(self, mocker, redis_flush):
        from utils.cache_utils import cache_lock

        # The image appears on the third check, as the other build finishes
        mocker.patch.object(ib, "_image_exists", side_effect=[False, False, True])
        mock_do_build = mocker.patch.object(ib, "_do_build")
        sleep = mocker.patch.object(ib.time, "sleep")
        lines = []
        with cache_lock(_build_lock_key(42), ttl=60) as held:
            assert held
            assert build_task_image(_metadata(), log_callback=lines.append) is True
        mock_do_build.assert_not_called()
        assert sleep.call_count == 2
        assert lines == ["Waiting for the task image that another run is building..."]

    def test_waiting_ends_at_the_budget(self, mocker, redis_flush):
        from utils.cache_utils import cache_lock

        mocker.patch.object(ib, "_image_exists", return_value=False)
        mock_do_build = mocker.patch.object(ib, "_do_build")
        mocker.patch.object(ib.time, "sleep")
        with cache_lock(_build_lock_key(42), ttl=60) as held:
            assert held
            assert build_task_image(_metadata(), wait_seconds=0) is False
        mock_do_build.assert_not_called()

    def test_the_default_wait_is_the_configured_budget(self, mocker, redis_flush):
        from utils.cache_utils import cache_lock

        mocker.patch.object(ib.Config, "IMAGE_BUILD_WAIT_SECONDS", 30)
        mocker.patch.object(ib, "_image_exists", return_value=False)
        clock = iter(range(0, 1000, 10))
        fake_time = mocker.patch.object(ib, "time")
        fake_time.monotonic.side_effect = lambda: next(clock)
        sleep = fake_time.sleep
        with cache_lock(_build_lock_key(42), ttl=60) as held:
            assert held
            assert build_task_image(_metadata()) is False
        # Checks at 10, 20 and 30 s after the start at 0, then the budget is spent
        assert sleep.call_count == 2

    def test_do_build_failure_returns_false_and_releases_lock(self, mocker, redis_flush):
        from utils.cache_utils import get_coordination_client

        mocker.patch.object(ib, "_image_exists", return_value=False)
        mock_do_build = mocker.patch.object(ib, "_do_build", return_value=False)
        assert build_task_image(_metadata()) is False
        mock_do_build.assert_called_once()
        assert get_coordination_client().get(_build_lock_key(42)) is None

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

    def test_an_older_image_never_stands_in_for_a_failed_build(self, mocker):
        mocker.patch.object(ib, "build_task_image", return_value=False)
        mocker.patch.object(ib, "_image_exists", return_value=True)
        mocker.patch.object(ib.time, "sleep")
        assert ib.ensure_task_image(_metadata()) is False

    def test_returns_false_after_retries(self, mocker):
        mock_build = mocker.patch.object(ib, "build_task_image", return_value=False)
        mocker.patch.object(ib.time, "sleep")
        assert ib.ensure_task_image(_metadata()) is False
        assert mock_build.call_count == 3
        budgets = [call.kwargs["wait_seconds"] for call in mock_build.call_args_list]
        assert all(0 < budget <= ib.Config.IMAGE_BUILD_WAIT_SECONDS for budget in budgets)


class TestDoBuild:
    @pytest.fixture(autouse=True)
    def _tmp_images_dir(self, tmp_path, mocker):
        mocker.patch.object(ib, "TASK_IMAGES_DIR", str(tmp_path))
        yield tmp_path

    def test_success_writes_meta_and_dockerfile(self, mocker, _tmp_images_dir):
        mocker.patch.object(ib, "_image_exists", return_value=False)
        mocker.patch.object(ib, "_check_build_disk_space", return_value=True)
        mocker.patch.object(ib, "_download_task_file_for_build")
        mocker.patch.object(ib, "_run_docker_build", return_value=(0, "", "", False))
        mock_report = mocker.patch.object(ib, "_report_build_error")
        prune = mocker.patch.object(ib, "prune_task_images")
        metadata = _metadata(
            pip_requirements="numpy",
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
        assert last_line == ("RUN mkdir -p /app && chown 65534:65534 /app && chmod 0755 /app")
        prune.assert_called_once_with(42, keep=ib.task_image_tag(metadata))
        mock_report.assert_called_once_with(42, "", "", None)

    def test_build_rc_failure_reports_error(self, mocker, _tmp_images_dir):
        mocker.patch.object(ib, "_image_exists", return_value=False)
        mocker.patch.object(ib, "_check_build_disk_space", return_value=True)

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
