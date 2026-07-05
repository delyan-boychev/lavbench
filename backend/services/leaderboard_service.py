"""Service-layer functions for leaderboard computation and caching."""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from functools import cmp_to_key
from typing import Any

from sqlalchemy.orm import joinedload

from cache_utils import cache_lock, get_cached, set_cached
from models import Challenge, Stage, Submission, Task, User, db, is_metric_lower_better
from services.submission_service import get_best_submission

logger = logging.getLogger(__name__)


def build_and_cache_leaderboard(
    challenge_id: uuid.UUID | str, is_frozen_view: bool = False, force_rebuild: bool = False
) -> list[dict[str, Any]] | None:
    """Compute, cache, and return the leaderboard for a challenge. Uses a distributed lock."""

    cache_key = f"leaderboard:raw:{challenge_id}:{'frozen' if is_frozen_view else 'unfrozen'}"
    lock_key = f"lock:{cache_key}"

    if not force_rebuild:
        cached: Any = get_cached(cache_key)
        if cached is not None:
            return cached  # type: ignore[no-any-return]

    with cache_lock(lock_key, ttl=30) as got_lock:
        if not got_lock:
            for _ in range(10):
                time.sleep(0.3)
                if not force_rebuild:
                    cached = get_cached(cache_key)
                    if cached is not None:
                        return cached  # type: ignore[no-any-return]

        challenge = db.session.get(Challenge, challenge_id)
        if not challenge:
            return None

        tasks = Task.query.filter_by(challenge_id=challenge_id).order_by(Task.id.asc()).all()
        task_metrics = {}  # per-task is_lower_better
        for task in tasks:
            task_lower = False
            if task.metrics_config:
                try:
                    cfg = (
                        json.loads(task.metrics_config)
                        if isinstance(task.metrics_config, str)
                        else task.metrics_config
                    )
                    for m_name in cfg:
                        if m_name.startswith("_"):
                            continue
                        if is_metric_lower_better(m_name):
                            task_lower = True
                            break
                except Exception as e:
                    logger.warning("Failed to parse metrics_config for task %s: %s", task.id, e)
            task_metrics[task.id] = task_lower

        challenge_finalized = challenge.scores_finalized

        # Determine users who have late submissions
        late_users = set()
        if challenge.end_time:
            late_user_ids = (
                db.session.query(Submission.user_id)
                .filter(
                    Submission.challenge_id == challenge_id,
                    Submission.executed_at > challenge.end_time,
                )
                .distinct()
                .all()
            )
            late_users = {uid[0] for uid in late_user_ids}

        from sqlalchemy import case, func

        if late_users:
            is_final_active = case(
                (Submission.user_id.in_(late_users), False),
                else_=Submission.is_final_selection,
            )
        else:
            is_final_active = Submission.is_final_selection

        test_stage_task_ids = [
            s[0]
            for s in db.session.query(Task.id)
            .join(Stage, Task.stage_id == Stage.id)
            .filter(Stage.challenge_id == challenge_id, Stage.is_test)
            .all()
        ]

        subq = (
            db.session.query(
                Submission.id.label("sub_id"),
                func.row_number()
                .over(
                    partition_by=(Submission.user_id, Submission.task_id),
                    order_by=(
                        is_final_active.desc(),
                        Submission.private_score.desc(),
                        Submission.public_score.desc(),
                        Submission.execution_time_ms.asc(),
                    ),
                )
                .label("rn"),
            )
            .filter(
                Submission.challenge_id == challenge_id,
                Submission.status == "completed",
                ~Submission.task_id.in_(test_stage_task_ids) if test_stage_task_ids else True,
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
                chosen_sub = get_best_submission(
                    task,
                    user_subs_for_task,
                    challenge,
                    is_lower_better=task_metrics.get(task.id, False),
                )

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
                        logger.warning("Failed to parse manual_points for user %s: %s", comp.id, e)
                        manual_points_dict = {}

            total_points = sum(manual_points_dict.get(str(t.id), 0) for t in tasks)

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
                    chosen = get_best_submission(
                        s.task,
                        [existing, s],
                        challenge,
                        is_lower_better=task_metrics.get(s.task.id, False),
                    )
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

        if not force_rebuild:
            cached = get_cached(cache_key)
            if cached is not None:
                return cached  # type: ignore[no-any-return]
        set_cached(cache_key, cached_entries, timeout=120)
        return cached_entries


def get_task_leaderboard_data(
    task_id: uuid.UUID | str, user_role: str, current_user_id: uuid.UUID | None
) -> dict[str, Any]:
    task = db.session.get(Task, task_id)
    if not task:
        return {"error": "Task not found."}
    challenge = task.challenge

    from routes.tasks import check_task_started

    if user_role == "competitor" and not check_task_started(task, user_role, current_user_id):
        return {"error": "Access denied or task not available yet."}

    all_completed = (
        Submission.query.filter_by(task_id=task_id, status="completed")
        .options(
            joinedload(Submission.challenge),
            joinedload(Submission.user),
            joinedload(Submission.task),
        )
        .all()
    )

    is_lower_better = False
    if task.metrics_config:
        try:
            m_config = (
                json.loads(task.metrics_config)
                if isinstance(task.metrics_config, str)
                else task.metrics_config
            )
            for m_name, m_info in m_config.items():
                if m_name.startswith("_"):
                    continue
                if isinstance(m_info, dict) and (
                    m_info.get("higher_is_better") is False or is_metric_lower_better(m_name)
                ):
                    is_lower_better = True
                break
        except Exception as e:
            logger.warning("Failed to parse metrics_config for task %s: %s", task.id, e)

    competitors = User.query.filter_by(role="competitor", challenge_id=task.challenge_id).all()
    challenge_cache = {challenge.id: challenge}
    user_best = {}
    for comp in competitors:
        comp_subs = [s for s in all_completed if s.user_id == comp.id]
        best_sub = get_best_submission(task, comp_subs, challenge, is_lower_better=is_lower_better)
        if best_sub:
            user_best[comp.id] = best_sub

    leaderboard_entries = []

    for comp in competitors:
        sub = user_best.get(comp.id)
        if sub:
            entry_dict = sub.to_dict(
                view_role=user_role,
                current_user_id=current_user_id,
                include_large_fields=False,
            )
            entry_dict["has_submitted"] = True
        else:
            entry_dict = {
                "id": None,
                "challenge_id": task.challenge_id,
                "task_id": task_id,
                "task_title": task.title,
                "status": None,
                "detailed_status": None,
                "code_cells": "[]",
                "public_score": None,
                "private_score": None,
                "logs": None,
                "gpu_node": None,
                "execution_time_ms": None,
                "created_at": None,
                "executed_at": None,
                "user": comp.to_dict(
                    view_role=user_role,
                    scores_finalized=challenge.scores_finalized,
                    current_user_id=current_user_id,
                    challenge_cache=challenge_cache,
                ),
                "metrics_payload_public": {},
                "metrics_payload_private": {},
                "final_weighted_score_public": None,
                "final_weighted_score_private": None,
                "is_final_selection": False,
                "is_disqualified": False,
                "celery_task_id": None,
                "has_submitted": False,
            }
        leaderboard_entries.append(entry_dict)

    # Add baseline to entries list so it gets sorted and ranked with competitors
    baseline_subs = [s for s in all_completed if s.is_baseline]
    if baseline_subs:
        best_baseline = get_best_submission(
            task, baseline_subs, challenge, is_lower_better=is_lower_better
        )
        if best_baseline:
            baseline_entry = best_baseline.to_dict(
                view_role=user_role,
                current_user_id=current_user_id,
                include_large_fields=False,
            )
            baseline_entry["is_baseline_entry"] = True
            baseline_entry["has_submitted"] = True
            leaderboard_entries.append(baseline_entry)

    def compare_entries(a: dict[str, Any], b: dict[str, Any]) -> int:
        if a["has_submitted"] != b["has_submitted"]:
            return -1 if a["has_submitted"] else 1

        if not a["has_submitted"]:
            name_a = (
                f"{a['user'].get('name') or ''} {a['user'].get('surname') or ''}".strip().lower()
                or (a["user"].get("username") or "").lower()
                or (a["user"].get("alias_id") or "").lower()
            )
            name_b = (
                f"{b['user'].get('name') or ''} {b['user'].get('surname') or ''}".strip().lower()
                or (b["user"].get("username") or "").lower()
                or (b["user"].get("alias_id") or "").lower()
            )
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
            if is_lower_better:
                return -1 if score_a < score_b else 1
            else:
                return -1 if score_a > score_b else 1

        ta = a["execution_time_ms"] if a["execution_time_ms"] is not None else 999999
        tb = b["execution_time_ms"] if b["execution_time_ms"] is not None else 999999
        if ta != tb:
            return -1 if ta < tb else 1

        ca = a["created_at"] or ""
        cb = b["created_at"] or ""
        if ca != cb:
            return -1 if ca < cb else 1
        return 0

    sorted_entries = sorted(leaderboard_entries, key=cmp_to_key(compare_entries))

    leaderboard = []
    tie_rank = 0
    prev_comp_key = None
    for entry_dict in sorted_entries:
        if entry_dict.get("is_baseline_entry") or not entry_dict.get("has_submitted"):
            entry_dict["rank"] = None
            leaderboard.append(entry_dict)
            continue
        comp_key = (
            entry_dict.get("public_score"),
            entry_dict.get("private_score"),
        )
        if prev_comp_key != comp_key:
            tie_rank = len([e for e in leaderboard if not e.get("is_baseline_entry")]) + 1
        prev_comp_key = comp_key
        entry_dict["rank"] = tie_rank
        leaderboard.append(entry_dict)

    metric_name = "Score"
    is_normalized = False
    if task.metrics_config:
        try:
            m_config = (
                json.loads(task.metrics_config)
                if isinstance(task.metrics_config, str)
                else task.metrics_config
            )
            if m_config:
                keys = [k for k in m_config if not k.startswith("_")]
                if keys:
                    m_name = keys[0]
                    metric_name = m_name.replace("_", " ").title()
                    is_normalized = is_metric_lower_better(m_name)
        except Exception as e:
            logger.warning("Failed to parse metrics_config for task %s: %s", task.id, e)

    return {
        "challenge_title": challenge.title,
        "task_title": task.title,
        "metric_name": metric_name,
        "is_normalized": is_normalized,
        "is_finalized": challenge.scores_finalized,
        "leaderboard": leaderboard,
    }
