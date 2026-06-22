import os
import json
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify
from sqlalchemy.orm import joinedload
from models import db, Challenge, Submission, User, Task
from auth_utils import login_required, rate_limit
from sse_utils import publish_submissions_update, publish_leaderboard_update

logger = logging.getLogger(__name__)


submissions_bp = Blueprint("submissions", __name__)


@submissions_bp.route("/challenges/<int:challenge_id>/parse-notebook", methods=["POST"])
@login_required
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
        type: integer
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
        user = db.session.get(User, user_id)
        if not user or user.challenge_id != challenge_id:
            return (
                jsonify(
                    {
                        "error": "Access denied. You are not registered for this competition.",
                        "code": "ERR_NOT_REGISTERED",
                    }
                ),
                403,
            )

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded.", "code": "ERR_NO_FILE_UPLOADED"}), 400
    file = request.files["file"]

    from services.file_validation import validate_extension, validate_notebook_content

    valid_ext, ext_err = validate_extension(file.filename, {".ipynb"})
    if not valid_ext:
        return jsonify({"error": ext_err, "code": "ERR_INVALID_FILE_TYPE"}), 400

    # Enforce strict 5MB file size limit to prevent memory exhaustion
    limit = 5 * 1024 * 1024
    content = file.read(limit + 1)
    if len(content) > limit:
        return (
            jsonify({"error": "File size exceeds the 5MB limit.", "code": "ERR_FILE_TOO_LARGE"}),
            413,
        )

    valid_content, content_err, notebook = validate_notebook_content(content)
    if not valid_content:
        return (
            jsonify(
                {"error": f"Invalid notebook file: {content_err}", "code": "ERR_PARSING_FAILED"}
            ),
            400,
        )

    cells = []
    for idx, cell in enumerate(notebook.get("cells", [])):
        cell_type = cell.get("cell_type", "code")
        source_lines = cell.get("source", [])
        source = "".join(source_lines) if isinstance(source_lines, list) else source_lines

        cells.append({"id": idx, "type": cell_type, "source": source})

    return jsonify({"filename": file.filename, "cells": cells})


@submissions_bp.route("/challenges/<int:challenge_id>/submit", methods=["POST"])
@login_required
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
        type: integer
        required: true
      - in: body
        name: body
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                task_id: {type: integer}
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
        user = db.session.get(User, user_id)
        if not user or user.challenge_id != challenge_id:
            return (
                jsonify(
                    {
                        "error": "Access denied. You are not registered for this competition.",
                        "code": "ERR_NOT_REGISTERED",
                    }
                ),
                403,
            )

    challenge = db.get_or_404(Challenge, challenge_id)
    if not challenge.is_active:
        return (
            jsonify(
                {"error": "This challenge is currently inactive.", "code": "ERR_CHALLENGE_INACTIVE"}
            ),
            400,
        )
    if challenge.is_archived:
        return (
            jsonify(
                {
                    "error": "This challenge has been archived and no longer accepts submissions.",
                    "code": "ERR_CHALLENGE_ARCHIVED",
                }
            ),
            400,
        )

    if challenge.is_frozen:
        return (
            jsonify(
                {
                    "error": "This competition is currently frozen. Submissions are temporarily blocked.",
                    "code": "ERR_COMPETITION_FROZEN",
                }
            ),
            403,
        )

    if challenge.scores_finalized:
        return (
            jsonify(
                {
                    "error": "Submissions are disabled for finalized competitions.",
                    "code": "ERR_COMPETITION_FINALIZED",
                }
            ),
            403,
        )

    data = request.json or {}
    task_id = data.get("task_id")
    selected_cells = data.get("selected_cells")

    # Retrieve task safely to see if it has a stage
    task = None
    if task_id:
        task = db.session.get(Task, task_id)

    if user_role == "competitor":
        now = datetime.utcnow()
        from datetime import timedelta
        from config import Config

        grace_seconds = Config.DEADLINE_GRACE_PERIOD_SECONDS

        if task and task.stage_id:
            from models import Stage

            stage = db.session.get(Stage, task.stage_id)
            if stage:
                if now < stage.start_time:
                    return (
                        jsonify(
                            {
                                "error": f"The stage '{stage.title}' has not started yet.",
                                "code": "ERR_STAGE_NOT_STARTED",
                            }
                        ),
                        400,
                    )
                if stage.end_time and now > (stage.end_time + timedelta(seconds=grace_seconds)):
                    return (
                        jsonify(
                            {
                                "error": f"The deadline for the stage '{stage.title}' has passed.",
                                "code": "ERR_STAGE_DEADLINE_PASSED",
                            }
                        ),
                        400,
                    )
        else:
            if challenge.start_time and now < challenge.start_time:
                return (
                    jsonify(
                        {
                            "error": "This competition has not started yet.",
                            "code": "ERR_COMPETITION_NOT_STARTED",
                        }
                    ),
                    400,
                )
            if challenge.end_time and now > (challenge.end_time + timedelta(seconds=grace_seconds)):
                return (
                    jsonify(
                        {
                            "error": "This competition has ended and no longer accepts submissions.",
                            "code": "ERR_COMPETITION_ENDED",
                        }
                    ),
                    400,
                )

    if not selected_cells or not isinstance(selected_cells, list):
        return (
            jsonify(
                {"error": "selected_cells list is required.", "code": "ERR_MISSING_SELECTED_CELLS"}
            ),
            400,
        )

    if not task_id:
        return jsonify({"error": "task_id is required.", "code": "ERR_MISSING_TASK_ID"}), 400

    if not task or task.challenge_id != challenge_id:
        return (
            jsonify(
                {"error": "Invalid task_id for this challenge.", "code": "ERR_INVALID_TASK_ID"}
            ),
            400,
        )

    # AST and general rule validation
    from services.submission_service import check_execution_rules

    passed, err_msg = check_execution_rules(task, selected_cells)
    if not passed:
        return jsonify({"error": err_msg, "code": "ERR_AST_RULE_FAILED"}), 400

    # Atomic rate-limited submission creation via Redis lock
    from cache_utils import cache_lock

    lock_key = f"submit_lock:user_{user_id}:challenge_{challenge_id}"

    with cache_lock(lock_key, ttl=10) as acquired:
        if not acquired:
            return (
                jsonify(
                    {
                        "error": "Another submission is being processed. Please wait.",
                        "code": "ERR_SUBMIT_LOCKED",
                    }
                ),
                429,
            )

        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        submission_count = Submission.query.filter(
            Submission.user_id == user_id,
            Submission.challenge_id == challenge_id,
            Submission.created_at >= today_start,
        ).count()

        if submission_count >= challenge.max_eval_requests:
            return (
                jsonify(
                    {
                        "error": f"Daily limit reached. You can only make {challenge.max_eval_requests} submissions per day.",
                        "code": "ERR_DAILY_LIMIT_REACHED",
                    }
                ),
                429,
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
    from tasks import evaluate_submission
    from services.submission_service import extract_code_from_cells, calculate_submission_priority

    task_files_list = []
    if task.files:
        try:
            task_files_list = json.loads(task.files)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    hf_token = task.get_hf_api_key() or ""
    main_server_url = os.environ.get("MAIN_SERVER_URL", "http://localhost:5001")

    gpu_required = False
    if task.gpu_required is not None:
        gpu_required = task.gpu_required
    elif challenge.gpu_required is not None:
        gpu_required = challenge.gpu_required

    metadata = {
        "submission_id": submission.id,
        "task_id": task.id,
        "challenge_id": challenge.id,
        "user_code": "\n\n".join(extract_code_from_cells(selected_cells)),
        "time_limit": task.time_limit_sec or challenge.time_limit_sec or 300,
        "ram_limit": task.ram_limit_mb or challenge.ram_limit_mb or 8192,
        "gpu_required": gpu_required,
        "base_docker_image": task.base_docker_image,
        "apt_packages": task.apt_packages,
        "pip_requirements": task.pip_requirements,
        "is_custom_eval": (
            True
            if (
                task.custom_eval_code
                or (task.evaluator_script_path and os.path.exists(task.evaluator_script_path))
            )
            else False
        ),
        "metrics_config": task.metrics_config,
        "hf_datasets": (
            task.hf_datasets
            if isinstance(task.hf_datasets, str)
            else (json.dumps(task.hf_datasets) if task.hf_datasets else None)
        ),
        "hf_models": (
            task.hf_models
            if isinstance(task.hf_models, str)
            else (json.dumps(task.hf_models) if task.hf_models else None)
        ),
        "public_eval_percentage": (
            task.public_eval_percentage if task.public_eval_percentage is not None else 30
        ),
        "task_files": task_files_list,
        "main_server_url": main_server_url,
        "celery_broker_url": os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    }

    priority = calculate_submission_priority(user_id, user_role)
    queue_name = "gpu_queue" if gpu_required else "celery"

    try:
        evaluate_submission.apply_async(
            args=[submission.id, metadata], priority=priority, queue=queue_name, countdown=1
        )
    except Exception as e:
        submission.status = "failed"
        submission.detailed_status = "failed"
        submission.logs = f"Submission queue unavailable: {e}"
        db.session.commit()
        return (
            jsonify(
                {
                    "error": "Submission queue is temporarily unavailable. Please try again.",
                    "submission_id": submission.id,
                }
            ),
            503,
        )

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


@submissions_bp.route("/challenges/<int:challenge_id>/submissions", methods=["GET"])
@login_required
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
        type: integer
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

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    per_page = min(per_page, 200)

    # Restrict competitors to their registered challenge
    if user_role == "competitor":
        user = db.session.get(User, user_id)
        if not user or user.challenge_id != challenge_id:
            return (
                jsonify(
                    {
                        "error": "Access denied. You are not registered for this competition.",
                        "code": "ERR_NOT_REGISTERED",
                    }
                ),
                403,
            )

        query = Submission.query.filter_by(challenge_id=challenge_id, user_id=user_id).options(
            joinedload(Submission.challenge),
            joinedload(Submission.user),
            joinedload(Submission.task),
        )
    else:
        query = Submission.query.filter_by(challenge_id=challenge_id).options(
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
            "page": pagination.page,
            "per_page": pagination.per_page,
            "total": pagination.total,
            "pages": pagination.pages,
        }
    )


@submissions_bp.route("/submissions/<int:submission_id>", methods=["GET"])
@login_required
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
        type: integer
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

    if user_role == "competitor" and submission.user_id != user_id:
        return (
            jsonify(
                {
                    "error": "Access denied. You can only view your own submissions.",
                    "code": "ERR_NOT_OWNER",
                }
            ),
            403,
        )

    return jsonify(submission.to_dict(view_role=user_role, current_user_id=user_id))


@submissions_bp.route("/submissions/<int:submission_id>/select-final", methods=["POST"])
@login_required
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
        type: integer
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
        return (
            jsonify(
                {"error": "Access denied. You do not own this submission.", "code": "ERR_NOT_OWNER"}
            ),
            403,
        )

    # Enforce stage select window for competitors
    if user_role == "competitor":
        challenge = db.session.get(Challenge, submission.challenge_id)
        if challenge and challenge.scores_finalized:
            return (
                jsonify(
                    {
                        "error": "Cannot change final selection for a finalized competition.",
                        "code": "ERR_COMPETITION_FINALIZED",
                    }
                ),
                403,
            )

        task = db.session.get(Task, submission.task_id)
        if task and task.stage_id:
            from models import Stage

            stage = db.session.get(Stage, task.stage_id)
            if stage:
                now = datetime.utcnow()
                if submission.created_at > stage.end_time:
                    return (
                        jsonify(
                            {
                                "error": "Cannot select a submission created after the stage deadline.",
                                "code": "ERR_SUBMISSION_LATE",
                            }
                        ),
                        400,
                    )

                from datetime import timedelta

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
                    return (
                        jsonify(
                            {
                                "error": "The final selection window for this stage has closed.",
                                "code": "ERR_SELECTION_WINDOW_CLOSED",
                            }
                        ),
                        400,
                    )

    # Atomically set final selection: lock all submissions for this user+task
    locked_subs = (
        Submission.query.filter_by(user_id=submission.user_id, task_id=submission.task_id)
        .with_for_update()
        .all()
    )

    for s in locked_subs:
        s.is_final_selection = s.id == submission.id
    db.session.commit()

    from cache_utils import invalidate_leaderboard_cache

    invalidate_leaderboard_cache(submission.challenge_id)

    publish_submissions_update(submission.task_id, submission.user_id)
    publish_leaderboard_update(submission.task_id)

    return jsonify(
        {
            "message": "Submission selected as final.",
            "submission": submission.to_dict(view_role=user_role, current_user_id=user_id),
        }
    )


@submissions_bp.route("/submissions/<int:submission_id>/logs/live", methods=["GET"])
@login_required
def stream_submission_logs(submission_id):
    """
    Stream live logs for a submission using Server-Sent Events (SSE).
    ---
    tags:
      - SSE Streaming
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: submission_id
        type: integer
        required: true
    responses:
      200:
        description: SSE stream of logs

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
    from flask import current_app, Response, stream_with_context

    user_id = request.user["user_id"]
    user_role = request.user["role"]

    submission = db.session.get(Submission, submission_id)
    if not submission:
        return jsonify({"error": "Submission not found.", "code": "ERR_NOT_FOUND"}), 404

    if user_role == "competitor" and submission.user_id != user_id:
        return jsonify({"error": "Access denied.", "code": "ERR_ACCESS_DENIED"}), 403

    def event_generator():
        from cache_utils import get_redis_client

        r = get_redis_client()

        # Yield an initial message to flush headers immediately and establish connection
        yield f"data: {json.dumps({'info': 'connected'})}\n\n"

        log_key = f"submission:{submission_id}:logs"
        existing_logs = r.lrange(log_key, 0, -1)
        if existing_logs:
            for log_bin in existing_logs:
                log_line = log_bin.decode("utf-8")
                yield f"data: {json.dumps({'log': log_line})}\n\n"

        with current_app.app_context():
            sub = db.session.get(Submission, submission_id)
            if sub and sub.status in ("completed", "failed"):
                yield f"data: {json.dumps({'status': sub.status})}\n\n"
                return

        pubsub = r.pubsub()
        pubsub.subscribe(f"submission_{submission_id}_logs")

        try:
            while True:
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=2.0)
                if message:
                    yield f"data: {message['data'].decode('utf-8')}\n\n"
                else:
                    yield ": keep-alive\n\n"

                with current_app.app_context():
                    db.session.expire_all()
                    sub = db.session.get(Submission, submission_id)
                    if sub and sub.status in ("completed", "failed"):
                        yield f"data: {json.dumps({'status': sub.status})}\n\n"
                        break
        except GeneratorExit:
            try:
                pubsub.unsubscribe()
                pubsub.close()
            except:
                pass
        except Exception as e:
            logger.error("SSE logs streaming error: %s", e)
            try:
                pubsub.unsubscribe()
                pubsub.close()
            except:
                pass

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return Response(
        stream_with_context(event_generator()), mimetype="text/event-stream", headers=headers
    )
