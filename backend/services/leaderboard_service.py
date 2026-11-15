"""Service-layer functions for leaderboard computation and caching."""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from functools import cmp_to_key
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload

from models import Challenge, Stage, Submission, Task, User, db
from services.submission_service import (
    get_best_submission,
    submission_deadline,
    uses_private_score_for_selection,
)
from utils.cache_utils import cache_lock, get_cached, leaderboard_cache_key, set_cached

logger = logging.getLogger(__name__)

# Single lifetime of the cached challenge leaderboard; the beat task rebuilds it on
# Every change, so this only bounds how long an unchanged leaderboard is kept
LEADERBOARD_CACHE_SECONDS = 300
_REBUILD_LOCK_SECONDS = 30
_LOCK_WAIT_SECONDS = 3.0
_LOCK_POLL_SECONDS = 0.3


def build_and_cache_leaderboard(challenge_id: uuid.UUID | str) -> list[dict[str, Any]] | None:
    """Return the cached leaderboard, computing it only when no cached value exists.

    A cached value is served even while the beat task rebuilds it, so readers never
    stampede. On a cold cache one reader computes under the lock; the others wait
    briefly for that result and compute themselves only if it never appears.
    """
    cache_key = leaderboard_cache_key(challenge_id)
    cached: Any = get_cached(cache_key)
    if cached is not None:
        return cached  # type: ignore[no-any-return]

    with cache_lock(f"lock:{cache_key}", ttl=_REBUILD_LOCK_SECONDS) as got_lock:
        if not got_lock:
            cached = _wait_for_cached(cache_key)
            if cached is not None:
                return cached  # type: ignore[no-any-return]
        entries = _compute_leaderboard_entries(challenge_id)
        if entries is not None:
            set_cached(cache_key, entries, timeout=LEADERBOARD_CACHE_SECONDS)
        return entries


def rebuild_leaderboard(challenge_id: uuid.UUID | str) -> bool:
    """Recompute and cache the leaderboard (beat task).

    Returns False without computing when another process holds the rebuild lock;
    readers keep the current cached value meanwhile and the caller retries later.
    """
    cache_key = leaderboard_cache_key(challenge_id)
    with cache_lock(f"lock:{cache_key}", ttl=_REBUILD_LOCK_SECONDS) as got_lock:
        if not got_lock:
            return False
        entries = _compute_leaderboard_entries(challenge_id)
        if entries is not None:
            set_cached(cache_key, entries, timeout=LEADERBOARD_CACHE_SECONDS)
        return True


def _wait_for_cached(cache_key: str) -> Any:
    """Poll for the value another process is building; None when it never appears."""
    deadline = time.monotonic() + _LOCK_WAIT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(_LOCK_POLL_SECONDS)
        cached = get_cached(cache_key)
        if cached is not None:
            return cached
    return None


def _compute_leaderboard_entries(challenge_id: uuid.UUID | str) -> list[dict[str, Any]] | None:
    """Compute the full (unfiltered) leaderboard for a challenge; None if it does not exist."""
    challenge = db.session.get(Challenge, challenge_id)
    if not challenge:
        return None

    tasks = Task.query.filter_by(challenge_id=challenge_id).order_by(Task.id.asc()).all()

    challenge_finalized = challenge.scores_finalized

    from sqlalchemy import case, func

    private_score_task_ids = [
        task.id for task in tasks if uses_private_score_for_selection(task, challenge)
    ]
    if private_score_task_ids:
        selection_score = case(
            (
                Submission.task_id.in_(private_score_task_ids),
                func.coalesce(Submission.private_score, Submission.public_score),
            ),
            else_=Submission.public_score,
        )
    else:
        selection_score = Submission.public_score

    test_stage_task_ids = [
        s[0]
        for s in db.session.query(Task.id)
        .join(Stage, Task.stage_id == Stage.id)
        .filter(Stage.challenge_id == challenge_id, Stage.is_test)
        .all()
    ]
    eligible_clauses = []
    for task in tasks:
        deadline = submission_deadline(task, challenge)
        if deadline is None:
            eligible_clauses.append(Submission.task_id == task.id)
        else:
            eligible_clauses.append(
                and_(Submission.task_id == task.id, Submission.created_at <= deadline)
            )

    subq = (
        db.session.query(
            Submission.id.label("sub_id"),
            func.row_number()
            .over(
                partition_by=(Submission.user_id, Submission.task_id),
                order_by=(
                    Submission.is_final_selection.desc(),
                    selection_score.desc(),
                    Submission.execution_time_ms.asc(),
                ),
            )
            .label("rn"),
        )
        .filter(
            Submission.challenge_id == challenge_id,
            Submission.status == "completed",
            ~Submission.task_id.in_(test_stage_task_ids) if test_stage_task_ids else True,
            or_(*eligible_clauses) if eligible_clauses else False,
        )
        .subquery()
    )

    all_completed = (
        Submission.query.join(subq, Submission.id == subq.c.sub_id)
        .filter(subq.c.rn == 1)
        .options(
            joinedload(Submission.challenge),
            joinedload(Submission.user),
            joinedload(Submission.task),
        )
        .all()
    )

    # Pre-group by (user_id, task_id)
    sub_by_key: dict[tuple[uuid.UUID, uuid.UUID], list[Submission]] = {}
    for s in all_completed:
        key = (s.user_id, s.task_id)
        sub_by_key.setdefault(key, []).append(s)

    competitors = User.query.filter_by(role="competitor", challenge_id=challenge_id).all()
    challenge_cache = {challenge.id: challenge}
    leaderboard_entries = []

    for comp in competitors:
        task_scores = {}
        has_submitted = False

        for task in tasks:
            user_subs_for_task = sub_by_key.get((comp.id, task.id), [])
            chosen_sub = get_best_submission(task, user_subs_for_task, challenge)

            if chosen_sub:
                has_submitted = True
                task_scores[str(task.id)] = {
                    "public_score": chosen_sub.public_score,
                    "private_score": chosen_sub.private_score,
                    "submission_id": chosen_sub.id,
                    "execution_time_ms": chosen_sub.execution_time_ms or 0,
                    "created_at": chosen_sub.created_at,
                }
            else:
                task_scores[str(task.id)] = {
                    "public_score": None,
                    "private_score": None,
                    "submission_id": None,
                    "execution_time_ms": 0,
                    "created_at": None,
                }

        pub_scores_list = [
            v["public_score"] for v in task_scores.values() if v["public_score"] is not None
        ]
        priv_scores_list = [
            v["private_score"] for v in task_scores.values() if v["private_score"] is not None
        ]

        if pub_scores_list:
            tot_pub = 0.0
            for task in tasks:
                sc = task_scores[str(task.id)]["public_score"]
                if sc is not None:
                    tot_pub += sc
                else:
                    tot_pub += 0.0
            aggregated_public = tot_pub
        else:
            aggregated_public = None

        if priv_scores_list:
            tot_priv = 0.0
            for task in tasks:
                sc = task_scores[str(task.id)]["private_score"]
                if sc is not None:
                    tot_priv += sc
                else:
                    tot_priv += 0.0
            aggregated_private = tot_priv
        else:
            aggregated_private = None

        manual_points_dict = {}
        if comp.manual_points:
            if isinstance(comp.manual_points, dict):
                manual_points_dict = comp.manual_points
            elif isinstance(comp.manual_points, str):
                try:
                    manual_points_dict = json.loads(comp.manual_points)
                except Exception as e:
                    logger.exception("Failed to parse manual_points for user %s: %s", comp.id, e)
                    manual_points_dict = {}

        # Points may have 2 decimals; rounding keeps float noise out of rank ties
        total_points = round(sum(manual_points_dict.get(str(t.id), 0) for t in tasks), 2)

        total_exec_time = 0
        sub_dates: list[Any] = []
        for v in task_scores.values():
            if v.get("submission_id") is not None:
                total_exec_time += v.get("execution_time_ms") or 0
                if v.get("created_at"):
                    sub_dates.append(v.get("created_at"))

        earliest_sub_date = min(sub_dates) if sub_dates else datetime.max

        entry_dict = {
            "user": comp.to_dict(
                view_role="admin",
                scores_finalized=False,
                current_user_id=None,
                challenge_cache=challenge_cache,
            ),
            "task_scores": task_scores,
            "public_score": aggregated_public,
            "private_score": aggregated_private,
            "total_points": total_points,
            "has_submitted": has_submitted,
            "total_execution_time_ms": total_exec_time,
            "earliest_submission_time": earliest_sub_date,
        }
        leaderboard_entries.append(entry_dict)

    # Add baseline entries (one per task that has a baseline submission)
    baseline_by_task: dict[uuid.UUID, Submission] = {}
    for s in all_completed:
        if s.is_baseline:
            existing = baseline_by_task.get(s.task_id)
            if existing is None:
                baseline_by_task[s.task_id] = s
            else:
                chosen = get_best_submission(s.task, [existing, s], challenge)
                if chosen is not None:
                    baseline_by_task[s.task_id] = chosen

    competitor_ids = {c.id for c in competitors}
    for task_id, baseline_sub in baseline_by_task.items():
        task = next((t for t in tasks if t.id == task_id), None)
        if not task or baseline_sub.user is None:
            continue
        # Skip if the baseline submitter is already a competitor entry
        if baseline_sub.user_id in competitor_ids:
            continue
        bt_scores = {}
        for t in tasks:
            if t.id == task_id:
                bt_scores[str(t.id)] = {
                    "public_score": baseline_sub.public_score,
                    "private_score": baseline_sub.private_score,
                    "submission_id": baseline_sub.id,
                    "execution_time_ms": baseline_sub.execution_time_ms or 0,
                    "created_at": baseline_sub.created_at,
                }
            else:
                bt_scores[str(t.id)] = {
                    "public_score": None,
                    "private_score": None,
                    "submission_id": None,
                    "execution_time_ms": 0,
                    "created_at": None,
                }
        baseline_entry = {
            "user": baseline_sub.user.to_dict(
                view_role="admin",
                scores_finalized=False,
                current_user_id=None,
                challenge_cache=challenge_cache,
            ),
            "task_scores": bt_scores,
            "public_score": baseline_sub.public_score,
            "private_score": baseline_sub.private_score,
            "total_points": 0,
            "has_submitted": True,
            "total_execution_time_ms": baseline_sub.execution_time_ms or 0,
            "earliest_submission_time": baseline_sub.created_at,
            "is_baseline_entry": True,
        }
        leaderboard_entries.append(baseline_entry)

    def compare_entries(a: dict[str, Any], b: dict[str, Any]) -> int:
        if challenge_finalized:
            pa = a["total_points"]
            pb = b["total_points"]
            if pa != pb:
                return -1 if pa > pb else 1
        else:
            if a["has_submitted"] != b["has_submitted"]:
                return -1 if a["has_submitted"] else 1

            if not a["has_submitted"]:
                name_a = (
                    f"{a['user'].get('name') or ''} {a['user'].get('surname') or ''}"
                ).strip().lower() or a["user"].get("username", "").lower()
                name_b = (
                    f"{b['user'].get('name') or ''} {b['user'].get('surname') or ''}"
                ).strip().lower() or b["user"].get("username", "").lower()
                if name_a != name_b:
                    return -1 if name_a < name_b else 1
                return 0

            score_a = a["public_score"]
            score_b = b["public_score"]
            if score_a is None and score_b is None:
                pass
            elif score_a is None:
                return 1
            elif score_b is None:
                return -1
            elif score_a != score_b:
                return -1 if score_a > score_b else 1

        eta = a.get("total_execution_time_ms", 0)
        etb = b.get("total_execution_time_ms", 0)
        if eta != etb:
            return -1 if eta < etb else 1

        cda = a.get("earliest_submission_time", datetime.max)
        cdb = b.get("earliest_submission_time", datetime.max)
        if cda != cdb:
            return -1 if cda < cdb else 1

        name_a = (
            f"{a['user'].get('name') or ''} {a['user'].get('surname') or ''}".strip().lower()
            or a["user"].get("username", "").lower()
        )
        name_b = (
            f"{b['user'].get('name') or ''} {b['user'].get('surname') or ''}".strip().lower()
            or b["user"].get("username", "").lower()
        )
        if name_a != name_b:
            return -1 if name_a < name_b else 1
        return 0

    sorted_entries = sorted(leaderboard_entries, key=cmp_to_key(compare_entries))

    cached_entries = []
    if challenge_finalized:
        current_rank = 1
        for i, entry_dict in enumerate(sorted_entries):
            if i > 0 and entry_dict["total_points"] != sorted_entries[i - 1]["total_points"]:
                current_rank = i + 1
            entry_dict["rank"] = current_rank
            cached_entries.append(entry_dict)
    else:
        current_rank = 1
        for i, entry_dict in enumerate(sorted_entries):
            if i > 0 and entry_dict["public_score"] != sorted_entries[i - 1]["public_score"]:
                current_rank = i + 1
            entry_dict["rank"] = current_rank
            cached_entries.append(entry_dict)

    # Convert datetime objects to string for JSON serialization
    for entry in cached_entries:
        if isinstance(entry.get("earliest_submission_time"), datetime):
            entry["earliest_submission_time"] = (
                entry["earliest_submission_time"].isoformat() + "Z"
                if entry["earliest_submission_time"] != datetime.max
                else None
            )
        for ts_score in entry["task_scores"].values():
            if isinstance(ts_score.get("created_at"), datetime):
                ts_score["created_at"] = ts_score["created_at"].isoformat() + "Z"

    return cached_entries
