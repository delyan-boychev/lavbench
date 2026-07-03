"""Celery task definitions and beat schedule for async evaluation and backups."""

import contextlib
import logging
import os
import time
from datetime import datetime, timedelta

from celery import Celery
from config import Config
from log_config import RemoteShipHandler, setup_logging
from task_modules.leaderboard import run_recalculate_all_leaderboards
from task_modules.submission_runner import run_eval_submission
from task_modules.system import (
    run_backup as _do_backup,
)
from task_modules.system import (
    run_docker_prune,
    run_register_worker_specs,
)
from utils.dates import utcnow

logger = logging.getLogger(__name__)

# Force UTC for Celery heartbeats to avoid clock drift warnings
# when the host system uses a non-UTC local timezone.
os.environ["TZ"] = "UTC"
time.tzset()

setup_logging("celery")

# Check if running as remote worker to bypass Flask/SQLAlchemy database connection setup
RUNNING_AS_WORKER = Config.RUNNING_AS_WORKER

if RUNNING_AS_WORKER and Config.WORKER_LOG_SHIP_URL:
    ship_url = Config.WORKER_LOG_SHIP_URL
    from worker_utils import _sign_worker_token

    token = _sign_worker_token("worker")
    if token:
        root = logging.getLogger()
        root.addHandler(RemoteShipHandler(ship_url, token))

if RUNNING_AS_WORKER:
    celery = Celery(
        "tasks",
        broker=Config.CELERY_BROKER_URL,
        backend=Config.CELERY_RESULT_BACKEND,
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
    )


def configure_celery_ssl(celery_app):
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
    result_expires=Config.CELERY_RESULT_EXPIRES,
    broker_transport_options={
        "socket_timeout": Config.CELERY_BROKER_TRANSPORT_OPTIONS["socket_timeout"],
        "socket_connect_timeout": Config.CELERY_BROKER_TRANSPORT_OPTIONS["socket_connect_timeout"],
    },
)


@celery.task(
    bind=True,
    soft_time_limit=1200,
    time_limit=1500,
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def evaluate_submission(self, submission_id, metadata=None):
    """Celery task: run a competitor submission through the evaluation pipeline in Docker."""
    try:
        return run_eval_submission(self, submission_id, metadata, app, db, Submission, Challenge)
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
def recalculate_all_leaderboards():
    """Celery task: rebuild leaderboard cache for all active challenges."""
    if RUNNING_AS_WORKER:
        return
    return run_recalculate_all_leaderboards(app)


@celery.task
def recalculate_leaderboard(challenge_id):
    """Celery task: rebuild leaderboard cache for a specific challenge."""
    if RUNNING_AS_WORKER:
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

        from cache_utils import get_redis_client

        r = get_redis_client()
        if r:
            channel_name = f"challenge_{challenge_id}_leaderboard"
            import json

            r.publish(channel_name, json.dumps({"event": "update"}))


@celery.task
def register_worker_specs():
    """Celery task: register worker node specs (CPU/GPU/memory) in Redis."""
    return run_register_worker_specs(celery)


@celery.task
def run_backup(auto=True, db_only=False):
    """Celery task: create a pg_dump+uploads tarball backup."""
    if RUNNING_AS_WORKER:
        return {"skipped": "remote_worker"}
    if not app:
        return {"error": "no_app"}
    return _do_backup(app, auto=auto, db_only=db_only)


@celery.task
def check_and_backup():
    """Celery beat task: check deadlines and trigger backups (20min active / 6h idle)."""
    if RUNNING_AS_WORKER:
        return {"skipped": "remote_worker"}
    if not app:
        return {"error": "no_app"}
    with app.app_context():
        from config import Config

        now = utcnow()
        timedelta(seconds=Config.DEADLINE_GRACE_PERIOD_SECONDS)
        timedelta(minutes=20)

        from models import Challenge

        challenges = Challenge.query.filter(Challenge.is_active, not Challenge.is_archived).all()

        active_count = 0
        for c in challenges:
            if c.start_time and c.start_time <= now and (not c.end_time or c.end_time >= now):
                active_count += 1

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
def watchdog_stuck_submissions():
    """Celery beat task: recover fallback results and time-out stuck submissions."""
    if RUNNING_AS_WORKER:
        return {"skipped": "running_as_remote_worker"}
    if not app:
        return {"skipped": "no_app_context"}
    with app.app_context():
        import json

        # 1. Recover fallback results from Redis (workers that finished but couldn't reach server)
        recovered = 0
        try:
            from cache_utils import get_redis_client

            r = get_redis_client()
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
            ).all()
            for sub in stuck:
                fallback_key = f"submission:{sub.id}:fallback"
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
        ).all()
        # Also check running submissions with executed_at set
        running_candidates = Submission.query.filter(
            Submission.status.in_(["running", "building_env", "running_inference", "evaluating"]),
            Submission.executed_at.isnot(None),
        ).all()
        now = utcnow()
        timeout_count = 0
        for sub in timed_out_candidates + running_candidates:
            task_time_limit = 300
            if sub.task:
                task_time_limit = sub.task.time_limit_sec or sub.challenge.time_limit_sec or 300
            if sub.executed_at:
                max_runtime = timedelta(seconds=int(task_time_limit * 1.5))
                if now - sub.executed_at <= max_runtime:
                    continue
                reason = f"task time limit ({task_time_limit}s) exceeded"
            else:
                if now - sub.created_at <= timedelta(minutes=10):
                    continue
                reason = "never picked up by a worker (10m+ queued)"
            sub.status = "failed"
            sub.detailed_status = "failed"
            sub.logs = (sub.logs or "") + f"\n[WATCHDOG] Submission timed out — {reason}."
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
def recalculate_dirty_leaderboards():
    """Celery beat task: rebuild leaderboard cache for challenges marked as dirty."""
    if RUNNING_AS_WORKER:
        return {"skipped": "running_as_remote_worker"}
    if not app:
        return {"skipped": "no_app_context"}

    from cache_utils import get_redis_client

    r = get_redis_client()
    if not r:
        return {"error": "redis_unavailable"}

    try:
        dirty_challenges = r.smembers("leaderboard:dirty_challenges")
        if not dirty_challenges:
            return {"recalculated": 0}

        recalculated_count = 0
        import json

        from models import Challenge
        from services.leaderboard_service import build_and_cache_leaderboard

        with app.app_context():
            for cid_bytes in dirty_challenges:
                cid = cid_bytes.decode("utf-8") if isinstance(cid_bytes, bytes) else str(cid_bytes)

                # Remove from dirty set first to prevent race condition
                r.srem("leaderboard:dirty_challenges", cid)

                try:
                    challenge = Challenge.query.get(cid)
                    if not challenge:
                        continue

                    # Rebuild cache
                    build_and_cache_leaderboard(cid, is_frozen_view=False, force_rebuild=True)
                    if challenge.is_frozen:
                        build_and_cache_leaderboard(cid, is_frozen_view=True, force_rebuild=True)

                    # Publish event for live SSE updates
                    channel_name = f"challenge_{cid}_leaderboard"
                    r.publish(channel_name, json.dumps({"event": "update"}))
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
def prune_docker_images():
    """Celery task: prune unused Docker images/layers on worker nodes."""
    return run_docker_prune()


celery.conf.beat_schedule = {
    "watchdog-every-5m": {
        "task": "tasks.watchdog_stuck_submissions",
        "schedule": 300.0,
    },
    "backup-check-every-20m": {
        "task": "tasks.check_and_backup",
        "schedule": 1200.0,
    },
    "recalculate-dirty-leaderboards-every-20s": {
        "task": "tasks.recalculate_dirty_leaderboards",
        "schedule": 20.0,
    },
    "docker-prune-weekly": {
        "task": "tasks.prune_docker_images",
        "schedule": 604800.0,  # once a week (7 days)
    },
}

# Unregister tasks conditionally based on environment variables
INTERNAL_ONLY_WORKER = Config.INTERNAL_ONLY_WORKER
EVALUATION_ONLY_WORKER = Config.EVALUATION_ONLY_WORKER

if INTERNAL_ONLY_WORKER or EVALUATION_ONLY_WORKER:
    all_task_names = [
        "tasks.evaluate_submission",
        "tasks.register_worker_specs",
        "tasks.prune_docker_images",
        "tasks.check_and_backup",
        "tasks.recalculate_all_leaderboards",
        "tasks.recalculate_dirty_leaderboards",
        "tasks.recalculate_leaderboard",
        "tasks.run_backup",
        "tasks.watchdog_stuck_submissions",
    ]
    evaluation_tasks = {
        "tasks.evaluate_submission",
        "tasks.register_worker_specs",
        "tasks.prune_docker_images",
    }
    for tname in all_task_names:
        if (INTERNAL_ONLY_WORKER and tname in evaluation_tasks) or (
            EVALUATION_ONLY_WORKER and tname not in evaluation_tasks
        ):
            with contextlib.suppress(KeyError):
                celery.tasks.unregister(tname)
