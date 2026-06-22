"""Celery task definitions and beat schedule for async evaluation and backups."""

import os
import time
import logging
from celery import Celery
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Force UTC for Celery heartbeats to avoid clock drift warnings
# when the host system uses a non-UTC local timezone.
os.environ["TZ"] = "UTC"
time.tzset()

# Check if running as remote worker to bypass Flask/SQLAlchemy database connection setup
RUNNING_AS_WORKER = os.environ.get("RUNNING_AS_WORKER") == "true"

if RUNNING_AS_WORKER:
    celery = Celery(
        "tasks",
        broker=os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"),
        backend=os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0"),
    )
    app = None
    db = None
    Submission = None
    Challenge = None
else:
    from app import create_app
    from models import db, Submission, Challenge

    app = create_app()
    celery = Celery(
        "tasks", broker=app.config["CELERY_BROKER_URL"], backend=app.config["CELERY_RESULT_BACKEND"]
    )

from task_modules.submission_runner import run_eval_submission
from task_modules.system import run_register_worker_specs, run_backup as _do_backup
from task_modules.leaderboard import run_recalculate_all_leaderboards


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
    """Celery task: run a student submission through the evaluation pipeline in Docker."""
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
def register_worker_specs():
    """Celery task: register worker node specs (CPU/GPU/memory) in Redis."""
    return run_register_worker_specs(celery)


@celery.task
def run_backup(auto=True, challenge_id=None, state=None):
    """Celery task: create a pg_dump+uploads tarball backup."""
    if RUNNING_AS_WORKER:
        return {"skipped": "remote_worker"}
    if not app:
        return {"error": "no_app"}
    return _do_backup(app, auto=auto, challenge_id=challenge_id, state=state)


@celery.task
def check_and_backup():
    """Celery beat task: check deadlines and trigger backups (20min active / 6h idle)."""
    if RUNNING_AS_WORKER:
        return {"skipped": "remote_worker"}
    if not app:
        return {"error": "no_app"}
    with app.app_context():
        from config import Config

        now = datetime.utcnow()
        grace = timedelta(seconds=Config.DEADLINE_GRACE_PERIOD_SECONDS)
        window = timedelta(minutes=20)

        from models import Challenge

        challenges = Challenge.query.filter(
            Challenge.is_active == True, Challenge.is_archived == False
        ).all()

        active_count = 0
        for c in challenges:
            if c.start_time and c.start_time <= now and (not c.end_time or c.end_time >= now):
                active_count += 1

            # Grace period just ended
            if (
                c.end_time
                and not c.scores_finalized
                and c.end_time + grace < now
                and c.end_time + grace > now - window
            ):
                run_backup.delay(auto=True, challenge_id=c.id, state="grace_ended")

            # Submission deadline just passed
            elif (
                c.end_time
                and not c.scores_finalized
                and c.end_time < now
                and c.end_time > now - window
            ):
                run_backup.delay(auto=True, challenge_id=c.id, state="submission_ended")

        # General auto backup: every 20min when active, every 6h when idle
        last_key = "backup:last_auto"
        from cache_utils import get_redis_client, get_cached, set_cached

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
                run_backup.delay(auto=True)

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
                    ["queued", "running", "building_env", "running_inference", "evaluating"]
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
                    except Exception as e:
                        logger.error(
                            "Watchdog: failed to recover fallback for submission %s: %s", sub.id, e
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
        now = datetime.utcnow()
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


# Celery Beat schedule for periodic tasks
# watchdog_stuck_submissions: checks for stuck submissions every 5 minutes
# Start with: celery -A tasks.celery beat -l info
celery.conf.beat_schedule = {
    "watchdog-every-5m": {
        "task": "tasks.watchdog_stuck_submissions",
        "schedule": 300.0,
    },
    "backup-check-every-20m": {
        "task": "tasks.check_and_backup",
        "schedule": 1200.0,
    },
}
