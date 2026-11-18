"""Baseline lifecycle: queue a task's baseline run and turn its outcome into readiness."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import uuid
from typing import Any

from models import Challenge, Submission, Task, db
from models.submission import ORIGIN_BASELINE
from services.file_submission import SubmissionFiles, baseline_files
from services.submission_service import create_submission, extract_code_from_notebook
from utils.submission_status import INFRA_FAILURE, TERMINAL_STATUSES

logger = logging.getLogger(__name__)

# A platform failure says nothing about the notebook, so it is rerun before blocking the task
MAX_BASELINE_INFRA_RETRIES = 2
# Uploads arrive one at a time, so the baseline runs once, this long after the last change
BASELINE_DEBOUNCE_SECONDS = 60
# A marker whose delayed run was lost expires instead of holding readiness for ever
BASELINE_DUE_TTL = 600


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
    """Queue the task's baseline; None when it has none or the broker refused it.

    A notebook task runs its baseline notebook; a file task scores its hidden
    baseline_submission.parquet through the same path as a student's file.
    """
    cells: list[dict[str, Any]] = []
    files: SubmissionFiles | None = None
    if task.is_file_mode:
        files = baseline_files(task)
        if files is None:
            return None
    else:
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
        infra_retry_count=infra_retry_count,
        files=files,
        origin=ORIGIN_BASELINE,
    )
    if isinstance(result, tuple):
        logger.warning("Baseline for task %s was not queued: HTTP %s", task.id, result[1])
        refused = current_baseline(task.id)
        if refused is not None:
            apply_baseline_outcome(refused)
        return None
    return result


def _drop_ended_baselines(task_id: Any) -> None:
    """Delete the task's ended baseline runs and their files; a queued or running one keeps
    its row, so its worker's report still lands (a newer run makes its outcome moot)."""
    ended = Submission.query.filter(
        Submission.task_id == task_id,
        Submission.is_baseline.is_(True),
        Submission.status.in_(TERMINAL_STATUSES),
    ).all()
    paths = [p for s in ended for p in (s.code_storage_path, s.log_storage_path) if p]
    for submission in ended:
        db.session.delete(submission)
    db.session.commit()
    for path in paths:
        with contextlib.suppress(OSError):
            os.remove(path)


def requeue_baseline(task: Task, challenge: Challenge, user_id: Any) -> None:
    """Drop the task's ended baseline runs, then queue a fresh one."""
    _drop_ended_baselines(task.id)
    queue_baseline(task, challenge, user_id)


def _due_key(task_id: Any) -> str:
    return f"baseline_due:{task_id}"


def baseline_pending(task_id: Any) -> bool:
    """A change is waiting for its debounced baseline run."""
    from utils.cache_utils import get_coordination_client

    r = get_coordination_client()
    if r is None:
        return False
    try:
        return bool(r.exists(_due_key(task_id)))
    except Exception:
        return False


def schedule_baseline(task: Task, user_id: Any) -> None:
    """Mark the baseline pending and run it once, ``BASELINE_DEBOUNCE_SECONDS`` after the
    last change (each change replaces the token; only the newest delayed run acts)."""
    from tasks import run_due_baseline
    from utils.cache_utils import get_coordination_client

    token = uuid.uuid4().hex
    r = get_coordination_client()
    try:
        if r is None:
            raise RuntimeError("no coordination Redis")
        value = json.dumps({"token": token, "user_id": str(user_id)})
        r.set(_due_key(task.id), value, ex=BASELINE_DUE_TTL)
        _drop_ended_baselines(task.id)
        run_due_baseline.apply_async(
            args=[str(task.id), token], countdown=BASELINE_DEBOUNCE_SECONDS, queue="internal"
        )
    except Exception as exc:
        logger.warning("Baseline of task %s not debounced (%s); queued now", task.id, exc)
        with contextlib.suppress(Exception):
            if r is not None:
                r.delete(_due_key(task.id))
        requeue_baseline(task, task.challenge, user_id)


def run_due_baseline(task_id: Any, token: str) -> str:
    """The delayed run: queue the baseline when no newer change arrived since *token*."""
    from utils.cache_utils import delete_if_value, get_coordination_client

    r = get_coordination_client()
    if r is None:
        return "no_redis"
    raw = r.get(_due_key(task_id))
    if raw is None:
        return "none"
    value = raw.decode() if isinstance(raw, bytes) else str(raw)
    if json.loads(value).get("token") != token or not delete_if_value(r, _due_key(task_id), value):
        return "superseded"
    task = db.session.get(Task, task_id)
    if task is None:
        return "gone"
    requeue_baseline(task, task.challenge, json.loads(value).get("user_id"))
    return "queued"


def apply_baseline_outcome(submission: Submission) -> None:
    """Settle task readiness from an ended baseline run; every way a run ends calls this."""
    if not submission.is_baseline or submission.task_id is None:
        return
    if submission.status not in TERMINAL_STATUSES:
        return
    # The task changed after this run started; the debounced run decides readiness
    if baseline_pending(submission.task_id):
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
    set_problems(task, problem_codes=["ERR_BASELINE_FAILED"], present=failed)


def set_problems(
    task: Task, *, problem_codes: list[str], present: bool, fields: dict[str, Any] | None = None
) -> None:
    """Add or remove stored problem codes, with the message fields of added ones, and drop
    the caches that show readiness."""
    from utils.cache import invalidate_entity_cache

    db.session.refresh(task)
    codes = set(task.problem_codes or [])
    updated = (codes | set(problem_codes)) if present else (codes - set(problem_codes))
    stored = task.problem_fields if isinstance(task.problem_fields, dict) else {}
    kept = {code: value for code, value in stored.items() if code in updated}
    if present:
        for code in problem_codes:
            kept.pop(code, None)
            if fields:
                kept[code] = fields
    if updated == codes and kept == stored:
        return
    task.problem_codes = sorted(updated) or None
    task.problem_fields = kept or None
    db.session.commit()
    # The staff challenge view caches each task's problem codes
    invalidate_entity_cache(task.challenge_id)
