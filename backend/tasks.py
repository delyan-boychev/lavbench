import os
import time
from celery import Celery

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

@celery.task(bind=True)
def evaluate_submission(self, submission_id, metadata=None):
    return run_eval_submission(self, submission_id, metadata, app, db, Submission, Challenge)

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
