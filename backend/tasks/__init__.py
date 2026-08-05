"""Celery task definitions and beat schedule for async evaluation and backups."""

from __future__ import annotations

import contextlib
import logging
import os
import time
from datetime import datetime, timedelta
from itertools import chain
from typing import Any

from celery import Celery
from celery import Task as CeleryTask
from celery.exceptions import SoftTimeLimitExceeded
from celery.signals import celeryd_init

from config import Config
from log_config import RemoteShipHandler, setup_logging
from utils.dates import utcnow

from .task_modules.submission_runner import run_eval_submission
from .task_modules.system import (
    run_backup as _do_backup,
)
from .task_modules.system import run_docker_prune

logger = logging.getLogger(__name__)

# Force UTC for Celery heartbeats to avoid clock drift warnings
# when the host system uses a non-UTC local timezone.
os.environ["TZ"] = "UTC"
time.tzset()

setup_logging("celery")

# Worker role capabilities (see Config._worker_role). Only 'server' and
# 'internal' boot a full app; 'eval' and 'scheduler' run a bare Celery
# instance (eval publishes results over HTTP, scheduler only dispatches).
HAS_APP = Config.HAS_APP
IS_EVAL_WORKER = Config.IS_EVAL_WORKER
RUNS_EVALUATION = Config.RUNS_EVALUATION
RUNS_INTERNAL = Config.RUNS_INTERNAL

if IS_EVAL_WORKER and Config.WORKER_LOG_SHIP_URL:
    ship_url = Config.WORKER_LOG_SHIP_URL
    from worker_utils import _sign_worker_token

    token = _sign_worker_token("worker")
    if token:
        root = logging.getLogger()
        root.addHandler(RemoteShipHandler(ship_url, token))

if not HAS_APP:
    celery = Celery(
        "tasks",
        broker=Config.CELERY_BROKER_URL,
        backend=Config.CELERY_RESULT_BACKEND,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
    )
    app = None
    db = None
    Submission = None
    Challenge = None
else:
    from app import create_app
    from models import Challenge, Submission, db

    app = create_app()
    celery = Celery(
        "tasks",
        broker=app.config["CELERY_BROKER_URL"],
        backend=app.config["CELERY_RESULT_BACKEND"],
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
    )


def configure_celery_ssl(celery_app: Celery) -> None:
    broker_url = celery_app.conf.broker_url or ""
    result_backend = celery_app.conf.result_backend or ""
    if broker_url.startswith("rediss://") or result_backend.startswith("rediss://"):
        import ssl

        ssl_ca_certs = Config.REDIS_SSL_CA_CERTS or None
        ssl_certfile = Config.REDIS_SSL_CERTFILE or None
        ssl_keyfile = Config.REDIS_SSL_KEYFILE or None
        ssl_cert_reqs_str = Config.REDIS_SSL_CERT_REQS

        ssl_cert_reqs = ssl.CERT_REQUIRED
        if ssl_cert_reqs_str == "none":
            ssl_cert_reqs = ssl.CERT_NONE
        elif ssl_cert_reqs_str == "optional":
            ssl_cert_reqs = ssl.CERT_OPTIONAL

        ssl_opts = {"ssl_cert_reqs": ssl_cert_reqs}
        if ssl_ca_certs:
            ssl_opts["ssl_ca_certs"] = ssl_ca_certs
        if ssl_certfile:
            ssl_opts["ssl_certfile"] = ssl_certfile
        if ssl_keyfile:
            ssl_opts["ssl_keyfile"] = ssl_keyfile

        celery_app.conf.update(broker_use_ssl=ssl_opts, redis_backend_use_ssl=ssl_opts)


configure_celery_ssl(celery)

# Recycle worker child processes after 50 tasks to reclaim memory from ML model execution
celery.conf.update(
    worker_max_tasks_per_child=50,
    worker_concurrency=Config.CELERY_WORKER_CONCURRENCY,
    worker_prefetch_multiplier=1,  # never hoard long-running evals per worker
    result_expires=Config.CELERY_RESULT_EXPIRES,
    broker_transport_options={
        "socket_timeout": Config.CELERY_BROKER_TRANSPORT_OPTIONS["socket_timeout"],
        "socket_connect_timeout": Config.CELERY_BROKER_TRANSPORT_OPTIONS["socket_connect_timeout"],
        "visibility_timeout": Config.CELERY_BROKER_TRANSPORT_OPTIONS["visibility_timeout"],
    },
)


@celeryd_init.connect
def _configure_worker_logging(sender: str, conf: Any, **kwargs: Any) -> None:
    logfmt = f"[{sender}] [%(asctime)s: %(levelname)s/%(processName)s] %(message)s"
    conf.worker_log_format = logfmt
    conf.worker_task_log_format = logfmt


@celeryd_init.connect
def _stale_dir_sweep_on_start(sender: str, conf: Any, **kwargs: Any) -> None:
    """Sweep abandoned task execution dirs once at worker startup.

    Complements the daily ``task-dir-sweep-daily`` beat task: a worker boot is
    the likeliest moment a previous instance was killed and left plaintext in
    its workspace root (see ``worker_utils.run_stale_dir_sweep``). Serialized
    with a file lock so concurrent worker starts don't sweep twice.
    """
    from worker_utils import run_stale_dir_sweep

    lock_path = os.path.join(Config.LAVBENCH_WORKSPACE_DIR or "", ".stale_sweep.lock")
    if not Config.LAVBENCH_WORKSPACE_DIR:
        return
    try:
        import fcntl

        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        return
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return
        try:
            removed = run_stale_dir_sweep()
            if removed:
                logger.info("[%s] removed %s stale task dir(s) on startup", sender, removed)
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


@celery.task(
    bind=True,
    soft_time_limit=1200,
    time_limit=1500,
    acks_late=True,
    reject_on_worker_lost=True,
)
def evaluate_submission(
    self: CeleryTask, submission_id: Any, metadata: dict[str, Any] | None = None
) -> Any:
    """Celery task: run a competitor submission through the evaluation pipeline in Docker."""
    try:
        return run_eval_submission(self, submission_id, metadata, app, db, Submission, Challenge)
    except SoftTimeLimitExceeded:
        if HAS_APP and app:
            with app.app_context():
                sub = db.session.get(Submission, submission_id)
                if sub and sub.status not in ("completed", "failed"):
                    sub.status = "failed"
                    sub.detailed_status = "failed"
                    sub.logs = (sub.logs or "") + "\n[TIMEOUT] Celery soft time limit exceeded."
                    db.session.commit()
                    from sse_utils import publish_submission_status

                    publish_submission_status(submission_id, "failed")
        elif IS_EVAL_WORKER and metadata:
            from worker_utils import report_status_to_server

            report_status_to_server(
                metadata=metadata,
                status="failed",
                detailed_status="failed",
                logs="[TIMEOUT] Celery soft time limit exceeded.",
            )
        return
    except Exception as e:
        from cache_utils import log_dead_letter

        log_dead_letter(
            submission_id,
            task_id=metadata.get("task_id") if metadata else None,
            challenge_id=metadata.get("challenge_id") if metadata else None,
            error=e,
        )
        raise


@celery.task
def recalculate_all_leaderboards() -> None:
    """Celery task: rebuild leaderboard cache for all active challenges."""
    if not RUNS_INTERNAL:
        return
    from .task_modules.leaderboard import run_recalculate_all_leaderboards

    return run_recalculate_all_leaderboards(app)


@celery.task
def recalculate_leaderboard(challenge_id: Any) -> None:
    """Celery task: rebuild leaderboard cache for a specific challenge."""
    if not RUNS_INTERNAL:
        return
    if not app:
        return
    from services.leaderboard_service import build_and_cache_leaderboard

    with app.app_context():
        challenge = Challenge.query.get(challenge_id)
        if not challenge:
            return
        build_and_cache_leaderboard(challenge_id, is_frozen_view=False, force_rebuild=True)
        if challenge.is_frozen:
            build_and_cache_leaderboard(challenge_id, is_frozen_view=True, force_rebuild=True)

        from sse_utils import publish_leaderboard_update

        publish_leaderboard_update(challenge_id)


@celery.task
def run_backup(auto: bool = True, db_only: bool = False) -> Any:
    """Celery task: create a pg_dump+uploads tarball backup."""
    if not RUNS_INTERNAL:
        return {"skipped": "role_not_internal"}
    if not app:
        return {"error": "no_app"}
    return _do_backup(app, auto=auto, db_only=db_only)


@celery.task
def check_and_backup() -> dict[str, Any]:
    """Celery beat task: check deadlines and trigger backups (20min active / 6h idle)."""
    if not RUNS_INTERNAL:
        return {"skipped": "role_not_internal"}
    if not app:
        return {"error": "no_app"}
    with app.app_context():
        now = utcnow()

        from models import Challenge

        active_count = Challenge.query.filter(
            Challenge.is_active,
            ~Challenge.is_archived,
            Challenge.start_time <= now,
            (Challenge.end_time.is_(None)) | (Challenge.end_time >= now),
        ).count()

        # General auto backup: every 20min when active, every 6h when idle
        last_key = "backup:last_auto"
        from cache_utils import get_cached, get_redis_client, set_cached

        r = get_redis_client()
        if r:
            last_ts = get_cached(last_key)
            should_run = False
            if last_ts:
                last = (
                    datetime.fromisoformat(last_ts)
                    if isinstance(last_ts, str)
                    else datetime.utcfromtimestamp(float(last_ts))
                )
                interval = timedelta(hours=6)
                if active_count > 0:
                    interval = timedelta(minutes=20)
                if now - last >= interval:
                    should_run = True
            else:
                should_run = True
            if should_run:
                set_cached(last_key, now.isoformat(), timeout=86400)
                run_backup.delay(auto=True, db_only=False)

    return {"active_competitions": active_count}


# Periodic watchdog: marks submissions as failed if stuck in queued/running for too long
# Also recovers results from Redis fallback (workers that completed but couldn't reach the server).
# Runs every 5 minutes. Only the main server process runs this (not remote workers).
@celery.task
def watchdog_stuck_submissions() -> dict[str, Any]:
    """Celery beat task: recover fallback results and time-out stuck submissions."""
    if not RUNS_INTERNAL:
        return {"skipped": "role_not_internal"}
    if not app:
        return {"skipped": "no_app_context"}
    with app.app_context():
        import json

        # 1. Recover fallback results from Redis (workers that finished but couldn't reach server)
        recovered = 0
        stuck: list[Any] = []
        try:
            from cache_utils import get_coordination_client, submission_fallback_key

            r = get_coordination_client()
            if not r:
                return {"error": "redis_unavailable"}
            stuck = Submission.query.filter(
                Submission.status.in_(
                    [
                        "queued",
                        "running",
                        "building_env",
                        "running_inference",
                        "evaluating",
                    ]
                )
            ).yield_per(100)
            for sub in stuck:
                fallback_key = submission_fallback_key(sub.id)
                fallback_data = r.get(fallback_key)
                if fallback_data:
                    try:
                        fb = json.loads(fallback_data)
                        sub.status = fb.get("status", "failed")
                        sub.detailed_status = fb.get("detailed_status", "failed")
                        sub.logs = (sub.logs or "") + "\n" + (fb.get("logs") or "")
                        if fb.get("public_score") is not None:
                            sub.public_score = float(fb["public_score"])
                        if fb.get("private_score") is not None:
                            sub.private_score = float(fb["private_score"])
                        if fb.get("execution_time_ms") is not None:
                            sub.execution_time_ms = int(fb["execution_time_ms"])
                        if fb.get("metrics_payload_pub"):
                            sub.metrics_payload_public = fb["metrics_payload_pub"]
                        if fb.get("metrics_payload_priv"):
                            sub.metrics_payload_private = fb["metrics_payload_priv"]
                        r.delete(fallback_key)
                        recovered += 1
                        try:
                            from sse_utils import publish_submission_status

                            publish_submission_status(sub.id, sub.status)
                        except Exception as e:
                            logger.warning(
                                ("Failed to publish status for recovered submission %s: %s"),
                                sub.id,
                                e,
                            )
                    except Exception as e:
                        logger.error(
                            "Watchdog: failed to recover fallback for submission %s: %s",
                            sub.id,
                            e,
                        )
        except Exception as e:
            logger.error("Watchdog: Redis connection error: %s", e)

        # 2. Time out stuck submissions with dynamic per-task timeout
        timed_out_candidates = Submission.query.filter(
            Submission.status.in_(
                ["queued", "running", "building_env", "running_inference", "evaluating"]
            ),
            Submission.executed_at.is_(None),
        ).yield_per(500)
        # Also check running submissions with executed_at set
        running_candidates = Submission.query.filter(
            Submission.status.in_(["running", "building_env", "running_inference", "evaluating"]),
            Submission.executed_at.isnot(None),
        ).yield_per(500)
        now = utcnow()
        timeout_count = 0
        # chain() streams both queries lazily (yield_per) without materializing
        for sub in chain(timed_out_candidates, running_candidates):
            task_time_limit = (
                sub.time_limit_snapshot
                or (sub.task.time_limit_sec if sub.task else None)
                or (sub.challenge.time_limit_sec if sub.challenge else None)
                or 300
            )
            if sub.executed_at:
                max_runtime = timedelta(seconds=int(task_time_limit * 1.5))
                if now - sub.executed_at <= max_runtime:
                    continue
                reason = f"task time limit ({task_time_limit}s) exceeded"
            else:
                if now - sub.created_at <= timedelta(hours=1):
                    continue
                reason = "never picked up by a worker (1h+ queued)"
            sub.status = "failed"
            sub.detailed_status = "failed"
            sub.logs = (sub.logs or "") + f"\n[WATCHDOG] Submission timed out — {reason}."
            if sub.celery_task_id:
                try:
                    celery.control.revoke(sub.celery_task_id, terminate=True)
                except Exception as e:
                    logger.warning(
                        "Watchdog: failed to revoke celery task %s: %s",
                        sub.celery_task_id,
                        e,
                    )
            timeout_count += 1
            try:
                from sse_utils import publish_submission_status

                publish_submission_status(sub.id, sub.status)
            except Exception as e:
                logger.warning(
                    ("Failed to publish status for timed-out submission %s: %s"), sub.id, e
                )

        if recovered > 0 or timeout_count > 0:
            db.session.commit()
            # Invalidate leaderboard cache for affected challenges
            from cache_utils import invalidate_leaderboard_cache

            challenge_ids = set()
            for sub in stuck:
                if sub.challenge_id:
                    challenge_ids.add(sub.challenge_id)
            for cid in challenge_ids:
                invalidate_leaderboard_cache(cid)
        return {"recovered": recovered, "timed_out": timeout_count}


@celery.task
def recalculate_dirty_leaderboards() -> dict[str, Any]:
    """Celery beat task: rebuild leaderboard cache for challenges marked as dirty."""
    if not RUNS_INTERNAL:
        return {"skipped": "role_not_internal"}
    if not app:
        return {"skipped": "no_app_context"}

    from cache_utils import DIRTY_CHALLENGES_SET, get_coordination_client

    r = get_coordination_client()
    if not r:
        return {"error": "redis_unavailable"}

    try:
        dirty_challenges = r.smembers(DIRTY_CHALLENGES_SET)
        if not dirty_challenges:
            return {"recalculated": 0}

        recalculated_count = 0

        from models import Challenge
        from services.leaderboard_service import build_and_cache_leaderboard
        from sse_utils import publish_leaderboard_update

        with app.app_context():
            for cid_bytes in dirty_challenges:
                cid = cid_bytes.decode("utf-8") if isinstance(cid_bytes, bytes) else str(cid_bytes)

                # Remove from dirty set first to prevent race condition
                r.srem(DIRTY_CHALLENGES_SET, cid)

                try:
                    challenge = Challenge.query.get(cid)
                    if not challenge:
                        continue

                    # Rebuild cache
                    build_and_cache_leaderboard(cid, is_frozen_view=False, force_rebuild=True)
                    if challenge.is_frozen:
                        build_and_cache_leaderboard(cid, is_frozen_view=True, force_rebuild=True)

                    # Publish event for live SSE updates
                    publish_leaderboard_update(cid)
                    recalculated_count += 1
                except Exception as e:
                    logger.error("recalculate_dirty_leaderboards: failed for %s: %s", cid, e)

        return {"recalculated": recalculated_count}
    except Exception as e:
        logger.error("recalculate_dirty_leaderboards failed: %s", e)
        return {"error": str(e)}


# Celery Beat schedule for periodic tasks
# watchdog_stuck_submissions: checks for stuck submissions every 5 minutes
# Start with: celery -A tasks.celery beat -l info
@celery.task
def prune_docker_images() -> dict[str, str]:
    """Celery task: prune unused Docker images/layers on worker nodes."""
    return run_docker_prune()


@celery.task
def sweep_stale_task_dirs() -> dict[str, Any]:
    """Celery task: remove abandoned task execution dirs left behind by
    killed/restarted workers (see ``worker_utils.run_stale_dir_sweep``)."""
    from worker_utils import run_stale_dir_sweep

    return {"removed": run_stale_dir_sweep()}


celery.conf.beat_schedule = {
    "watchdog-every-5m": {
        "task": "tasks.watchdog_stuck_submissions",
        "schedule": 300.0,
        "options": {"queue": "internal"},
    },
    "backup-check-every-20m": {
        "task": "tasks.check_and_backup",
        "schedule": 1200.0,
        "options": {"queue": "internal"},
    },
    "recalculate-dirty-leaderboards-every-20s": {
        "task": "tasks.recalculate_dirty_leaderboards",
        "schedule": 20.0,
        "options": {"queue": "internal"},
    },
    "docker-prune-weekly-cpu": {
        "task": "tasks.prune_docker_images",
        "schedule": 604800.0,  # once a week (7 days)
        "options": {"queue": "cpu_queue"},
    },
    "docker-prune-weekly-gpu": {
        "task": "tasks.prune_docker_images",
        "schedule": 604800.0,  # once a week (7 days)
        "options": {"queue": "gpu_queue"},
    },
    "task-dir-sweep-daily-cpu": {
        "task": "tasks.sweep_stale_task_dirs",
        "schedule": 86400.0,  # once a day
        "options": {"queue": "cpu_queue"},
    },
    "task-dir-sweep-daily-gpu": {
        "task": "tasks.sweep_stale_task_dirs",
        "schedule": 86400.0,  # once a day
        "options": {"queue": "gpu_queue"},
    },
}

# Role-gated task registration. 'internal' workers handle only system tasks;
# 'eval' workers handle only evaluation/image tasks; the main server runs all.
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

if not RUNS_EVALUATION:
    for tname in EVALUATION_TASKS:
        with contextlib.suppress(KeyError):
            celery.tasks.unregister(tname)
if not RUNS_INTERNAL:
    for tname in INTERNAL_TASKS:
        with contextlib.suppress(KeyError):
            celery.tasks.unregister(tname)
