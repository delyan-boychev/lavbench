"""Route handlers for the leaderboard blueprint."""

from __future__ import annotations

import json
import logging
from typing import Any

from flask import Blueprint, request
from flask import Response as FlaskResponse
from spectree import Response

from models import AuditLog, Challenge, Stage, Submission, Task, User, db, is_metric_lower_better
from schemas.leaderboard import ManualPointsSchema
from schemas.responses import ErrorResponse, LeaderboardResponse, ManualPointsResponse
from services.leaderboard_service import (
    assign_overall_ranks,
    build_and_cache_leaderboard,
    holds_rank,
)
from services.task_locks import task_locks
from utils.access import ensure_registered
from utils.auth_utils import jury_access_required, login_required, rate_limit, role_required
from utils.cache_utils import invalidate_leaderboard_cache
from utils.dates import utcnow
from utils.error_utils import err
from utils.json_utils import safe_json_loads
from utils.score_visibility import can_view_private_scores, private_scores_revealed
from utils.spec import api
from utils.sse import signal_stream, sse_response
from utils.sse_utils import leaderboard_channel
from utils.task_visibility import competitor_visible_tasks

logger = logging.getLogger(__name__)
leaderboard_bp = Blueprint("leaderboard", __name__)

# The only user fields a competitor receives; never email, school, city or grade
_COMPETITOR_USER_FIELDS = ("id", "alias_id", "is_anonymous")
# Added only where the challenge shows this competitor the user's name
_COMPETITOR_NAME_FIELDS = ("name", "surname")


def _competitor_user_view(
    user: dict[str, Any], show_name: bool, manual_points: dict[str, Any]
) -> dict[str, Any]:
    """Return the whitelisted part of a user record that a competitor may see."""
    fields = _COMPETITOR_USER_FIELDS + (_COMPETITOR_NAME_FIELDS if show_name else ())
    view = {field: user.get(field) for field in fields}
    view["is_anonymous"] = bool(view["is_anonymous"])
    view["manual_points"] = manual_points
    return view


def _task_score(entry: dict[str, Any], tid: str) -> float | None:
    """Return a row's public score on one task; None without a scored run."""
    score = entry.get("task_scores", {}).get(tid, {}).get("public_score")
    return None if score is None else float(score)


def _task_points(entry: dict[str, Any], tid: str) -> float:
    """Return the manual points a row's user holds on one task."""
    manual_points = (entry.get("user") or {}).get("manual_points") or {}
    return float(manual_points.get(tid) or 0)


def _compute_task_ranks(
    entries: list[dict[str, Any]],
    tasks: list[Any],
    challenge_finalized: bool,
    reveal_results: bool,
) -> None:
    """Rank each task tab and place its Baseline row; stored scores are higher-is-better."""
    by_points = challenge_finalized and reveal_results
    baselines = [e for e in entries if e.get("is_baseline_entry")]
    for baseline in baselines:
        baseline.setdefault("task_rows_before", {})

    for task in tasks:
        tid = str(task.id)
        ranked: list[tuple[dict[str, Any], float]] = []
        for e in entries:
            score = _task_score(e, tid)
            points = _task_points(e, tid) if by_points else 0.0
            value = points if by_points else score
            if value is not None and holds_rank(e, score is not None, points):
                ranked.append((e, value))
        ranked.sort(key=lambda item: item[1], reverse=True)

        rank = 0
        for idx, (e, value) in enumerate(ranked):
            if idx == 0 or value != ranked[idx - 1][1]:
                rank = idx + 1
            e.setdefault("task_ranks", {})[tid] = rank
        for e in entries:
            e.setdefault("task_ranks", {}).setdefault(tid, None)

        # Points and scores do not compare, so a tab ranked by points has no Baseline row
        if by_points:
            continue
        for baseline in baselines:
            baseline_score = _task_score(baseline, tid)
            if baseline_score is not None:
                # A competitor tied with the baseline is listed before it
                baseline["task_rows_before"][tid] = sum(
                    1 for _, row_score in ranked if row_score >= baseline_score
                )


def _compute_stage_ranks(
    entries: list[dict[str, Any]],
    tasks: list[Any],
) -> None:
    stage_tasks: dict[int, list[Any]] = {}
    for t in tasks:
        if t.stage_id:
            stage_tasks.setdefault(t.stage_id, []).append(t)

    for stage_id, stage_tasks_list in stage_tasks.items():
        sid = str(stage_id)

        scorable = []
        for e in entries:
            total = 0.0
            has_any = False
            for t in stage_tasks_list:
                score = e.get("task_scores", {}).get(str(t.id), {}).get("public_score")
                if score is not None:
                    total += score
                    has_any = True
            if holds_rank(e, has_any):
                scorable.append((e, total))

        # Normalized scores are higher-is-better on every task, so their sum is too
        scorable.sort(key=lambda x: x[1], reverse=True)

        rank = 0
        prev_score = None
        for idx, (e, score) in enumerate(scorable):
            if idx == 0 or score != prev_score:
                rank = idx + 1
            e.setdefault("stage_ranks", {})[sid] = rank
            prev_score = score

        for e in entries:
            e.setdefault("stage_ranks", {})
            if sid not in e["stage_ranks"]:
                e["stage_ranks"][sid] = None


def _hide_private_scores(
    entry: dict[str, Any],
    tasks: list[Any],
    stages: dict[Any, Any],
    challenge: Any,
    user_role: str,
) -> None:
    """Null the private scores this viewer may not see, then re-sum the visible ones."""
    task_scores = dict(entry.get("task_scores", {}))
    total = 0.0
    has_private = False
    for task in tasks:
        tid = str(task.id)
        if tid not in task_scores:
            continue
        score = dict(task_scores[tid])
        stage = stages.get(task.stage_id) if task.stage_id else None
        if not can_view_private_scores(user_role, challenge, stage):
            score["private_score"] = None
        elif score.get("private_score") is not None:
            total += score["private_score"]
            has_private = True
        task_scores[tid] = score
    entry["task_scores"] = task_scores
    entry["private_score"] = total if has_private else None


def _get_leaderboard_payload(
    challenge: Any, user_role: str, current_user_id: int | None
) -> dict[str, Any]:
    challenge_id = challenge.id
    tasks = Task.query.filter_by(challenge_id=challenge_id).order_by(Task.id.asc()).all()
    challenge_finalized = challenge.scores_finalized

    cached_entries = build_and_cache_leaderboard(challenge_id) or []

    # Preload all stages in a single query to avoid N+1 lookups
    stage_ids = {t.stage_id for t in tasks if t.stage_id}
    stages = (
        {s.id: s for s in Stage.query.filter(Stage.id.in_(stage_ids)).all()} if stage_ids else {}
    )

    if user_role == "competitor":
        now = utcnow()

        # 1. Filter tasks
        visible_ids = {t.id for t in competitor_visible_tasks(challenge, now)}
        visible_tasks = [t for t in tasks if t.id in visible_ids]

        # 2. Filter entries
        post_processed_leaderboard = []
        for entry in cached_entries:
            entry_copy = dict(entry)
            is_baseline = bool(entry.get("is_baseline_entry"))
            comp_user = entry.get("user") or {}
            is_self = (
                not is_baseline
                and current_user_id is not None
                and current_user_id == comp_user.get("id")
            )

            # Recalculate sums based only on visible task scores for competitors
            filtered_task_scores = {}
            tot_pub = 0.0
            tot_priv = 0.0
            tot_pts = 0

            has_pub_sum = False
            has_priv_sum = False

            # Parse manual points safely
            manual_points_dict = safe_json_loads(comp_user.get("manual_points"), {})

            # Will accumulate only the tasks whose points are allowed to be revealed
            revealed_manual_points = {}

            for t in visible_tasks:
                tid_str = str(t.id)
                sc_dict = entry.get("task_scores", {}).get(
                    tid_str,
                    {
                        "public_score": None,
                        "private_score": None,
                        "submission_id": None,
                    },
                )

                s_copy = dict(sc_dict)
                stage = stages.get(t.stage_id) if t.stage_id else None

                # Public scores are always visible; private scores and points once revealed
                reveal_task_priv = can_view_private_scores(user_role, challenge, stage)
                reveal_task_pts = private_scores_revealed(challenge, stage)

                if not reveal_task_priv:
                    s_copy["private_score"] = None

                filtered_task_scores[tid_str] = s_copy

                if s_copy["public_score"] is not None:
                    tot_pub += s_copy["public_score"]
                    has_pub_sum = True

                if reveal_task_priv and s_copy["private_score"] is not None:
                    tot_priv += s_copy["private_score"]
                    has_priv_sum = True
                else:
                    tot_priv += 0.0

                if reveal_task_pts:
                    pts_val = manual_points_dict.get(tid_str, 0)
                    tot_pts += pts_val
                    revealed_manual_points[tid_str] = pts_val

            entry_copy["task_scores"] = filtered_task_scores
            entry_copy["public_score"] = tot_pub if has_pub_sum else None
            entry_copy["private_score"] = tot_priv if has_priv_sum else None
            entry_copy["total_points"] = round(tot_pts, 2)
            entry_copy["has_submitted"] = has_pub_sum

            if is_baseline:
                # A baseline for a task this competitor cannot see yet has nothing to show
                if not has_pub_sum:
                    continue
                entry_copy["user"] = None
            else:
                show_name = (
                    challenge.scores_finalized or is_self if challenge.double_blind else True
                )
                if comp_user.get("is_anonymous", False) and not is_self:
                    show_name = False
                entry_copy["user"] = _competitor_user_view(
                    comp_user, show_name, revealed_manual_points
                )

            post_processed_leaderboard.append(entry_copy)

        from functools import cmp_to_key

        def compare_competitor_entries(a, b):
            if challenge.scores_finalized and challenge.reveal_results:
                pa = a["total_points"]
                pb = b["total_points"]
                if pa != pb:
                    return -1 if pa > pb else 1
                # Within equal points a scored entry holds a rank, so it is listed first
                if a["has_submitted"] != b["has_submitted"]:
                    return -1 if a["has_submitted"] else 1
            else:
                if a["has_submitted"] != b["has_submitted"]:
                    return -1 if a["has_submitted"] else 1
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
            name_a = ((a["user"] or {}).get("alias_id") or a.get("label") or "").lower()
            name_b = ((b["user"] or {}).get("alias_id") or b.get("label") or "").lower()
            if name_a != name_b:
                return -1 if name_a < name_b else 1
            return 0

        sorted_competitor = sorted(
            post_processed_leaderboard, key=cmp_to_key(compare_competitor_entries)
        )

        assign_overall_ranks(
            sorted_competitor,
            by_points=bool(challenge.scores_finalized and challenge.reveal_results),
        )

        post_processed_leaderboard = sorted_competitor
        _compute_task_ranks(
            post_processed_leaderboard,
            visible_tasks,
            challenge_finalized,
            challenge.reveal_results,
        )
        _compute_stage_ranks(post_processed_leaderboard, visible_tasks)
        locks = task_locks(visible_tasks)
        tasks_list = [t.to_dict(view_role=user_role, locks=locks[str(t.id)]) for t in visible_tasks]
    else:
        now = utcnow()
        has_started = challenge.start_time is not None and now >= challenge.start_time

        post_processed_leaderboard = []
        for entry in cached_entries:
            entry_copy = dict(entry)

            # The Baseline row carries no user record to filter
            comp_user = entry_copy.get("user")
            if comp_user is not None:
                comp_user_id = comp_user["id"]
                is_self = current_user_id is not None and current_user_id == comp_user_id

                if challenge.double_blind:
                    show_details = (
                        (user_role == "admin")
                        or (user_role == "jury" and (not has_started or challenge_finalized))
                        or is_self
                    )
                else:
                    show_details = True

                if not show_details:
                    entry_copy["user"] = {
                        "id": comp_user_id,
                        "alias_id": comp_user.get("alias_id"),
                        "role": comp_user.get("role"),
                        "challenge_id": comp_user.get("challenge_id"),
                        "is_anonymous": comp_user.get("is_anonymous", False),
                        "manual_points": comp_user.get("manual_points", {}),
                    }
            if user_role != "admin":
                _hide_private_scores(entry_copy, tasks, stages, challenge, user_role)
            post_processed_leaderboard.append(entry_copy)
        _compute_task_ranks(
            post_processed_leaderboard,
            tasks,
            challenge_finalized,
            challenge.reveal_results,
        )
        _compute_stage_ranks(post_processed_leaderboard, tasks)
        locks = task_locks(tasks)
        tasks_list = [t.to_dict(view_role=user_role, locks=locks[str(t.id)]) for t in tasks]

    metric_name = "Score"
    is_normalized = False
    for task in tasks:
        if task.metrics_config:
            try:
                cfg = (
                    json.loads(task.metrics_config)
                    if isinstance(task.metrics_config, str)
                    else task.metrics_config
                )
                keys = [k for k in cfg if not k.startswith("_")]
                if keys:
                    m_name = keys[0]
                    metric_name = m_name.replace("_", " ").title()
                    is_normalized = is_metric_lower_better(m_name)
                    break
            except Exception as e:
                logger.warning("Failed to parse metrics_config for task %s: %s", task.id, e)

    return {
        "challenge_title": challenge.title,
        "metric_name": metric_name,
        "is_normalized": is_normalized,
        "is_finalized": challenge.scores_finalized,
        "reveal_results": challenge.reveal_results,
        "tasks": tasks_list,
        "leaderboard": post_processed_leaderboard,
    }


@leaderboard_bp.route("/challenges/<uuid:challenge_id>/leaderboard", methods=["GET"])
@login_required
@jury_access_required
@api.validate(
    resp=Response(HTTP_200=LeaderboardResponse, HTTP_403=ErrorResponse),
    tags=["Leaderboard"],
    security=[{"cookieAuth": []}],
)
def get_leaderboard(
    challenge_id: Any,
) -> tuple[dict[str, Any], int, dict[str, str]] | tuple[FlaskResponse, int]:
    """Get the leaderboard for a specific challenge."""
    challenge = db.get_or_404(Challenge, challenge_id)
    user_role = request.user["role"]
    current_user_id = request.user["user_id"]

    # Restrict competitors to their registered challenge
    if user_role == "competitor" and not ensure_registered(current_user_id, challenge_id):
        return err("ERR_NOT_REGISTERED", 403)

    payload = _get_leaderboard_payload(challenge, user_role, current_user_id)
    payload["challenge_id"] = str(challenge_id)
    return (
        payload,
        200,
        {
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@leaderboard_bp.route("/challenges/<uuid:challenge_id>/leaderboard/live", methods=["GET"])
@login_required
@jury_access_required
@api.validate(
    resp=Response(HTTP_200=None, HTTP_403=ErrorResponse, HTTP_404=ErrorResponse),
    tags=["SSE Streaming"],
    security=[{"cookieAuth": []}],
)
def stream_challenge_leaderboard(
    challenge_id: Any,
) -> tuple[FlaskResponse, int, dict[str, str]] | tuple[FlaskResponse, int]:
    """Signal ``{"event": "update"}`` after each leaderboard rebuild (SSE).

    The client refetches GET /leaderboard, which applies its role's visibility rules.
    """
    user_id = request.user["user_id"]
    user_role = request.user["role"]

    challenge = db.session.get(Challenge, challenge_id)
    if not challenge:
        return err("ERR_NOT_FOUND", 404)

    # Competitor check: can only view if it's their challenge
    if user_role == "competitor":
        u = db.session.get(User, user_id)
        if not u or str(u.challenge_id) != str(challenge_id):
            return err("ERR_ACCESS_DENIED", 403)

    return sse_response(signal_stream(leaderboard_channel(challenge_id), user_id))


@leaderboard_bp.route("/challenges/<uuid:challenge_id>/manual-points", methods=["POST"])
@login_required
@role_required(["admin", "jury"])
@jury_access_required
@rate_limit(max_requests=20, window_seconds=60)
@api.validate(
    json=ManualPointsSchema,
    tags=["Leaderboard"],
    security=[{"cookieAuth": []}],
    resp=Response(HTTP_200=ManualPointsResponse, HTTP_422=ErrorResponse),
)
def save_manual_points(
    challenge_id: Any, json: ManualPointsSchema
) -> ManualPointsResponse | tuple[FlaskResponse, int]:
    """Save manual points for a user in a challenge (admin or jury); each change is audited."""
    challenge = db.get_or_404(Challenge, challenge_id)

    if challenge.scores_finalized and challenge.reveal_results:
        return err(
            "ERR_EDITING_BLOCKED",
            400,
            message="Cannot modify manual points once the "
            "competition results are finalized and revealed.",
        )

    user_id = json.user_id
    points_dict = json.points
    reason = json.reason

    user = User.query.filter_by(id=user_id, challenge_id=challenge_id).with_for_update().first()
    if not user:
        return err("ERR_USER_NOT_FOUND", 404)

    if challenge.scores_finalized and not reason:
        return err(
            "ERR_REASON_REQUIRED",
            400,
            message="A justification reason is mandatory to modify "
            "manual points after the competition is finalized.",
        )

    validated_points = {}
    tasks = {t.id for t in challenge.tasks}
    for k, v in points_dict.items():
        task_id = str(k)
        if task_id not in tasks:
            return err(
                "ERR_TASK_NOT_IN_CHALLENGE",
                400,
                message=f"Task ID {task_id} does not belong to this challenge.",
            )

        pts = v

        task = db.session.get(Task, task_id)
        if task and task.stage_id:
            stage = db.session.get(Stage, task.stage_id)
            if stage and stage.is_finalized and stage.reveal_results:
                return err(
                    "ERR_EDITING_BLOCKED",
                    400,
                    message=f"Cannot modify manual points for task {task.title} "
                    f"because the stage is finalized and revealed.",
                )

        total_count = Submission.query.filter_by(user_id=user_id, task_id=task_id).count()
        if total_count == 0:
            return err(
                "ERR_NO_SUBMISSIONS",
                400,
                message="Only competitors with submissions can be assigned manual "
                "points. Competitors without submissions automatically receive 0 points.",
            )

        validated_points[str(task_id)] = pts

    current_points = safe_json_loads(user.manual_points, {})

    # Create audit logs for changed points
    admin_id = request.user["user_id"]

    for task_id_str, pts in validated_points.items():
        task_id = str(task_id_str)
        old_score = current_points.get(task_id_str)
        if old_score != pts:
            audit_entry = AuditLog(
                admin_id=admin_id,
                action_type="update",
                target_type="user",
                target_user_id=user.id,
                task_id=task_id,
                old_score=old_score,
                new_score=pts,
                reason=reason or "Initial scoring before finalization",
            )
            db.session.add(audit_entry)

    current_points.update(validated_points)
    user.manual_points = current_points
    db.session.commit()

    # Invalidate cache

    invalidate_leaderboard_cache(challenge_id)

    return ManualPointsResponse(
        message="Manual points saved successfully.",
        user_id=user.id,
        manual_points=user.manual_points,
    )
