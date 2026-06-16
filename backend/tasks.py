import os
import time
from celery import Celery
from datetime import datetime, timedelta

# Force UTC for Celery heartbeats to avoid clock drift warnings
# when the host system uses a non-UTC local timezone.
os.environ["TZ"] = "UTC"
time.tzset()

# Check if running as remote worker to bypass Flask/SQLAlchemy database connection setup
RUNNING_AS_WORKER = os.environ.get("RUNNING_AS_WORKER") == "true"

if RUNNING_AS_WORKER:
    celery = Celery(
        'tasks',
        broker=os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
        backend=os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')
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
        'tasks',
        broker=app.config['CELERY_BROKER_URL'],
        backend=app.config['CELERY_RESULT_BACKEND']
    )

from task_modules.submission_runner import run_eval_submission
from task_modules.system import run_register_worker_specs, run_automated_backup as auto_backup
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
    retry_jitter=True
)
def evaluate_submission(self, submission_id, metadata=None):
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
    if RUNNING_AS_WORKER: return
    return run_recalculate_all_leaderboards(app)

@celery.task
def register_worker_specs():
    return run_register_worker_specs(celery)

@celery.task
def run_automated_backup():
    return auto_backup(app)

# Periodic watchdog: marks submissions as failed if stuck in queued/running for too long
# Also recovers results from Redis fallback (workers that completed but couldn't reach the server).
# Runs every 5 minutes. Only the main server process runs this (not remote workers).
@celery.task
def watchdog_stuck_submissions():
    if RUNNING_AS_WORKER:
        return {"skipped": "running_as_remote_worker"}
    if not app:
        return {"skipped": "no_app_context"}
    with app.app_context():
        import redis as redis_lib
        import json
        
        # 1. Recover fallback results from Redis (workers that finished but couldn't reach server)
        recovered = 0
        try:
            r = redis_lib.Redis.from_url(app.config.get('CELERY_BROKER_URL', 'redis://localhost:6379/0'))
            stuck = Submission.query.filter(
                Submission.status.in_(['queued', 'running', 'building_env', 'running_inference', 'evaluating'])
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
                        print(f"Watchdog: failed to recover fallback for submission {sub.id}: {e}")
        except Exception as e:
            print(f"Watchdog: Redis connection error: {e}")
        
        # 2. Time out truly stuck submissions (30+ minutes without any update)
        stuck_since = datetime.utcnow() - timedelta(minutes=30)
        timed_out = Submission.query.filter(
            Submission.status.in_(['queued', 'running', 'building_env', 'running_inference', 'evaluating']),
            Submission.created_at < stuck_since
        ).all()
        timeout_count = 0
        for sub in timed_out:
            sub.status = 'failed'
            sub.detailed_status = 'failed'
            sub.logs = (sub.logs or '') + '\n[WATCHDOG] Submission timed out — worker did not report back within 30 minutes.'
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
    'watchdog-every-5m': {
        'task': 'tasks.watchdog_stuck_submissions',
        'schedule': 300.0,  # seconds (5 minutes)
    },
}
