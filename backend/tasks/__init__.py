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
from celery.signals import celeryd_init, worker_process_init
from flask import current_app, has_app_context

from config import Config
from config.log_config import RemoteShipHandler, setup_logging
from utils.dates import utcnow
from utils.submission_status import (
    ACTIVE_STATUSES,
    INFRA_FAILURE,
    RUNNING_STATUSES,
    TERMINAL_STATUSES,
)

from .task_modules.submission_runner import run_eval_submission
from .task_modules.system import (
    BACKUP_DISPATCH_KEY,
    LAST_AUTO_BACKUP_KEY,
    LAST_FULL_BACKUP_KEY,
    backup_dispatch_ttl,
    release_backup_dispatch,
    run_docker_prune,
)
from .task_modules.system import (
    run_backup as _do_backup,
)

logger = logging.getLogger(__name__)

# Force UTC for Celery heartbeats to avoid clock drift warnings
# When the host system uses a non-UTC local timezone
os.environ["TZ"] = "UTC"
time.tzset()

# Imported inside an app context means a request handler in the web server, which
# Only dispatches tasks: reuse its app and logging instead of building a second app,
# DB engine and celery.log handler in every gunicorn process
DISPATCH_ONLY = has_app_context()

if not DISPATCH_ONLY:
    setup_logging("celery")

# Worker role capabilities (see Config._worker_role). Only 'server' and
# 'internal' boot a full app; 'eval' and 'scheduler' run a bare Celery
# Instance (eval publishes results over HTTP, scheduler only dispatches)
HAS_APP = Config.HAS_APP
IS_EVAL_WORKER = Config.IS_EVAL_WORKER
RUNS_EVALUATION = Config.RUNS_EVALUATION
RUNS_INTERNAL = Config.RUNS_INTERNAL

if IS_EVAL_WORKER and Config.WORKER_LOG_SHIP_URL:
    ship_url = Config.WORKER_LOG_SHIP_URL
    from utils.worker_utils import _sign_worker_token

    token = _sign_worker_token("worker")
    if token:
        root = logging.getLogger()
        root.addHandler(RemoteShipHandler(ship_url, token))

if not HAS_APP:
    celery = Celery(
        "tasks",
        broker=Config.CELERY_BROKER_URL,
        task_serializer="json",
        accept_content=["json"],
    )
    app = None
    db = None
    Submission = None
    Challenge = None
else:
    from models import Challenge, Submission, db

    if DISPATCH_ONLY:
        app = current_app._get_current_object()
    else:
        from app import create_app

        app = create_app()
    celery = Celery(
        "tasks",
        broker=app.config["CELERY_BROKER_URL"],
        task_serializer="json",
        accept_content=["json"],
    )


def configure_celery_ssl(celery_app: Celery) -> None:
    broker_url = celery_app.conf.broker_url or ""
    if broker_url.startswith("rediss://"):
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

        celery_app.conf.update(broker_use_ssl=ssl_opts)


configure_celery_ssl(celery)

# Recycle worker child processes after 50 tasks to reclaim memory from ML model execution
celery.conf.update(
    worker_max_tasks_per_child=50,
    worker_concurrency=Config.CELERY_WORKER_CONCURRENCY,
    worker_prefetch_multiplier=1,  # Never hoard long-running evals per worker
    # Results travel over HTTP and the DB, never through Celery, so no result backend
    task_ignore_result=True,
    broker_transport_options={
        "socket_timeout": Config.CELERY_BROKER_TRANSPORT_OPTIONS["socket_timeout"],
        "socket_connect_timeout": Config.CELERY_BROKER_TRANSPORT_OPTIONS["socket_connect_timeout"],
        "visibility_timeout": Config.CELERY_BROKER_TRANSPORT_OPTIONS["visibility_timeout"],
    },
)

# The watchdog fails a submission whose container has not started after this long;
# Config.CELERY_MESSAGE_EXPIRES must stay at least 15 min below it, because a worker
# That takes a message just before it expires still has to build the image
NEVER_PICKED_UP_CUTOFF = timedelta(hours=1)


@worker_process_init.connect
def _dispose_inherited_db_connections(**kwargs: Any) -> None:
    """Drop pooled DB connections a prefork child inherited from its parent.

    The parent opened them at startup (schema revision check); sharing those
    sockets across processes corrupts the protocol stream. ``close=False`` leaves
    them open for the parent and only resets this child's pool.
    """
    if not HAS_APP or app is None:
        return
    with app.app_context():
        db.engine.dispose(close=False)


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
    from utils.worker_utils import run_stale_dir_sweep

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
    soft_time_limit=Config.CELERY_TASK_SOFT_TIME_LIMIT,
    time_limit=Config.CELERY_TASK_TIME_LIMIT,
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
        # The sandbox enforces the task's own time limit, so hitting Celery's limit means
        # the time went to waiting for a GPU or building the image: a platform failure
        if HAS_APP and app:
            with app.app_context():
                sub = db.session.get(Submission, submission_id)
                if sub and sub.status not in TERMINAL_STATUSES:
                    sub.status = "failed"
                    sub.detailed_status = INFRA_FAILURE
                    sub.logs = (sub.logs or "") + "\n[TIMEOUT] Celery soft time limit exceeded."
                    db.session.commit()
                    from services.baseline_service import apply_baseline_outcome
                    from utils.sse_utils import publish_submission_status

                    apply_baseline_outcome(sub)
                    publish_submission_status(submission_id, "failed")
        elif IS_EVAL_WORKER and metadata:
            from utils.worker_utils import report_status_to_server

            report_status_to_server(
                metadata=metadata,
                status="failed",
                detailed_status=INFRA_FAILURE,
                logs="[TIMEOUT] Celery soft time limit exceeded.",
            )
        return
    except Exception as e:
        from utils.cache_utils import log_dead_letter

        log_dead_letter(
            submission_id,
            task_id=metadata.get("task_id") if metadata else None,
            challenge_id=metadata.get("challenge_id") if metadata else None,
            error=e,
        )
        raise


@celery.task
def run_backup(auto: bool = True, db_only: bool = False, scheduled_at: str | None = None) -> Any:
    """Celery task: create a pg_dump+uploads tarball backup.

    ``scheduled_at`` is set by ``check_and_backup``; the claim it identifies is
    released however the backup ends, so a failed backup is retried at the next check.
    """
    try:
        if not RUNS_INTERNAL:
            return {"skipped": "role_not_internal"}
        if not app:
            return {"error": "no_app"}
        return _do_backup(app, auto=auto, db_only=db_only, scheduled_at=scheduled_at)
    finally:
        if scheduled_at:
            release_backup_dispatch(scheduled_at)


_ACTIVE_BACKUP_INTERVAL = timedelta(minutes=20)
_IDLE_BACKUP_INTERVAL = timedelta(hours=6)
# The check itself runs every 20 min; the slack keeps beat jitter from skipping a run
_BACKUP_SCHEDULE_SLACK = timedelta(minutes=1)


def _backup_due(last_ts: Any, now: datetime, interval: timedelta) -> bool:
    if isinstance(last_ts, bytes):
        last_ts = last_ts.decode("utf-8")
    if not isinstance(last_ts, str):
        return True
    try:
        last = datetime.fromisoformat(last_ts)
    except ValueError:
        return True
    return now - last >= interval - _BACKUP_SCHEDULE_SLACK


@celery.task
def check_and_backup() -> dict[str, Any]:
    """Celery beat task: schedule automatic backups.

    The database is backed up every 20 min while a contest is active (every 6 h
    otherwise); the uploads folder is included only every
    BACKUP_UPLOADS_INTERVAL_SECONDS, because it dominates the backup size.

    The schedule markers record successful backups only (the backup writes them),
    so a failed backup is retried at the next check. While one is queued or running,
    the dispatch claim keeps further checks from queueing a duplicate.
    """
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

        from utils.cache_utils import get_coordination_client

        result: dict[str, Any] = {"active_competitions": active_count}
        # The markers and the claim prevent duplicate backups, so they live on the
        # Broker instance, which never evicts (the cache instance runs volatile-lru)
        r = get_coordination_client()
        if not r:
            return result
        scheduled_at = now.isoformat()
        try:
            interval = _ACTIVE_BACKUP_INTERVAL if active_count > 0 else _IDLE_BACKUP_INTERVAL
            if not _backup_due(r.get(LAST_AUTO_BACKUP_KEY), now, interval):
                return result
            uploads_interval = timedelta(seconds=Config.BACKUP_UPLOADS_INTERVAL_SECONDS)
            include_uploads = _backup_due(r.get(LAST_FULL_BACKUP_KEY), now, uploads_interval)
            claimed = r.set(BACKUP_DISPATCH_KEY, scheduled_at, nx=True, ex=backup_dispatch_ttl())
        except Exception as e:
            logger.warning("check_and_backup: backup markers unavailable, skipping: %s", e)
            return result
        if not claimed:
            result["backup"] = "in_progress"
            return result
        try:
            run_backup.delay(auto=True, db_only=not include_uploads, scheduled_at=scheduled_at)
        except Exception:
            release_backup_dispatch(scheduled_at)
            raise
        result["backup"] = "full" if include_uploads else "db_only"

    return result


# Periodic watchdog: marks submissions as failed if stuck in queued/running for too long
# Also recovers results from Redis fallback (workers that completed but couldn't reach the server)
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
        affected_challenge_ids: set[Any] = set()
        stuck: list[Any] = []
        # (id, status, is_baseline) of each submission this run ended; settled after the commit
        ended: list[tuple[Any, str, bool]] = []
        try:
            from utils.cache_utils import get_coordination_client, submission_fallback_key

            r = get_coordination_client()
            if not r:
                return {"error": "redis_unavailable"}
            stuck = Submission.query.filter(Submission.status.in_(ACTIVE_STATUSES)).yield_per(100)
            for sub in stuck:
                fallback_key = submission_fallback_key(sub.id)
                fallback_data = r.get(fallback_key)
                if fallback_data:
                    try:
                        fb = json.loads(fallback_data)
                        if not sub.celery_task_id or fb.get("attempt_id") != sub.celery_task_id:
                            logger.warning(
                                "Discarding stale fallback for submission %s (attempt %s)",
                                sub.id,
                                fb.get("attempt_id"),
                            )
                            r.delete(fallback_key)
                            continue
                        bound_worker = r.get(f"worker:attempt:{sub.celery_task_id}")
                        if isinstance(bound_worker, bytes):
                            bound_worker = bound_worker.decode()
                        # The lease expires after WORKER_ATTEMPT_LEASE_TTL without
                        # Server contact, which is exactly when a worker falls back
                        # To Redis; only a lease held by another worker disowns it
                        if not fb.get("worker_id") or (
                            bound_worker and fb.get("worker_id") != bound_worker
                        ):
                            logger.warning(
                                "Discarding unowned fallback for submission %s (worker %s)",
                                sub.id,
                                fb.get("worker_id"),
                            )
                            r.delete(fallback_key)
                            continue
                        sub.status = fb.get("status", "failed")
                        sub.detailed_status = fb.get("detailed_status", "failed")
                        sub.logs = (sub.logs or "") + "\n" + (fb.get("logs") or "")
                        if fb.get("public_score") is not None:
                            sub.public_score = float(fb["public_score"])
                        if fb.get("private_score") is not None:
                            sub.private_score = float(fb["private_score"])
                        if fb.get("execution_time_ms") is not None:
                            sub.execution_time_ms = int(fb["execution_time_ms"])
                        if fb.get("evaluation_time_ms") is not None:
                            sub.evaluation_time_ms = int(fb["evaluation_time_ms"])
                        if fb.get("metrics_payload_pub"):
                            sub.metrics_payload_public = fb["metrics_payload_pub"]
                        if fb.get("metrics_payload_priv"):
                            sub.metrics_payload_private = fb["metrics_payload_priv"]
                        r.delete(fallback_key)
                        recovered += 1
                        if sub.challenge_id:
                            affected_challenge_ids.add(sub.challenge_id)
                        ended.append((sub.id, sub.status, bool(sub.is_baseline)))
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
            Submission.status.in_(ACTIVE_STATUSES),
            Submission.executed_at.is_(None),
        ).yield_per(500)
        # Also check running submissions with executed_at set
        running_candidates = Submission.query.filter(
            Submission.status.in_(RUNNING_STATUSES),
            Submission.executed_at.isnot(None),
        ).yield_per(500)
        now = utcnow()
        timeout_count = 0
        # Chain() streams both queries lazily (yield_per) without materializing
        for sub in chain(timed_out_candidates, running_candidates):
            task_time_limit = (
                sub.time_limit_snapshot
                or (sub.task.time_limit_sec if sub.task else None)
                or (sub.challenge.time_limit_sec if sub.challenge else None)
                or 300
            )
            # The runner enforces the time limit inside the sandbox, so a run still
            # Going at 1.5x the limit means its worker was lost; like a submission no
            # Worker ever took, that is the platform's failure and costs no quota
            if sub.executed_at:
                max_runtime = timedelta(seconds=int(task_time_limit * 1.5))
                if now - sub.executed_at <= max_runtime:
                    continue
                reason = f"worker lost, task time limit ({task_time_limit}s) exceeded"
            else:
                # Config.CELERY_MESSAGE_EXPIRES stays at least 15 min below this cutoff,
                # So a late pickup still has time for its image build and first report
                if now - sub.created_at <= NEVER_PICKED_UP_CUTOFF:
                    continue
                reason = "never picked up by a worker (1h+ queued)"
            sub.status = "failed"
            sub.detailed_status = INFRA_FAILURE
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
            if sub.challenge_id:
                affected_challenge_ids.add(sub.challenge_id)
            ended.append((sub.id, sub.status, bool(sub.is_baseline)))

        if recovered > 0 or timeout_count > 0:
            db.session.commit()
            from utils.cache_utils import invalidate_leaderboard_cache

            for cid in affected_challenge_ids:
                invalidate_leaderboard_cache(cid)
            _settle_ended_submissions(ended)
        return {"recovered": recovered, "timed_out": timeout_count}


def _settle_ended_submissions(ended: list[tuple[Any, str, bool]]) -> None:
    """Signal final statuses, then settle ended baselines; called after the watchdog commits."""
    from services.baseline_service import apply_baseline_outcome
    from utils.sse_utils import publish_submission_status

    for submission_id, status, is_baseline in ended:
        publish_submission_status(submission_id, status)
        if not is_baseline:
            continue
        try:
            sub = db.session.get(Submission, submission_id)
            if sub is not None:
                apply_baseline_outcome(sub)
        except Exception as e:
            db.session.rollback()
            logger.warning("Watchdog: failed to settle submission %s: %s", submission_id, e)


@celery.task
def recalculate_dirty_leaderboards() -> dict[str, Any]:
    """Celery beat task: rebuild leaderboard cache for challenges marked as dirty."""
    if not RUNS_INTERNAL:
        return {"skipped": "role_not_internal"}
    if not app:
        return {"skipped": "no_app_context"}

    from utils.cache_utils import (
        clear_dirty_leaderboard_version,
        get_coordination_client,
        get_dirty_leaderboard_versions,
    )

    r = get_coordination_client()
    if not r:
        return {"error": "redis_unavailable"}

    try:
        dirty_versions = get_dirty_leaderboard_versions(r)
        if not dirty_versions:
            return {"recalculated": 0}

        recalculated_count = 0

        from models import Challenge
        from services.leaderboard_service import rebuild_leaderboard
        from utils.sse_utils import publish_leaderboard_update

        with app.app_context():
            for cid, dirty_version in dirty_versions.items():
                try:
                    challenge = db.session.get(Challenge, cid)
                    if not challenge:
                        clear_dirty_leaderboard_version(r, cid, dirty_version)
                        continue

                    if not rebuild_leaderboard(cid):
                        # Another rebuild holds the lock; keep the marker for the next run
                        continue

                    # The only publisher of leaderboard SSE updates
                    publish_leaderboard_update(cid)
                    clear_dirty_leaderboard_version(r, cid, dirty_version)
                    recalculated_count += 1
                except Exception as e:
                    logger.error("recalculate_dirty_leaderboards: failed for %s: %s", cid, e)

        return {"recalculated": recalculated_count}
    except Exception as e:
        logger.error("recalculate_dirty_leaderboards failed: %s", e)
        return {"error": str(e)}


@celery.task
def sync_environments() -> dict[str, Any]:
    """Celery beat task: queue one sync per enabled nanoColab environment."""
    if not RUNS_INTERNAL:
        return {"skipped": "role_not_internal"}
    if not app:
        return {"skipped": "no_app_context"}

    from services.environment_service import enabled_environment_ids, nanocolab_enabled
    from utils.cache_utils import cache_lock

    interval = Config.NANOCOLAB_SYNC_INTERVAL_SECONDS
    with app.app_context():
        if not nanocolab_enabled():
            return {"skipped": "nanocolab_disabled"}
        with cache_lock("nanocolab_sync", ttl=interval) as got:
            if not got:
                return {"skipped": "locked"}
            ids = enabled_environment_ids()
            for environment_id in ids:
                sync_environment.apply_async(
                    args=[environment_id], queue="internal", expires=interval
                )
    return {"queued": len(ids)}


# Listing every event of the API key is heavier than a sync tick, so it runs less often
NANOCOLAB_RECONCILE_SECONDS = 600.0


@celery.task
def reconcile_nanocolab_events() -> dict[str, Any]:
    """Celery beat task: cancel nanoColab events whose stage or competition LavBench deleted."""
    if not RUNS_INTERNAL:
        return {"skipped": "role_not_internal"}
    if not app:
        return {"skipped": "no_app_context"}

    from services.environment_service import nanocolab_enabled, reconcile_events

    with app.app_context():
        if not nanocolab_enabled():
            return {"skipped": "nanocolab_disabled"}
        try:
            return dict(reconcile_events())
        except Exception:
            db.session.rollback()
            logger.exception("nanoColab event reconciliation failed")
            return {"result": "error"}


# Room to build and upload a 2 GiB package, while the hard limit stays under the sync lock TTL
ENVIRONMENT_SYNC_SOFT_TIME_LIMIT = 3000
ENVIRONMENT_SYNC_TIME_LIMIT = 3300


@celery.task(
    soft_time_limit=ENVIRONMENT_SYNC_SOFT_TIME_LIMIT, time_limit=ENVIRONMENT_SYNC_TIME_LIMIT
)
def sync_environment(environment_id: str) -> dict[str, Any]:
    """Celery task: package, push and refresh one nanoColab environment."""
    if not RUNS_INTERNAL:
        return {"skipped": "role_not_internal"}
    if not app:
        return {"skipped": "no_app_context"}

    from services.environment_service import sync_environment as run_sync

    with app.app_context():
        try:
            return {"result": run_sync(environment_id)}
        except Exception:
            db.session.rollback()
            logger.exception("Environment sync failed for %s", environment_id)
            return {"result": "error"}


# Celery Beat schedule for periodic tasks
# Watchdog_stuck_submissions: checks for stuck submissions every 5 minutes
# Start with: celery -A tasks.celery beat -l info
@celery.task
def prune_docker_images() -> dict[str, str]:
    """Celery task: prune unused Docker images/layers on worker nodes."""
    return run_docker_prune()


@celery.task
def sweep_stale_task_dirs() -> dict[str, Any]:
    """Celery task: remove abandoned task execution dirs left behind by
    killed/restarted workers (see ``worker_utils.run_stale_dir_sweep``)."""
    from utils.worker_utils import run_stale_dir_sweep

    return {"removed": run_stale_dir_sweep()}


def _beat_entry(task: str, every_seconds: float, queue: str) -> dict[str, Any]:
    """Schedule a periodic task whose message expires before the next run is sent.

    Runs that wait behind slow work (or on a queue with no consumer) are dropped
    instead of piling up and executing back to back.
    """
    return {
        "task": task,
        "schedule": every_seconds,
        "options": {"queue": queue, "expires": every_seconds * 0.75},
    }


celery.conf.beat_schedule = {
    "watchdog-every-5m": _beat_entry("tasks.watchdog_stuck_submissions", 300.0, "internal"),
    "backup-check-every-20m": _beat_entry("tasks.check_and_backup", 1200.0, "internal"),
    "recalculate-dirty-leaderboards-every-20s": _beat_entry(
        "tasks.recalculate_dirty_leaderboards", 20.0, "internal"
    ),
    "nanocolab-sync": _beat_entry(
        "tasks.sync_environments", float(Config.NANOCOLAB_SYNC_INTERVAL_SECONDS), "internal"
    ),
    "nanocolab-reconcile": _beat_entry(
        "tasks.reconcile_nanocolab_events", NANOCOLAB_RECONCILE_SECONDS, "internal"
    ),
    "docker-prune-weekly-cpu": _beat_entry("tasks.prune_docker_images", 604800.0, "cpu_queue"),
    "docker-prune-weekly-gpu": _beat_entry("tasks.prune_docker_images", 604800.0, "gpu_queue"),
    "task-dir-sweep-daily-cpu": _beat_entry("tasks.sweep_stale_task_dirs", 86400.0, "cpu_queue"),
    "task-dir-sweep-daily-gpu": _beat_entry("tasks.sweep_stale_task_dirs", 86400.0, "gpu_queue"),
}

# Role-gated task registration. 'internal' workers handle only system tasks;
# 'eval' workers handle only evaluation/image tasks; the main server runs all
INTERNAL_TASKS = {
    "tasks.check_and_backup",
    "tasks.recalculate_dirty_leaderboards",
    "tasks.run_backup",
    "tasks.sync_environment",
    "tasks.sync_environments",
    "tasks.reconcile_nanocolab_events",
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
