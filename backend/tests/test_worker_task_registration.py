"""Tests for worker task registration."""

import os
import subprocess
import sys

INTERNAL_TASKS = {
    "tasks.check_and_backup",
    "tasks.recalculate_all_leaderboards",
    "tasks.recalculate_dirty_leaderboards",
    "tasks.recalculate_leaderboard",
    "tasks.run_backup",
    "tasks.watchdog_stuck_submissions",
}
EVALUATION_TASKS = {
    "tasks.evaluate_submission",
    "tasks.prune_docker_images",
}


def _registered_tasks(env):
    # Run python to import tasks and print registered tasks
    return subprocess.check_output(
        [sys.executable, "-c", "import tasks; print(list(tasks.celery.tasks.keys()))"],
        env=env,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    ).decode()


def test_internal_only_worker_registration():
    env = os.environ.copy()
    env["WORKER_ROLE"] = "internal"
    res = _registered_tasks(env)

    for tname in EVALUATION_TASKS:
        assert tname not in res
    for tname in INTERNAL_TASKS:
        assert tname in res


def test_evaluation_only_worker_registration():
    env = os.environ.copy()
    env["WORKER_ROLE"] = "eval"
    res = _registered_tasks(env)

    for tname in EVALUATION_TASKS:
        assert tname in res
    for tname in INTERNAL_TASKS:
        assert tname not in res


def test_scheduler_registration():
    env = os.environ.copy()
    env["WORKER_ROLE"] = "scheduler"
    res = _registered_tasks(env)

    for tname in INTERNAL_TASKS | EVALUATION_TASKS:
        assert tname not in res


def test_default_registration():
    env = os.environ.copy()
    env.pop("WORKER_ROLE", None)
    res = _registered_tasks(env)

    for tname in INTERNAL_TASKS | EVALUATION_TASKS:
        assert tname in res


def test_task_sets_exposed():
    import tasks

    assert tasks.INTERNAL_TASKS == INTERNAL_TASKS
    assert tasks.EVALUATION_TASKS == EVALUATION_TASKS


def test_register_worker_specs_removed():
    import tasks

    assert not hasattr(tasks, "register_worker_specs")


def test_beat_schedule_prune_and_sweep_on_evaluation_queues():
    import tasks

    schedule = tasks.celery.conf.beat_schedule
    # Prune/sweep are host-side Docker ops that must run on evaluation worker
    # Nodes (they own the Docker socket). Emit on both cpu_queue and gpu_queue
    # Since either may be the deployed worker pool
    assert schedule["docker-prune-weekly-cpu"]["options"]["queue"] == "cpu_queue"
    assert schedule["docker-prune-weekly-gpu"]["options"]["queue"] == "gpu_queue"
    assert schedule["task-dir-sweep-daily-cpu"]["options"]["queue"] == "cpu_queue"
    assert schedule["task-dir-sweep-daily-gpu"]["options"]["queue"] == "gpu_queue"


def test_every_beat_entry_expires_before_its_next_run():
    import tasks

    for name, entry in tasks.celery.conf.beat_schedule.items():
        expires = entry["options"].get("expires")
        assert expires is not None, f"{name} has no expires"
        assert 0 < expires < entry["schedule"], name


def test_evaluation_workers_prefetch_one_message():
    import tasks

    assert tasks.celery.conf.worker_prefetch_multiplier == 1


def test_message_expiry_leaves_15_minutes_before_the_watchdog_cutoff():
    """A message taken just before it expires still has time to build its image."""
    from datetime import timedelta

    import tasks
    from config import Config

    headroom = timedelta(minutes=15)
    assert timedelta(seconds=Config.CELERY_MESSAGE_EXPIRES) <= (
        tasks.NEVER_PICKED_UP_CUTOFF - headroom
    )
    assert Config.CELERY_BROKER_TRANSPORT_OPTIONS["visibility_timeout"] > (
        tasks.NEVER_PICKED_UP_CUTOFF.total_seconds()
    )


def test_prefork_child_drops_inherited_db_connections(app, monkeypatch):
    from unittest.mock import MagicMock

    import tasks

    engine = MagicMock()
    monkeypatch.setattr(tasks, "app", app)
    monkeypatch.setattr(type(tasks.db), "engine", property(lambda _self: engine))
    tasks._dispose_inherited_db_connections()
    engine.dispose.assert_called_once_with(close=False)
