"""Tests for the labels and the sweep of sandboxes a dead or killed run left behind."""

import contextlib
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from utils import worker_utils
from utils.cache_utils import (
    attempt_ended_key,
    get_coordination_client,
    mark_attempt_ended,
    sandbox_live_key,
)
from utils.worker_utils import (
    SANDBOX_ATTEMPT_LABEL,
    SANDBOX_DEADLINE_LABEL,
    SANDBOX_LABEL,
    SANDBOX_ORPHAN_GRACE_SECONDS,
    SANDBOX_SEED_LIMIT_SECONDS,
    SANDBOX_TIME_LIMIT_LABEL,
    reap_orphaned_sandboxes,
    run_sandbox,
)


def _iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%S.123456789Z")


def _container(name, started=None, created=None, time_limit=300, attempt=None):
    container = MagicMock()
    container.name = name
    container.labels = {SANDBOX_LABEL: "1", SANDBOX_TIME_LIMIT_LABEL: str(time_limit)}
    if attempt:
        container.labels[SANDBOX_ATTEMPT_LABEL] = attempt
    now = datetime.now(UTC)
    container.attrs = {
        "Created": _iso(created or now),
        "State": {"StartedAt": _iso(started) if started else "0001-01-01T00:00:00Z"},
    }
    return container


def _volume(name, deadline, attempt=None):
    volume = MagicMock()
    volume.name = name
    labels = {SANDBOX_LABEL: "1", SANDBOX_DEADLINE_LABEL: str(int(deadline))}
    if attempt:
        labels[SANDBOX_ATTEMPT_LABEL] = attempt
    volume.attrs = {"Labels": labels}
    return volume


def _client(containers=(), volumes=()):
    client = MagicMock()
    client.containers.list.return_value = list(containers)
    client.volumes.list.return_value = list(volumes)
    return client


def test_sandboxes_carry_their_attempt_and_time_limit(tmp_path, redis_flush):
    client = MagicMock()
    container = client.containers.create.return_value
    container.status = "exited"
    container.wait.return_value = {"StatusCode": 0}
    container.logs.return_value = iter([])
    seen_live = []
    container.start.side_effect = lambda: seen_live.append(
        get_coordination_client().exists(sandbox_live_key("attempt-7"))
    )
    before = time.time()
    run_sandbox(
        client,
        "lavbench_task_1_abc",
        ["python", "-u", "x.py"],
        seed_dir=str(tmp_path),
        collect_files=[],
        logs_list=[],
        time_limit=300,
        storage_opt={},
        attempt_id="attempt-7",
    )
    labels = client.containers.create.call_args.kwargs["labels"]
    assert labels[SANDBOX_ATTEMPT_LABEL] == "attempt-7"
    assert labels[SANDBOX_TIME_LIMIT_LABEL] == "300"
    deadline = int(labels[SANDBOX_DEADLINE_LABEL])
    assert deadline >= int(before) + SANDBOX_SEED_LIMIT_SECONDS + 300 + SANDBOX_ORPHAN_GRACE_SECONDS
    assert client.volumes.create.call_args.kwargs["labels"] == labels
    # The sandbox is marked live while it runs and unmarked once it is removed
    assert seen_live == [1]
    assert not get_coordination_client().exists(sandbox_live_key("attempt-7"))


def test_the_deadline_counts_from_the_start_not_from_a_long_seed_copy():
    """A container that took 40 minutes to seed and started a minute ago is a live run."""
    now = datetime.now(UTC)
    slow_seed = _container(
        "slow", started=now - timedelta(minutes=1), created=now - timedelta(minutes=41)
    )
    overdue = _container(
        "overdue", started=now - timedelta(seconds=300 + SANDBOX_ORPHAN_GRACE_SECONDS + 5)
    )
    assert reap_orphaned_sandboxes(_client([slow_seed, overdue])) == 1
    slow_seed.remove.assert_not_called()
    overdue.remove.assert_called_once_with(force=True)


def test_a_container_never_started_is_removed_after_the_seed_limit():
    now = datetime.now(UTC)
    seeding = _container("seeding", created=now - timedelta(minutes=30))
    limit = SANDBOX_SEED_LIMIT_SECONDS + 300 + SANDBOX_ORPHAN_GRACE_SECONDS + 5
    abandoned = _container("abandoned", created=now - timedelta(seconds=limit))
    assert reap_orphaned_sandboxes(_client([seeding, abandoned])) == 1
    seeding.remove.assert_not_called()


def test_a_killed_run_loses_its_sandbox_at_the_next_sweep(redis_flush):
    """The server marks a killed attempt ended; the worker removes its running sandbox."""
    now = datetime.now(UTC)
    killed = _container("killed", started=now, attempt="attempt-killed")
    other = _container("other", started=now, attempt="attempt-live")
    volume = _volume("killed-volume", time.time() + 3600, attempt="attempt-killed")
    r = get_coordination_client()
    r.set(sandbox_live_key("attempt-killed"), "1", ex=600)
    mark_attempt_ended("attempt-killed")
    assert reap_orphaned_sandboxes(_client([killed, other], [volume])) == 2
    killed.remove.assert_called_once_with(force=True)
    other.remove.assert_not_called()
    volume.remove.assert_called_once_with(force=True)
    assert not r.exists(sandbox_live_key("attempt-killed"))
    assert r.exists(attempt_ended_key("attempt-killed"))


def test_old_labels_without_a_time_limit_still_expire():
    container = MagicMock()
    container.name = "old"
    container.labels = {SANDBOX_LABEL: "1", SANDBOX_DEADLINE_LABEL: str(int(time.time()) - 5)}
    container.attrs = {}
    assert reap_orphaned_sandboxes(_client([container])) == 1


def test_a_failed_removal_does_not_stop_the_sweep():
    old = datetime.now(UTC) - timedelta(hours=2)
    stuck, orphan = _container("stuck", started=old), _container("orphan", started=old)
    stuck.remove.side_effect = RuntimeError("device busy")
    assert reap_orphaned_sandboxes(_client([stuck, orphan])) == 1
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


def test_the_sweep_uses_its_own_client_and_survives_a_docker_error(monkeypatch):
    """The shared client stays unopened in the parent, so forked children never inherit it."""
    import docker

    import tasks
    from tasks.task_modules import docker_utils

    own = MagicMock()
    monkeypatch.setattr(docker, "from_env", lambda: own)
    monkeypatch.setattr(docker_utils, "_client", None)
    seen = []

    def reap(client):
        seen.append(client)
        raise RuntimeError("docker unavailable")

    def stop(_seconds):
        raise SystemExit

    monkeypatch.setattr(worker_utils, "reap_orphaned_sandboxes", reap)
    monkeypatch.setattr(tasks.time, "sleep", stop)
    with contextlib.suppress(SystemExit):
        tasks._reap_sandboxes_forever()
    assert seen == [own]
    assert docker_utils._client is None


def test_a_forked_child_opens_its_own_docker_client(monkeypatch):
    import tasks
    from tasks.task_modules import docker_utils

    monkeypatch.setattr(docker_utils, "_client", MagicMock(name="parent socket"))
    tasks._reset_inherited_docker_client()
    assert docker_utils._client is None


@pytest.mark.parametrize("sandbox_gone", [True, False])
def test_a_killed_run_holds_its_slot_until_its_sandbox_is_gone(
    sandbox_gone, sample_task, sample_competitor, db_session, redis_flush
):
    from models import Submission
    from services.submission_service import _check_active_runs

    for attempt in ("a1", "a2"):
        db_session.add(
            Submission(
                user_id=sample_competitor.id,
                challenge_id=sample_task.challenge_id,
                task_id=sample_task.id,
                status="failed",
                detailed_status="killed",
                celery_task_id=attempt,
                origin="cells",
            )
        )
    db_session.commit()
    r = get_coordination_client()
    if not sandbox_gone:
        r.set(sandbox_live_key("a1"), "1", ex=600)
        r.set(sandbox_live_key("a2"), "1", ex=600)
    refused = _check_active_runs(sample_competitor.id, "competitor")
    assert (refused is None) is sandbox_gone
