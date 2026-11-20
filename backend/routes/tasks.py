"""Route handlers for the tasks blueprint."""

from __future__ import annotations

import contextlib
import gzip
import io
import json
import logging
import math
import os
import shutil
import uuid
from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Any

from flask import Blueprint, current_app, request
from flask import Response as FlaskResponse
from spectree import Response
from sqlalchemy import func
from sqlalchemy import inspect as sa_inspect
from werkzeug.utils import secure_filename

from config import Config
from models import Challenge, Stage, Submission, Task, db
from models.submission import (
    ORIGIN_CELLS,
    ORIGIN_EMERGENCY_UPLOAD,
    ORIGIN_WORKSPACE,
    remove_submission_files,
)
from schemas.responses import (
    ErrorResponse,
    MessageResponse,
    ParseNotebookResponse,
    SubmitResponse,
    TaskAdminResponse,
    TaskSubmissionsResponse,
    WorkerActiveTasksResponse,
    WorkerLogsResponse,
    WorkerReportResponse,
    WorkerRunContentResponse,
)
from schemas.submission import SelectedCellsSchema
from schemas.task import CreateTaskMetaSchema, EmergencyUploadSchema, UpdateTaskMetaSchema
from services import contest_rules, environment_service, hf_zip
from services.audit_service import log_action
from services.baseline_service import apply_baseline_outcome, schedule_baseline, set_problems
from services.environment_package import (
    SOLUTION_NOTEBOOK,
    SUBMISSION_PARQUET,
    PackageError,
    check_projected,
)
from services.evaluator_script import parse_evaluator_script
from services.file_submission import (
    ParquetRules,
    SubmissionFiles,
    baseline_unreadable,
    check_baseline_parquet,
    check_submission_parquet,
    incoming_dir,
    labels_sha256,
    notebook_problem,
    parquet_rules,
    prune_label_cache,
    read_notebook,
    task_file_path,
)
from services.submission_service import (
    create_submission,
    extract_code_from_cells,
    file_precheck,
    submission_gate,
)
from services.submission_status import (
    ACTIVE_STATUSES,
    BUILDING_ENV,
    COMPLETED,
    FAILED,
    FAILURE_DETAILS,
    KILLED,
    QUEUED,
    RUNNING,
    RUNNING_INFERENCE,
    STATUSES,
    TERMINAL_STATUSES,
    is_allowed,
    transition,
)
from services.task_data import owner_lock, remove_unreferenced_hf_zip
from services.task_locks import mode_locked
from utils.access import competitor_submissions_locked, ensure_registered
from utils.audit import log_audit
from utils.auth_utils import (
    jury_access_required,
    login_required,
    rate_limit,
    role_required,
)
from utils.cache import invalidate_entity_cache
from utils.cache_utils import (
    LockUnavailableError,
    get_coordination_client,
    record_attempt_claimed,
    renewing_lock,
)
from utils.dates import utcnow
from utils.error_utils import err, format_size, service_busy, with_retry_after
from utils.files import (
    BASELINE_SUBMISSION_FILE,
    copy_with_digest,
    task_file_visibility,
    unique_saved_name,
)
from utils.ipynb import notebook_cells, sanitize_filename_part
from utils.json_utils import safe_json_loads
from utils.request_helpers import release_db_before_body
from utils.spec import api
from utils.sse_utils import publish_queue_update
from utils.streaming import stream_file_response
from utils.text import task_folder_name
from utils.uploads import busy, store_lock
from utils.worker_auth import (
    build_submission_capabilities,
    check_worker_auth,
    signed_worker_id,
    verify_worker_capability,
)

tasks_bp = Blueprint("tasks", __name__)

ErrorResult = tuple[FlaskResponse, int]

logger = logging.getLogger(__name__)


def _notebook_save_path(task_upload_dir: str, role: str, original_name: str) -> str:
    """Keep the public notebook filename while isolating each stored version."""
    directory = os.path.join(task_upload_dir, f"{role}-{uuid.uuid4().hex}")
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, secure_filename(original_name) or "notebook.ipynb")


SMALL_FILE_FIELDS = ("baseline_notebook", "solution_notebook", "evaluator_script")


def _form_files_refused() -> ErrorResult | None:
    """Data files stream through ``PUT /tasks/<id>/files/<name>``; the form takes only the
    notebooks and the evaluator, each within ``MAX_NOTEBOOK_BYTES``."""
    if any(key.startswith(("file", "hidden_file")) for key in request.files):
        return err("ERR_INVALID_UPLOAD_FORMAT", 400)
    limit = Config.MAX_NOTEBOOK_BYTES
    for field in SMALL_FILE_FIELDS:
        upload = request.files.get(field)
        if not upload or not upload.filename:
            continue
        upload.stream.seek(0, os.SEEK_END)
        size = upload.stream.tell()
        upload.stream.seek(0)
        if size > limit:
            return err(
                "ERR_FILE_TOO_LARGE",
                413,
                message=f"{upload.filename} exceeds the {format_size(limit)} limit.",
                limit=format_size(limit),
                field=field,
            )
    return None


def _worker_token_identity() -> str:
    """Rate-limit key: the signed worker id, so workers behind one NAT have separate limits."""
    worker_id = signed_worker_id(request.headers.get("X-Worker-Token"))
    if worker_id:
        return f"worker:{worker_id}"
    return request.remote_addr or "unknown"


def _worker_capability(
    operation: str,
    resource_type: str,
    resource_id: Any,
    *,
    attempt_id: str | None = None,
    identity: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Authenticate a worker request and verify its exact operation scope."""
    identity = identity or check_worker_auth(request.headers.get("X-Worker-Token"))
    if not identity or not identity.get("worker_id"):
        return None
    claims = verify_worker_capability(
        request.headers.get("X-Worker-Capability"),
        worker_id=identity["worker_id"],
        method=request.method,
        operation=operation,
        resource_type=resource_type,
        resource_id=resource_id,
        attempt_id=attempt_id,
    )
    if not claims:
        return None
    coordination = get_coordination_client()
    if coordination is None:
        return None
    binding_key = f"worker:attempt:{claims['attempt_id']}"
    try:
        bound_worker = coordination.get(binding_key)
        if isinstance(bound_worker, bytes):
            bound_worker = bound_worker.decode()
        if bound_worker != identity["worker_id"]:
            return None
        coordination.expire(binding_key, Config.WORKER_ATTEMPT_LEASE_TTL)
    except Exception:
        logger.exception("Failed to verify worker attempt binding")
        return None
    return claims


def _task_capability(operation: str, task_id: Any) -> dict[str, Any] | None:
    """Verify a task capability is tied to a live submission attempt for that task."""
    claims = _worker_capability(operation, "task", task_id)
    if not claims:
        return None
    submission = Submission.query.filter_by(celery_task_id=claims.get("attempt_id")).first()
    if not submission or str(submission.task_id) != str(task_id):
        return None
    if submission.status not in ACTIVE_STATUSES:
        return None
    return claims


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


# ── TASK CRUD ──
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
@release_db_before_body
@api.validate(
    form=CreateTaskMetaSchema,
    resp=Response(
        HTTP_201=TaskAdminResponse,
        HTTP_400=ErrorResponse,
        HTTP_403=ErrorResponse,
        HTTP_409=ErrorResponse,
        HTTP_422=ErrorResponse,
    ),
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
    file_mode = form.evaluation_mode == "file"

    # A file task's baseline is its hidden baseline_submission.parquet, checked once saved
    if not file_mode and (
        "baseline_notebook" not in request.files
        or request.files["baseline_notebook"].filename == ""
    ):
        return err("ERR_BASELINE_REQUIRED", 400)
    refused = _form_files_refused()
    if refused:
        return refused

    ram_limit_mb = form.ram_limit_mb
    time_limit_sec = form.time_limit_sec
    gpu_required = form.gpu_required

    base_docker_image = form.base_docker_image
    apt_packages = form.apt_packages
    pip_requirements = form.pip_requirements

    if request.user.get("role") != "admin" and (
        base_docker_image or apt_packages or pip_requirements
    ):
        return err("ERR_FORBIDDEN", 403)

    ban_magic_commands = form.ban_magic_commands
    banned_imports = form.banned_imports
    whitelisted_imports = form.whitelisted_imports

    evaluator_code = None
    evaluator_metric_name = None
    if "evaluator_script" in request.files:
        f = request.files["evaluator_script"]
        if f and f.filename != "":
            try:
                evaluator_code = f.read().decode("utf-8")
            except UnicodeDecodeError:
                return err("ERR_EVALUATOR_SCRIPT_INVALID", 400)
            f.seek(0)
            eval_result, eval_err = parse_evaluator_script(evaluator_code)
            if eval_result is None:
                return err("ERR_EVALUATOR_SCRIPT_INVALID", 400, message=eval_err)
            evaluator_metric_name = eval_result["metric_name"]

    metrics_config = form.metrics_config
    refused = _unknown_metric_refusal(metrics_config, evaluator_metric_name)
    if refused:
        return refused

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
            return err("ERR_STAGE_REQUIRED", 400)

    locked = environment_service.task_files_locked(challenge, [stage_id])
    if locked:
        return locked
    if form.folder_name:
        if environment_service.folder_name_taken(challenge_id, stage_id, form.folder_name):
            return err("ERR_TASK_FOLDER_TAKEN", 409)
        folder_name = form.folder_name
    else:
        folder_name = environment_service.unique_folder_name(
            challenge_id, stage_id, task_folder_name(title)
        )

    task = Task(
        challenge_id=challenge_id,
        stage_id=stage_id,
        title=title,
        evaluation_mode=form.evaluation_mode,
        folder_name=folder_name,
        folder_name_custom=bool(form.folder_name),
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
        public_eval_percentage=public_eval_percentage,
        max_submissions_per_period=max_submissions_per_period,
        submission_period_hours=submission_period_hours,
        files="[]",
    )

    db.session.add(task)
    db.session.commit()

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
            task.evaluator_metric_name = evaluator_metric_name

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
            save_path = _notebook_save_path(task_upload_dir, "baseline", f.filename)
            f.save(save_path)
            task.baseline_notebook_path = save_path
            task.baseline_notebook_size = os.path.getsize(save_path)

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
            save_path = _notebook_save_path(task_upload_dir, "solution", f.filename)
            f.save(save_path)
            task.solution_notebook_path = save_path
            task.solution_notebook_size = os.path.getsize(save_path)

    db.session.commit()

    # Parse code cells from notebooks and queue baseline submission
    admin_id = request.user["user_id"]
    schedule_baseline(task, admin_id)

    log_audit(
        request.user["user_id"],
        "create",
        "task",
        target_id=task.id,
        details={"title": task.title, "challenge_id": challenge_id},
    )
    db.session.commit()

    invalidate_entity_cache(challenge_id)

    return task.to_dict(view_role=request.user["role"]), 201


def _changes_public_files(form: UpdateTaskMetaSchema) -> bool:
    """The starter notebook ships as ``solution.ipynb``; data files have their own route."""
    baseline = request.files.get("baseline_notebook")
    return bool(form.delete_baseline) or bool(baseline and baseline.filename)


def _changes_hidden_files(task: Task, form: UpdateTaskMetaSchema) -> bool:
    """The evaluator: what an admin may still fix after publish."""
    evaluator = request.files.get("evaluator_script")
    return bool(form.delete_evaluator and task.evaluator_script_path) or bool(
        evaluator and evaluator.filename
    )


def _target_stage(task: Task, form: UpdateTaskMetaSchema, fields: set[str]) -> Any:
    return (form.stage_id or None) if "stage_id" in fields else task.stage_id


def _moved(task: Task, target_stage: Any) -> bool:
    return str(target_stage or "") != str(task.stage_id or "")


def _planned_folder(task: Task, form: UpdateTaskMetaSchema, fields: set[str]) -> tuple[str, bool]:
    """The folder after this update: set by hand, or following the title until publish."""
    if environment_service.folder_locked(task):
        return task.folder_name, task.folder_name_custom
    if "folder_name" in fields and form.folder_name:
        return form.folder_name, True
    if task.folder_name_custom and "folder_name" not in fields:
        return task.folder_name, True
    title = form.title if "title" in fields and form.title else task.title
    folder = environment_service.unique_folder_name(
        task.challenge_id,
        _target_stage(task, form, fields),
        task_folder_name(title),
        exclude_task_id=task.id,
    )
    return folder, False


def _hidden_fix_after_publish(task: Task, form: UpdateTaskMetaSchema) -> bool:
    published = environment_service.task_files_locked(task.challenge, [task.stage_id]) is not None
    return published and _changes_hidden_files(task, form)


def _check_baseline(task: Task) -> ErrorResult | None:
    """A file task's stored baseline Parquet against the current labels and columns."""
    if task_file_path(task, BASELINE_SUBMISSION_FILE) is None:
        return None
    try:
        return check_baseline_parquet(task)
    except Exception:
        logger.exception("Checking the baseline of task %s failed", task.id)
        db.session.rollback()
        return baseline_unreadable()


def _environment_change_blocked(
    task: Task, form: UpdateTaskMetaSchema, fields: set[str]
) -> tuple[FlaskResponse, int] | None:
    """Refuse changes to what a published environment shipped, and folder clashes."""
    target_stage = _target_stage(task, form, fields)
    moved = _moved(task, target_stage)
    if moved or _changes_public_files(form):
        locked = environment_service.task_files_locked(
            task.challenge, [task.stage_id, target_stage]
        )
        if locked:
            return locked
    if _hidden_fix_after_publish(task, form):
        if request.user.get("role") != "admin":
            return err("ERR_FORBIDDEN", 403)
        if not (form.reason or "").strip():
            return err("ERR_REASON_REQUIRED", 400)
    explicit = "folder_name" in fields and form.folder_name not in (None, task.folder_name)
    locked = environment_service.folder_locked(task) if explicit else None
    if locked:
        return locked
    folder, custom = _planned_folder(task, form, fields)
    if (
        custom
        and (moved or folder != task.folder_name)
        and environment_service.folder_name_taken(
            task.challenge_id, target_stage, folder, exclude_task_id=task.id
        )
    ):
        return err("ERR_TASK_FOLDER_TAKEN", 409)
    if moved and environment_service.environments_on(task.challenge):
        return _projected_after_move(task, target_stage)
    return None


def _projected_after_move(task: Task, target_stage: Any) -> tuple[FlaskResponse, int] | None:
    """The target owner's package caps and HF conflicts with the task moved in; the caller
    holds the target owner's lock until the move commits."""
    stage = db.session.get(Stage, target_stage) if target_stage else None
    owner = environment_service.Owner(challenge=task.challenge, stage=stage)
    tasks = [each for each in owner.tasks() if str(each.id) != str(task.id)] + [task]
    try:
        check_projected(tasks, task)
    except PackageError as exc:
        if exc.code in ("ERR_ENVIRONMENT_PACKAGE_TOO_LARGE", "ERR_HF_FOLDER_CONFLICT"):
            return environment_service.package_error(exc)
    return None


@tasks_bp.route("/tasks/<uuid:task_id>", methods=["PUT"])
@role_required(["admin", "jury"])
@jury_access_required
@release_db_before_body
@api.validate(
    form=UpdateTaskMetaSchema,
    resp=Response(
        HTTP_200=TaskAdminResponse,
        HTTP_400=ErrorResponse,
        HTTP_403=ErrorResponse,
        HTTP_409=ErrorResponse,
        HTTP_422=ErrorResponse,
    ),
    tags=["Tasks"],
    security=[{"cookieAuth": []}],
)
def update_task(
    task_id: Any, form: UpdateTaskMetaSchema
) -> dict[str, Any] | tuple[FlaskResponse, int]:
    """Update an existing task configuration including files and evaluator scripts."""
    task = db.get_or_404(Task, task_id)
    target_stage = _target_stage(task, form, form.model_fields_set)
    with contextlib.ExitStack() as move_lock:
        if _moved(task, target_stage) and environment_service.environments_on(task.challenge):
            # Held from the projected checks to the commit, so two moves cannot both pass
            if not move_lock.enter_context(store_lock(owner_lock(task, target_stage or ""))):
                return busy()
            db.session.expire_all()
        return _update_task(task, form, after_commit=move_lock.close)


def _unknown_metric_refusal(
    metrics_config: Any, evaluator_metric_name: str | None
) -> tuple[FlaskResponse, int] | None:
    """Refuse a metric that is neither built in nor the one the task's evaluator returns."""
    from services.evaluation import AVAILABLE_METRICS

    if isinstance(metrics_config, str):
        metrics_config = safe_json_loads(metrics_config, {})
    allowed_metrics = list(AVAILABLE_METRICS.keys())
    for metric_name in metrics_config or {}:
        if metric_name in ("_columns", evaluator_metric_name):
            continue
        if metric_name not in allowed_metrics:
            return err(
                "ERR_INVALID_METRIC_NAME",
                400,
                message=f"Invalid metric '{metric_name}'. Allowed metrics: {allowed_metrics}",
            )
    return None


def _update_task(
    task: Task, form: UpdateTaskMetaSchema, *, after_commit: Callable[[], None]
) -> dict[str, Any] | tuple[FlaskResponse, int]:
    fields = form.model_fields_set
    before_update = {attr.key: getattr(task, attr.key) for attr in sa_inspect(Task).column_attrs}

    # Snapshot semantic inputs so we can decide whether the rebuild/baseline
    # actually needs to run (title changes must not rebuild the image)
    semantic_before = {
        "base_docker_image": task.base_docker_image,
        "apt_packages": task.apt_packages,
        "pip_requirements": task.pip_requirements,
        "custom_eval_code": task.custom_eval_code,
        "baseline_notebook_path": task.baseline_notebook_path,
        "evaluation_mode": task.evaluation_mode,
    }

    if request.user.get("role") != "admin":
        for field in ["base_docker_image", "apt_packages", "pip_requirements"]:
            if field in fields:
                val = getattr(form, field)
                current_val = getattr(task, field)
                if (val or "").strip() != (current_val or "").strip():
                    return err("ERR_FORBIDDEN", 403)

    mode_changes = bool(form.evaluation_mode) and form.evaluation_mode != task.evaluation_mode
    if mode_changes and mode_locked(task):
        return err("ERR_TASK_MODE_LOCKED", 409)
    refused = _form_files_refused()
    if refused:
        return refused
    blocked = _environment_change_blocked(task, form, fields)
    if blocked:
        return blocked
    hidden_fix = _hidden_fix_after_publish(task, form)

    update_savepoint = db.session.begin_nested()

    if "title" in fields:
        task.title = form.title
    if mode_changes:
        task.evaluation_mode = form.evaluation_mode
    task.folder_name, task.folder_name_custom = _planned_folder(task, form, fields)
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

    # NOTE: build-family problem codes are NOT cleared here. The gate stays
    # closed until the worker reports a successful rebuild (report-build-error
    # with empty error), so a broken env cannot silently re-open submissions

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
                update_savepoint.rollback()
                return err("ERR_CANNOT_MOVE_FINALIZED", 400)
            if old_stage.end_time and old_stage.end_time <= utcnow():
                update_savepoint.rollback()
                return err("ERR_CANNOT_MOVE_ENDED", 400)

        if stage_id_val is not None and stage_id_val != task.stage_id:
            from models import User as _TaskUser

            task_id_str = str(task.id)
            has_manual_points = False
            for u in _TaskUser.query.filter_by(challenge_id=task.challenge_id).all():
                manual_pts = safe_json_loads(u.manual_points, {})
                if task_id_str in manual_pts:
                    has_manual_points = True
                    break
            if has_manual_points:
                update_savepoint.rollback()
                return err("ERR_CANNOT_MOVE_HAS_MANUAL_POINTS", 400)

        if stage_id_val:
            st = Stage.query.filter_by(id=stage_id_val, challenge_id=task.challenge_id).first()
            if not st:
                update_savepoint.rollback()
                return err("ERR_INVALID_STAGE_ID", 400)
            task.stage_id = stage_id_val
        else:
            regular_stage_count = Stage.query.filter_by(
                challenge_id=task.challenge_id, is_test=False
            ).count()
            if regular_stage_count > 0:
                update_savepoint.rollback()
                return err("ERR_STAGE_REQUIRED", 400)
            task.stage_id = None

    task_upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], f"task_{task.id}")
    os.makedirs(task_upload_dir, exist_ok=True)
    newly_saved_paths: list[str] = []
    replaced_paths: list[str] = []

    def discard_uploads() -> None:
        for path in newly_saved_paths:
            with contextlib.suppress(OSError):
                os.remove(path)
            if os.path.dirname(path) != task_upload_dir:
                with contextlib.suppress(OSError):
                    os.rmdir(os.path.dirname(path))
        update_savepoint.rollback()

    if "evaluator_script" in request.files:
        f = request.files["evaluator_script"]
        if f and f.filename != "":
            try:
                code = f.read().decode("utf-8")
            except UnicodeDecodeError:
                discard_uploads()
                return err("ERR_EVALUATOR_SCRIPT_INVALID", 400)
            f.seek(0)
            eval_result, eval_err = parse_evaluator_script(code)
            if eval_result is None:
                discard_uploads()
                return err("ERR_EVALUATOR_SCRIPT_INVALID", 400, message=eval_err)
            save_path = os.path.join(task_upload_dir, unique_saved_name("evaluator.py"))
            f.save(save_path)
            newly_saved_paths.append(save_path)
            if task.evaluator_script_path:
                replaced_paths.append(task.evaluator_script_path)
            task.evaluator_script_path = save_path
            task.custom_eval_code = code
            task.evaluator_metric_name = eval_result["metric_name"]

    if "baseline_notebook" in request.files:
        f = request.files["baseline_notebook"]
        if f and f.filename != "":
            from services.file_validation import validate_extension

            valid_ext, ext_err = validate_extension(f.filename, {".ipynb"})
            if not valid_ext:
                discard_uploads()
                return err("ERR_INVALID_FILE_TYPE", 400, message=ext_err)
            save_path = _notebook_save_path(task_upload_dir, "baseline", f.filename)
            f.save(save_path)
            newly_saved_paths.append(save_path)
            if task.baseline_notebook_path:
                replaced_paths.append(task.baseline_notebook_path)
            task.baseline_notebook_path = save_path
            task.baseline_notebook_size = os.path.getsize(save_path)

    if "solution_notebook" in request.files:
        f = request.files["solution_notebook"]
        if f and f.filename != "":
            from services.file_validation import validate_extension

            valid_ext, ext_err = validate_extension(f.filename, {".ipynb"})
            if not valid_ext:
                discard_uploads()
                return err("ERR_INVALID_FILE_TYPE", 400, message=ext_err)
            save_path = _notebook_save_path(task_upload_dir, "solution", f.filename)
            f.save(save_path)
            newly_saved_paths.append(save_path)
            if task.solution_notebook_path:
                replaced_paths.append(task.solution_notebook_path)
            task.solution_notebook_path = save_path
            task.solution_notebook_size = os.path.getsize(save_path)

    if form.delete_evaluator and task.evaluator_script_path:
        replaced_paths.append(task.evaluator_script_path)
        task.evaluator_script_path = None
        task.custom_eval_code = None
        task.evaluator_metric_name = None
    if form.delete_baseline and task.baseline_notebook_path:
        replaced_paths.append(task.baseline_notebook_path)
        task.baseline_notebook_path = None
        task.baseline_notebook_size = None

    scoring_inputs_changed = (
        mode_changes
        or task.custom_eval_code != semantic_before["custom_eval_code"]
        or "metrics_config" in fields
    )
    if scoring_inputs_changed:
        refused = _unknown_metric_refusal(task.metrics_config, task.evaluator_metric_name)
        if refused:
            discard_uploads()
            return refused
    try:
        update_savepoint.commit()
        db.session.commit()
    except Exception:
        for path in newly_saved_paths:
            with contextlib.suppress(OSError):
                os.remove(path)
            if os.path.dirname(path) != task_upload_dir:
                with contextlib.suppress(OSError):
                    os.rmdir(os.path.dirname(path))
        db.session.rollback()
        raise
    after_commit()

    # Checked after the commit, so no transaction is held; the replaced files still exist
    invalid = _check_baseline(task) if task.is_file_mode and scoring_inputs_changed else None
    if invalid:
        for key, value in before_update.items():
            setattr(task, key, value)
        db.session.commit()
        for path in newly_saved_paths:
            with contextlib.suppress(OSError):
                os.remove(path)
            if os.path.dirname(path) != task_upload_dir:
                with contextlib.suppress(OSError):
                    os.rmdir(os.path.dirname(path))
        return invalid

    referenced_paths = {
        path
        for path in (
            task.evaluator_script_path,
            task.baseline_notebook_path,
            task.solution_notebook_path,
        )
        if path
    }
    for old_path in replaced_paths:
        if old_path not in referenced_paths:
            with contextlib.suppress(OSError):
                os.remove(old_path)
            if os.path.dirname(old_path).startswith(f"{task_upload_dir}{os.sep}"):
                with contextlib.suppress(OSError):
                    os.rmdir(os.path.dirname(old_path))

    log_action(
        admin_id=request.user["user_id"],
        action_type="update",
        target_type="task",
        target_id=task.id,
        details={
            "title": task.title,
            "challenge_id": str(task.challenge_id),
            "hidden_files_after_publish": hidden_fix,
        },
        reason=(form.reason or "").strip() or None,
    )
    db.session.commit()

    invalidate_entity_cache(task.challenge_id)

    # Only recompute the baseline and notify workers to rebuild when the
    # image-affecting (semantic) or scoring inputs actually changed — title,
    # description, periods, limits etc. must not churn images or baselines.
    semantic_now = {
        "base_docker_image": task.base_docker_image,
        "apt_packages": task.apt_packages,
        "pip_requirements": task.pip_requirements,
        "custom_eval_code": task.custom_eval_code,
        "baseline_notebook_path": task.baseline_notebook_path,
        "evaluation_mode": task.evaluation_mode,
    }
    semantic_changed = any(semantic_before[k] != semantic_now[k] for k in semantic_before)
    scoring_fields = {
        "metrics_config",
        "public_eval_percentage",
        "ram_limit_mb",
        "time_limit_sec",
        "gpu_required",
        "ban_magic_commands",
        "banned_imports",
        "whitelisted_imports",
    }

    if semantic_changed or (fields & scoring_fields):
        schedule_baseline(task, request.user["user_id"])

    return task.to_dict(view_role=request.user["role"])


@tasks_bp.route("/tasks/<uuid:task_id>", methods=["DELETE"])
@role_required(["admin", "jury"])
@jury_access_required
@api.validate(
    resp=Response(HTTP_200=MessageResponse, HTTP_409=ErrorResponse),
    tags=["Tasks"],
    security=[{"cookieAuth": []}],
)
def delete_task(task_id: Any) -> MessageResponse | tuple[FlaskResponse, int]:
    """Remove a task and all its submissions from a challenge."""
    task = db.get_or_404(Task, task_id)
    locked = environment_service.task_files_locked(task.challenge, [task.stage_id])
    if locked:
        return locked
    challenge_id = task.challenge_id
    task_upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], f"task_{task.id}")
    # Collect file paths before bulk delete for cleanup
    subs = Submission.query.filter_by(task_id=task_id).all()
    from tasks import celery

    for s in subs:
        if s.celery_task_id:
            with contextlib.suppress(Exception):
                celery.control.revoke(s.celery_task_id, terminate=True)
    paths = [(s.code_storage_path, s.log_storage_path) for s in subs]
    sub_ids = [s.id for s in subs]
    task_files = task.files
    hf_sha256 = task.hf_zip_sha256
    Submission.query.filter_by(task_id=task_id).delete(synchronize_session=False)
    db.session.delete(task)
    db.session.commit()

    # Remove on-disk files only after the transaction succeeded — a failed
    # commit (e.g. FK constraint) must never leave a half-deleted task behind.
    import shutil

    shutil.rmtree(task_upload_dir, ignore_errors=True)
    for code_path, log_path in paths:
        if code_path and os.path.exists(code_path):
            with contextlib.suppress(OSError):
                os.remove(code_path)
        if log_path and os.path.exists(log_path):
            with contextlib.suppress(OSError):
                os.remove(log_path)
    # A bulk delete skips the after_delete hook that removes each submission's own files
    for sub_id in sub_ids:
        remove_submission_files(sub_id)
    prune_label_cache(labels_sha256(task_files))
    if hf_sha256:
        remove_unreferenced_hf_zip(hf_sha256)

    log_audit(
        request.user["user_id"],
        "delete",
        "task",
        target_id=task.id,
        details={"title": task.title, "challenge_id": challenge_id},
    )
    db.session.commit()

    invalidate_entity_cache(challenge_id)

    return MessageResponse(message=f"Task '{task.title}' has been deleted successfully.")


# ── DOWNLOAD FILE ──
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
) -> (
    FlaskResponse
    | tuple[Generator[bytes, None, None], int, dict[str, str]]
    | tuple[FlaskResponse, int]
):
    """Download a resource file attached to a task."""
    task = db.get_or_404(Task, task_id)
    user_role = request.user["role"]
    user_id = request.user["user_id"]

    if user_role == "competitor":
        entries = [f for f in safe_json_loads(task.files, []) if f.get("filename") == filename]
        hidden = filename == "labels.parquet" or any(
            task_file_visibility(f) == "hidden" for f in entries
        )
        if hidden:
            return err("ERR_ACCESS_DENIED", 403)
        if not check_task_started(task, user_role, user_id):
            return err("ERR_NOT_AVAILABLE", 403)

    # Assigned jury members and admins read hidden files at any time (plan J4 a)
    try:
        files_meta = json.loads(task.files)
    except json.JSONDecodeError:
        files_meta = []

    entry = next((f for f in files_meta if f["filename"] == filename), None)
    saved_name = entry["saved_name"] if entry else None

    if entry and saved_name:
        task_upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], f"task_{task.id}")
        file_path = os.path.join(task_upload_dir, saved_name)
        if not os.path.isfile(file_path):
            return err("ERR_NOT_FOUND", 404)
        # Stream from disk (files can be up to 500 MB — never buffer in RAM)
        safe_filename = sanitize_filename_part(filename)
        return stream_file_response(
            file_path, "application/octet-stream", safe_filename, sha256=entry.get("sha256")
        )

    if task.baseline_notebook_path:
        baseline_basename = os.path.basename(task.baseline_notebook_path)
        if filename == baseline_basename:
            if not os.path.isfile(task.baseline_notebook_path):
                return err("ERR_NOT_FOUND", 404)
            safe_filename = sanitize_filename_part(filename)
            return stream_file_response(
                task.baseline_notebook_path, "application/octet-stream", safe_filename
            )

    return err("ERR_FILE_NOT_FOUND", 404)


# ── TASK SUBMISSIONS & EVALUATIONS ──
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
    task = db.get_or_404(Task, task_id)
    result = create_submission(
        task,
        task.challenge,
        request.user["user_id"],
        request.user["role"],
        json.selected_cells,
        origin=ORIGIN_CELLS,
    )
    if isinstance(result, tuple):
        return result
    submission = result

    return SubmitResponse(
        message="Submission received and queued for execution.",
        submission_id=submission.id,
        status=submission.status,
    ), 202


# Renewed while the request works, so a crashed worker frees it within a minute
FILE_SUBMIT_LOCK_TTL = 60
FILE_SUBMIT_RETRY_SECONDS = 10


def _file_submit_lock(task: Task) -> str:
    """One file submission at a time per user and task; other tasks are not blocked."""
    return f"file_submit:user_{request.user['user_id']}:task_{task.id}"


def _busy_lock() -> ErrorResult:
    return with_retry_after(err("ERR_SUBMIT_LOCKED", 429), FILE_SUBMIT_RETRY_SECONDS)


def _precheck(task: Task, sha256: str) -> ErrorResult | None:
    """Quota and duplicate from the hash, then end the transaction before the slow steps."""
    refused = file_precheck(
        task, task.challenge, request.user["user_id"], request.user["role"], sha256
    )
    db.session.commit()
    return refused


def _submit_files(
    task_id: Any, files: SubmissionFiles, rules: ParquetRules, origin: str
) -> tuple[SubmitResponse, int] | ErrorResult:
    """Check the content with no transaction open, then queue through the one submission path."""
    invalid = check_submission_parquet(files.artifact_path, rules)
    if invalid:
        return invalid
    problem = notebook_problem(str(files.notebook_path))
    if problem:
        return err("ERR_PARSING_FAILED", 400, message=f"Invalid notebook file: {problem}")
    task = db.get_or_404(Task, task_id)
    result = create_submission(
        task,
        task.challenge,
        request.user["user_id"],
        request.user["role"],
        [],
        files=files,
        origin=origin,
    )
    if isinstance(result, tuple):
        return result
    return SubmitResponse(
        message="Submission received and queued for scoring.",
        submission_id=result.id,
        status=result.status,
    ), 202


def _file_task_gate(task: Task) -> ErrorResult | None:
    if not task.is_file_mode:
        return err("ERR_TASK_MODE_MISMATCH", 409)
    return submission_gate(task, task.challenge, request.user["user_id"], request.user["role"])


_SUBMIT_FILE_ERRORS = {
    f"HTTP_{code}": ErrorResponse for code in (400, 403, 404, 409, 410, 413, 422, 429, 502, 503)
}


@tasks_bp.route("/tasks/<uuid:task_id>/workspace-notebook", methods=["POST"])
@login_required
@jury_access_required
@rate_limit(max_requests=10, window_seconds=60)
@api.validate(
    resp=Response(HTTP_200=ParseNotebookResponse, **_SUBMIT_FILE_ERRORS),
    tags=["Tasks"],
    security=[{"cookieAuth": []}],
)
def load_workspace_notebook(task_id: Any) -> ParseNotebookResponse | ErrorResult:
    """Read solution.ipynb from the student's workspace into the cell picker."""
    task = db.get_or_404(Task, task_id)
    if task.is_file_mode:
        return err("ERR_TASK_MODE_MISMATCH", 409)
    if not check_task_started(task, request.user["role"], request.user["user_id"]):
        return err("ERR_NOT_AVAILABLE", 403)
    source = environment_service.workspace_source(task, request.user["user_id"])
    if not isinstance(source, environment_service.WorkspaceSource):
        return source
    db.session.commit()
    meta = environment_service.export_metadata(source, SOLUTION_NOTEBOOK)
    if not isinstance(meta, environment_service.ExportMeta):
        return meta
    directory = incoming_dir()
    try:
        fetched = environment_service.fetch_exports(source, [meta], directory)
        if not isinstance(fetched, list):
            return fetched
        environment_service.audit_exports(source, fetched)
        problem, notebook = read_notebook(fetched[0].path)
    finally:
        shutil.rmtree(directory, ignore_errors=True)
    if notebook is None:
        return err("ERR_PARSING_FAILED", 400, message=f"Invalid notebook file: {problem}")
    return ParseNotebookResponse(filename=SOLUTION_NOTEBOOK, cells=notebook_cells(notebook))


@tasks_bp.route("/tasks/<uuid:task_id>/submit-workspace", methods=["POST"])
@login_required
@jury_access_required
@rate_limit(max_requests=10, window_seconds=60)
@api.validate(
    resp=Response(HTTP_202=SubmitResponse, **_SUBMIT_FILE_ERRORS),
    tags=["Tasks"],
    security=[{"cookieAuth": []}],
)
def submit_workspace(task_id: Any) -> tuple[SubmitResponse, int] | ErrorResult:
    """Submit submission.parquet and solution.ipynb from the task folder of the workspace."""
    task = db.get_or_404(Task, task_id)
    blocked = _file_task_gate(task)
    if blocked:
        return blocked
    try:
        with renewing_lock(_file_submit_lock(task), ttl=FILE_SUBMIT_LOCK_TTL, strict=True) as got:
            if not got:
                return _busy_lock()
            source = environment_service.workspace_source(task, request.user["user_id"])
            if not isinstance(source, environment_service.WorkspaceSource):
                return source
            rules = parquet_rules(task)
            db.session.commit()
            metas = []
            for name in (SUBMISSION_PARQUET, SOLUTION_NOTEBOOK):
                meta = environment_service.export_metadata(source, name)
                if not isinstance(meta, environment_service.ExportMeta):
                    return meta
                metas.append(meta)
            refused = _precheck(task, metas[0].sha256)
            if refused:
                return refused
            directory = incoming_dir()
            try:
                fetched = environment_service.fetch_exports(source, metas, directory)
                if not isinstance(fetched, list):
                    return fetched
                environment_service.audit_exports(source, fetched)
                parquet, notebook = fetched
                files = SubmissionFiles(
                    artifact_path=parquet.path,
                    artifact_sha256=parquet.sha256,
                    artifact_size=parquet.size,
                    notebook_path=notebook.path,
                    notebook_sha256=notebook.sha256,
                    workspace_meta={
                        "source": parquet.source,
                        "exported_at": utcnow().isoformat() + "Z",
                        "artifact_size": parquet.size,
                        "artifact_modified_at": parquet.modified_at,
                        "notebook_size": notebook.size,
                        "notebook_modified_at": notebook.modified_at,
                    },
                    directory=directory,
                )
                return _submit_files(task_id, files, rules, ORIGIN_WORKSPACE)
            finally:
                shutil.rmtree(directory, ignore_errors=True)
    except LockUnavailableError:
        return service_busy()


@dataclass(frozen=True)
class _SavedUpload:
    path: str
    size: int
    sha256: str


def _save_upload(field: str, directory: str, name: str) -> _SavedUpload | ErrorResult:
    upload = request.files.get(field)
    if upload is None or not upload.filename:
        return err("ERR_FILE_REQUIRED", 400, message=f"Attach {name}.")
    path = os.path.join(directory, name)
    try:
        with open(path, "wb") as target:
            size, sha256 = copy_with_digest(
                upload.stream, target, Config.NANOCOLAB_EXPORT_MAX_BYTES
            )
    except ValueError:
        limit = format_size(Config.NANOCOLAB_EXPORT_MAX_BYTES)
        return err(
            "ERR_WORKSPACE_FILE_TOO_LARGE",
            413,
            message=f"The file exceeds the {limit} limit.",
            limit=limit,
        )
    return _SavedUpload(path, size, sha256)


@tasks_bp.route("/tasks/<uuid:task_id>/submit-file", methods=["POST"])
@login_required
@jury_access_required
@rate_limit(max_requests=10, window_seconds=60)
@release_db_before_body
@api.validate(
    resp=Response(HTTP_202=SubmitResponse, **_SUBMIT_FILE_ERRORS),
    tags=["Tasks"],
    security=[{"cookieAuth": []}],
)
def submit_file(task_id: Any) -> tuple[SubmitResponse, int] | ErrorResult:
    """Emergency path: upload submission.parquet and solution.ipynb while the admin allows it."""
    task = db.get_or_404(Task, task_id)
    if task.is_file_mode and not task.emergency_upload_enabled:
        return err("ERR_EMERGENCY_UPLOAD_DISABLED", 403)
    blocked = _file_task_gate(task)
    if blocked:
        return blocked
    try:
        with renewing_lock(_file_submit_lock(task), ttl=FILE_SUBMIT_LOCK_TTL, strict=True) as got:
            if not got:
                return _busy_lock()
            rules = parquet_rules(task)
            db.session.commit()
            directory = incoming_dir()
            try:
                parquet = _save_upload("submission", directory, SUBMISSION_PARQUET)
                if not isinstance(parquet, _SavedUpload):
                    return parquet
                notebook = _save_upload("notebook", directory, SOLUTION_NOTEBOOK)
                if not isinstance(notebook, _SavedUpload):
                    return notebook
                refused = _precheck(task, parquet.sha256)
                if refused:
                    return refused
                files = SubmissionFiles(
                    artifact_path=parquet.path,
                    artifact_sha256=parquet.sha256,
                    artifact_size=parquet.size,
                    notebook_path=notebook.path,
                    notebook_sha256=notebook.sha256,
                    directory=directory,
                )
                return _submit_files(task_id, files, rules, ORIGIN_EMERGENCY_UPLOAD)
            finally:
                shutil.rmtree(directory, ignore_errors=True)
    except LockUnavailableError:
        return service_busy()


@tasks_bp.route("/tasks/<uuid:task_id>/emergency-upload", methods=["PUT"])
@role_required(["admin"])
@api.validate(
    json=EmergencyUploadSchema,
    resp=Response(
        HTTP_200=TaskAdminResponse,
        HTTP_400=ErrorResponse,
        HTTP_403=ErrorResponse,
        HTTP_409=ErrorResponse,
        HTTP_422=ErrorResponse,
    ),
    tags=["Tasks"],
    security=[{"cookieAuth": []}],
)
def set_emergency_upload(task_id: Any, json: EmergencyUploadSchema) -> dict[str, Any] | ErrorResult:
    """Let a file task take direct uploads during a nanoColab outage; off by default."""
    task = db.get_or_404(Task, task_id)
    if not task.is_file_mode:
        return err("ERR_TASK_MODE_MISMATCH", 409)
    if json.enabled and not json.reason:
        return err("ERR_REASON_REQUIRED", 400)
    task.emergency_upload_enabled = json.enabled
    log_action(
        admin_id=request.user["user_id"],
        action_type="emergency_upload",
        target_type="task",
        target_id=task.id,
        details={"enabled": json.enabled, "challenge_id": str(task.challenge_id)},
        reason=json.reason or None,
    )
    db.session.commit()
    invalidate_entity_cache(task.challenge_id)
    return task.to_dict(view_role="admin")


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
        if competitor_submissions_locked(task.challenge):
            return {"locked": True}
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
    data: dict[str, Any] = {
        "items": [
            s.to_dict_light(view_role=user_role, current_user_id=user_id) for s in pagination.items
        ],
        "total": pagination.total,
        "page": pagination.page,
        "pages": pagination.pages,
    }
    if user_role == "competitor":
        data["final_selection"] = _final_selection_state(task, user_id)
    return data


def _final_selection_state(task: Task, user_id: Any) -> dict[str, Any]:
    """The competitor's selection window and counted run, so the page never recomputes them."""
    challenge = task.challenge
    window = contest_rules.selection_window(user_id, task, challenge)
    completed = Submission.query.filter_by(
        task_id=task.id, user_id=user_id, status=COMPLETED, is_baseline=False
    ).all()
    counted = contest_rules.counted_run(task, completed, challenge)
    return {
        "open": window.open,
        "closes_at": window.closes_at.isoformat() + "Z" if window.closes_at else None,
        "counted_submission": counted.to_dict_light(view_role="competitor", current_user_id=user_id)
        if counted
        else None,
    }


@tasks_bp.route("/tasks/<uuid:task_id>/submissions", methods=["GET"])
@login_required
@jury_access_required
@api.validate(
    resp=Response(HTTP_200=TaskSubmissionsResponse, HTTP_403=ErrorResponse),
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
    if isinstance(data, dict) and data.get("locked"):
        return err("ERR_SUBMISSIONS_LOCKED", 403)
    if isinstance(data, dict) and "error" in data:
        return err("ERR_ACCESS_DENIED", 403, message=data["error"])
    return data


@tasks_bp.route("/worker/capabilities/<uuid:submission_id>", methods=["POST"])
@rate_limit(max_requests=30, window_seconds=60, per_user=False, identity=_worker_token_identity)
@api.validate(
    resp=Response(
        HTTP_200=None,
        HTTP_400=ErrorResponse,
        HTTP_401=ErrorResponse,
        HTTP_409=ErrorResponse,
        HTTP_503=ErrorResponse,
    ),
    tags=["Tasks"],
)
def claim_worker_capabilities(
    submission_id: Any,
) -> tuple[dict[str, dict[str, str]], int] | tuple[FlaskResponse, int]:
    """Bind a broker-delivered attempt to one registered worker and issue scopes."""
    identity = check_worker_auth(request.headers.get("X-Worker-Token"))
    if not identity:
        return err("ERR_UNAUTHORIZED", 401)
    data = request.get_json(silent=True) or {}
    attempt_id = data.get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id:
        return err("ERR_INVALID_REQUEST_BODY", 400)

    submission = Submission.query.filter_by(id=submission_id).with_for_update().first()
    if not submission or submission.celery_task_id != attempt_id:
        return err("ERR_STALE_WORKER_ATTEMPT", 409)
    if submission.status not in ACTIVE_STATUSES:
        return err("ERR_STALE_WORKER_ATTEMPT", 409)

    coordination = get_coordination_client()
    if coordination is None:
        return err("ERR_WORKER_AUTH_UNAVAILABLE", 503)
    binding_key = f"worker:attempt:{attempt_id}"
    worker_id = identity["worker_id"]
    try:
        bound = coordination.get(binding_key)
        if isinstance(bound, bytes):
            bound = bound.decode()
        if bound and bound != worker_id:
            retry_after = coordination.ttl(binding_key)
            if not isinstance(retry_after, int) or retry_after < 1:
                retry_after = Config.WORKER_ATTEMPT_LEASE_TTL
            return err("ERR_STALE_WORKER_ATTEMPT", 409, retry_after=retry_after)
        if not bound and not coordination.set(
            binding_key, worker_id, nx=True, ex=Config.WORKER_ATTEMPT_LEASE_TTL
        ):
            retry_after = coordination.ttl(binding_key)
            if not isinstance(retry_after, int) or retry_after < 1:
                retry_after = Config.WORKER_ATTEMPT_LEASE_TTL
            return err("ERR_STALE_WORKER_ATTEMPT", 409, retry_after=retry_after)
        if bound == worker_id:
            coordination.expire(binding_key, Config.WORKER_ATTEMPT_LEASE_TTL)
    except Exception:
        logger.exception("Failed to bind worker attempt %s", attempt_id)
        return err("ERR_WORKER_AUTH_UNAVAILABLE", 503)

    if submission.status == QUEUED:
        if not transition(submission.id, RUNNING, from_statuses=(QUEUED,), attempt_id=attempt_id):
            db.session.rollback()
            return err("ERR_STALE_WORKER_ATTEMPT", 409)
        db.session.commit()
    record_attempt_claimed(attempt_id)
    metadata = {
        "submission_id": submission.id,
        "task_id": submission.task_id,
        "attempt_id": attempt_id,
        # The ZIP recorded at dispatch (notebook runs only), even if the task replaced it
        "hf_zip_sha256": submission.hf_zip_sha256,
    }
    capabilities = build_submission_capabilities(metadata, worker_id)
    return {"capabilities": capabilities}, 200


def _clear_hf_data_failure(submission: Submission) -> None:
    """A run prepared the task's current HF data, so a recorded HF data failure is over."""
    task = submission.task
    if (
        task is not None
        and submission.hf_zip_sha256
        and task.hf_zip_sha256 == submission.hf_zip_sha256
        and "ERR_HF_DATA_SYNC_FAILED" in (task.problem_codes or [])
    ):
        set_problems(task, problem_codes=["ERR_HF_DATA_SYNC_FAILED"], present=False)


def _clear_sync_failures(submission: Submission) -> None:
    """A run that got past a sync step proves it works again, cached image or not."""
    task = submission.task
    if task is None or not task.problem_codes:
        return
    cleared = []
    # Workers report running_inference only after the task files synced
    if submission.detailed_status == RUNNING_INFERENCE:
        cleared.append("ERR_TASK_FILE_SYNC_FAILED")
    # A scored run has read the labels from the worker's cache
    if submission.status == COMPLETED and submission.public_score is not None:
        cleared.append("ERR_TASK_LABELS_SYNC_FAILED")
    present = [code for code in cleared if code in task.problem_codes]
    if present:
        set_problems(task, problem_codes=present, present=False)


@tasks_bp.route("/worker/report/<uuid:submission_id>", methods=["POST"])
@rate_limit(max_requests=120, window_seconds=60, per_user=False, identity=_worker_token_identity)
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
    if not request.is_json:
        return err("ERR_INVALID_REQUEST_BODY", 400)
    data = request.get_json()
    if not isinstance(data, dict):
        return err("ERR_INVALID_REQUEST_BODY", 400)
    submission = Submission.query.filter_by(id=submission_id).with_for_update().first()
    if not submission:
        return err("ERR_NOT_FOUND", 404)
    identity = check_worker_auth(request.headers.get("X-Worker-Token"))
    if not identity:
        return err("ERR_UNAUTHORIZED", 401)
    if not _worker_capability(
        "report_submission",
        "submission",
        submission_id,
        attempt_id=submission.celery_task_id,
        identity=identity,
    ):
        return err("ERR_STALE_WORKER_ATTEMPT", 409)

    # A killed submission is terminal; a stale in-flight report must not resurrect it
    if submission.detailed_status == KILLED:
        return err("ERR_SUBMISSION_KILLED", 409)

    current_status = submission.status
    status_val = current_status
    if "status" in data:
        status_val = data["status"]
        if not isinstance(status_val, str) or status_val not in STATUSES:
            return err("ERR_INVALID_STATUS", 400, message=f"Invalid status value: {status_val}")
        if current_status in TERMINAL_STATUSES and status_val == current_status:
            return {"message": "Status already applied"}, 200
    if not is_allowed(current_status, status_val):
        # Also refuses a report without a status on a terminal run
        return err("ERR_STALE_WORKER_ATTEMPT", 409)
    values: dict[str, Any] = {}
    detailed_status = None
    if "detailed_status" in data:
        detailed_status = data["detailed_status"]
        if not isinstance(detailed_status, str) or len(detailed_status) > 100:
            return err("ERR_INVALID_REQUEST_BODY", 400)
        if detailed_status in FAILURE_DETAILS and status_val != FAILED:
            return err("ERR_INVALID_REQUEST_BODY", 400)
    # Executed_at anchors the watchdog clock; it must reflect actual container
    # execution, not pre-execution phases (image build, GPU acquisition) that the
    # runner reports under detailed_status="building_env" while status="running"
    detailed_val = detailed_status or submission.detailed_status
    if (
        submission.executed_at is None
        and status_val == RUNNING
        and detailed_val not in (BUILDING_ENV, QUEUED)
    ):
        values["executed_at"] = func.coalesce(Submission.executed_at, utcnow())
    logs_val = None
    if "logs" in data:
        logs_val = data["logs"]
        if isinstance(logs_val, list):
            logs_val = "\n".join(str(line) for line in logs_val)
        if isinstance(logs_val, str) and len(logs_val.encode("utf-8")) > MAX_LOG_SIZE:
            logs_val = logs_val.encode("utf-8")[:MAX_LOG_SIZE].decode("utf-8", errors="ignore")
        if logs_val is not None and not isinstance(logs_val, str):
            return err("ERR_INVALID_REQUEST_BODY", 400)
    if "public_score" in data:
        val = data["public_score"]
        if val is not None and (
            not isinstance(val, (int, float))
            or isinstance(val, bool)
            or (isinstance(val, float) and (math.isnan(val) or math.isinf(val)))
        ):
            return err("ERR_INVALID_PUBLIC_SCORE", 400)
        values["public_score"] = val
        values["final_weighted_score_public"] = val
    if "private_score" in data:
        val = data["private_score"]
        if val is not None and (
            not isinstance(val, (int, float))
            or isinstance(val, bool)
            or (isinstance(val, float) and (math.isnan(val) or math.isinf(val)))
        ):
            return err("ERR_INVALID_PRIVATE_SCORE", 400)
        values["private_score"] = val
        values["final_weighted_score_private"] = val
    if "execution_time_ms" in data:
        try:
            exec_time = (
                -1
                if isinstance(data["execution_time_ms"], bool)
                else int(data["execution_time_ms"])
            )
        except (TypeError, ValueError, OverflowError):
            exec_time = -1
        if exec_time < 0 or exec_time > Config.MAX_EXECUTION_TIME_MS:
            return err("ERR_INVALID_EXECUTION_TIME", 400)
        values["execution_time_ms"] = exec_time
    if "evaluation_time_ms" in data:
        try:
            scoring_ms = (
                -1
                if isinstance(data["evaluation_time_ms"], bool)
                else int(data["evaluation_time_ms"])
            )
        except (TypeError, ValueError, OverflowError):
            scoring_ms = -1
        if scoring_ms < 0 or scoring_ms > Config.MAX_EXECUTION_TIME_MS:
            return err("ERR_INVALID_EXECUTION_TIME", 400)
        values["evaluation_time_ms"] = scoring_ms
    if "metrics_payload_public" in data:
        values["metrics_payload_public"] = data["metrics_payload_public"]
    elif "metrics_payload_pub" in data:
        values["metrics_payload_public"] = data["metrics_payload_pub"]
    if "metrics_payload_private" in data:
        values["metrics_payload_private"] = data["metrics_payload_private"]
    elif "metrics_payload_priv" in data:
        values["metrics_payload_private"] = data["metrics_payload_priv"]
    if "gpu_node" in data:
        gpu_node = data["gpu_node"]
        if gpu_node is not None and (not isinstance(gpu_node, str) or len(gpu_node) > 255):
            return err("ERR_INVALID_REQUEST_BODY", 400)
        values["gpu_node"] = gpu_node
    if "final_weighted_score_public" in data:
        val = data["final_weighted_score_public"]
        if val is not None and (
            not isinstance(val, (int, float))
            or isinstance(val, bool)
            or (isinstance(val, float) and not math.isfinite(val))
        ):
            return err("ERR_INVALID_PUBLIC_SCORE", 400)
        values["final_weighted_score_public"] = val
    if "final_weighted_score_private" in data:
        val = data["final_weighted_score_private"]
        if val is not None and (
            not isinstance(val, (int, float))
            or isinstance(val, bool)
            or (isinstance(val, float) and not math.isfinite(val))
        ):
            return err("ERR_INVALID_PRIVATE_SCORE", 400)
        values["final_weighted_score_private"] = val

    if not transition(
        submission.id,
        status_val,
        from_statuses=(current_status,),
        detailed_status=detailed_status,
        attempt_id=submission.celery_task_id,
        fields=values,
    ):
        db.session.rollback()
        return err("ERR_STALE_WORKER_ATTEMPT", 409)
    # Log files are written only for a report that applied
    if logs_val is not None:
        submission.logs = logs_val
    db.session.commit()

    # An ended baseline run settles its task's readiness
    apply_baseline_outcome(submission)
    if data.get("hf_ready") is True:
        _clear_hf_data_failure(submission)
    _clear_sync_failures(submission)

    publish_queue_update()

    if submission.status in TERMINAL_STATUSES:
        from utils.sse_utils import publish_submission_status

        publish_submission_status(submission.id, submission.status)

        try:
            from utils.cache_utils import invalidate_leaderboard_cache

            invalidate_leaderboard_cache(submission.challenge_id)
        except Exception:
            current_app.logger.exception("Failed to invalidate leaderboard cache in report route")

    return {"message": "Status updated successfully"}, 200


@tasks_bp.route("/worker/tasks/<uuid:task_id>/files/<string:filename>", methods=["GET"])
# Each job syncs every file of its task, and workers behind one address share this budget
@rate_limit(max_requests=120, window_seconds=60, per_user=False, identity=_worker_token_identity)
@api.validate(resp=Response(HTTP_200=None, HTTP_403=ErrorResponse), tags=["Tasks"])
def worker_download_task_file(
    task_id: Any, filename: str
) -> tuple[Generator[bytes, None, None], int, dict[str, str]] | tuple[FlaskResponse, int]:
    """Worker endpoint to securely download task resource files."""
    if not _task_capability("task_file", task_id):
        return err("ERR_UNAUTHORIZED", 401)

    task = db.get_or_404(Task, task_id)
    try:
        files_meta = json.loads(task.files)
    except (json.JSONDecodeError, TypeError, ValueError):
        files_meta = []

    entry = next((f for f in files_meta if f["filename"] == filename), None)
    saved_name = entry["saved_name"] if entry else None

    if not saved_name:
        return err("ERR_FILE_NOT_FOUND", 404)

    if ".." in saved_name or "/" in saved_name or "\\" in saved_name:
        return err("ERR_INVALID_FILENAME", 400)

    task_upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], f"task_{task.id}")
    file_path = os.path.join(task_upload_dir, saved_name)
    if not os.path.isfile(file_path):
        return err("ERR_FILE_NOT_FOUND", 404)
    safe_filename = sanitize_filename_part(filename)
    # Stream from disk (files can be up to 500 MB — never buffer in RAM)
    return stream_file_response(
        file_path, "application/octet-stream", safe_filename, sha256=entry.get("sha256")
    )


@tasks_bp.route("/worker/active-tasks", methods=["GET"])
@api.validate(
    resp=Response(HTTP_200=WorkerActiveTasksResponse, HTTP_401=ErrorResponse),
    tags=["Tasks"],
)
def get_active_tasks() -> tuple[WorkerActiveTasksResponse, int] | tuple[FlaskResponse, int]:
    """Reject the retired fleet-wide task enumeration contract."""
    return err("ERR_UNAUTHORIZED", 401)


@tasks_bp.route("/worker/hf-zip/<string:sha256>", methods=["GET"])
@rate_limit(max_requests=120, window_seconds=60, per_user=False, identity=_worker_token_identity)
@api.validate(
    resp=Response(HTTP_200=None, HTTP_401=ErrorResponse, HTTP_404=ErrorResponse),
    tags=["Tasks"],
)
def worker_download_hf_zip(
    sha256: str,
) -> tuple[Generator[bytes, None, None], int, dict[str, str]] | tuple[FlaskResponse, int]:
    """Stream a task's Hugging Face ZIP to a worker running a submission of that task."""
    if not hf_zip.SHA256_RE.fullmatch(sha256):
        return err("ERR_FILE_NOT_FOUND", 404)
    claims = _worker_capability("hf_zip", "hf_zip", sha256)
    if not claims:
        return err("ERR_UNAUTHORIZED", 401)
    submission = Submission.query.filter_by(celery_task_id=claims.get("attempt_id")).first()
    if (
        submission is None
        or submission.status not in ACTIVE_STATUSES
        or submission.hf_zip_sha256 != sha256
    ):
        return err("ERR_UNAUTHORIZED", 401)
    path = hf_zip.hf_zip_path(sha256)
    if not os.path.isfile(path):
        return err("ERR_FILE_NOT_FOUND", 404)
    return stream_file_response(path, "application/zip", f"{sha256}.zip", sha256=sha256)


@tasks_bp.route("/worker/tasks/<uuid:task_id>/report-build-error", methods=["POST"])
@rate_limit(max_requests=30, window_seconds=60, per_user=False, identity=_worker_token_identity)
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
    if not _task_capability("report_build_error", task_id):
        return err("ERR_UNAUTHORIZED", 401)
    data = request.get_json(silent=True) or {}
    error_msg = (data.get("error") or "").strip()
    task = db.session.get(Task, task_id)
    if not task:
        return err("ERR_TASK_NOT_FOUND", 404)
    if error_msg:
        # Record every reported root cause; if none were reported, fall back
        # to the generic build-failed code
        reported = [c for c in data.get("problem_codes", []) if isinstance(c, str)]
        merged = set(task.problem_codes or [])
        merged.update(reported or ["ERR_TASK_BUILD_FAILED"])
        task.problem_codes = sorted(merged) or None
    else:
        # A successful build clears build problems; ERR_BASELINE_FAILED waits for a baseline
        build_codes = {
            "ERR_TASK_FILE_SYNC_FAILED",
            "ERR_TASK_LABELS_SYNC_FAILED",
            "ERR_TASK_BUILD_FAILED",
            "ERR_HF_DATA_SYNC_FAILED",
        }
        task.problem_codes = [c for c in (task.problem_codes or []) if c not in build_codes] or None
    db.session.commit()
    return {"message": "ok"}, 200


@tasks_bp.route("/workers/logs", methods=["POST"])
@rate_limit(max_requests=12, window_seconds=60, per_user=False, identity=_worker_token_identity)
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

    # Cap the decompressed payload to prevent disk fill from a compromised worker
    if len(body) > Config.MAX_WORKER_LOG_SHIP_BYTES:
        return err("ERR_PAYLOAD_TOO_LARGE", 413)

    try:
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as compressed:
            lines_bytes = compressed.read(Config.MAX_WORKER_LOG_SHIP_BYTES + 1)
        lines = lines_bytes.decode()
    except (OSError, EOFError, UnicodeDecodeError):
        return err("ERR_INVALID_REQUEST_BODY", 400)

    if len(lines_bytes) > Config.MAX_WORKER_LOG_SHIP_BYTES:
        return err("ERR_PAYLOAD_TOO_LARGE", 413)

    log_dir = os.environ.get("LOG_DIR", "/app/logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "worker_remote.log")
    try:
        # Rotate before appending so a churny worker cannot grow the log file
        # without bound
        if os.path.exists(log_path) and os.path.getsize(log_path) > Config.MAX_WORKER_LOG_BYTES:
            backup = f"{log_path}.1"
            if os.path.exists(backup):
                os.remove(backup)
            os.replace(log_path, backup)
        with open(log_path, "a") as f:
            f.write(lines if lines.endswith("\n") else lines + "\n")
    except OSError as e:
        logger.error("Failed to write worker logs: %s", e)
        return err("ERR_INTERNAL_SERVER_ERROR", 500)
    return {"status": "ok"}, 200


@tasks_bp.route("/worker/submission-run-content/<uuid:submission_id>", methods=["GET"])
@rate_limit(max_requests=120, window_seconds=60, per_user=False, identity=_worker_token_identity)
@api.validate(
    resp=Response(
        HTTP_200=WorkerRunContentResponse,
        HTTP_401=ErrorResponse,
        HTTP_404=ErrorResponse,
        HTTP_500=ErrorResponse,
    ),
    tags=["Tasks"],
)
def get_submission_run_content(submission_id: Any) -> tuple[WorkerRunContentResponse, int]:
    """Return the code a worker must execute for a submission.

    The submission's code and evaluator script are fetched on demand with a
    signed worker token bound to this exact submission_id — they are never
    embedded in the Celery message. ``user_code`` is reconstructed from the
    stored ``code_cells`` exactly as the submission runner consumes it.
    """
    submission = db.session.get(Submission, submission_id)
    if not submission:
        return err("ERR_NOT_FOUND", 404)
    if not _worker_capability(
        "submission_run_content",
        "submission",
        submission_id,
        attempt_id=submission.celery_task_id,
    ):
        return err("ERR_UNAUTHORIZED", 401)

    try:
        cells_list = json.loads(submission.code_cells or "[]")
    except Exception:
        cells_list = []
    user_code = "\n\n".join(extract_code_from_cells(cells_list))

    custom_eval_code = None
    task = submission.task
    if task:
        custom_eval_code = task.custom_eval_code
        if not custom_eval_code and task.evaluator_script_path:
            try:
                with open(task.evaluator_script_path) as ef:
                    custom_eval_code = ef.read()
            except OSError as e:
                logger.error("Failed to read evaluator script for task %s: %s", task.id, e)
                return err("ERR_EVALUATOR_LOAD_FAILED", 500)

    return WorkerRunContentResponse(
        user_code=user_code or None, custom_eval_code=custom_eval_code
    ), 200


@tasks_bp.route("/worker/submission-artifact/<uuid:submission_id>", methods=["GET"])
@rate_limit(max_requests=120, window_seconds=60, per_user=False, identity=_worker_token_identity)
@api.validate(
    resp=Response(HTTP_200=None, HTTP_401=ErrorResponse, HTTP_404=ErrorResponse),
    tags=["Tasks"],
)
def get_submission_artifact(
    submission_id: Any,
) -> tuple[Generator[bytes, None, None], int, dict[str, str]] | tuple[FlaskResponse, int]:
    """Stream the Parquet of a file-task submission to the worker scoring it."""
    submission = db.session.get(Submission, submission_id)
    if not submission:
        return err("ERR_NOT_FOUND", 404)
    if not _worker_capability(
        "submission_artifact",
        "submission",
        submission_id,
        attempt_id=submission.celery_task_id,
    ):
        return err("ERR_UNAUTHORIZED", 401)
    path = submission.artifact_path
    if not path or not os.path.isfile(path):
        return err("ERR_FILE_NOT_FOUND", 404)
    return stream_file_response(
        path, "application/octet-stream", "submission.parquet", sha256=submission.artifact_sha256
    )
