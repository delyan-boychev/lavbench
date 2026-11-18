"""Whether a task's mode and its published files can still change: one rule each."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from models import Submission, Task, User, db
from services.environment_service import owner_published, published_owners


def competitor_submitted(task_ids: Iterable[Any]) -> set[str]:
    """Ids of the tasks that have a competitor's submission, in one query."""
    ids = list(task_ids)
    if not ids:
        return set()
    rows = (
        db.session.query(Submission.task_id)
        .join(User, Submission.user_id == User.id)
        .filter(
            Submission.task_id.in_(ids),
            Submission.is_baseline.is_(False),
            User.role == "competitor",
        )
        .distinct()
        .all()
    )
    return {str(task_id) for (task_id,) in rows}


def mode_locked(task: Task) -> bool:
    """The evaluation mode is fixed once a competitor has submitted to the task."""
    return str(task.id) in competitor_submitted([task.id])


def task_locks(tasks: list[Task]) -> dict[str, dict[str, bool]]:
    """``mode_locked`` and ``files_locked`` for every task, with one query per rule."""
    submitted = competitor_submitted(task.id for task in tasks)
    published: dict[Any, set[str | None]] = {}
    locks = {}
    for task in tasks:
        if task.challenge_id not in published:
            published[task.challenge_id] = published_owners(task.challenge_id)
        locks[str(task.id)] = {
            "mode_locked": str(task.id) in submitted,
            "files_locked": owner_published(published[task.challenge_id], task.stage_id),
        }
    return locks
