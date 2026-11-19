"""Submission statuses, the transitions allowed between them, and the one writer of both.

Every change of ``Submission.status`` and of the final selection goes through
``transition`` or ``select_final``: a conditional UPDATE that applies only while the row
is still in an expected status, so a writer that lost a race changes nothing and says so.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

# Dependency-free at import on purpose: beat and eval workers read the vocabulary without
# The app, the database or the PII key; the writers import the models when called

# ── Statuses ──
QUEUED = "queued"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
STATUSES: tuple[str, ...] = (QUEUED, RUNNING, COMPLETED, FAILED)
# A worker may still change an active run; a terminal one never changes again
ACTIVE_STATUSES: tuple[str, ...] = (QUEUED, RUNNING)
TERMINAL_STATUSES: tuple[str, ...] = (COMPLETED, FAILED)

# ── Detailed statuses ──
# Progress of a running run, reported by its worker
BUILDING_ENV = "building_env"
RUNNING_INFERENCE = "running_inference"
EVALUATING = "evaluating"
# Why a run failed: stopped by a person, or by the platform (enqueue failure, never picked
# Up, lost worker, file sync, GPU, Docker or image build). A platform failure never counts
# Toward a quota (R16, R60, Q22)
KILLED = "killed"
INFRA_FAILURE = "failed_infra"
FAILURE_DETAILS: tuple[str, ...] = (KILLED, INFRA_FAILURE)

# ── Transitions ──
# Every (from, to) pair a writer may apply; a run never leaves a terminal status, and a
# Self-transition of an active status carries progress (detailed status, logs, timings)
ALLOWED_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        (QUEUED, QUEUED),
        (QUEUED, RUNNING),
        (QUEUED, FAILED),
        (RUNNING, RUNNING),
        (RUNNING, COMPLETED),
        (RUNNING, FAILED),
    }
)


def is_allowed(from_status: str | None, to_status: str) -> bool:
    return (from_status, to_status) in ALLOWED_TRANSITIONS


def predecessors(to_status: str) -> tuple[str, ...]:
    """The statuses a run may be in to move to ``to_status``."""
    return tuple(s for s in STATUSES if (s, to_status) in ALLOWED_TRANSITIONS)


def _expire_loaded(submission_id: Any) -> None:
    """Make an already loaded row read the database again after a Core UPDATE."""
    from sqlalchemy import inspect

    from models import Submission, db

    # Ids load as strings but new rows keep their UUID, so compare them as text
    target = str(submission_id)
    for loaded in list(db.session.identity_map.values()):
        state = inspect(loaded, raiseerr=False)
        identity = state.identity if state is not None else None
        if isinstance(loaded, Submission) and identity and str(identity[0]) == target:
            db.session.expire(loaded)


def transition(
    submission_id: Any,
    to_status: str,
    *,
    from_statuses: Iterable[str],
    detailed_status: str | None = None,
    attempt_id: str | None = None,
    fields: Mapping[str, Any] | None = None,
) -> bool:
    """Move a run to ``to_status`` if it is still in one of ``from_statuses``.

    One ``UPDATE ... WHERE id = :id AND status IN (:from_statuses)`` (and the attempt id
    when given) sets the status, the detailed status, ``fields`` and, for a terminal
    status, ``finished_at``. Returns whether it applied; the caller commits, and does
    nothing more (no logs, no signals, no quota give-back) when it did not.
    """
    from sqlalchemy import update

    from models import Submission, db
    from utils.dates import utcnow

    expected = tuple(from_statuses)
    forbidden = [s for s in expected if not is_allowed(s, to_status)]
    if not expected or forbidden:
        raise ValueError(f"Transition {forbidden or expected} -> {to_status!r} is not allowed")
    if detailed_status in FAILURE_DETAILS and to_status != FAILED:
        raise ValueError(f"Detailed status {detailed_status!r} needs status {FAILED!r}")
    values: dict[str, Any] = dict(fields or {})
    values["status"] = to_status
    if detailed_status is not None:
        values["detailed_status"] = detailed_status
    if to_status in TERMINAL_STATUSES:
        values["finished_at"] = utcnow()
    stmt = update(Submission).where(Submission.id == submission_id, Submission.status.in_(expected))
    if attempt_id is not None:
        stmt = stmt.where(Submission.celery_task_id == attempt_id)
    result = db.session.execute(stmt.values(**values).execution_options(synchronize_session=False))
    _expire_loaded(submission_id)
    return bool(getattr(result, "rowcount", 0) == 1)


def select_final(submission_id: Any, user_id: Any, task_id: Any) -> bool:
    """Make one completed, non-baseline run its owner's only final selection on the task.

    One UPDATE sets the flag of every run of the owner on the task, so two selections that
    race leave exactly one selected. Returns False when the run is not selectable.
    """
    from sqlalchemy import case, select, update
    from sqlalchemy.orm import aliased

    from models import Submission, db

    chosen = aliased(Submission)
    selectable = (
        select(chosen.id)
        .where(
            chosen.id == submission_id,
            chosen.user_id == user_id,
            chosen.task_id == task_id,
            chosen.status == COMPLETED,
            chosen.is_baseline.is_(False),
        )
        .exists()
    )
    stmt = (
        update(Submission)
        .where(Submission.user_id == user_id, Submission.task_id == task_id, selectable)
        .values(is_final_selection=case((Submission.id == submission_id, True), else_=False))
        .execution_options(synchronize_session=False)
    )
    result = db.session.execute(stmt)
    db.session.expire_all()
    return bool(getattr(result, "rowcount", 0) > 0)
