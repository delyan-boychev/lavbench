"""Baseline lifecycle: turn a finished baseline run into its task's readiness."""

from __future__ import annotations

import logging
from typing import Any

from models import Challenge, Submission, Task, db
from services.submission_service import dispatch_submission
from utils.dates import utcnow
from utils.submission_status import INFRA_FAILURE, TERMINAL_STATUSES

logger = logging.getLogger(__name__)

# A platform failure (GPU, Docker, image build, file sync, lost worker, expiry) says
# Nothing about the baseline notebook, so it is retried before the task is blocked
MAX_BASELINE_INFRA_RETRIES = 2
# Baselines decide whether competitors may submit at all, so they run first
BASELINE_PRIORITY = 0


def current_baseline(task_id: Any) -> Submission | None:
    """Return the task's newest baseline row, the only one that may change readiness."""
    # Ids are UUIDv7 and sort in creation order; created_at moves on a retry
    newest: Submission | None = (
        Submission.query.filter(
            Submission.task_id == task_id,
            Submission.is_baseline.is_(True),
        )
        .order_by(Submission.id.desc())
        .first()
    )
    return newest


def apply_baseline_outcome(submission: Submission) -> None:
    """Apply a terminal baseline run to its task's problem codes.

    The single place every way a run ends (worker report, watchdog, Redis fallback
    recovery, Celery soft time limit, kill) settles task readiness. A completed run
    clears ``ERR_BASELINE_FAILED``; a failed run sets it; a platform failure
    (``failed_infra``) is requeued as a fresh attempt up to
    ``MAX_BASELINE_INFRA_RETRIES`` times before it sets the code. Callers commit the
    terminal status first and signal the submission's status after this returns,
    because a requeued run is no longer terminal.
    """
    if not submission.is_baseline or submission.task_id is None:
        return
    if submission.status not in TERMINAL_STATUSES:
        return
    newest = current_baseline(submission.task_id)
    if newest is None or str(newest.id) != str(submission.id):
        return
    task = db.session.get(Task, submission.task_id)
    challenge = db.session.get(Challenge, submission.challenge_id)
    if task is None or challenge is None:
        return

    if submission.status == "completed":
        _set_baseline_failed(task, failed=False)
        return
    # Each pass raises infra_retry_count, and a refused requeue leaves the row
    # Failed_infra again, so the loop ends after at most MAX_BASELINE_INFRA_RETRIES
    while (
        submission.detailed_status == INFRA_FAILURE
        and (submission.infra_retry_count or 0) < MAX_BASELINE_INFRA_RETRIES
    ):
        if _requeue(submission, task, challenge):
            return
    _set_baseline_failed(task, failed=True)


def _requeue(submission: Submission, task: Task, challenge: Challenge) -> bool:
    """Queue the same row again as a fresh attempt; False when the broker refused it."""
    from utils.sse_utils import clear_submission_logs, publish_queue_update

    submission.infra_retry_count = (submission.infra_retry_count or 0) + 1
    attempt = submission.infra_retry_count + 1
    total = MAX_BASELINE_INFRA_RETRIES + 1
    submission.logs = (
        f"{submission.logs or ''}\n[RETRY] Platform failure; baseline requeued "
        f"(attempt {attempt} of {total})."
    ).strip()
    submission.status = "queued"
    submission.detailed_status = "queued"
    # The watchdog's never-picked-up clock runs from created_at
    submission.created_at = utcnow()
    submission.executed_at = None
    submission.gpu_node = None
    submission.execution_time_ms = None
    submission.public_score = None
    submission.private_score = None
    submission.final_weighted_score_public = None
    submission.final_weighted_score_private = None
    submission.metrics_payload_public = None
    submission.metrics_payload_private = None
    db.session.commit()
    clear_submission_logs(submission.id)
    publish_queue_update()

    if not dispatch_submission(submission, task, challenge, priority=BASELINE_PRIORITY):
        logger.warning(
            "Baseline %s for task %s could not be requeued (attempt %s)",
            submission.id,
            task.id,
            attempt,
        )
        return False
    # Persists the dispatch-time limit snapshot the metadata builder recorded
    db.session.commit()
    logger.info(
        "Baseline %s for task %s requeued after a platform failure (attempt %s of %s)",
        submission.id,
        task.id,
        attempt,
        total,
    )
    return True


def _set_baseline_failed(task: Task, *, failed: bool) -> None:
    """Add or remove ``ERR_BASELINE_FAILED`` and drop the caches that show readiness."""
    from utils.cache import invalidate_entity_cache

    codes = set(task.problem_codes or [])
    baseline_codes = {"ERR_BASELINE_FAILED"}
    updated = (codes | baseline_codes) if failed else (codes - baseline_codes)
    if updated == codes:
        return
    task.problem_codes = sorted(updated) or None
    db.session.commit()
    # The staff challenge view caches each task's problem codes
    invalidate_entity_cache(task.challenge_id)
