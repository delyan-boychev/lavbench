from __future__ import annotations

import contextlib
import gzip
import json
import logging
import os
import time
from datetime import timedelta
from typing import Any

from flask import Blueprint, current_app, request
from flask import Response as FlaskResponse
from spectree import Response
from werkzeug.utils import secure_filename

from auth_utils import (
    check_worker_auth,
    jury_access_required,
    login_required,
    rate_limit,
    role_required,
)
from cache_utils import get_redis_client, invalidate_leaderboard_cache
from error_utils import err
from models import Challenge, Stage, Submission, Task, db
from schemas.responses import (
    ErrorResponse,
    MessageResponse,
    PaginatedResponse,
    SubmissionLightResponse,
    SubmitResponse,
    TaskAdminResponse,
    TaskLeaderboardResponse,
    WorkerActiveDatasetsResponse,
    WorkerActiveTasksResponse,
    WorkerHfKeyResponse,
    WorkerLogsResponse,
    WorkerReportResponse,
    WorkerStatusResponse,
)
from schemas.submission import SelectedCellsSchema
from schemas.task import CreateTaskMetaSchema, UpdateTaskMetaSchema
from services.leaderboard_service import get_task_leaderboard_data
from services.submission_service import (
    calculate_submission_priority,
    check_execution_rules,
    extract_code_from_cells,
    extract_code_from_notebook,
)
from spec import api
from sse_utils import (
    SSE_IDLE_TIMEOUT,
    publish_leaderboard_update,
    publish_queue_update,
    publish_submissions_update,
    sse_connection_limit,
)
from utils.access import ensure_registered
from utils.audit import log_audit
from utils.cache import invalidate_entity_cache
from utils.cache_helpers import cached_or_compute_unless_testing
from utils.dates import utcnow
from utils.ipynb import sanitize_filename_part
from utils.json_utils import safe_json_loads
from utils.metadata import build_submission_metadata
from utils.sse import sse_response

tasks_bp = Blueprint("tasks", __name__)

logger = logging.getLogger(__name__)


def _validate_evaluator_script(code: str) -> tuple[dict[str, Any] | None, str | None]:
    """Parse and validate required module-level variables from an evaluator script.

    Required: METRIC_NAME (str), SUBMISSION_COLUMNS (list[dict{name, type}]),
              LABELS_COLUMNS (list[dict{name, type}])
    Optional: EVALUATOR_OPTIONS (dict)

    Returns (metadata_dict, None) on success or (None, error_message) on failure.
    """
    try:
        import ast

        tree = ast.parse(code)
    except SyntaxError as e:
        return None, f"Syntax error in evaluator script: {e}"

    def _get_value(var_name: str) -> Any:
        for node in ast.iter_child_nodes(tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == var_name
            ):
                return ast.literal_eval(node.value)
        return None

    metric_name = _get_value("METRIC_NAME")
    if metric_name is None:
        return None, "Missing required variable: METRIC_NAME (str)"
    if not isinstance(metric_name, str) or not metric_name.strip():
        return None, "METRIC_NAME must be a non-empty string"

    sub_cols = _get_value("SUBMISSION_COLUMNS")
    if sub_cols is None:
        return None, "Missing required variable: SUBMISSION_COLUMNS (list of {name, type})"
    if not isinstance(sub_cols, list):
        return None, "SUBMISSION_COLUMNS must be a list"
    for i, col in enumerate(sub_cols):
        if not isinstance(col, dict) or "name" not in col or "type" not in col:
            return (
                None,
                f"SUBMISSION_COLUMNS[{i}]: each entry must be a dict with 'name' and 'type' keys",
            )
        if not isinstance(col["name"], str) or not isinstance(col["type"], str):
            return None, f"SUBMISSION_COLUMNS[{i}]: 'name' and 'type' must be strings"

    lbl_cols = _get_value("LABELS_COLUMNS")
    if lbl_cols is None:
        return None, "Missing required variable: LABELS_COLUMNS (list of {name, type})"
    if not isinstance(lbl_cols, list):
        return None, "LABELS_COLUMNS must be a list"
    for i, col in enumerate(lbl_cols):
        if not isinstance(col, dict) or "name" not in col or "type" not in col:
            return (
                None,
                f"LABELS_COLUMNS[{i}]: each entry must be a dict with 'name' and 'type' keys",
            )
        if not isinstance(col["name"], str) or not isinstance(col["type"], str):
            return None, f"LABELS_COLUMNS[{i}]: 'name' and 'type' must be strings"

    options = _get_value("EVALUATOR_OPTIONS")
    if options is not None and not isinstance(options, dict):
        return None, "EVALUATOR_OPTIONS must be a dict"

    return {
        "metric_name": metric_name.strip(),
        "submission_columns": sub_cols,
        "labels_columns": lbl_cols,
        "options": options or {},
    }, None


class UUIDEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        import uuid

        if isinstance(obj, uuid.UUID):
            return str(obj)
        return super().default(obj)


MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024  # 500 MB limit per file
MAX_TOTAL_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB limit per task

VALID_STATUSES = {"queued", "running", "completed", "failed"}
MAX_LOG_SIZE = 100 * 1024


def check_competitor_access(user_id: Any, challenge_id: Any) -> bool:
    return ensure_registered(user_id, challenge_id) is not None


def check_task_started(task: Any, user_role: str, user_id: Any) -> bool:
    if user_role == "competitor":
        if not check_competitor_access(user_id, task.challenge_id):
            return False
        challenge = task.challenge
        if challenge and not challenge.is_started:
            return False
        if task.stage_id:
            from models import Stage

            stage = db.session.get(Stage, task.stage_id)
            if stage and utcnow() < stage.start_time:
                return False
    return True


def to_bool(val: Any) -> bool | None:
    if val is None:
        return None
    if isinstance(val, str):
        return val.lower() in ["true", "1", "yes", "on"]
    return bool(val)


def to_int(val: Any) -> int | None:
    if val is None or str(val).strip() == "":
        return None
    try:
        return int(val)
    except ValueError:
        return None


def queue_system_submission(
    task: Any, challenge: Any, code_cells: list[dict[str, Any]], admin_id: Any, priority: int = 8
) -> None:
    submission = Submission(
        user_id=admin_id,
        challenge_id=challenge.id,
        task_id=task.id,
        status="queued",
        detailed_status="queued",
        is_baseline=True,
        code_cells=json.dumps(code_cells),
    )
    db.session.add(submission)
    db.session.commit()

    publish_submissions_update(submission.task_id, submission.challenge_id)
    publish_queue_update()
    publish_leaderboard_update(submission.challenge_id)

    from tasks import evaluate_submission

    task_files_list = safe_json_loads(task.files, [])

    gpu_required = False
    if task.gpu_required is not None:
        gpu_required = task.gpu_required
    elif challenge.gpu_required is not None:
        gpu_required = challenge.gpu_required

    metadata = build_submission_metadata(
        task,
        challenge,
        submission,
        user_code="\n\n".join(extract_code_from_cells(code_cells)),
        task_files_list=task_files_list,
        gpu_required=gpu_required,
    )

    if task.custom_eval_code:
        metadata["custom_eval_code"] = task.custom_eval_code
    elif task.evaluator_script_path and os.path.exists(task.evaluator_script_path):
        try:
            with open(task.evaluator_script_path) as ef:
                metadata["custom_eval_code"] = ef.read()
        except Exception:
            logger.exception("Failed to read evaluator script for task %s", task.id)

    # Dispatch the submission via Celery
    queue_name = "gpu_queue" if gpu_required else "cpu_queue"

    result = evaluate_submission.apply_async(
        args=[submission.id, metadata],
        priority=priority,
        queue=queue_name,
        countdown=1,
        task_id=f"submission_{int(utcnow().timestamp() * 1000):016d}_{submission.id}",
    )
    if result is not None:
        submission.celery_task_id = str(result.id)
    db.session.commit()


def _maybe_queue_baseline(task: Any, challenge: Any, admin_id: Any) -> None:
    """Delete old baseline submissions and queue a new one if a baseline notebook exists."""
    # Remove old baseline submissions for this task and their physical files
    import os

    old_baselines = Submission.query.filter_by(task_id=task.id, is_baseline=True).all()
    paths_to_delete = [(s.code_storage_path, s.log_storage_path) for s in old_baselines]

    Submission.query.filter_by(task_id=task.id, is_baseline=True).delete(synchronize_session=False)
    db.session.commit()

    for code_path, log_path in paths_to_delete:
        if code_path and os.path.exists(code_path):
            with contextlib.suppress(OSError):
                os.remove(code_path)
        if log_path and os.path.exists(log_path):
            with contextlib.suppress(OSError):
                os.remove(log_path)

    # Parse and submit new baseline if notebook exists
    baseline_cells = []
    if task.baseline_notebook_path and os.path.exists(task.baseline_notebook_path):
        baseline_cells = extract_code_from_notebook(task.baseline_notebook_path)

    if baseline_cells:
        queue_system_submission(task, challenge, baseline_cells, admin_id, priority=8)


# --- TASK CRUD ---


@tasks_bp.route("/tasks/<uuid:task_id>", methods=["GET"])
@login_required
@jury_access_required
@api.validate(
    resp=Response(HTTP_200=TaskAdminResponse, HTTP_403=ErrorResponse),
    tags=["Tasks"],
    security=[{"cookieAuth": []}],
)
def get_task(task_id: Any) -> dict[str, Any] | tuple[FlaskResponse, int]:
    """API endpoint."""
    task = db.get_or_404(Task, task_id)
    user_role = request.user["role"]
    user_id = request.user["user_id"]

    if not check_task_started(task, user_role, user_id):
        return err("ERR_NOT_AVAILABLE", 403)

    return task.to_dict(view_role=user_role)


@tasks_bp.route("/challenges/<uuid:challenge_id>/tasks", methods=["POST"])
@role_required(["admin", "jury"])
@jury_access_required
@api.validate(
    form=CreateTaskMetaSchema,
    resp=Response(HTTP_201=TaskAdminResponse, HTTP_400=ErrorResponse, HTTP_403=ErrorResponse),
    tags=["Tasks"],
    security=[{"cookieAuth": []}],
)
def create_task(
    challenge_id: Any, form: CreateTaskMetaSchema
) -> tuple[dict[str, Any], int] | tuple[FlaskResponse, int]:
    """Create a new evaluation task with resource limits, metrics, and test data files."""
    challenge = db.get_or_404(Challenge, challenge_id)

    title = form.title
    description = form.description

    if (
        "baseline_notebook" not in request.files
        or request.files["baseline_notebook"].filename == ""
    ):
        return err("ERR_BASELINE_REQUIRED", 400)

    ram_limit_mb = form.ram_limit_mb
    time_limit_sec = form.time_limit_sec
    gpu_required = form.gpu_required

    base_docker_image = form.base_docker_image
    apt_packages = form.apt_packages
    pip_requirements = form.pip_requirements

    if request.user.get("role") != "admin" and (
        base_docker_image or apt_packages or pip_requirements
    ):
        return err(
            "ERR_FORBIDDEN",
            403,
            message="Only administrators are allowed to configure custom environments.",
        )

    ban_magic_commands = form.ban_magic_commands
    banned_imports = form.banned_imports
    whitelisted_imports = form.whitelisted_imports

    hf_datasets = form.hf_datasets
    hf_models = form.hf_models

    evaluator_code = None
    evaluator_metric_name = None
    if "evaluator_script" in request.files:
        f = request.files["evaluator_script"]
        if f and f.filename != "":
            evaluator_code = f.read().decode("utf-8")
            f.seek(0)
            eval_result, eval_err = _validate_evaluator_script(evaluator_code)
            if eval_result is None:
                return err("ERR_EVALUATOR_SCRIPT_INVALID", 400, message=eval_err)
            evaluator_metric_name = eval_result["metric_name"]

    metrics_config = form.metrics_config
    if metrics_config:
        from evaluation_engine import AVAILABLE_METRICS

        allowed_metrics = list(AVAILABLE_METRICS.keys())
        for metric_name in metrics_config:
            if metric_name == "_columns" or metric_name == evaluator_metric_name:
                continue
            if metric_name not in allowed_metrics:
                return err(
                    "ERR_INVALID_METRIC_NAME",
                    400,
                    message=f"Invalid metric '{metric_name}'. Allowed metrics: {allowed_metrics}",
                )

    public_eval_percentage = form.public_eval_percentage
    max_submissions_per_period = form.max_submissions_per_period
    submission_period_hours = form.submission_period_hours
    stage_id = form.stage_id
    if stage_id == "":
        stage_id = None

    if stage_id:
        st = Stage.query.filter_by(id=stage_id, challenge_id=challenge_id).first()
        if not st:
            return err("ERR_INVALID_STAGE_ID", 400)
    else:
        regular_stage_count = Stage.query.filter_by(
            challenge_id=challenge_id, is_test=False
        ).count()
        if regular_stage_count > 0:
            return err(
                "ERR_STAGE_REQUIRED",
                400,
                message="Task must be assigned to a stage when the competition has stages.",
            )

    task = Task(
        challenge_id=challenge_id,
        stage_id=stage_id,
        title=title,
        description=description,
        ram_limit_mb=ram_limit_mb,
        time_limit_sec=time_limit_sec,
        gpu_required=gpu_required,
        base_docker_image=base_docker_image,
        apt_packages=apt_packages,
        pip_requirements=pip_requirements,
        ban_magic_commands=ban_magic_commands,
        banned_imports=banned_imports,
        whitelisted_imports=whitelisted_imports,
        metrics_config=metrics_config,
        hf_datasets=hf_datasets,
        hf_models=hf_models,
        public_eval_percentage=public_eval_percentage,
        max_submissions_per_period=max_submissions_per_period,
        submission_period_hours=submission_period_hours,
        files="[]",
    )

    hf_api_key = request.form.get("hf_api_key")
    if hf_api_key:
        task.set_hf_api_key(hf_api_key)

    db.session.add(task)
    db.session.commit()

    uploaded_files_meta = []
    files_keys = [k for k in request.files if k.startswith("file")]

    if len(files_keys) > 5:
        db.session.delete(task)
        db.session.commit()
        return err("ERR_TOO_MANY_FILES", 400)

    task_upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], f"task_{task.id}")
    os.makedirs(task_upload_dir, exist_ok=True)

    if "evaluator_script" in request.files:
        f = request.files["evaluator_script"]
        if f and f.filename != "":
            safe_name = "evaluator.py"
            save_path = os.path.join(task_upload_dir, safe_name)
            f.save(save_path)
            task.evaluator_script_path = save_path
            with open(save_path, encoding="utf-8") as ef:
                code = ef.read()
            task.custom_eval_code = code
            eval_result, eval_err = _validate_evaluator_script(code)
            if eval_result is None:
                db.session.delete(task)
                db.session.commit()
                import shutil

                shutil.rmtree(task_upload_dir, ignore_errors=True)
                return err("ERR_EVALUATOR_SCRIPT_INVALID", 400, message=eval_err)
            task.evaluator_metric_name = eval_result["metric_name"]

    if "baseline_notebook" in request.files:
        f = request.files["baseline_notebook"]
        if f and f.filename != "":
            from services.file_validation import validate_extension

            valid_ext, ext_err = validate_extension(f.filename, {".ipynb"})
            if not valid_ext:
                db.session.delete(task)
                db.session.commit()
                import shutil

                shutil.rmtree(task_upload_dir, ignore_errors=True)
                return err("ERR_INVALID_FILE_TYPE", 400, message=ext_err)
            safe_name = secure_filename(f.filename)
            save_path = os.path.join(task_upload_dir, safe_name)
            f.save(save_path)
            task.baseline_notebook_path = save_path

    if "solution_notebook" in request.files:
        f = request.files["solution_notebook"]
        if f and f.filename != "":
            from services.file_validation import validate_extension

            valid_ext, ext_err = validate_extension(f.filename, {".ipynb"})
            if not valid_ext:
                db.session.delete(task)
                db.session.commit()
                import shutil

                shutil.rmtree(task_upload_dir, ignore_errors=True)
                return err("ERR_INVALID_FILE_TYPE", 400, message=ext_err)
            safe_name = secure_filename(f.filename)
            save_path = os.path.join(task_upload_dir, safe_name)
            f.save(save_path)
            task.solution_notebook_path = save_path

    total_upload_size = 0

    for key in files_keys:
        uploaded_file = request.files[key]
        if uploaded_file and uploaded_file.filename != "":
            from services.file_validation import check_dangerous_extension

            if check_dangerous_extension(uploaded_file.filename):
                db.session.delete(task)
                db.session.commit()
                import shutil

                shutil.rmtree(task_upload_dir, ignore_errors=True)
                return err(
                    "ERR_INVALID_FILE_TYPE",
                    400,
                    message=f"File type '{uploaded_file.filename}' is not allowed.",
                )

            uploaded_file.seek(0, os.SEEK_END)
            size = uploaded_file.tell()
            uploaded_file.seek(0)

            total_upload_size += size
            if total_upload_size > MAX_TOTAL_UPLOAD_BYTES:
                db.session.delete(task)
                db.session.commit()
                import shutil

                shutil.rmtree(task_upload_dir, ignore_errors=True)
                return err(
                    "ERR_TOTAL_SIZE_EXCEEDED",
                    400,
                    message="Total file size exceeds the 2 GB limit for a single task.",
                )

            if size > MAX_FILE_SIZE_BYTES:
                db.session.delete(task)
                db.session.commit()
                import shutil

                shutil.rmtree(task_upload_dir, ignore_errors=True)
                return err(
                    "ERR_TASK_FILE_TOO_LARGE",
                    400,
                    message=f"File '{uploaded_file.filename}' exceeds the 500 MB size limit.",
                )

            safe_name = secure_filename(uploaded_file.filename)
            save_path = os.path.join(task_upload_dir, safe_name)
            uploaded_file.save(save_path)

            if uploaded_file.filename == "labels.parquet":
                try:
                    import pyarrow.parquet as pq

                    from evaluation_engine import validate_parquet_schema_columns

                    schema = pq.read_schema(save_path)
                    columns = [col.name for col in schema]
                    is_valid, schema_err = validate_parquet_schema_columns(
                        columns, is_submission=False
                    )
                    if not is_valid:
                        db.session.delete(task)
                        db.session.commit()
                        import shutil

                        shutil.rmtree(task_upload_dir, ignore_errors=True)
                        return err(
                            "ERR_INVALID_LABELS_SCHEMA",
                            400,
                            message=f"Invalid labels.parquet schema: {schema_err}",
                        )
                except Exception as e:
                    db.session.delete(task)
                    db.session.commit()
                    import shutil

                    shutil.rmtree(task_upload_dir, ignore_errors=True)
                    return err(
                        "ERR_LABELS_PARSE_FAILED",
                        400,
                        message=f"Failed to parse labels.parquet: {e!s}",
                    )

            uploaded_files_meta.append(
                {
                    "filename": uploaded_file.filename,
                    "saved_name": safe_name,
                    "size_bytes": size,
                }
            )

    task.files = json.dumps(uploaded_files_meta)
    db.session.commit()

    # Parse code cells from notebooks and queue baseline submission
    admin_id = request.user["user_id"]
    _maybe_queue_baseline(task, challenge, admin_id)

    log_audit(
        request.user["user_id"],
        "create",
        "task",
        target_id=task.id,
        details={"title": task.title, "challenge_id": challenge_id},
    )

    invalidate_entity_cache(challenge_id)

    # Notify workers to rebuild Docker image for this task
    try:
        if not current_app.config.get("TESTING"):
            from cache_utils import get_redis_client

            r = get_redis_client()
            if r:
                r.publish("task_rebuild", str(task.id))
    except Exception as e:
        logger.warning("Failed to publish task_rebuild notification for task %s: %s", task.id, e)

    return task.to_dict(view_role=request.user["role"]), 201


@tasks_bp.route("/tasks/<uuid:task_id>", methods=["PUT"])
@role_required(["admin", "jury"])
@jury_access_required
@api.validate(
    form=UpdateTaskMetaSchema,
    resp=Response(HTTP_200=TaskAdminResponse, HTTP_400=ErrorResponse, HTTP_403=ErrorResponse),
    tags=["Tasks"],
    security=[{"cookieAuth": []}],
)
def update_task(
    task_id: Any, form: UpdateTaskMetaSchema
) -> dict[str, Any] | tuple[FlaskResponse, int]:
    """Update an existing task configuration including files and evaluator scripts."""
    task = db.get_or_404(Task, task_id)
    fields = form.model_fields_set

    if request.user.get("role") != "admin":
        for field in ["base_docker_image", "apt_packages", "pip_requirements"]:
            if field in fields:
                val = getattr(form, field)
                current_val = getattr(task, field)
                if (val or "").strip() != (current_val or "").strip():
                    return err(
                        "ERR_FORBIDDEN",
                        403,
                        message="Only administrators are allowed to configure custom environments.",
                    )

    if "title" in fields:
        task.title = form.title
    if "description" in fields:
        task.description = form.description

    if "ram_limit_mb" in fields:
        task.ram_limit_mb = form.ram_limit_mb

    if "base_docker_image" in fields:
        task.base_docker_image = form.base_docker_image

    if "apt_packages" in fields:
        task.apt_packages = form.apt_packages

    if "pip_requirements" in fields:
        task.pip_requirements = form.pip_requirements

    # Clear build_error when environment config is changed
    if task.build_error:
        env_fields = {
            "base_docker_image",
            "apt_packages",
            "pip_requirements",
            "hf_datasets",
            "hf_models",
        }
        if (fields & env_fields) or (
            "hf_api_key" in request.form and request.form.get("hf_api_key", "").strip()
        ):
            task.build_error = None

    if "time_limit_sec" in fields:
        task.time_limit_sec = form.time_limit_sec
    if "gpu_required" in fields:
        task.gpu_required = form.gpu_required

    if "ban_magic_commands" in fields:
        task.ban_magic_commands = form.ban_magic_commands
    if "banned_imports" in fields:
        task.banned_imports = form.banned_imports

    if "metrics_config" in fields:
        task.metrics_config = form.metrics_config

    if "whitelisted_imports" in fields:
        task.whitelisted_imports = form.whitelisted_imports

    if "hf_datasets" in fields:
        task.hf_datasets = form.hf_datasets

    if "hf_models" in fields:
        task.hf_models = form.hf_models

    if "hf_api_key" in request.form:
        hf_api_key = request.form.get("hf_api_key")
        if hf_api_key:
            task.set_hf_api_key(hf_api_key)
    if "public_eval_percentage" in fields:
        task.public_eval_percentage = form.public_eval_percentage
    if "max_submissions_per_period" in fields:
        task.max_submissions_per_period = form.max_submissions_per_period
    if "submission_period_hours" in fields:
        task.submission_period_hours = form.submission_period_hours
    if "stage_id" in fields:
        from models import Stage

        stage_id_val = form.stage_id
        if stage_id_val == "":
            stage_id_val = None

        old_stage = db.session.get(Stage, task.stage_id) if task.stage_id else None
        if stage_id_val is not None and old_stage:
            if old_stage.is_finalized:
                return err("ERR_CANNOT_MOVE_FINALIZED", 400)
            if old_stage.end_time and old_stage.end_time <= utcnow():
                return err("ERR_CANNOT_MOVE_ENDED", 400)

        if (
            stage_id_val is not None
            and stage_id_val != task.stage_id
            and Submission.query.filter(
                Submission.task_id == task.id,
                Submission.manual_points.isnot(None),
                Submission.manual_points != "{}",
            ).first()
        ):
            return err("ERR_CANNOT_MOVE_HAS_MANUAL_POINTS", 400)

        if stage_id_val:
            st = Stage.query.filter_by(id=stage_id_val, challenge_id=task.challenge_id).first()
            if not st:
                return err("ERR_INVALID_STAGE_ID", 400)
            task.stage_id = stage_id_val
        else:
            regular_stage_count = Stage.query.filter_by(
                challenge_id=task.challenge_id, is_test=False
            ).count()
            if regular_stage_count > 0:
                return err(
                    "ERR_STAGE_REQUIRED",
                    400,
                    message="Task must be assigned to a stage when the competition has stages.",
                )
            task.stage_id = None

    task_upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], f"task_{task.id}")
    os.makedirs(task_upload_dir, exist_ok=True)

    if "evaluator_script" in request.files:
        f = request.files["evaluator_script"]
        if f and f.filename != "":
            safe_name = "evaluator.py"
            save_path = os.path.join(task_upload_dir, safe_name)
            f.save(save_path)
            task.evaluator_script_path = save_path
            with open(save_path, encoding="utf-8") as ef:
                code = ef.read()
            task.custom_eval_code = code
            eval_result, eval_err = _validate_evaluator_script(code)
            if eval_result is None:
                return err("ERR_EVALUATOR_SCRIPT_INVALID", 400, message=eval_err)
            task.evaluator_metric_name = eval_result["metric_name"]

    if "baseline_notebook" in request.files:
        f = request.files["baseline_notebook"]
        if f and f.filename != "":
            from services.file_validation import validate_extension

            valid_ext, ext_err = validate_extension(f.filename, {".ipynb"})
            if not valid_ext:
                return err("ERR_INVALID_FILE_TYPE", 400, message=ext_err)
            safe_name = secure_filename(f.filename)
            save_path = os.path.join(task_upload_dir, safe_name)
            f.save(save_path)
            task.baseline_notebook_path = save_path

    if "solution_notebook" in request.files:
        f = request.files["solution_notebook"]
        if f and f.filename != "":
            from services.file_validation import validate_extension

            valid_ext, ext_err = validate_extension(f.filename, {".ipynb"})
            if not valid_ext:
                return err("ERR_INVALID_FILE_TYPE", 400, message=ext_err)
            safe_name = secure_filename(f.filename)
            save_path = os.path.join(task_upload_dir, safe_name)
            f.save(save_path)
            task.solution_notebook_path = save_path

    current_files = safe_json_loads(task.files, [])

    deleted_files_raw = form.deleted_files
    if deleted_files_raw:
        try:
            deleted_filenames = json.loads(deleted_files_raw)
            updated_files = []
            for f in current_files:
                if f["filename"] in deleted_filenames:
                    file_path = os.path.join(task_upload_dir, f["saved_name"])
                    if os.path.exists(file_path):
                        os.remove(file_path)
                else:
                    updated_files.append(f)
            current_files = updated_files
        except (json.JSONDecodeError, TypeError, KeyError, OSError) as e:
            logger.warning("Failed to process deleted_files for task %s: %s", task.id, e)

    if form.delete_evaluator and task.evaluator_script_path:
        if os.path.exists(task.evaluator_script_path):
            os.remove(task.evaluator_script_path)
        task.evaluator_script_path = None
        task.custom_eval_code = None
        task.evaluator_metric_name = None
    if form.delete_baseline and task.baseline_notebook_path:
        if os.path.exists(task.baseline_notebook_path):
            os.remove(task.baseline_notebook_path)
        task.baseline_notebook_path = None

    new_files_keys = [k for k in request.files if k.startswith("file")]
    if len(current_files) + len(new_files_keys) > 5:
        return err("ERR_TOO_MANY_FILES", 400)

    newly_saved_paths: list[str] = []
    total_update_size = 0

    for key in new_files_keys:
        uploaded_file = request.files[key]
        if uploaded_file and uploaded_file.filename != "":
            from services.file_validation import check_dangerous_extension

            if check_dangerous_extension(uploaded_file.filename):
                for p in newly_saved_paths:
                    if os.path.exists(p):
                        os.remove(p)
                return err(
                    "ERR_INVALID_FILE_TYPE",
                    400,
                    message=f"File type '{uploaded_file.filename}' is not allowed.",
                )

            uploaded_file.seek(0, os.SEEK_END)
            size = uploaded_file.tell()
            uploaded_file.seek(0)

            total_update_size += size
            if total_update_size > MAX_TOTAL_UPLOAD_BYTES:
                for p in newly_saved_paths:
                    if os.path.exists(p):
                        os.remove(p)
                return err(
                    "ERR_TOTAL_SIZE_EXCEEDED",
                    400,
                    message="Total file size exceeds the 2 GB limit for a single task.",
                )

            if size > MAX_FILE_SIZE_BYTES:
                for p in newly_saved_paths:
                    if os.path.exists(p):
                        os.remove(p)
                return err(
                    "ERR_TASK_FILE_TOO_LARGE",
                    400,
                    message=f"File '{uploaded_file.filename}' exceeds the 500 MB size limit.",
                )

            safe_name = secure_filename(uploaded_file.filename)
            save_path = os.path.join(task_upload_dir, safe_name)
            uploaded_file.save(save_path)
            newly_saved_paths.append(save_path)

            if uploaded_file.filename == "labels.parquet":
                try:
                    import pyarrow.parquet as pq

                    from evaluation_engine import validate_parquet_schema_columns

                    schema = pq.read_schema(save_path)
                    columns = [col.name for col in schema]
                    is_valid, schema_err = validate_parquet_schema_columns(
                        columns, is_submission=False
                    )
                    if not is_valid:
                        for p in newly_saved_paths:
                            if os.path.exists(p):
                                os.remove(p)
                        return err(
                            "ERR_INVALID_LABELS_SCHEMA",
                            400,
                            message=f"Invalid labels.parquet schema: {schema_err}",
                        )
                except Exception as e:
                    for p in newly_saved_paths:
                        if os.path.exists(p):
                            os.remove(p)
                    return err(
                        "ERR_LABELS_PARSE_FAILED",
                        400,
                        message=f"Failed to parse labels.parquet: {e!s}",
                    )

            current_files.append(
                {
                    "filename": uploaded_file.filename,
                    "saved_name": safe_name,
                    "size_bytes": size,
                }
            )
    task.files = json.dumps(current_files)
    db.session.commit()

    log_audit(
        request.user["user_id"],
        "update",
        "task",
        target_id=task.id,
        details={"title": task.title, "challenge_id": task.challenge_id},
    )

    invalidate_entity_cache(task.challenge_id)
    _maybe_queue_baseline(task, task.challenge, request.user["user_id"])

    # Notify workers to rebuild Docker image for this task
    try:
        if not current_app.config.get("TESTING"):
            from cache_utils import get_redis_client

            r = get_redis_client()
            if r:
                r.publish("task_rebuild", str(task.id))
    except Exception as e:
        logger.warning("Failed to publish task_rebuild notification for task %s: %s", task.id, e)

    return task.to_dict(view_role=request.user["role"])


@tasks_bp.route("/tasks/<uuid:task_id>", methods=["DELETE"])
@role_required(["admin", "jury"])
@jury_access_required
@api.validate(
    resp=Response(HTTP_200=MessageResponse),
    tags=["Tasks"],
    security=[{"cookieAuth": []}],
)
def delete_task(task_id: Any) -> MessageResponse | tuple[FlaskResponse, int]:
    """Remove a task and all its submissions from a challenge."""
    task = db.get_or_404(Task, task_id)
    challenge_id = task.challenge_id
    task_upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], f"task_{task.id}")
    import shutil

    shutil.rmtree(task_upload_dir, ignore_errors=True)
    # Collect file paths before bulk delete for cleanup
    subs = Submission.query.filter_by(task_id=task_id).all()
    from tasks import celery

    for s in subs:
        if s.celery_task_id:
            with contextlib.suppress(Exception):
                celery.control.revoke(s.celery_task_id, terminate=True)
    paths = [(s.code_storage_path, s.log_storage_path) for s in subs]
    Submission.query.filter_by(task_id=task_id).delete(synchronize_session=False)
    for code_path, log_path in paths:
        if code_path and os.path.exists(code_path):
            with contextlib.suppress(OSError):
                os.remove(code_path)
        if log_path and os.path.exists(log_path):
            with contextlib.suppress(OSError):
                os.remove(log_path)
    db.session.delete(task)
    db.session.commit()

    log_audit(
        request.user["user_id"],
        "delete",
        "task",
        target_id=task.id,
        details={"title": task.title, "challenge_id": challenge_id},
    )

    invalidate_entity_cache(challenge_id)

    return MessageResponse(message=f"Task '{task.title}' has been deleted successfully.")


# --- DOWNLOAD FILE ---


@tasks_bp.route("/tasks/<uuid:task_id>/download/<string:filename>", methods=["GET"])
@login_required
@jury_access_required
@rate_limit(max_requests=5, window_seconds=60)
@api.validate(
    resp=Response(HTTP_200=None, HTTP_403=ErrorResponse, HTTP_404=ErrorResponse),
    tags=["Tasks"],
    security=[{"cookieAuth": []}],
)
def download_task_file(
    task_id: Any, filename: str
) -> FlaskResponse | tuple[bytes, int, dict[str, str]] | tuple[FlaskResponse, int]:
    """Download a resource file attached to a task."""
    task = db.get_or_404(Task, task_id)
    user_role = request.user["role"]
    user_id = request.user["user_id"]

    if user_role == "competitor":
        if filename == "labels.parquet":
            return err("ERR_ACCESS_DENIED", 403)
        if not check_task_started(task, user_role, user_id):
            return err("ERR_NOT_AVAILABLE", 403)

    try:
        files_meta = json.loads(task.files)
    except json.JSONDecodeError:
        files_meta = []

    saved_name = None
    for f in files_meta:
        if f["filename"] == filename:
            saved_name = f["saved_name"]
            break

    if saved_name:
        task_upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], f"task_{task.id}")
        file_path = os.path.join(task_upload_dir, saved_name)
        if not os.path.isfile(file_path):
            return err("ERR_NOT_FOUND", 404)
        with open(file_path, "rb") as f:
            file_data = f.read()
        safe_filename = sanitize_filename_part(filename)
        return (
            file_data,
            200,
            {
                "Content-Type": "application/octet-stream",
                "Content-Disposition": f'attachment; filename="{safe_filename}"',
            },
        )

    if task.baseline_notebook_path:
        baseline_basename = os.path.basename(task.baseline_notebook_path)
        if filename == baseline_basename:
            with open(task.baseline_notebook_path, "rb") as fh:
                baseline_bytes = fh.read()
            safe_filename = sanitize_filename_part(filename)
            return (
                baseline_bytes,
                200,
                {
                    "Content-Type": "application/octet-stream",
                    "Content-Disposition": f'attachment; filename="{safe_filename}"',
                },
            )

    return err("ERR_FILE_NOT_FOUND", 404)


# --- TASK SUBMISSIONS & EVALUATIONS ---


@tasks_bp.route("/tasks/<uuid:task_id>/submit", methods=["POST"])
@login_required
@jury_access_required
@rate_limit(max_requests=10, window_seconds=60)
@api.validate(
    json=SelectedCellsSchema,
    resp=Response(
        HTTP_202=SubmitResponse,
        HTTP_400=ErrorResponse,
        HTTP_403=ErrorResponse,
        HTTP_500=ErrorResponse,
        HTTP_503=ErrorResponse,
    ),
    tags=["Tasks"],
    security=[{"cookieAuth": []}],
)
def submit_task(
    task_id: Any, json: SelectedCellsSchema
) -> tuple[SubmitResponse, int] | tuple[FlaskResponse, int]:
    """Submit code cells for execution under a specific task."""
    import json as jsonlib

    task = db.get_or_404(Task, task_id)
    challenge = task.challenge

    if not challenge.is_active:
        return err("ERR_CHALLENGE_INACTIVE", 400)
    if challenge.is_archived:
        return err("ERR_CHALLENGE_ARCHIVED", 400)

    user_id = request.user["user_id"]
    user_role = request.user["role"]
    selected_cells = json.selected_cells

    if user_role == "competitor":
        if not check_competitor_access(user_id, task.challenge_id):
            return err("ERR_NOT_REGISTERED", 403)

        if challenge.scores_finalized:
            return err("ERR_COMPETITION_FINALIZED", 403)

        if task.stage_id:
            from models import Stage

            stage = db.session.get(Stage, task.stage_id)
            if stage:
                if utcnow() < stage.start_time:
                    return err(
                        "ERR_STAGE_NOT_STARTED",
                        400,
                        message=f"The stage '{stage.title}' has not started yet.",
                    )
                if utcnow() > stage.end_time:
                    return err(
                        "ERR_STAGE_DEADLINE_PASSED",
                        400,
                        message=f"The deadline for the stage '{stage.title}' has passed.",
                    )
        else:
            if not challenge.is_started:
                return err("ERR_COMPETITION_NOT_STARTED", 400)
            if challenge.is_ended:
                return err("ERR_COMPETITION_ENDED", 400)

    today_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    submission_count = Submission.query.filter(
        Submission.user_id == user_id,
        Submission.challenge_id == challenge.id,
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

    if task.max_submissions_per_period and task.submission_period_hours:
        period_start = utcnow() - timedelta(hours=task.submission_period_hours)
        sub_count = Submission.query.filter(
            Submission.user_id == user_id,
            Submission.task_id == task.id,
            Submission.created_at >= period_start,
        ).count()
        if sub_count >= task.max_submissions_per_period:
            return err(
                "ERR_TASK_LIMIT_REACHED",
                429,
                message=f"Task limit reached. Max {task.max_submissions_per_period} "
                f"submissions per {task.submission_period_hours} hours.",
            )

    passed, err_msg = check_execution_rules(task, selected_cells)
    if not passed:
        submission = Submission(
            user_id=user_id,
            challenge_id=challenge.id,
            task_id=task.id,
            status="failed",
            detailed_status="failed",
            code_cells=jsonlib.dumps(selected_cells),
            public_score=0.0,
            private_score=0.0,
            logs=f"--- Rule Check Failed ---\n{err_msg}",
            execution_time_ms=0,
        )
        db.session.add(submission)
        db.session.commit()
        publish_submissions_update(submission.task_id, submission.challenge_id)
        publish_queue_update()
        publish_leaderboard_update(submission.challenge_id)
        return err(
            "ERR_AST_RULE_FAILED",
            200,
            message=err_msg,
            submission_id=submission.id,
            submission_status=submission.status,
        )

    priority = calculate_submission_priority(user_id, user_role)

    submission = Submission(
        user_id=user_id,
        challenge_id=challenge.id,
        task_id=task.id,
        status="queued",
        detailed_status="queued",
        code_cells=jsonlib.dumps(selected_cells),
    )
    db.session.add(submission)
    db.session.commit()

    invalidate_leaderboard_cache(submission.challenge_id)

    publish_submissions_update(submission.task_id, submission.challenge_id)
    publish_queue_update()
    publish_leaderboard_update(submission.challenge_id)
    from tasks import evaluate_submission

    gpu_required = False
    if task.gpu_required is not None:
        gpu_required = task.gpu_required
    elif challenge.gpu_required is not None:
        gpu_required = challenge.gpu_required

    queue_name = "gpu_queue" if gpu_required else "cpu_queue"

    # Compile complete metadata dictionary for remote workers (avoids DB exposure on remote nodes)
    task_files_list = safe_json_loads(task.files, [])

    metadata = build_submission_metadata(
        task,
        challenge,
        submission,
        user_code="\n\n".join(extract_code_from_cells(selected_cells)),
        task_files_list=task_files_list,
        gpu_required=gpu_required,
    )

    if task.custom_eval_code:
        metadata["custom_eval_code"] = task.custom_eval_code
    elif task.evaluator_script_path and os.path.exists(task.evaluator_script_path):
        try:
            with open(task.evaluator_script_path) as ef:
                metadata["custom_eval_code"] = ef.read()
        except Exception as ef_err:
            logger.error("Failed to read evaluator script for task %s: %s", task.id, ef_err)
            submission.status = "failed"
            submission.detailed_status = "failed"
            submission.logs = f"Evaluator script read error: {ef_err}"
            db.session.commit()
            return err("ERR_EVALUATOR_LOAD_FAILED", 500, submission_id=submission.id)

    try:
        result = evaluate_submission.apply_async(
            args=[submission.id, metadata],
            priority=priority,
            queue=queue_name,
            countdown=1,
            task_id=f"submission_{int(utcnow().timestamp() * 1000):016d}_{submission.id}",
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

    return SubmitResponse(
        message="Submission received and queued for execution.",
        submission_id=submission.id,
        status=submission.status,
    ), 202


def _get_task_submissions_data(
    task_id: Any,
    user_role: str,
    user_id: Any,
    page: int = 1,
    per_page: int = 10,
    filter_user_id: Any | None = None,
    baseline: bool = False,
) -> dict[str, Any]:
    task = db.session.get(Task, task_id)
    if not task:
        return {"error": "Task not found."}

    if user_role == "competitor":
        if not check_task_started(task, user_role, user_id):
            return {"error": "Access denied or task not available yet."}
        challenge = task.challenge
        if challenge and challenge.scores_finalized:
            return {"error": "Access denied. Submissions are hidden for finalized competitions."}
        query = Submission.query.filter_by(task_id=task_id, user_id=user_id)
    else:
        if baseline:
            query = Submission.query.filter_by(task_id=task_id, is_baseline=True)
        else:
            query = Submission.query.filter_by(task_id=task_id, is_baseline=False)

    if filter_user_id and user_role in ("admin", "jury") and not baseline:
        query = query.filter_by(user_id=filter_user_id)

    from sqlalchemy.orm import joinedload

    query = query.options(
        joinedload(Submission.challenge),
        joinedload(Submission.user),
        joinedload(Submission.task),
    )

    pagination = query.order_by(Submission.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return {
        "items": [
            s.to_dict_light(view_role=user_role, current_user_id=user_id) for s in pagination.items
        ],
        "total": pagination.total,
        "page": pagination.page,
        "pages": pagination.pages,
    }


@tasks_bp.route("/tasks/<uuid:task_id>/submissions", methods=["GET"])
@login_required
@jury_access_required
@api.validate(
    resp=Response(HTTP_200=PaginatedResponse[SubmissionLightResponse], HTTP_403=ErrorResponse),
    tags=["Tasks"],
    security=[{"cookieAuth": []}],
)
def get_task_submissions(task_id: Any) -> dict[str, Any] | tuple[FlaskResponse, int]:
    """List submissions for a specific task with pagination."""
    user_role = request.user["role"]
    user_id = request.user["user_id"]
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 10, type=int), 100)
    filter_user_id = request.args.get("user_id")
    baseline = request.args.get("baseline", type=str, default="").lower() in ("true", "1")

    data = _get_task_submissions_data(
        task_id, user_role, user_id, page, per_page, filter_user_id, baseline=baseline
    )
    if isinstance(data, dict) and "error" in data:
        return err("ERR_ACCESS_DENIED", 403, message=data["error"])
    return data


def _get_task_leaderboard_data(
    task_id: Any, user_role: str, current_user_id: Any
) -> dict[str, Any]:
    return get_task_leaderboard_data(task_id, user_role, current_user_id)


@tasks_bp.route("/tasks/<uuid:task_id>/leaderboard", methods=["GET"])
@login_required
@jury_access_required
@api.validate(
    resp=Response(HTTP_200=TaskLeaderboardResponse, HTTP_403=ErrorResponse),
    tags=["Tasks"],
    security=[{"cookieAuth": []}],
)
def get_task_leaderboard(
    task_id: Any,
) -> tuple[dict[str, Any], int, dict[str, str]] | tuple[FlaskResponse, int]:
    """Get cached leaderboard data for a specific task."""
    user_role = request.user["role"]
    current_user_id = request.user["user_id"]
    data = _get_task_leaderboard_data(task_id, user_role, current_user_id)
    if "error" in data:
        return err("ERR_ACCESS_DENIED", 403, message=data["error"])
    return (
        data,
        200,
        {
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@tasks_bp.route("/tasks/<uuid:task_id>/submissions/live", methods=["GET"])
@login_required
@jury_access_required
@api.validate(
    resp=Response(HTTP_200=None, HTTP_403=ErrorResponse),
    tags=["SSE Streaming"],
    security=[{"cookieAuth": []}],
)
def stream_task_submissions(
    task_id: Any,
) -> tuple[FlaskResponse, int, dict[str, str]] | tuple[FlaskResponse, int]:
    """Stream live task submission updates via SSE."""
    user_role = request.user["role"]
    current_user_id = request.user["user_id"]
    page = request.args.get("page", type=int)
    per_page = min(request.args.get("per_page", 10, type=int), 100)

    task = db.session.get(Task, task_id)
    if not task:
        return err("ERR_NOT_FOUND", 404)
    challenge_id = task.challenge_id

    if user_role == "competitor":
        if not check_task_started(task, user_role, current_user_id):
            return err("ERR_NOT_AVAILABLE", 403)
        if task.challenge and task.challenge.scores_finalized:
            return err(
                "ERR_COMPETITION_FINALIZED",
                403,
                message="Access denied. Submissions are hidden for finalized competitions.",
            )

    def event_generator():
        with sse_connection_limit(user_id=current_user_id) as allowed:
            if not allowed:
                yield f"data: {json.dumps({'error': 'too many connections'})}\n\n"
                return

            data = _get_task_submissions_data(task_id, user_role, current_user_id, page, per_page)
            yield f"data: {json.dumps(data)}\n\n"

            r = get_redis_client()
            pubsub = r.pubsub() if r else None

            if pubsub:
                pubsub.subscribe(f"challenge_{challenge_id}_submissions")

            start_time = time.time()

            try:
                while True:
                    if time.time() - start_time > SSE_IDLE_TIMEOUT:
                        yield f"data: {json.dumps({'event': 'timeout'})}\n\n"
                        break
                    if pubsub:
                        message = pubsub.get_message(ignore_subscribe_messages=True, timeout=2.0)
                        if message:
                            data = _get_task_submissions_data(
                                task_id, user_role, current_user_id, page, per_page
                            )
                            yield f"data: {json.dumps(data)}\n\n"
                            continue
                    else:
                        time.sleep(2.0)
                    yield ": keep-alive\n\n"
            except GeneratorExit:
                pass
            except Exception as e:
                logger.error("Submissions SSE error: %s", e)
            finally:
                if pubsub:
                    with contextlib.suppress(Exception):
                        pubsub.unsubscribe()
                        pubsub.close()

    return sse_response(event_generator)


@tasks_bp.route("/worker-status", methods=["GET"])
@login_required
@api.validate(
    resp=Response(HTTP_200=WorkerStatusResponse),
    tags=["Tasks"],
    security=[{"cookieAuth": []}],
)
def get_worker_status() -> dict[str, Any]:
    """Get current worker cluster health status with specs."""
    return _get_worker_status_data()


@tasks_bp.route("/worker-status/live", methods=["GET"])
@login_required
@api.validate(resp=Response(HTTP_200=None), tags=["SSE Streaming"], security=[{"cookieAuth": []}])
def stream_worker_status() -> tuple[FlaskResponse, int, dict[str, str]]:
    """Stream worker cluster health status via SSE."""

    def event_generator():
        user_id = request.user["user_id"]
        with sse_connection_limit(user_id=user_id) as allowed:
            if not allowed:
                yield f"data: {json.dumps({'error': 'too many connections'})}\n\n"
                return

            res_data = _get_worker_status_data()
            yield f"data: {json.dumps(res_data)}\n\n"

            r = get_redis_client()
            pubsub = r.pubsub() if r else None
            if pubsub:
                pubsub.subscribe("worker_status_live")

            last_sent = time.time()
            start_time = time.time()
            try:
                while True:
                    if time.time() - start_time > SSE_IDLE_TIMEOUT:
                        yield f"data: {json.dumps({'event': 'timeout'})}\n\n"
                        break
                    got_message = False
                    if pubsub:
                        message = pubsub.get_message(ignore_subscribe_messages=True, timeout=5.0)
                        got_message = bool(message)
                    else:
                        time.sleep(5.0)
                    now = time.time()
                    if got_message or (now - last_sent) >= 10:
                        res_data = _get_worker_status_data()
                        yield f"data: {json.dumps(res_data)}\n\n"
                        last_sent = now
                    else:
                        yield ": keep-alive\n\n"
            except GeneratorExit:
                pass
            finally:
                if pubsub:
                    with contextlib.suppress(Exception):
                        pubsub.unsubscribe()
                        pubsub.close()

    return sse_response(event_generator)


def _get_worker_status_data() -> dict[str, Any]:

    def _compute():
        import json as json_lib

        from tasks import celery

        inspect = celery.control.inspect(timeout=1.0)
        pings = inspect.ping() or {}
        stats = inspect.stats() or {}
        registered = inspect.registered() or {}

        r = None
        try:
            from cache_utils import get_redis_client

            r = get_redis_client()
        except Exception as e:
            logger.warning("Failed to get Redis client for worker status: %s", e)
            r = None

        clusters = []
        for worker_name in pings:
            w_registered = registered.get(worker_name, []) if registered else []
            if "tasks.evaluate_submission" not in w_registered:
                continue

            spec = None
            if r:
                try:
                    spec_data = r.get(f"worker_spec:{worker_name}")
                    if spec_data:
                        spec = json_lib.loads(spec_data)
                except Exception as e:
                    logger.warning("Failed to retrieve worker spec for %s: %s", worker_name, e)

            if not spec:
                w_stats = stats.get(worker_name, {}) if stats else {}
                pool = w_stats.get("pool", {}) if w_stats else {}
                concurrency = pool.get("max-concurrency", 1) if pool else 1
                try:
                    concurrency = int(concurrency)
                except Exception:
                    concurrency = 1
                has_gpu = "gpu" in worker_name.lower()
                spec = {
                    "name": worker_name,
                    "type": "GPU" if has_gpu else "CPU",
                    "concurrency": concurrency,
                    "gpu_type": "NVIDIA GPU" if has_gpu else "N/A",
                    "ram_gb": 16.0 if has_gpu else 8.0,
                    "vram_gb": 8.0 if has_gpu else "N/A",
                }
            clusters.append(spec)

        is_online = len(clusters) > 0
        return {"status": "online" if is_online else "offline", "clusters": clusters}

    return cached_or_compute_unless_testing("worker:status:summary", _compute, timeout=10)


@tasks_bp.route("/worker/report/<uuid:submission_id>", methods=["POST"])
@rate_limit(max_requests=120, window_seconds=60, per_user=False)
@api.validate(
    resp=Response(
        HTTP_200=WorkerReportResponse,
        HTTP_400=ErrorResponse,
        HTTP_401=ErrorResponse,
        HTTP_404=ErrorResponse,
    ),
    tags=["Tasks"],
)
def report_worker_progress(
    submission_id: Any,
) -> tuple[dict[str, str], int] | tuple[FlaskResponse, int]:
    """Worker callback to report submission status and scores."""
    token = request.headers.get("X-Worker-Token")

    if not check_worker_auth(token):
        return err("ERR_UNAUTHORIZED", 401)

    if not request.is_json:
        return err("ERR_INVALID_REQUEST_BODY", 400)
    data = request.get_json()
    submission = Submission.query.filter_by(id=submission_id).with_for_update().first()
    if not submission:
        return err("ERR_NOT_FOUND", 404)

    if "status" in data:
        status_val = data["status"]
        if not isinstance(status_val, str) or status_val not in VALID_STATUSES:
            return err("ERR_INVALID_STATUS", 400, message=f"Invalid status value: {status_val}")
        submission.status = status_val
    if submission.executed_at is None:
        submission.executed_at = utcnow()
    if "detailed_status" in data:
        submission.detailed_status = data["detailed_status"]
    if "logs" in data:
        logs_val = data["logs"]
        if isinstance(logs_val, list):
            logs_val = "\n".join(str(line) for line in logs_val)
        if isinstance(logs_val, str) and len(logs_val.encode("utf-8")) > MAX_LOG_SIZE:
            logs_val = logs_val[: MAX_LOG_SIZE // 2]
        submission.logs = logs_val
    if "public_score" in data:
        val = data["public_score"]
        if val is not None and not isinstance(val, (int, float)):
            return err("ERR_INVALID_PUBLIC_SCORE", 400)
        submission.public_score = val
        submission.final_weighted_score_public = val
    if "private_score" in data:
        val = data["private_score"]
        if val is not None and not isinstance(val, (int, float)):
            return err("ERR_INVALID_PRIVATE_SCORE", 400)
        submission.private_score = val
        submission.final_weighted_score_private = val
    if "execution_time_ms" in data:
        submission.execution_time_ms = data["execution_time_ms"]
    if "metrics_payload_public" in data:
        submission.metrics_payload_public = data["metrics_payload_public"]
    elif "metrics_payload_pub" in data:
        submission.metrics_payload_public = data["metrics_payload_pub"]
    if "metrics_payload_private" in data:
        submission.metrics_payload_private = data["metrics_payload_private"]
    elif "metrics_payload_priv" in data:
        submission.metrics_payload_private = data["metrics_payload_priv"]
    if "gpu_node" in data:
        submission.gpu_node = data["gpu_node"]
    if "final_weighted_score_public" in data:
        submission.final_weighted_score_public = data["final_weighted_score_public"]
    if "final_weighted_score_private" in data:
        submission.final_weighted_score_private = data["final_weighted_score_private"]
    db.session.commit()

    publish_submissions_update(submission.task_id, submission.challenge_id)
    publish_queue_update()
    publish_leaderboard_update(submission.challenge_id)

    if submission.status in ("completed", "failed"):
        from sse_utils import publish_submission_status

        publish_submission_status(submission.id, submission.status)

        try:
            from cache_utils import invalidate_leaderboard_cache

            invalidate_leaderboard_cache(submission.challenge_id)
        except Exception:
            current_app.logger.exception("Failed to invalidate leaderboard cache in report route")

    return {"message": "Status updated successfully"}, 200


@tasks_bp.route("/worker/tasks/<uuid:task_id>/files/<string:filename>", methods=["GET"])
@rate_limit(max_requests=10, window_seconds=60, per_user=False)
@api.validate(resp=Response(HTTP_200=None, HTTP_403=ErrorResponse), tags=["Tasks"])
def worker_download_task_file(
    task_id: Any, filename: str
) -> tuple[bytes, int, dict[str, str]] | tuple[FlaskResponse, int]:
    """Worker endpoint to securely download task resource files."""
    token = request.headers.get("X-Worker-Token")

    if not check_worker_auth(token):
        return err("ERR_UNAUTHORIZED", 401)

    task = db.get_or_404(Task, task_id)
    try:
        files_meta = json.loads(task.files)
    except (json.JSONDecodeError, TypeError, ValueError):
        files_meta = []

    saved_name = None
    for f in files_meta:
        if f["filename"] == filename:
            saved_name = f["saved_name"]
            break

    if not saved_name:
        return err("ERR_FILE_NOT_FOUND", 404)

    if ".." in saved_name or "/" in saved_name or "\\" in saved_name:
        return err("ERR_INVALID_FILENAME", 400)

    task_upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], f"task_{task.id}")
    file_path = os.path.join(task_upload_dir, saved_name)
    safe_filename = sanitize_filename_part(filename)
    with open(file_path, "rb") as fh:
        file_bytes = fh.read()
    return (
        file_bytes,
        200,
        {
            "Content-Type": "application/octet-stream",
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
        },
    )


@tasks_bp.route("/worker/active-tasks", methods=["GET"])
@api.validate(
    resp=Response(HTTP_200=WorkerActiveTasksResponse, HTTP_401=ErrorResponse),
    tags=["Tasks"],
)
def get_active_tasks() -> tuple[WorkerActiveTasksResponse, int] | tuple[FlaskResponse, int]:
    """List all active task configurations for worker image pre-building."""
    token = request.headers.get("X-Worker-Token")

    if not check_worker_auth(token):
        return err("ERR_UNAUTHORIZED", 401)

    active_challenges = Challenge.query.filter_by(is_archived=False).all()
    tasks_list = []
    import json

    for challenge in active_challenges:
        for task in challenge.tasks:
            hf_datasets_list: list[str] = []
            if task.hf_datasets:
                with contextlib.suppress(Exception):
                    hf_datasets_list = (
                        json.loads(task.hf_datasets)
                        if isinstance(task.hf_datasets, str)
                        else (task.hf_datasets or [])
                    )
            hf_models_list: list[str] = []
            if task.hf_models:
                with contextlib.suppress(Exception):
                    hf_models_list = (
                        json.loads(task.hf_models)
                        if isinstance(task.hf_models, str)
                        else (task.hf_models or [])
                    )
            tasks_list.append(
                {
                    "id": task.id,
                    "base_docker_image": task.base_docker_image
                    or "pytorch/pytorch:2.6.0-cuda12.6-cudnn9-runtime",
                    "pip_requirements": task.pip_requirements or "",
                    "hf_datasets": hf_datasets_list,
                    "hf_models": hf_models_list,
                    "hf_api_key": task.get_hf_api_key() if task.hf_api_key else "",
                    "task_files": safe_json_loads(task.files, []),
                    "custom_eval_code": task.custom_eval_code or "",
                }
            )

    return {"tasks": tasks_list}, 200


@tasks_bp.route("/worker/active-datasets", methods=["GET"])
@api.validate(
    resp=Response(HTTP_200=WorkerActiveDatasetsResponse, HTTP_401=ErrorResponse),
    tags=["Tasks"],
)
def get_active_datasets() -> tuple[WorkerActiveDatasetsResponse, int] | tuple[FlaskResponse, int]:
    """List all HuggingFace datasets used by active challenges for worker preloading."""
    token = request.headers.get("X-Worker-Token")

    if not check_worker_auth(token):
        return err("ERR_UNAUTHORIZED", 401)

    active_challenges = Challenge.query.filter_by(is_archived=False).all()
    datasets_set = set()
    hf_api_key = None
    import json
    import re

    for challenge in active_challenges:
        for task in challenge.tasks:
            # Collect from task.hf_datasets field
            if task.hf_datasets:
                try:
                    hf_list = (
                        json.loads(task.hf_datasets)
                        if isinstance(task.hf_datasets, str)
                        else (task.hf_datasets or [])
                    )
                    for d in hf_list:
                        if isinstance(d, str) and d.strip():
                            datasets_set.add(d.strip())
                except (json.JSONDecodeError, TypeError, ValueError) as e:
                    logger.warning("Failed to parse hf_datasets for task %s: %s", task.id, e)

            # Extract from custom evaluation code
            eval_code = ""
            if task.custom_eval_code:
                eval_code = task.custom_eval_code
            elif task.evaluator_script_path and os.path.exists(task.evaluator_script_path):
                try:
                    with open(task.evaluator_script_path) as f:
                        eval_code = f.read()
                except (OSError, UnicodeDecodeError) as e:
                    logger.warning("Failed to read evaluator script for task %s: %s", task.id, e)
                    eval_code = ""

            if eval_code:
                matches = re.findall(
                    r'(?:datasets\.)?load_dataset\(\s*[\'"]([^\'"]+)[\'"]', eval_code
                )
                for m in matches:
                    datasets_set.add(m)

            # Grab first hf_api_key from any active task
            if hf_api_key is None and task.hf_api_key:
                try:
                    hf_api_key = task.get_hf_api_key()
                except Exception as e:
                    logger.warning("Failed to decrypt hf_api_key for task %s: %s", task.id, e)

    resp = {"datasets": list(datasets_set)}
    if hf_api_key:
        resp["hf_api_key"] = hf_api_key
    return resp, 200


@tasks_bp.route("/worker/tasks/<uuid:task_id>/hf-key", methods=["GET"])
@api.validate(
    resp=Response(HTTP_200=WorkerHfKeyResponse, HTTP_401=ErrorResponse, HTTP_404=ErrorResponse),
    tags=["Tasks"],
)
def get_task_hf_key(task_id: Any) -> tuple[WorkerHfKeyResponse, int] | tuple[FlaskResponse, int]:
    token = request.headers.get("X-Worker-Token")

    if not check_worker_auth(token):
        return err("ERR_UNAUTHORIZED", 401)
    task = db.session.get(Task, task_id)
    if not task:
        return err("ERR_TASK_NOT_FOUND", 404)
    hf_key = task.get_hf_api_key() or ""
    if not hf_key:
        logger.warning("No HF API key configured for task %s", task_id)
    return {"hf_key": hf_key}, 200


@tasks_bp.route("/worker/tasks/<uuid:task_id>/report-build-error", methods=["POST"])
@rate_limit(max_requests=30, window_seconds=60, per_user=False)
@api.validate(
    resp=Response(
        HTTP_200=MessageResponse,
        HTTP_400=ErrorResponse,
        HTTP_401=ErrorResponse,
        HTTP_404=ErrorResponse,
    ),
    tags=["Tasks"],
)
def report_build_error(
    task_id: Any,
) -> tuple[FlaskResponse, int] | tuple[dict[str, str], int]:
    token = request.headers.get("X-Worker-Token")
    if not check_worker_auth(token):
        return err("ERR_UNAUTHORIZED", 401)
    data = request.get_json(silent=True) or {}
    error_msg = (data.get("error") or "").strip()
    task = db.session.get(Task, task_id)
    if not task:
        return err("ERR_TASK_NOT_FOUND", 404)
    task.build_error = error_msg if error_msg else None
    db.session.commit()
    return {"message": "ok"}, 200


@tasks_bp.route("/workers/logs", methods=["POST"])
@rate_limit(max_requests=12, window_seconds=60, per_user=False)
@api.validate(
    resp=Response(
        HTTP_200=WorkerLogsResponse,
        HTTP_400=ErrorResponse,
        HTTP_401=ErrorResponse,
        HTTP_500=ErrorResponse,
    ),
    tags=["Tasks"],
)
def receive_worker_logs() -> tuple[WorkerLogsResponse, int] | tuple[FlaskResponse, int]:
    token = request.headers.get("X-Worker-Token")
    if not check_worker_auth(token):
        return err("ERR_UNAUTHORIZED", 401)

    body = request.get_data()
    if not body:
        return err("ERR_INVALID_REQUEST_BODY", 400)

    try:
        lines = gzip.decompress(body).decode()
    except Exception:
        return err("ERR_INVALID_REQUEST_BODY", 400)

    log_dir = os.environ.get("LOG_DIR", "/app/logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "worker_remote.log")
    try:
        with open(log_path, "a") as f:
            f.write(lines if lines.endswith("\n") else lines + "\n")
    except OSError as e:
        logger.error("Failed to write worker logs: %s", e)
        return err("ERR_INTERNAL_SERVER_ERROR", 500)
    return {"status": "ok"}, 200
