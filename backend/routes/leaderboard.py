import json
import logging
from datetime import datetime

from auth_utils import jury_access_required, login_required, role_required
from cache_utils import get_redis_client, invalidate_leaderboard_cache
from error_utils import err
from flask import Blueprint, jsonify, request
from models import AuditLog, Challenge, Stage, Submission, Task, User, db, is_metric_lower_better
from services.leaderboard_service import build_and_cache_leaderboard
from utils.access import ensure_registered
from utils.cache_helpers import cached_or_compute
from utils.json_utils import safe_json_loads
from utils.sse import sse_response

logger = logging.getLogger(__name__)
leaderboard_bp = Blueprint("leaderboard", __name__)


class UUIDEncoder(json.JSONEncoder):
    def default(self, obj):
        import uuid

        if isinstance(obj, uuid.UUID):
            return str(obj)
        return super().default(obj)


def _get_leaderboard_payload(challenge, user_role, current_user_id):
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
        now = datetime.utcnow()
        from models import Stage

        # 1. Filter tasks
        visible_tasks = []
        for t in tasks:
            if not t.stage_id:
                visible_tasks.append(t)
            else:
                stage = db.session.get(Stage, t.stage_id)
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
                stage = db.session.get(Stage, t.stage_id) if t.stage_id else None

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
                entry_copy["has_submitted"] = False
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
        tasks_list = [t.to_dict() for t in visible_tasks]
    else:
        now = datetime.utcnow()
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
                entry_copy["has_submitted"] = False
                entry_copy["user"] = {
                    "id": comp_user_id,
                    "alias_id": comp_user.get("alias_id"),
                    "role": comp_user.get("role"),
                    "challenge_id": comp_user.get("challenge_id"),
                    "is_anonymous": is_anonymous,
                    "manual_points": comp_user.get("manual_points", {}),
                }
            post_processed_leaderboard.append(entry_copy)
        tasks_list = [t.to_dict() for t in tasks]

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
def get_leaderboard(challenge_id):
    """
    Get the leaderboard for a specific challenge.
    Competitors only see their own challenge, and frozen/finalized rules apply.
    ---
    tags:
      - Leaderboard
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: challenge_id
        type: string
        required: true
        description: ID of the challenge
    responses:
      200:
        description: Success
        content:
          application/json:
            schema:
              type: object
    """
    challenge = db.get_or_404(Challenge, challenge_id)
    user_role = request.user["role"]
    current_user_id = request.user["user_id"]

    # Restrict competitors to their registered challenge
    if user_role == "competitor" and not ensure_registered(current_user_id, challenge_id):
        return err("ERR_NOT_REGISTERED", 403)

    payload = _get_leaderboard_payload(challenge, user_role, current_user_id)
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@leaderboard_bp.route("/challenges/<uuid:challenge_id>/leaderboard/live", methods=["GET"])
@login_required
@jury_access_required
def stream_challenge_leaderboard(challenge_id):
    """
    Stream live updates to the challenge leaderboard using Server-Sent Events (SSE).
    ---
    tags:
      - SSE Streaming
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: challenge_id
        type: string
        required: true
        description: ID of the challenge
    responses:
      200:
        description: Success
        content:
          text/event-stream:
            schema:
              type: string
    """
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
        r = get_redis_client()

        # Yield initial connection confirmation
        yield f"data: {json.dumps({'info': 'connected'})}\n\n"

        # Helper to fetch current processed leaderboard and yield it
        def get_and_yield_leaderboard():
            with current_app.app_context():
                c = db.session.get(Challenge, challenge_id)
                if not c:
                    return
                payload = _get_leaderboard_payload(c, user_role, user_id)
                yield f"data: {json.dumps(payload, cls=UUIDEncoder)}\n\n"

        # Yield initial leaderboard state
        for msg in get_and_yield_leaderboard():
            yield msg

        if r:
            pubsub = r.pubsub()
            channel_name = f"challenge_{challenge_id}_leaderboard"
            try:
                pubsub.subscribe(channel_name)
            except Exception as e:
                logger.warning("Failed to subscribe to Redis channel %s: %s", channel_name, e)
                r = None  # Fallback to standard polling

        if r:
            try:
                while True:
                    # Listen for message on the channel
                    message = pubsub.get_message(ignore_subscribe_messages=True, timeout=5.0)
                    if message:
                        # Message received means leaderboard recalculation completed!
                        for msg in get_and_yield_leaderboard():
                            yield msg
                    else:
                        yield ": keep-alive\n\n"
            except Exception as e:
                logger.warning("Leaderboard SSE stream error: %s", e)
        else:
            # Fallback to polling every 10 seconds if Redis is down
            import time

            while True:
                time.sleep(10.0)
                for msg in get_and_yield_leaderboard():
                    yield msg

    return sse_response(event_generator)


@leaderboard_bp.route("/challenges/<uuid:challenge_id>/manual-points", methods=["POST"])
@login_required
@role_required(["jury"])
@jury_access_required
def save_manual_points(challenge_id):
    """
    Save manual points for a user in a challenge.
    Jury members only.
    ---
    tags:
      - Leaderboard
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: challenge_id
        type: integer
        required: true
        description: ID of the challenge
      - in: body
        name: body
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                user_id:
                  type: integer
                points:
                  type: object
                reason:
                  type: string
    responses:
      200:
        description: Manual points saved successfully

        content:
          application/json:
            schema:
              type: object
      400:
        description: Validation error

        content:
          application/json:
            schema:
              type: object
      404:
        description: User or Challenge not found

        content:
          application/json:
            schema:
              type: object
    """
    challenge = db.get_or_404(Challenge, challenge_id)

    if challenge.scores_finalized and challenge.reveal_results:
        return err(
            "ERR_EDITING_BLOCKED",
            400,
            message="Cannot modify manual points once the "
            "competition results are finalized and revealed.",
        )

    data = request.get_json() or {}
    user_id = data.get("user_id")
    points_dict = data.get("points")
    reason = data.get("reason")

    if not user_id or not isinstance(points_dict, dict):
        return err("ERR_MISSING_FIELDS", 400)

    user = User.query.filter_by(id=user_id, challenge_id=challenge_id).first()
    if not user:
        return err("ERR_USER_NOT_FOUND", 404)

    if challenge.scores_finalized and not reason:
        return err(
            "ERR_REASON_REQUIRED",
            400,
            message="A justification reason is mandatory to modify "
            "manual points after the competition is finalized.",
        )

    # Validate points (0-100 integers) and completed submissions count
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

        try:
            pts = int(v)
        except (ValueError, TypeError):
            return err(
                "ERR_POINTS_MUST_BE_INT",
                400,
                message=f"Points for task {task_id} must be an integer.",
            )

        # Check if the task is in a finalized stage with revealed results
        from models import Task

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

        if not (0 <= pts <= 100):
            return err(
                "ERR_POINTS_OUT_OF_BOUNDS",
                400,
                message=f"Points for task {task_id} must be between 0 and 100.",
            )

        # Check if the user has any submissions at all for this task
        total_count = Submission.query.filter_by(user_id=user_id, task_id=task_id).count()
        if total_count == 0:
            return err(
                "ERR_NO_SUBMISSIONS",
                400,
                message="Only students with submissions can be assigned manual "
                "points. Students without submissions automatically receive 0 points.",
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

    return jsonify(
        {
            "message": "Manual points saved successfully.",
            "user_id": user.id,
            "manual_points": user.manual_points,
        }
    )
