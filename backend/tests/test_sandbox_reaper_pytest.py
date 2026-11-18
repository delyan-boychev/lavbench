"""Tests for the labels and the sweep of sandboxes a dead worker left behind."""

import contextlib
import time
from unittest.mock import MagicMock

from utils import worker_utils
from utils.worker_utils import (
    SANDBOX_DEADLINE_LABEL,
    SANDBOX_LABEL,
    SANDBOX_ORPHAN_GRACE_SECONDS,
    reap_orphaned_sandboxes,
    run_sandbox,
)


def _container(name, deadline):
    container = MagicMock()
    container.name = name
    container.labels = {SANDBOX_LABEL: "1", SANDBOX_DEADLINE_LABEL: str(int(deadline))}
    return container


def _volume(name, deadline):
    volume = MagicMock()
    volume.name = name
    volume.attrs = {"Labels": {SANDBOX_LABEL: "1", SANDBOX_DEADLINE_LABEL: str(int(deadline))}}
    return volume


def test_sandboxes_and_their_volumes_carry_a_deadline(tmp_path):
    client = MagicMock()
    container = client.containers.create.return_value
    container.status = "exited"
    container.wait.return_value = {"StatusCode": 0}
    container.logs.return_value = iter([])
    before = time.time()
    run_sandbox(
        client,
        "lavbench_task_1",
        ["python", "-u", "x.py"],
        seed_dir=str(tmp_path),
        collect_files=[],
        logs_list=[],
        time_limit=300,
        storage_opt={},
    )
    labels = client.containers.create.call_args.kwargs["labels"]
    assert labels[SANDBOX_LABEL] == "1"
    deadline = int(labels[SANDBOX_DEADLINE_LABEL])
    assert before + 300 + SANDBOX_ORPHAN_GRACE_SECONDS <= deadline + 1
    assert deadline <= time.time() + 300 + SANDBOX_ORPHAN_GRACE_SECONDS + 1
    assert client.volumes.create.call_args.kwargs["labels"] == labels


def test_the_sweep_removes_only_sandboxes_past_their_deadline():
    now = time.time()
    orphan, live = _container("orphan", now - 5), _container("live", now + 600)
    old_volume, live_volume = _volume("old", now - 5), _volume("in-use", now + 600)
    client = MagicMock()
    client.containers.list.return_value = [orphan, live]
    client.volumes.list.return_value = [old_volume, live_volume]

    assert reap_orphaned_sandboxes(client) == 2
    client.containers.list.assert_called_once_with(all=True, filters={"label": SANDBOX_LABEL})
    client.volumes.list.assert_called_once_with(filters={"label": SANDBOX_LABEL})
    orphan.remove.assert_called_once_with(force=True)
    live.remove.assert_not_called()
    old_volume.remove.assert_called_once_with(force=True)
    live_volume.remove.assert_not_called()


def test_a_failed_removal_does_not_stop_the_sweep():
    now = time.time()
    stuck, orphan = _container("stuck", now - 5), _container("orphan", now - 5)
    stuck.remove.side_effect = RuntimeError("device busy")
    client = MagicMock()
    client.containers.list.return_value = [stuck, orphan]
    client.volumes.list.return_value = []
    assert reap_orphaned_sandboxes(client) == 1
    orphan.remove.assert_called_once()


def test_evaluation_workers_start_the_sweep_when_ready(monkeypatch):
    import tasks

    started = []
    monkeypatch.setattr(tasks, "RUNS_EVALUATION", True)
    monkeypatch.setattr("threading.Thread", lambda **kwargs: started.append(kwargs) or MagicMock())
    tasks._start_sandbox_reaper()
    assert started[0]["target"] is tasks._reap_sandboxes_forever

    started.clear()
    monkeypatch.setattr(tasks, "RUNS_EVALUATION", False)
    tasks._start_sandbox_reaper()
    assert started == []


def test_the_sweep_loop_survives_a_docker_error(monkeypatch):
    import tasks

    calls = []

    def reap(_client):
        calls.append(1)
        raise RuntimeError("docker unavailable")

    def stop(_seconds):
        raise SystemExit

    monkeypatch.setattr(worker_utils, "reap_orphaned_sandboxes", reap)
    monkeypatch.setattr("tasks.task_modules.docker_utils._get_client", MagicMock)
    monkeypatch.setattr(tasks.time, "sleep", stop)
    with contextlib.suppress(SystemExit):
        tasks._reap_sandboxes_forever()
    assert calls == [1]
