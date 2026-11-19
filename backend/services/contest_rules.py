"""Rules that decide results: deadlines, the counted run, final selection and finalising.

Every route, query and service that needs one of these rules calls this module; score
visibility stays in ``utils.score_visibility``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func

from config import Config
from models import Challenge, Stage, Submission, Task, User, db
from services.submission_status import ACTIVE_STATUSES
from utils.dates import utcnow

# A competitor may change the final selection until this long after the deadline, or after
# their last run sent before it finished (when its result was first shown), whichever is later
FINAL_SELECTION_WINDOW = timedelta(seconds=300)


def grace_period() -> timedelta:
    return timedelta(seconds=int(Config.DEADLINE_GRACE_PERIOD_SECONDS))


def _task_stage(task: Task) -> Stage | None:
    stage: Stage | None = getattr(task, "stage", None) if task.stage_id else None
    if stage is None and task.stage_id:
        stage = db.session.get(Stage, task.stage_id)
    return stage


def submission_deadline(task: Task, challenge: Challenge) -> datetime | None:
    """The last moment a submission to the task is accepted: its end time plus the grace.

    The stage's end when the task has a stage with one, else the competition's end.
    Competitors are shown the end time itself; the grace only absorbs delays.
    """
    stage = _task_stage(task)
    base = stage.end_time if stage is not None and stage.end_time is not None else None
    base = base or challenge.end_time
    if base is None:
        return None
    deadline: datetime = base + grace_period()
    return deadline


def is_submission_eligible(submission: Submission, task: Task, challenge: Challenge) -> bool:
    """Whether a submission was sent within the task's deadline (grace included)."""
    deadline = submission_deadline(task, challenge)
    return deadline is None or (
        submission.created_at is not None and submission.created_at <= deadline
    )


# ── The counted run ──
# One ordering, read in SQL and in Python: the selected final submission, then the best
# public score, then the faster run, then the earlier submission, then the id. Private
# scores never decide which run counts, before or after they are revealed


def counted_run_order() -> tuple[Any, ...]:
    """The ORDER BY of the counted run, best first; NULLs sort last on every engine."""
    return (
        Submission.is_final_selection.desc().nulls_last(),
        Submission.public_score.desc().nulls_last(),
        Submission.execution_time_ms.asc().nulls_last(),
        Submission.created_at.asc().nulls_last(),
        Submission.id.asc(),
    )


def counted_run_key(submission: Submission) -> tuple[Any, ...]:
    """The same ordering as ``counted_run_order`` as an ascending Python sort key."""
    final = submission.is_final_selection
    public = submission.public_score
    runtime = submission.execution_time_ms
    created = submission.created_at
    return (
        final is None,
        not final,
        public is None,
        -(public or 0.0),
        runtime is None,
        runtime or 0,
        created is None,
        created or datetime.min,
        str(submission.id),
    )


def counted_run(
    task: Task, user_subs: Iterable[Submission], challenge: Challenge
) -> Submission | None:
    """The run that counts among one competitor's completed runs on a task."""
    eligible = [s for s in user_subs if is_submission_eligible(s, task, challenge)]
    return min(eligible, key=counted_run_key) if eligible else None


# ── Final selection ──


@dataclass(frozen=True)
class SelectionWindow:
    """Whether a competitor may still choose the final submission of a task, and until when."""

    open: bool
    # None while a run sent before the deadline is still waiting or running
    closes_at: datetime | None


def _window_close(deadline: datetime, last_finished: datetime | None) -> datetime:
    start = max(deadline, last_finished) if last_finished else deadline
    return start + FINAL_SELECTION_WINDOW


def selection_window(
    user_id: Any, task: Task, challenge: Challenge, now: datetime | None = None
) -> SelectionWindow:
    """The final-selection window of one competitor on one task."""
    deadline = submission_deadline(task, challenge)
    if deadline is None:
        return SelectionWindow(open=True, closes_at=None)
    base = Submission.query.filter(
        Submission.user_id == user_id,
        Submission.task_id == task.id,
        Submission.is_baseline.is_(False),
        Submission.created_at <= deadline,
    )
    if base.filter(Submission.status.in_(ACTIVE_STATUSES)).first() is not None:
        return SelectionWindow(open=True, closes_at=None)
    last_finished = base.with_entities(func.max(Submission.finished_at)).scalar()
    closes_at = _window_close(deadline, last_finished)
    return SelectionWindow(open=(now or utcnow()) <= closes_at, closes_at=closes_at)


def _competitor_runs(task_ids: list[Any]) -> Any:
    return (
        Submission.query.join(User, Submission.user_id == User.id)
        .filter(
            Submission.task_id.in_(task_ids),
            Submission.is_baseline.is_(False),
            User.role == "competitor",
        )
        .with_entities(Submission)
    )


def latest_selection_close(tasks: list[Task], challenge: Challenge) -> datetime | None:
    """When the last competitor's final-selection window closes on any of the tasks."""
    latest: datetime | None = None
    by_deadline: dict[datetime, list[Any]] = {}
    for task in tasks:
        deadline = submission_deadline(task, challenge)
        if deadline is not None:
            by_deadline.setdefault(deadline, []).append(task.id)
    for deadline, task_ids in by_deadline.items():
        last_finished = (
            _competitor_runs(task_ids)
            .filter(Submission.created_at <= deadline)
            .with_entities(func.max(Submission.finished_at))
            .scalar()
        )
        closes = _window_close(deadline, last_finished)
        latest = closes if latest is None or closes > latest else latest
    return latest


def pending_competitor_runs(tasks: list[Task]) -> int:
    """Competitor runs on the tasks that are still waiting or running."""
    task_ids = [task.id for task in tasks]
    if not task_ids:
        return 0
    count: int = _competitor_runs(task_ids).filter(Submission.status.in_(ACTIVE_STATUSES)).count()
    return count


# ── Finalising ──
FINALIZE_NOT_ENDED = "not_ended"
FINALIZE_RUNS_PENDING = "runs_pending"
FINALIZE_SELECTION_OPEN = "selection_open"


@dataclass(frozen=True)
class FinalizeReadiness:
    """Whether a stage or competition may be finalised; if not, why and from when."""

    ready: bool
    reason: str | None = None
    available_at: datetime | None = None
    pending_runs: int = 0


def finalize_readiness(
    challenge: Challenge, stage: Stage | None = None, now: datetime | None = None
) -> FinalizeReadiness:
    """Finalising needs the deadline and grace over, no competitor run left and every
    competitor's final-selection window closed; the competition skips its test stages."""
    now = now or utcnow()
    end = stage.end_time if stage is not None else challenge.end_time
    if end is not None and now <= end + grace_period():
        return FinalizeReadiness(False, FINALIZE_NOT_ENDED, end + grace_period())
    if stage is not None:
        tasks = Task.query.filter_by(stage_id=stage.id).all()
    else:
        test_stage_ids = {
            s.id for s in Stage.query.filter_by(challenge_id=challenge.id) if s.is_test
        }
        tasks = [
            t
            for t in Task.query.filter_by(challenge_id=challenge.id).all()
            if t.stage_id not in test_stage_ids
        ]
    pending = pending_competitor_runs(tasks)
    if pending:
        return FinalizeReadiness(False, FINALIZE_RUNS_PENDING, None, pending)
    closes = latest_selection_close(tasks, challenge)
    if closes is not None and now <= closes:
        return FinalizeReadiness(False, FINALIZE_SELECTION_OPEN, closes)
    return FinalizeReadiness(True)
