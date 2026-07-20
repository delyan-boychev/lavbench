from __future__ import annotations

import contextlib
import json
import logging
import time
from typing import Any

from flask import Blueprint, request
from flask import Response as FlaskResponse
from spectree import Response

from auth_utils import jury_access_required, login_required, rate_limit, role_required
from cache_utils import get_redis_client, invalidate_leaderboard_cache
from error_utils import err
from models import AuditLog, Challenge, Stage, Submission, Task, User, db, is_metric_lower_better
from schemas.leaderboard import ManualPointsSchema
from schemas.responses import ErrorResponse, LeaderboardResponse, ManualPointsResponse
from services.leaderboard_service import build_and_cache_leaderboard
from spec import api
from sse_utils import SSE_IDLE_TIMEOUT, sse_connection_limit
from utils.access import ensure_registered
from utils.cache_helpers import cached_or_compute
from utils.dates import utcnow
from utils.json_utils import safe_json_loads
from utils.sse import sse_response

logger = logging.getLogger(__name__)
leaderboard_bp = Blueprint("leaderboard", __name__)


class UUIDEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        import uuid

        if isinstance(obj, uuid.UUID):
            return str(obj)
        return super().default(obj)


def _compute_task_ranks(
    entries: list[dict[str, Any]],
    tasks: list[Any],
    challenge_finalized: bool,
    reveal_results: bool,
) -> None:
    task_lower_better: dict[int, bool] = {}
    for task in tasks:
        lower = False
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
                        lower = True
                        break
            except Exception:
                logger.warning("Failed to parse metrics_config for task %s", task.id)
        task_lower_better[task.id] = lower

    for task in tasks:
        tid = str(task.id)
        scorable = []
        for e in entries:
            ts = e.get("task_scores", {}).get(tid, {})
            if ts.get("public_score") is not None:
                scorable.append(e)

        if challenge_finalized and reveal_results:
            scorable.sort(
                key=lambda e: e.get("user", {}).get("manual_points", {}).get(tid, 0),
                reverse=True,
            )
        else:
            is_lower = task_lower_better.get(task.id, False)
            scorable.sort(
                key=lambda e: e["task_scores"][tid]["public_score"],
                reverse=not is_lower,
            )

        rank = 0
        prev_key = None
        for idx, e in enumerate(scorable):
            if challenge_finalized and reveal_results:
                key = e.get("user", {}).get("manual_points", {}).get(tid, 0)
            else:
                key = e["task_scores"][tid]["public_score"]
            if idx == 0 or key != prev_key:
                rank = idx + 1
            e.setdefault("task_ranks", {})[tid] = rank
            prev_key = key

        for e in entries:
            e.setdefault("task_ranks", {})
            if tid not in e["task_ranks"]:
                e["task_ranks"][tid] = None


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
            if has_any:
                scorable.append((e, total))

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


def _get_leaderboard_payload(
    challenge: Any, user_role: str, current_user_id: int | None
) -> dict[str, Any]:
    challenge_id = challenge.id
    tasks = Task.query.filter_by(challenge_id=challenge_id).order_by(Task.id.asc()).all()
    challenge_finalized = challenge.scores_finalized

    # Check if competitor needs to see frozen leaderboard
    is_frozen_view = False
    if user_role == "competitor" and challenge.is_frozen and not challenge.scores_finalized:
        is_frozen_view = True

    cache_key = f"leaderboard:raw:{challenge_id}:{'frozen' if is_frozen_view else 'unfrozen'}"
    cached_entries = cached_or_compute(
        cache_key, lambda: build_and_cache_leaderboard(challenge_id, is_frozen_view)
    )

    if user_role == "competitor":
        now = utcnow()
        from models import Stage

        # Preload all stages in a single query to avoid N+1 lookups
        stage_ids = {t.stage_id for t in tasks if t.stage_id}
        stages = (
            {s.id: s for s in Stage.query.filter(Stage.id.in_(stage_ids)).all()}
            if stage_ids
            else {}
        )

        # 1. Filter tasks
        visible_tasks = []
        for t in tasks:
            if not t.stage_id:
                visible_tasks.append(t)
            else:
                stage = stages.get(t.stage_id)
                if stage and now >= stage.start_time:
                    visible_tasks.append(t)

        # 2. Filter entries
        post_processed_leaderboard = []
        for entry in cached_entries:
            entry_copy = dict(entry)
            comp_user = entry_copy["user"]
            comp_user_id = comp_user["id"]
            is_self = current_user_id is not None and current_user_id == comp_user_id

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

                # Determine score visibility for this task
                reveal_task_pub = False
                reveal_task_priv = False
                reveal_task_pts = False

                if challenge.scores_finalized:
                    reveal_task_pub = True
                    reveal_task_priv = challenge.reveal_results
                    reveal_task_pts = challenge.reveal_results
                elif stage:
                    if stage.is_finalized:
                        reveal_task_pub = True
                        reveal_task_priv = stage.reveal_results
                        reveal_task_pts = stage.reveal_results
                    else:
                        reveal_task_pub = True
                else:
                    reveal_task_pub = True

                if is_self:
                    reveal_task_pub = True

                if not reveal_task_pub:
                    s_copy["public_score"] = None
                if not reveal_task_priv:
                    s_copy["private_score"] = None

                filtered_task_scores[tid_str] = s_copy

                if reveal_task_pub and s_copy["public_score"] is not None:
                    tot_pub += s_copy["public_score"]
                    has_pub_sum = True
                else:
                    tot_pub += 0.0

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
            entry_copy["total_points"] = tot_pts
            entry_copy["has_submitted"] = has_pub_sum

            show_details = challenge.scores_finalized or is_self if challenge.double_blind else True

            is_anonymous = comp_user.get("is_anonymous", False)
            if is_anonymous and not is_self:
                show_details = False

            if not show_details:
                entry_copy["user"] = {
                    "id": comp_user_id,
                    "alias_id": comp_user.get("alias_id"),
                    "role": comp_user.get("role"),
                    "challenge_id": comp_user.get("challenge_id"),
                    "is_anonymous": is_anonymous,
                    "manual_points": revealed_manual_points,
                }
            else:
                user_copy = dict(comp_user)
                user_copy.pop("middle_name", None)
                user_copy.pop("birth_date", None)
                user_copy["manual_points"] = revealed_manual_points
                entry_copy["user"] = user_copy

            post_processed_leaderboard.append(entry_copy)

        from functools import cmp_to_key

        def compare_competitor_entries(a, b):
            if challenge.scores_finalized and challenge.reveal_results:
                pa = a["total_points"]
                pb = b["total_points"]
                if pa != pb:
                    return -1 if pa > pb else 1
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
            name_a = (a["user"].get("alias_id") or "").lower()
            name_b = (b["user"].get("alias_id") or "").lower()
            if name_a != name_b:
                return -1 if name_a < name_b else 1
            return 0

        sorted_competitor = sorted(
            post_processed_leaderboard, key=cmp_to_key(compare_competitor_entries)
        )

        if challenge.scores_finalized and challenge.reveal_results:
            current_rank = 1
            for idx, entry_dict in enumerate(sorted_competitor):
                if (
                    idx > 0
                    and entry_dict["total_points"] != sorted_competitor[idx - 1]["total_points"]
                ):
                    current_rank = idx + 1
                entry_dict["rank"] = current_rank
        else:
            current_rank = 1
            for idx, entry_dict in enumerate(sorted_competitor):
                if (
                    idx > 0
                    and entry_dict["public_score"] != sorted_competitor[idx - 1]["public_score"]
                ):
                    current_rank = idx + 1
                entry_dict["rank"] = current_rank

        post_processed_leaderboard = sorted_competitor
        _compute_task_ranks(
            post_processed_leaderboard,
            visible_tasks,
            challenge_finalized,
            challenge.reveal_results,
        )
        _compute_stage_ranks(post_processed_leaderboard, visible_tasks)
        tasks_list = [t.to_dict(view_role=user_role) for t in visible_tasks]
    else:
        now = utcnow()
        has_started = challenge.start_time is not None and now >= challenge.start_time

        post_processed_leaderboard = []
        for entry in cached_entries:
            entry_copy = dict(entry)

            comp_user = entry_copy["user"]
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

            is_anonymous = comp_user.get("is_anonymous", False)
            if is_anonymous and user_role == "competitor" and not is_self:
                show_details = False

            if not show_details:
                entry_copy["user"] = {
                    "id": comp_user_id,
                    "alias_id": comp_user.get("alias_id"),
                    "role": comp_user.get("role"),
                    "challenge_id": comp_user.get("challenge_id"),
                    "is_anonymous": is_anonymous,
                    "manual_points": comp_user.get("manual_points", {}),
                }
            post_processed_leaderboard.append(entry_copy)
        _compute_task_ranks(
            post_processed_leaderboard,
            tasks,
            challenge_finalized,
            challenge.reveal_results,
        )
        _compute_stage_ranks(post_processed_leaderboard, tasks)
        tasks_list = [t.to_dict(view_role=user_role) for t in tasks]

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
    """Stream live updates to the challenge leaderboard using Server-Sent Events (SSE)."""
    from flask import current_app

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

    def event_generator():
        with sse_connection_limit(user_id=user_id) as allowed:
            if not allowed:
                yield f"data: {json.dumps({'error': 'too many connections'})}\n\n"
                return

            r = get_redis_client()

            yield f"data: {json.dumps({'info': 'connected'})}\n\n"

            def get_and_yield_leaderboard():
                with current_app.app_context():
                    c = db.session.get(Challenge, challenge_id)
                    if not c:
                        return
                    payload = _get_leaderboard_payload(c, user_role, user_id)
                    yield f"data: {json.dumps(payload, cls=UUIDEncoder)}\n\n"

            for msg in get_and_yield_leaderboard():
                yield msg

            if r:
                pubsub = r.pubsub()
                channel_name = f"challenge_{challenge_id}_leaderboard"
                try:
                    pubsub.subscribe(channel_name)
                except Exception as e:
                    logger.warning("Failed to subscribe to Redis channel %s: %s", channel_name, e)
                    r = None

            start_time = time.time()

            if r:
                try:
                    while True:
                        if time.time() - start_time > SSE_IDLE_TIMEOUT:
                            yield f"data: {json.dumps({'event': 'timeout'})}\n\n"
                            break
                        message = pubsub.get_message(ignore_subscribe_messages=True, timeout=5.0)
                        if message:
                            for msg in get_and_yield_leaderboard():
                                yield msg
                        else:
                            yield ": keep-alive\n\n"
                except Exception as e:
                    logger.warning("Leaderboard SSE stream error: %s", e)
                finally:
                    with contextlib.suppress(Exception):
                        pubsub.unsubscribe()
                        pubsub.close()
            else:
                while time.time() - start_time <= SSE_IDLE_TIMEOUT:
                    time.sleep(10.0)
                    for msg in get_and_yield_leaderboard():
                        yield msg
                yield f"data: {json.dumps({'event': 'timeout'})}\n\n"

    return sse_response(event_generator)


@leaderboard_bp.route("/challenges/<uuid:challenge_id>/manual-points", methods=["POST"])
@login_required
@role_required(["jury"])
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
    """Save manual points for a user in a challenge. Jury members only."""
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
