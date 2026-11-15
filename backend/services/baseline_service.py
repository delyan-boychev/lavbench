"""Baseline lifecycle: queue a task's baseline run and turn its outcome into readiness."""

from __future__ import annotations

import logging
import os
from typing import Any

from models import Challenge, Submission, Task, db
from services.submission_service import create_submission, extract_code_from_notebook
from utils.submission_status import INFRA_FAILURE, TERMINAL_STATUSES

logger = logging.getLogger(__name__)

# A platform failure says nothing about the notebook, so it is rerun before blocking the task
MAX_BASELINE_INFRA_RETRIES = 2
# Baselines gate competitor submissions, so they share the staff priority, ahead of competitors
BASELINE_PRIORITY = 0


def current_baseline(task_id: Any) -> Submission | None:
    """Return the task's newest baseline run, the only one that may change readiness."""
    # Ids are UUIDv7 and sort in creation order, also within one millisecond
    newest: Submission | None = (
        Submission.query.filter(
            Submission.task_id == task_id,
            Submission.is_baseline.is_(True),
        )
        .order_by(Submission.id.desc())
        .first()
    )
    return newest


def queue_baseline(
    task: Task, challenge: Challenge, user_id: Any, *, infra_retry_count: int = 0
) -> Submission | None:
    """Queue the task's baseline notebook; None when it has none or the broker refused it."""
    path = task.baseline_notebook_path
    sources = extract_code_from_notebook(path) if path and os.path.exists(path) else []
    if not sources:
        return None
    cells = [{"source": source} for source in sources]
    result = create_submission(
        task,
        challenge,
        user_id,
        "admin",
        cells,
        is_baseline=True,
        priority=BASELINE_PRIORITY,
        infra_retry_count=infra_retry_count,
    )
    if isinstance(result, tuple):
        logger.warning("Baseline for task %s was not queued: HTTP %s", task.id, result[1])
        refused = current_baseline(task.id)
        if refused is not None:
            apply_baseline_outcome(refused)
        return None
    return result


def apply_baseline_outcome(submission: Submission) -> None:
    """Settle task readiness from an ended baseline run; every way a run ends calls this."""
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
    if _needs_rerun(submission, task):
        retries = submission.infra_retry_count + 1
        rerun = queue_baseline(task, challenge, submission.user_id, infra_retry_count=retries)
        if rerun is not None:
            logger.info(
                "Baseline %s for task %s failed on the platform; rerun as %s (retry %s of %s)",
                submission.id,
                task.id,
                rerun.id,
                retries,
                MAX_BASELINE_INFRA_RETRIES,
            )
            return
    _set_baseline_failed(task, failed=True)


def _needs_rerun(submission: Submission, task: Task) -> bool:
    """Whether a failed baseline run was a platform failure that a new run may avoid."""
    return (
        submission.detailed_status == INFRA_FAILURE
        and submission.infra_retry_count < MAX_BASELINE_INFRA_RETRIES
        # A refused enqueue sent nothing: the broker is down; saving the task queues it again
        and submission.celery_task_id is not None
        # A build or sync problem fails every run the same way until the task is fixed
        and set(task.problem_codes or []) <= {"ERR_BASELINE_FAILED"}
    )


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
