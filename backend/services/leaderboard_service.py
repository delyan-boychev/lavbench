"""Service-layer functions for leaderboard computation and caching."""

import json
import time
from datetime import datetime
from functools import cmp_to_key
from sqlalchemy.orm import joinedload
from models import db, Challenge, Submission, User, Task, is_metric_lower_better
from services.submission_service import get_best_submission


def build_and_cache_leaderboard(challenge_id, is_frozen_view=False):
    """Compute, cache, and return the leaderboard for a challenge. Uses a distributed lock."""
    from cache_utils import set_cached, get_cached, cache_lock

    cache_key = f"leaderboard:raw:{challenge_id}:{'frozen' if is_frozen_view else 'unfrozen'}"
    lock_key = f"lock:{cache_key}"

    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    with cache_lock(lock_key, ttl=30) as got_lock:
        if not got_lock:
            for _ in range(10):
                time.sleep(0.3)
                cached = get_cached(cache_key)
                if cached is not None:
                    return cached

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
                    for m_name in cfg.keys():
                        if m_name.startswith("_"):
                            continue
                        if is_metric_lower_better(m_name):
                            task_lower = True
                            break
                except Exception:
                    pass
            task_metrics[task.id] = task_lower

        challenge_finalized = challenge.scores_finalized
        all_completed = (
            Submission.query.filter_by(challenge_id=challenge_id, status="completed")
            .options(
                joinedload(Submission.challenge),
                joinedload(Submission.user),
                joinedload(Submission.task),
            )
            .all()
        )

        # Pre-group by (user_id, task_id) — avoids O(N*M) scan
        sub_by_key = {}
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
                        tot_pub += 999.0 if task_metrics.get(task.id, False) else 0.0
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
                        tot_priv += 999.0 if task_metrics.get(task.id, False) else 0.0
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
                    except Exception:
                        manual_points_dict = {}

            total_points = sum(manual_points_dict.get(str(t.id), 0) for t in tasks)

            total_exec_time = 0
            sub_dates = []
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

        # Add baseline entries with per-task scores to the general leaderboard
        baseline_subs = [s for s in all_completed if s.is_baseline]
        if baseline_subs:
            bl_task_scores = {}
            has_any = False
            for t in tasks:
                task_bl = [s for s in baseline_subs if s.task_id == t.id]
                if task_bl:
                    best_bl = get_best_submission(t, task_bl, challenge)
                    if best_bl:
                        bl_task_scores[str(t.id)] = {
                            "submission_id": best_bl.id,
                            "public_score": best_bl.public_score,
                            "private_score": best_bl.private_score,
                            "execution_time_ms": best_bl.execution_time_ms or 0,
                            "created_at": (
                                best_bl.created_at.isoformat() if best_bl.created_at else None
                            ),
                        }
                        has_any = True
            if has_any:
                bl_pub = sum(
                    v["public_score"]
                    for v in bl_task_scores.values()
                    if v["public_score"] is not None
                )
                bl_priv = sum(
                    v["private_score"]
                    for v in bl_task_scores.values()
                    if v["private_score"] is not None
                )
                baseline_entry = {
                    "user": {
                        "id": -1,
                        "username": "baseline",
                        "alias_id": "Baseline",
                        "role": "baseline",
                    },
                    "public_score": bl_pub if bl_task_scores else None,
                    "private_score": bl_priv if bl_task_scores else None,
                    "total_points": 0,
                    "has_submitted": True,
                    "total_execution_time_ms": sum(
                        v["execution_time_ms"] for v in bl_task_scores.values()
                    ),
                    "earliest_submission_time": None,
                    "task_scores": bl_task_scores,
                    "is_baseline_entry": True,
                }
                leaderboard_entries.append(baseline_entry)

        def compare_entries(a, b):
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

                score_a = a["public_score"]
                score_b = b["public_score"]
                if score_a is not None and score_b is not None and score_a != score_b:
                    return (
                        -1 if score_a > score_b else 1
                    )  # all scores normalized to higher-is-better

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
            for rank, entry_dict in enumerate(sorted_entries, 1):
                entry_dict["rank"] = rank
                cached_entries.append(entry_dict)

        # Convert datetime objects to string for JSON serialization
        for entry in cached_entries:
            if isinstance(entry.get("earliest_submission_time"), datetime):
                entry["earliest_submission_time"] = (
                    entry["earliest_submission_time"].isoformat()
                    if entry["earliest_submission_time"] != datetime.max
                    else None
                )
            for ts_score in entry["task_scores"].values():
                if isinstance(ts_score.get("created_at"), datetime):
                    ts_score["created_at"] = ts_score["created_at"].isoformat()

        cached = get_cached(cache_key)
        if cached is not None:
            return cached
        set_cached(cache_key, cached_entries, timeout=120)
        return cached_entries


def get_task_leaderboard_data(task_id, user_role, current_user_id):
    task = db.session.get(Task, task_id)
    if not task:
        return {"error": "Task not found."}
    challenge = task.challenge

    from routes.tasks import check_task_started

    if user_role == "competitor":
        if not check_task_started(task, user_role, current_user_id):
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
        except Exception:
            pass

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
                view_role=user_role, current_user_id=current_user_id, include_large_fields=False
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
                view_role=user_role, current_user_id=current_user_id, include_large_fields=False
            )
            baseline_entry["is_baseline_entry"] = True
            baseline_entry["has_submitted"] = True
            leaderboard_entries.append(baseline_entry)

    def compare_entries(a, b):
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

        if score_a != score_b:
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
    for rank, entry_dict in enumerate(sorted_entries, 1):
        entry_dict["rank"] = rank
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
                keys = [k for k in m_config.keys() if not k.startswith("_")]
                if keys:
                    m_name = keys[0]
                    metric_name = m_name.replace("_", " ").title()
                    is_normalized = is_metric_lower_better(m_name)
        except Exception:
            pass

    return {
        "challenge_title": challenge.title,
        "task_title": task.title,
        "metric_name": metric_name,
        "is_normalized": is_normalized,
        "is_finalized": challenge.scores_finalized,
        "leaderboard": leaderboard,
    }
