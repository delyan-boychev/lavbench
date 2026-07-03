import contextlib
import io
import json
import logging
import time

from auth_utils import jury_access_required, login_required, rate_limit, role_required
from cache_utils import cache_lock, get_redis_client, invalidate_leaderboard_cache
from error_utils import err
from flask import Blueprint, jsonify, request
from models import Challenge, Submission, Task, User, db, decrypt_field
from services.file_validation import validate_extension, validate_notebook_content
from services.submission_service import check_execution_rules
from sqlalchemy.orm import joinedload
from sse_utils import (
    SSE_IDLE_TIMEOUT,
    publish_leaderboard_update,
    publish_submissions_update,
    sse_connection_limit,
)
from utils.dates import utcnow
from utils.ipynb import cells_to_ipynb_json
from utils.json_utils import safe_json_loads
from utils.metadata import build_submission_metadata
from utils.pagination import extract_pagination
from utils.sse import sse_response

logger = logging.getLogger(__name__)


submissions_bp = Blueprint("submissions", __name__)


@submissions_bp.route("/challenges/<uuid:challenge_id>/parse-notebook", methods=["POST"])
@login_required
@jury_access_required
@rate_limit(max_requests=30, window_seconds=60)
def parse_notebook(challenge_id):
    """
    Upload and parse a Jupyter Notebook (.ipynb) to preview cells.
    5MB file limit. Returns a list of cell objects with type and source.
    ---
    tags:
      - Submissions
    parameters:
      - in: path
        name: challenge_id
        type: string
        required: true
      - in: formData
        name: file
        type: file
        required: true
        description: Jupyter Notebook .ipynb file (max 5MB)
    responses:
      200:
        description: Notebook parsed successfully
        content:
          application/json:
            schema:
              type: object
              properties:
                filename: {type: string}
                cells: {type: array, items: {$ref: '#/components/schemas/Cell'}}
      400:
        description: Invalid file type, file too large, or parse error
        schema: {$ref: '#/components/schemas/Error'}
      403:
        description: Not registered for this challenge
        schema: {$ref: '#/components/schemas/Error'}
    """
    user_id = request.user["user_id"]
    user_role = request.user["role"]

    # Restrict competitors to their registered challenge
    if user_role == "competitor":
        from utils.access import ensure_registered

        if not ensure_registered(user_id, challenge_id):
            return err("ERR_NOT_REGISTERED", 403)

    if "file" not in request.files:
        return err("ERR_NO_FILE_UPLOADED", 400)
    file = request.files["file"]

    valid_ext, ext_err = validate_extension(file.filename, {".ipynb"})
    if not valid_ext:
        return err("ERR_INVALID_FILE_TYPE", 400, message=ext_err)

    # Enforce strict 5MB file size limit to prevent memory exhaustion
    limit = 5 * 1024 * 1024
    content = file.read(limit + 1)
    if len(content) > limit:
        return err("ERR_FILE_TOO_LARGE", 413)

    valid_content, content_err, notebook = validate_notebook_content(content)
    if not valid_content:
        return err("ERR_PARSING_FAILED", 400, message=f"Invalid notebook file: {content_err}")

    cells = []
    for idx, cell in enumerate(notebook.get("cells", [])):
        cell_type = cell.get("cell_type", "code")
        source_lines = cell.get("source", [])
        source = "".join(source_lines) if isinstance(source_lines, list) else source_lines

        cells.append({"id": idx, "type": cell_type, "source": source})

    return jsonify({"filename": file.filename, "cells": cells})


@submissions_bp.route("/challenges/<uuid:challenge_id>/submit", methods=["POST"])
@login_required
@jury_access_required
@rate_limit(max_requests=30, window_seconds=60)
def submit_code(challenge_id):
    """
    Submit parsed code cells for a task.
    ---
    tags:
      - Submissions
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: challenge_id
        type: string
        required: true
      - in: body
        name: body
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                task_id: {type: string}
                selected_cells: {type: array, items: {type: object}}
    responses:
      202:
        description: Submission received and queued

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
      403:
        description: Access denied or challenge frozen

        content:
          application/json:
            schema:
              type: object
      429:
        description: Rate limit exceeded

        content:
          application/json:
            schema:
              type: object
    """
    user_id = request.user["user_id"]
    user_role = request.user["role"]

    # Restrict competitors to their registered challenge
    if user_role == "competitor":
        from utils.access import ensure_registered

        if not ensure_registered(user_id, challenge_id):
            return err("ERR_NOT_REGISTERED", 403)

    challenge = db.get_or_404(Challenge, challenge_id)
    if not challenge.is_active:
        return err("ERR_CHALLENGE_INACTIVE", 400)
    if challenge.is_archived:
        return err("ERR_CHALLENGE_ARCHIVED", 400)

    if challenge.is_frozen:
        return err("ERR_COMPETITION_FROZEN", 403)

    if challenge.scores_finalized:
        return err("ERR_COMPETITION_FINALIZED", 403)

    data = request.json or {}
    task_id = data.get("task_id")
    selected_cells = data.get("selected_cells")

    # Retrieve task safely to see if it has a stage
    task = None
    if task_id:
        task = db.session.get(Task, task_id)

    if user_role == "competitor":
        from datetime import timedelta

        now = utcnow()
        from config import Config

        grace_seconds = Config.DEADLINE_GRACE_PERIOD_SECONDS

        if task and task.stage_id:
            from models import Stage

            stage = db.session.get(Stage, task.stage_id)
            if stage:
                if now < stage.start_time:
                    return err(
                        "ERR_STAGE_NOT_STARTED",
                        400,
                        message=f"The stage '{stage.title}' has not started yet.",
                    )
                if stage.end_time and now > (stage.end_time + timedelta(seconds=grace_seconds)):
                    return err(
                        "ERR_STAGE_DEADLINE_PASSED",
                        400,
                        message=f"The deadline for the stage '{stage.title}' has passed.",
                    )
        else:
            if challenge.start_time and now < challenge.start_time:
                return err("ERR_COMPETITION_NOT_STARTED", 400)
            if challenge.end_time and now > (challenge.end_time + timedelta(seconds=grace_seconds)):
                return err("ERR_COMPETITION_ENDED", 400)

    if not selected_cells or not isinstance(selected_cells, list):
        return err("ERR_MISSING_SELECTED_CELLS", 400)

    if not task_id:
        return err("ERR_MISSING_TASK_ID", 400)

    if not task or str(task.challenge_id) != str(challenge_id):
        return err("ERR_INVALID_TASK_ID", 400)

    # AST and general rule validation

    passed, err_msg = check_execution_rules(task, selected_cells)
    if not passed:
        return err("ERR_AST_RULE_FAILED", 400, message=err_msg)

    # Atomic rate-limited submission creation via Redis lock

    lock_key = f"submit_lock:user_{user_id}:challenge_{challenge_id}"

    with cache_lock(lock_key, ttl=10) as acquired:
        if not acquired:
            return err("ERR_SUBMIT_LOCKED", 429)

        today_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        submission_count = Submission.query.filter(
            Submission.user_id == user_id,
            Submission.challenge_id == challenge_id,
            Submission.created_at >= today_start,
        ).count()

        if submission_count >= challenge.max_eval_requests:
            return err(
                "ERR_DAILY_LIMIT_REACHED",
                429,
                message=(
                    f"Daily limit reached. Max {challenge.max_eval_requests} submissions per day."
                ),
            )

        # Create submission
        submission = Submission(
            user_id=user_id,
            challenge_id=challenge_id,
            task_id=task.id,
            status="queued",
            code_cells=json.dumps(selected_cells),
        )
        db.session.add(submission)
        db.session.commit()

    # Trigger Celery Task asynchronously
    from services.submission_service import (
        calculate_submission_priority,
        extract_code_from_cells,
    )
    from tasks import evaluate_submission

    task_files_list = safe_json_loads(task.files, [])

    task.get_hf_api_key() or ""

    gpu_required = False
    if task.gpu_required is not None:
        gpu_required = task.gpu_required
    elif challenge.gpu_required is not None:
        gpu_required = challenge.gpu_required

    metadata = build_submission_metadata(
        task,
        challenge,
        submission,
        user_code="\n\n".join(extract_code_from_cells(selected_cells)),
        task_files_list=task_files_list,
        gpu_required=gpu_required,
    )

    priority = calculate_submission_priority(user_id, user_role)
    queue_name = "gpu_queue" if gpu_required else "cpu_queue"

    try:
        result = evaluate_submission.apply_async(
            args=[submission.id, metadata],
            priority=priority,
            queue=queue_name,
            countdown=1,
            task_id=f"submission_{submission.id}",
        )
        if result is not None:
            submission.celery_task_id = str(result.id)
        db.session.commit()
    except Exception as e:
        submission.status = "failed"
        submission.detailed_status = "failed"
        submission.logs = f"Submission queue unavailable: {e}"
        db.session.commit()
        return err("ERR_QUEUE_UNAVAILABLE", 503, submission_id=submission.id)

    return (
        jsonify(
            {
                "message": "Submission received and queued for execution.",
                "submission_id": submission.id,
                "status": submission.status,
            }
        ),
        202,
    )


@submissions_bp.route("/challenges/<uuid:challenge_id>/submissions", methods=["GET"])
@login_required
@jury_access_required
def get_submissions(challenge_id):
    """
    Get paginated submissions for a challenge.
    ---
    tags:
      - Submissions
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: challenge_id
        type: string
        required: true
      - in: query
        name: page
        type: integer
        required: false
      - in: query
        name: per_page
        type: integer
        required: false
    responses:
      200:
        description: List of submissions

        content:
          application/json:
            schema:
              type: object
      403:
        description: Access denied

        content:
          application/json:
            schema:
              type: object
    """
    challenge = db.get_or_404(Challenge, challenge_id)
    user_role = request.user["role"]
    user_id = request.user["user_id"]

    page, per_page = extract_pagination(request, default_per_page=50, max_per_page=200)

    # Restrict competitors to their registered challenge
    if user_role == "competitor":
        from utils.access import ensure_registered

        if not ensure_registered(user_id, challenge_id):
            return err("ERR_NOT_REGISTERED", 403)

        if challenge.end_time and utcnow() >= challenge.end_time:
            return err("ERR_SUBMISSIONS_LOCKED", 403)

        # Check ended stages

        now = utcnow()
        active_stages = [s for s in challenge.stages if s.end_time and now < s.end_time]
        active_stage_ids = [s.id for s in active_stages]

        from sqlalchemy import or_

        query = (
            Submission.query.filter_by(challenge_id=challenge_id, user_id=user_id)
            .options(
                joinedload(Submission.challenge),
                joinedload(Submission.user),
                joinedload(Submission.task),
            )
            .join(Task)
            .filter(or_(Task.stage_id.is_(None), Task.stage_id.in_(active_stage_ids)))
        )
    else:
        query = Submission.query.filter_by(challenge_id=challenge_id, is_baseline=False).options(
            joinedload(Submission.challenge),
            joinedload(Submission.user),
            joinedload(Submission.task),
        )

    pagination = query.order_by(Submission.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return jsonify(
        {
            "submissions": [
                s.to_dict_light(view_role=user_role, current_user_id=user_id)
                for s in pagination.items
            ],
            "per_page": pagination.per_page,
            "challenge": challenge.to_dict(),
            "total": pagination.total,
            "page": pagination.page,
            "pages": pagination.pages,
        }
    )


@submissions_bp.route("/submissions/<uuid:submission_id>", methods=["GET"])
@login_required
@jury_access_required
def get_submission_detail(submission_id):
    """
    Get details of a specific submission.
    ---
    tags:
      - Submissions
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: submission_id
        type: string
        required: true
    responses:
      200:
        description: Submission details

        content:
          application/json:
            schema:
              type: object
      403:
        description: Access denied

        content:
          application/json:
            schema:
              type: object
      404:
        description: Submission not found

        content:
          application/json:
            schema:
              type: object
    """
    user_id = request.user["user_id"]
    user_role = request.user["role"]

    submission = db.get_or_404(Submission, submission_id)

    if user_role == "competitor":
        if submission.user_id != user_id:
            return err("ERR_NOT_FOUND", 404)

        challenge = db.session.get(Challenge, submission.challenge_id)
        if challenge and challenge.end_time and utcnow() >= challenge.end_time:
            return err("ERR_SUBMISSIONS_LOCKED", 403)

        if submission.task_id:
            task = db.session.get(Task, submission.task_id)
            if task and task.stage_id:
                from models import Stage

                stage = db.session.get(Stage, task.stage_id)
                if stage and stage.end_time and utcnow() >= stage.end_time:
                    return err("ERR_SUBMISSIONS_LOCKED", 403)

    return jsonify(submission.to_dict(view_role=user_role, current_user_id=user_id))


@submissions_bp.route("/submissions/<uuid:submission_id>/select-final", methods=["POST"])
@login_required
@jury_access_required
@rate_limit(max_requests=20, window_seconds=60)
def select_final_submission(submission_id):
    """
    Select a submission as the final one for scoring.
    ---
    tags:
      - Submissions
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: submission_id
        type: string
        required: true
    responses:
      200:
        description: Submission selected as final

        content:
          application/json:
            schema:
              type: object
      400:
        description: Selection window closed

        content:
          application/json:
            schema:
              type: object
      403:
        description: Access denied

        content:
          application/json:
            schema:
              type: object
      404:
        description: Submission not found

        content:
          application/json:
            schema:
              type: object
    """
    user_id = request.user["user_id"]
    user_role = request.user["role"]

    submission = db.get_or_404(Submission, submission_id)

    # Only competitor owner or admin/jury can set it
    if user_role == "competitor" and submission.user_id != user_id:
        return err("ERR_NOT_FOUND", 404)

    # Enforce stage select window for competitors
    if user_role == "competitor":
        challenge = db.session.get(Challenge, submission.challenge_id)
        if challenge and challenge.scores_finalized:
            return err("ERR_COMPETITION_FINALIZED", 403)

        task = db.session.get(Task, submission.task_id)
        if task and task.stage_id:
            from models import Stage

            stage = db.session.get(Stage, task.stage_id)
            if stage:
                from datetime import timedelta

                now = utcnow()
                if submission.created_at > stage.end_time:
                    return err("ERR_SUBMISSION_LATE", 400)

                t_base_select = stage.end_time + timedelta(seconds=300)

                # Fetch all pre-deadline submissions for this task
                user_subs = Submission.query.filter(
                    Submission.user_id == user_id,
                    Submission.task_id == submission.task_id,
                    Submission.created_at <= stage.end_time,
                ).all()

                t_final_select = t_base_select
                for s in user_subs:
                    if s.executed_at:
                        t_select = s.executed_at + timedelta(seconds=300)
                        if t_select > t_final_select:
                            t_final_select = t_select

                if now > t_final_select:
                    return err("ERR_SELECTION_WINDOW_CLOSED", 400)

    # Atomically set final selection: lock all submissions for this user+task
    locked_subs = (
        Submission.query.filter_by(user_id=submission.user_id, task_id=submission.task_id)
        .with_for_update()
        .all()
    )

    for s in locked_subs:
        s.is_final_selection = s.id == submission.id
    db.session.commit()

    invalidate_leaderboard_cache(submission.challenge_id)

    publish_submissions_update(submission.task_id, submission.user_id)
    publish_leaderboard_update(submission.task_id, submission.challenge_id)

    return jsonify(
        {
            "message": "Submission selected as final.",
            "submission": submission.to_dict(view_role=user_role, current_user_id=user_id),
        }
    )


@submissions_bp.route("/submissions/<uuid:submission_id>/logs/live", methods=["GET"])
@login_required
@jury_access_required
def stream_submission_logs(submission_id):
    """
    Stream live logs for a submission using Server-Sent Events (SSE).
    """
    from flask import current_app

    user_id = request.user["user_id"]
    user_role = request.user["role"]

    submission = db.session.get(Submission, submission_id)
    if not submission:
        return err("ERR_NOT_FOUND", 404)

    if user_role == "competitor":
        if submission.user_id != user_id:
            return err("ERR_ACCESS_DENIED", 403)

        challenge = db.session.get(Challenge, submission.challenge_id)
        if challenge and challenge.end_time and utcnow() >= challenge.end_time:
            return err("ERR_SUBMISSIONS_LOCKED", 403)

        if submission.task_id:
            task = db.session.get(Task, submission.task_id)
            if task and task.stage_id:
                from models import Stage

                stage = db.session.get(Stage, task.stage_id)
                if stage and stage.end_time and utcnow() >= stage.end_time:
                    return err("ERR_SUBMISSIONS_LOCKED", 403)

    def event_generator():
        user_id = request.user["user_id"]
        with sse_connection_limit(user_id=user_id) as allowed:
            if not allowed:
                yield f"data: {json.dumps({'error': 'too many connections'})}\n\n"
                return

            r = get_redis_client()

            yield f"data: {json.dumps({'info': 'connected'})}\n\n"

            if r:
                try:
                    log_key = f"submission:{submission_id}:logs"
                    existing_logs = r.lrange(log_key, 0, -1)
                    if existing_logs:
                        for log_bin in existing_logs:
                            log_line = log_bin.decode("utf-8")
                            yield f"data: {json.dumps({'log': log_line})}\n\n"
                    else:
                        with current_app.app_context():
                            sub = db.session.get(Submission, submission_id)
                            if sub and sub.logs:
                                for line in sub.logs.splitlines():
                                    yield f"data: {json.dumps({'log': line})}\n\n"
                except Exception as e:
                    logger.warning(
                        ("Failed to retrieve existing logs for submission %s: %s"), submission_id, e
                    )
            else:
                with current_app.app_context():
                    sub = db.session.get(Submission, submission_id)
                    if sub and sub.logs:
                        for line in sub.logs.splitlines():
                            yield f"data: {json.dumps({'log': line})}\n\n"

            with current_app.app_context():
                sub = db.session.get(Submission, submission_id)
                if sub and sub.status in ("completed", "failed"):
                    yield f"data: {json.dumps({'status': sub.status})}\n\n"
                    return

            if r:
                try:
                    pubsub = r.pubsub()
                    pubsub.subscribe(f"submission_{submission_id}_logs")
                except Exception:
                    r = None

            start_time = time.time()

            if r:
                last_db_check = time.time()
                try:
                    while True:
                        if time.time() - start_time > SSE_IDLE_TIMEOUT:
                            yield f"data: {json.dumps({'event': 'timeout'})}\n\n"
                            break
                        message = pubsub.get_message(ignore_subscribe_messages=True, timeout=2.0)
                        if message:
                            data_str = message["data"].decode("utf-8")
                            yield f"data: {data_str}\n\n"
                            try:
                                parsed = json.loads(data_str)
                                if isinstance(parsed, dict) and parsed.get("status") in (
                                    "completed",
                                    "failed",
                                ):
                                    break
                            except Exception as e:
                                logger.debug("Failed to parse SSE message: %s", e)
                        else:
                            yield ": keep-alive\n\n"

                        now = time.time()
                        if now - last_db_check >= 10.0:
                            last_db_check = now
                            with current_app.app_context():
                                db.session.expire_all()
                                sub = db.session.get(Submission, submission_id)
                                if sub and sub.status in ("completed", "failed"):
                                    yield f"data: {json.dumps({'status': sub.status})}\n\n"
                                    break
                except GeneratorExit:
                    pass
                except Exception as e:
                    logger.error("SSE logs streaming error: %s", e)
                finally:
                    with contextlib.suppress(Exception):
                        pubsub.unsubscribe()
                        pubsub.close()
            else:
                last_yielded_len = 0
                with current_app.app_context():
                    sub = db.session.get(Submission, submission_id)
                    if sub and sub.logs:
                        last_yielded_len = len(sub.logs.splitlines())

                try:
                    while True:
                        if time.time() - start_time > SSE_IDLE_TIMEOUT:
                            yield f"data: {json.dumps({'event': 'timeout'})}\n\n"
                            break
                        with current_app.app_context():
                            db.session.expire_all()
                            sub = db.session.get(Submission, submission_id)
                            if not sub:
                                break

                            logs_str = sub.logs or ""
                            lines = logs_str.splitlines()
                            if len(lines) > last_yielded_len:
                                for line in lines[last_yielded_len:]:
                                    yield f"data: {json.dumps({'log': line})}\n\n"
                                last_yielded_len = len(lines)

                            if sub.status in ("completed", "failed"):
                                yield f"data: {json.dumps({'status': sub.status})}\n\n"
                                break

                        time.sleep(2.0)
                except GeneratorExit:
                    pass
                except Exception as e:
                    logger.error("Polling logs fallback error: %s", e)

    return sse_response(event_generator)


@submissions_bp.route(
    "/challenges/<uuid:challenge_id>/tasks/<uuid:task_id>/users/<uuid:user_id>/download",
    methods=["GET"],
)
@role_required(["admin", "jury"])
@jury_access_required
def download_competitor_submission(challenge_id, task_id, user_id):
    """
    Download a competitor's submission resolving to the final selection or the highest public score.
    """
    subs = Submission.query.filter_by(task_id=task_id, user_id=user_id, status="completed").all()

    best_sub = next((s for s in subs if s.is_final_selection), None)
    if not best_sub:
        subs_sorted = sorted(
            subs,
            key=lambda x: (
                x.public_score if x.public_score is not None else -999999,
                -(x.execution_time_ms if x.execution_time_ms is not None else 999999),
            ),
            reverse=True,
        )
        if subs_sorted:
            best_sub = subs_sorted[0]

    if not best_sub:
        return err("ERR_NO_COMPLETED_SUBMISSIONS", 404)

    try:
        cells_data = safe_json_loads(best_sub.code_cells, [])
    except json.JSONDecodeError:
        cells_data = []

    notebook_str = cells_to_ipynb_json(cells_data)
    mem_file = io.BytesIO(notebook_str.encode("utf-8"))

    user = db.session.get(User, user_id)
    task = db.session.get(Task, task_id)

    name_part = decrypt_field(user.name) or ""
    surname_part = decrypt_field(user.surname) or ""
    comp_name = f"{name_part}_{surname_part}_{user.alias_id}"
    comp_name = "".join(c for c in comp_name if c.isalnum() or c in (" ", "_", "-")).strip()

    task_title = "".join(c for c in task.title if c.isalnum() or c in (" ", "_", "-")).strip()

    filename = f"{comp_name}_{task_title}_sub_{best_sub.id}.ipynb"

    from flask import send_file

    return send_file(
        mem_file,
        mimetype="application/x-ipynb+json",
        as_attachment=True,
        download_name=filename,
    )
