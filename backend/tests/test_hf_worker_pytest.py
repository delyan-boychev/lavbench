"""Tests for the worker side of Hugging Face data: lock budget, fail-closed mounts, run logs."""

import hashlib
from unittest.mock import MagicMock

import pytest

import utils.worker_utils as wu
from config import Config
from tasks.task_modules import submission_runner as sr
from tests.helpers.hf import hf_zip_bytes
from utils.metadata import hf_prep_seconds

CONTAINER_ID = "c" * 64
OTHER_ID = "e" * 64


@pytest.fixture
def cache(tmp_path, monkeypatch):
    root = tmp_path / "hf_cache"
    root.mkdir()
    monkeypatch.setattr(Config, "HF_CACHE_DIR", str(root))
    return root


def _mountinfo(tmp_path, monkeypatch, lines):
    path = tmp_path / "mountinfo"
    path.write_text("".join(f"{line}\n" for line in lines))
    real_open = open

    def fake_open(name, *args, **kwargs):
        if name == "/proc/self/mountinfo":
            return real_open(path, *args, **kwargs)
        return real_open(name, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fake_open)


def _line(mount_point, root):
    return f"36 35 98:0 {root} {mount_point} rw,relatime - ext4 /dev/sda1 rw"


# ── Preparation budget ──


def test_the_hf_lock_wait_follows_the_zip_size(cache, tmp_path, monkeypatch):
    data = hf_zip_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    local = tmp_path / "local.zip"
    local.write_bytes(data)
    waits = []
    real_lock = wu._file_lock

    def spy(path, max_wait=None):
        waits.append(max_wait)
        return real_lock(path, max_wait=max_wait)

    monkeypatch.setattr(wu, "_file_lock", spy)
    size = 10 * 1024**3
    with pytest.raises(wu.HfCacheError):
        wu.ensure_hf_cache(sha256, size, None, [], local_zip=str(local))
    wu.ensure_hf_cache(sha256, None, None, [], local_zip=str(local))
    assert waits == [hf_prep_seconds(size), wu.DOWNLOAD_LOCK_MAX_WAIT]
    assert hf_prep_seconds(size) == 60 + 1024


def test_a_held_lock_is_a_worker_problem_not_the_tasks(cache, monkeypatch):
    sha256 = "a" * 64
    monkeypatch.setattr(wu, "_LOCK_POLL_SECONDS", 0.01)
    monkeypatch.setattr(wu, "hf_prep_seconds", lambda size: 0)
    with wu._file_lock(wu._hf_lock(sha256)), pytest.raises(wu.HfCacheError) as caught:
        wu.ensure_hf_cache(sha256, 1, None, [], local_zip="/missing.zip")
    assert caught.value.task_problem is False


def test_a_missing_zip_is_a_task_problem(cache):
    with pytest.raises(wu.HfCacheError) as caught:
        wu.ensure_hf_cache("a" * 64, None, None, [], local_zip="/missing.zip")
    assert caught.value.task_problem is True


# ── Mounts fail closed ──


def test_the_container_id_comes_from_the_hostname_mount_only(tmp_path, monkeypatch):
    _mountinfo(
        tmp_path,
        monkeypatch,
        [
            _line("/data", f"/var/lib/docker/containers/{OTHER_ID}/x"),
            _line("/etc/hostname", f"/var/lib/docker/containers/{CONTAINER_ID}/hostname"),
        ],
    )
    assert wu._own_container_id() == CONTAINER_ID


def test_a_host_worker_has_no_container_mounts(tmp_path, monkeypatch):
    _mountinfo(tmp_path, monkeypatch, [_line("/", "/")])
    monkeypatch.setattr(wu.os.path, "exists", lambda path: False)
    assert wu._own_container_mounts(MagicMock()) is None


def test_an_unidentified_container_fails_closed(tmp_path, monkeypatch):
    _mountinfo(tmp_path, monkeypatch, [_line("/", "/")])
    monkeypatch.setattr(wu.os.path, "exists", lambda path: path == wu.DOCKERENV)
    with pytest.raises(wu.HfCacheError, match="identified"):
        wu._own_container_mounts(MagicMock())


def test_a_failed_inspect_fails_closed(tmp_path, monkeypatch):
    _mountinfo(
        tmp_path,
        monkeypatch,
        [_line("/etc/hostname", f"/var/lib/docker/containers/{CONTAINER_ID}/hostname")],
    )
    client = MagicMock()
    client.containers.get.side_effect = RuntimeError("socket gone")
    with pytest.raises(wu.HfCacheError, match="inspected"):
        wu._own_container_mounts(client)


def test_a_container_without_a_cache_mount_fails_closed(cache, monkeypatch):
    other = {"Type": "volume", "Name": "workspace", "Destination": "/var/lib/elsewhere"}
    monkeypatch.setattr(wu, "_own_container_mounts", lambda client: [other])
    directory = cache / ("b" * 64)
    (directory / "models" / "acme" / "x").mkdir(parents=True)
    with pytest.raises(wu.HfCacheError, match="no mount"):
        wu.hf_sandbox_mounts(MagicMock(), str(directory))


# ── Runner ──


def _metadata(**overrides):
    metadata = {
        "task_id": 456,
        "time_limit": 30,
        "ram_limit": 4096,
        "gpu_required": False,
        "base_docker_image": "python:3.10-slim",
        "metrics_config": {"accuracy": {"weight": 1.0}},
        "public_eval_percentage": 100,
        "challenge_id": 789,
        "user_code": "print('hello')",
        "submission_id": "sub_hf_1",
        "attempt_id": "attempt-hf-1",
        "main_server_url": "http://localhost:5000",
        "hf_zip_sha256": "d" * 64,
        "hf_zip_size": 10,
    }
    metadata.update(overrides)
    return metadata


@pytest.fixture
def runner(mocker):
    mocker.patch.object(sr, "fetch_submission_capabilities", return_value=None)
    mocker.patch(
        "utils.worker_utils.fetch_submission_run_content",
        side_effect=lambda metadata: (metadata.get("user_code"), None),
    )
    mocker.patch.object(sr, "check_docker_available", return_value=True)
    mocker.patch.object(sr, "_get_client", return_value=MagicMock())
    mocker.patch.object(sr, "_image_exists_docker", return_value=True)
    mocker.patch.object(sr, "run_sandbox", return_value=(0, "", "", False))
    mocker.patch.object(sr, "sync_task_files_to_assets_cache", return_value=True)
    report = mocker.patch.object(sr, "report_status_to_server", return_value=True)
    problem = mocker.patch.object(sr, "_report_runtime_sync_failure")
    return report, problem


def _run(metadata):
    return sr.run_eval_submission(
        self_task=None,
        submission_id="sub_hf_1",
        metadata=metadata,
        app=None,
        db=None,
        submission_cls=None,
        challenge_cls=None,
    )


def _failed_logs(report):
    failed = [c for c in report.call_args_list if c.kwargs.get("status") == "failed"]
    assert failed and failed[-1].kwargs["detailed_status"] == "failed_infra"
    logs = failed[-1].kwargs.get("logs") or ""
    return logs if isinstance(logs, str) else "\n".join(logs)


def test_a_failed_download_logs_a_generic_line_and_reports_the_task(runner, mocker):
    report, problem = runner
    secret = "HTTP 404 from http://10.0.0.5/api/worker/hf-zip"
    mocker.patch.object(
        sr, "ensure_hf_cache", side_effect=wu.HfCacheError(secret, task_problem=True)
    )
    assert _run(_metadata()) is None
    logs = _failed_logs(report)
    assert sr.HF_FAILED_LINE in logs
    assert secret not in logs
    problem.assert_called_once()
    assert problem.call_args.args[2] == ["ERR_HF_DATA_SYNC_FAILED"]
    sr.run_sandbox.assert_not_called()


def test_a_worker_side_hf_failure_does_not_block_the_task(runner, mocker):
    report, problem = runner
    mocker.patch.object(sr, "ensure_hf_cache", side_effect=wu.HfCacheError("read-only cache"))
    assert _run(_metadata()) is None
    assert "read-only" not in _failed_logs(report)
    problem.assert_not_called()


def test_a_full_worker_disk_fails_the_run_without_blocking_the_task(runner, mocker, caplog):
    report, problem = runner
    full = wu.HfCacheError("worker disk full: 1 GB free, 3 GB needed")
    mocker.patch.object(sr, "ensure_hf_cache", side_effect=full)
    assert _run(_metadata()) is None
    logs = _failed_logs(report)
    assert sr.HF_FAILED_LINE in logs
    assert "disk" not in logs
    assert "worker disk full: 1 GB free, 3 GB needed" in caplog.text
    problem.assert_not_called()
    sr.run_sandbox.assert_not_called()


def test_a_run_that_prepared_the_hf_data_says_so_in_its_report(runner, mocker):
    report, _problem = runner
    mocker.patch.object(sr, "ensure_hf_cache", return_value="/cache/abc")
    mocker.patch.object(sr, "hf_sandbox_mounts", return_value=[])
    _run(_metadata())
    inference = [
        c for c in report.call_args_list if c.kwargs.get("detailed_status") == "running_inference"
    ]
    assert inference and inference[0].kwargs["hf_ready"] is True


def _usage(*free):
    values = iter(free)
    return lambda _path: MagicMock(free=next(values))


def test_a_short_cache_disk_is_swept_before_unpacking(cache, mocker):
    mocker.patch.object(wu.shutil, "disk_usage", side_effect=_usage(10, 100))
    sweep = mocker.patch.object(wu, "run_hf_cache_sweep", return_value=1)
    wu.ensure_hf_space(str(cache), 50)
    sweep.assert_called_once()


def test_a_cache_disk_still_short_after_the_sweep_fails_before_the_download(
    cache, tmp_path, mocker, caplog
):
    data = hf_zip_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    local = tmp_path / "local.zip"
    local.write_bytes(data)
    mocker.patch.object(wu.shutil, "disk_usage", side_effect=_usage(10, 20))
    sweep = mocker.patch.object(wu, "run_hf_cache_sweep", return_value=0)
    with pytest.raises(wu.HfCacheError, match="worker disk full") as raised:
        wu.ensure_hf_cache(sha256, len(data), 1000, [], local_zip=str(local))
    sweep.assert_called_once()
    assert not raised.value.task_problem
    assert "1024 MB needed" in str(raised.value)
    assert "Worker disk full" in caplog.text
    assert sorted(p.name for p in cache.iterdir()) == [".locks"]


def test_a_mount_that_fails_closed_is_a_platform_failure(runner, mocker):
    report, problem = runner
    mocker.patch.object(sr, "ensure_hf_cache", return_value="/cache/abc")
    mocker.patch.object(
        sr, "hf_sandbox_mounts", side_effect=wu.HfCacheError("no mount of the worker container")
    )
    assert _run(_metadata()) is None
    logs = _failed_logs(report)
    assert sr.HF_FAILED_LINE in logs
    assert "no mount" not in logs
    problem.assert_not_called()
    sr.run_sandbox.assert_not_called()


def test_the_local_run_uses_the_zip_recorded_at_dispatch():
    task = MagicMock(hf_zip_sha256="n" * 64)
    submission = MagicMock(task=task, hf_zip_sha256="o" * 64)
    assert sr.same_hf_zip(submission) is False
    submission.hf_zip_sha256 = "n" * 64
    assert sr.same_hf_zip(submission) is True
    submission.hf_zip_sha256 = None
    assert sr.same_hf_zip(submission) is False


# ── Startup sweep ──


def test_the_hf_cache_is_swept_when_a_worker_is_ready(mocker):
    import tasks

    sweep = mocker.patch("utils.worker_utils.run_hf_cache_sweep", return_value=2)
    tasks._hf_cache_sweep_on_ready(sender=None)
    sweep.assert_called_once_with()


def test_a_failed_startup_sweep_does_not_stop_the_worker(mocker):
    import tasks

    mocker.patch("utils.worker_utils.run_hf_cache_sweep", side_effect=OSError("gone"))
    tasks._hf_cache_sweep_on_ready(sender=None)
