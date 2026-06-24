import os
import subprocess
import sys


def test_internal_only_worker_registration():
    env = os.environ.copy()
    env["INTERNAL_ONLY_WORKER"] = "true"
    env["EVALUATION_ONLY_WORKER"] = "false"
    # Run python to import tasks and print registered tasks
    res = subprocess.check_output(
        [sys.executable, "-c", "import tasks; print(list(tasks.celery.tasks.keys()))"],
        env=env,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    ).decode()

    assert "tasks.evaluate_submission" not in res
    assert "tasks.register_worker_specs" not in res
    assert "tasks.prune_docker_images" not in res
    assert "tasks.run_backup" in res
    assert "tasks.recalculate_all_leaderboards" in res


def test_evaluation_only_worker_registration():
    env = os.environ.copy()
    env["INTERNAL_ONLY_WORKER"] = "false"
    env["EVALUATION_ONLY_WORKER"] = "true"
    # Run python to import tasks and print registered tasks
    res = subprocess.check_output(
        [sys.executable, "-c", "import tasks; print(list(tasks.celery.tasks.keys()))"],
        env=env,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    ).decode()

    assert "tasks.evaluate_submission" in res
    assert "tasks.register_worker_specs" in res
    assert "tasks.prune_docker_images" in res
    assert "tasks.run_backup" not in res
    assert "tasks.recalculate_all_leaderboards" not in res


def test_default_registration():
    env = os.environ.copy()
    env.pop("INTERNAL_ONLY_WORKER", None)
    env.pop("EVALUATION_ONLY_WORKER", None)
    # Run python to import tasks and print registered tasks
    res = subprocess.check_output(
        [sys.executable, "-c", "import tasks; print(list(tasks.celery.tasks.keys()))"],
        env=env,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    ).decode()

    assert "tasks.evaluate_submission" in res
    assert "tasks.register_worker_specs" in res
    assert "tasks.prune_docker_images" in res
    assert "tasks.run_backup" in res
    assert "tasks.recalculate_all_leaderboards" in res
