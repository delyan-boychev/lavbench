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
    # nodes (they own the Docker socket). Emit on both cpu_queue and gpu_queue
    # since either may be the deployed worker pool.
    assert schedule["docker-prune-weekly-cpu"]["options"] == {"queue": "cpu_queue"}
    assert schedule["docker-prune-weekly-gpu"]["options"] == {"queue": "gpu_queue"}
    assert schedule["task-dir-sweep-daily-cpu"]["options"] == {"queue": "cpu_queue"}
    assert schedule["task-dir-sweep-daily-gpu"]["options"] == {"queue": "gpu_queue"}
