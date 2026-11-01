"""Stage compute configuration, competitor environments and workspace submissions."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from flask import Blueprint, request
from flask import Response as FlaskResponse
from spectree import Response

from models import Stage, StageCompute, Submission, Task, db
from schemas.compute import StageComputeSchema, WorkspacePathsSchema
from schemas.responses import ErrorResponse
from schemas.responses.compute import (
    EnvironmentLaunchResponse,
    EnvironmentStatusResponse,
    StageComputeResponse,
    WorkspaceImagesResponse,
    WorkspacePathsResponse,
    WorkspaceSubmitResponse,
)
from services import compute_service, stage_package
from services.nanocolab_client import NanoColabClient, NanoColabError
from services.submission_service import validate_submission_allowed
from utils.access import ensure_registered
from utils.audit import log_audit
from utils.auth_utils import jury_access_required, login_required, rate_limit, role_required
from utils.cache import invalidate_entity_cache
from utils.cache_utils import cache_lock
from utils.dates import utcnow
from utils.error_utils import err
from utils.spec import api

environment_bp = Blueprint("environment", __name__)


def _stage(challenge_id: Any, stage_id: Any) -> Stage:
    stage: Stage = Stage.query.filter_by(id=stage_id, challenge_id=challenge_id).first_or_404()
    return stage


def _compute_payload(stage: Stage, compute: StageCompute) -> dict[str, Any]:
    payload = compute.to_dict(stage.challenge.timezone or "UTC")
    payload["declared_paths"] = compute_service.declared_paths(stage)
    payload["task_folders"] = stage_package.task_folders(stage)
    payload["readiness"] = None
    client = NanoColabClient.from_config()
    if client and compute.enabled and compute.nanocolab_event_id:
        try:
            payload["readiness"] = client.get_readiness(compute_service.event_external_id(stage))
        except NanoColabError as exc:
            payload["readiness"] = {
                "status": "UNKNOWN",
                "message": f"nano-colab status {exc.status}",
            }
    return payload


def _package_failed(compute: StageCompute) -> tuple[FlaskResponse, int]:
    if compute.package_error == "ERR_STAGE_PACKAGE_EMPTY":
        return err("ERR_STAGE_PACKAGE_EMPTY", 422)
    return err("ERR_STAGE_PACKAGE_INVALID", 422)


@environment_bp.route("/challenges/<uuid:challenge_id>/compute/images", methods=["GET"])
@role_required(["admin", "jury"])
@jury_access_required
@api.validate(
    resp=Response(HTTP_200=WorkspaceImagesResponse, HTTP_503=ErrorResponse),
    tags=["Compute"],
    security=[{"cookieAuth": []}],
)
def list_workspace_images(challenge_id: Any) -> dict[str, Any] | tuple[FlaskResponse, int]:
    """List the notebook environments nano-colab offers for stage compute."""
    result = compute_service.workspace_images()
    if isinstance(result, tuple):
        return result
    return {"images": result}


@environment_bp.route(
    "/challenges/<uuid:challenge_id>/stages/<uuid:stage_id>/compute", methods=["GET"]
)
@role_required(["admin", "jury"])
@jury_access_required
@api.validate(
    resp=Response(HTTP_200=StageComputeResponse, HTTP_404=ErrorResponse),
    tags=["Compute"],
    security=[{"cookieAuth": []}],
)
def get_stage_compute(
    challenge_id: Any, stage_id: Any
) -> dict[str, Any] | tuple[FlaskResponse, int]:
    """Return the stage compute binding and live readiness."""
    stage = _stage(challenge_id, stage_id)
    compute = compute_service.compute_for(stage) or StageCompute(
        stage_id=stage.id,
        enabled=False,
        published=False,
        compute_kind="CPU",
        cpu_cores=2,
        memory_gib=8,
        disk_gib=10,
        image_id="",
        image_digest="",
        asset_version="",
        package_state="NONE",
        max_attendance=1,
        retention_days=30,
        sync_state="PENDING",
    )
    if compute.enabled and compute.sync_state == "PACKAGING":
        compute_service.sync_stage(stage, request.user["user_id"])
    return _compute_payload(stage, compute)


@environment_bp.route(
    "/challenges/<uuid:challenge_id>/stages/<uuid:stage_id>/compute", methods=["PUT"]
)
@role_required(["admin", "jury"])
@jury_access_required
@api.validate(
    json=StageComputeSchema,
    resp=Response(
        HTTP_200=StageComputeResponse,
        HTTP_400=ErrorResponse,
        HTTP_409=ErrorResponse,
        HTTP_422=ErrorResponse,
        HTTP_502=ErrorResponse,
        HTTP_503=ErrorResponse,
    ),
    tags=["Compute"],
    security=[{"cookieAuth": []}],
)
def put_stage_compute(
    challenge_id: Any, stage_id: Any, json: StageComputeSchema
) -> dict[str, Any] | tuple[FlaskResponse, int]:
    """Create or update the stage compute binding and push it to nano-colab."""
    stage = _stage(challenge_id, stage_id)
    values = json.model_dump()
    if values["compute_kind"] == "CPU":
        values["gpu_type"] = None
    compute = compute_service.compute_for(stage)
    blocked = compute_service.compute_update_blocked(compute, values) if compute else None
    if blocked:
        return blocked
    if values["enabled"] and (compute is None or values["image_id"] != compute.image_id):
        unknown = compute_service.image_choice_blocked(values["image_id"])
        if unknown:
            return unknown
    if compute is None:
        compute = StageCompute(stage_id=stage.id, sync_state="PENDING")
        db.session.add(compute)
    for key, value in values.items():
        setattr(compute, key, value)
    compute.sync_state = "PENDING"
    db.session.commit()
    actor = request.user["user_id"]
    log_audit(
        actor,
        "update",
        "stage_compute",
        target_id=stage.id,
        details={"enabled": compute.enabled, "published": compute.published},
    )
    db.session.commit()
    result = compute_service.sync_stage(stage, actor)
    if result != compute_service.SYNCED and compute.published:
        compute.published = False
        db.session.commit()
    invalidate_entity_cache(challenge_id)
    if result == compute_service.FAILED:
        return err("ERR_COMPUTE_SYNC_FAILED", 502)
    if result == compute_service.PACKAGE_FAILED:
        return _package_failed(compute)
    if result == compute_service.PACKAGING and values["published"]:
        return err("ERR_STAGE_PACKAGE_NOT_READY", 409)
    return _compute_payload(stage, compute)


@environment_bp.route(
    "/challenges/<uuid:challenge_id>/stages/<uuid:stage_id>/compute/sync", methods=["POST"]
)
@role_required(["admin", "jury"])
@jury_access_required
@api.validate(
    resp=Response(HTTP_200=StageComputeResponse, HTTP_422=ErrorResponse, HTTP_502=ErrorResponse),
    tags=["Compute"],
    security=[{"cookieAuth": []}],
)
def sync_stage_compute(
    challenge_id: Any, stage_id: Any
) -> dict[str, Any] | tuple[FlaskResponse, int]:
    """Retry pushing the stage compute binding to nano-colab."""
    stage = _stage(challenge_id, stage_id)
    compute = compute_service.compute_for(stage)
    if compute is None or not compute.enabled:
        return err("ERR_COMPUTE_NOT_ENABLED", 404)
    result = compute_service.sync_stage(stage, request.user["user_id"])
    if result == compute_service.FAILED:
        return err("ERR_COMPUTE_SYNC_FAILED", 502)
    if result == compute_service.PACKAGE_FAILED:
        return _package_failed(compute)
    return _compute_payload(stage, compute)


@environment_bp.route("/tasks/<uuid:task_id>/workspace-paths", methods=["PUT"])
@role_required(["admin", "jury"])
@jury_access_required
@api.validate(
    json=WorkspacePathsSchema,
    resp=Response(HTTP_200=WorkspacePathsResponse, HTTP_409=ErrorResponse),
    tags=["Compute"],
    security=[{"cookieAuth": []}],
)
def put_task_workspace_paths(
    task_id: Any, json: WorkspacePathsSchema
) -> dict[str, Any] | tuple[FlaskResponse, int]:
    """Declare which workspace files the task's Submit button reads."""
    task = db.get_or_404(Task, task_id)
    if json.notebook_path and not json.submission_path:
        return err("ERR_INVALID_WORKSPACE_PATH", 400)
    task.workspace_submission_path = json.submission_path
    task.workspace_notebook_path = json.notebook_path
    db.session.commit()
    actor = request.user["user_id"]
    log_audit(
        actor,
        "update",
        "task_workspace_paths",
        target_id=task.id,
        details={"submission_path": json.submission_path, "notebook_path": json.notebook_path},
    )
    db.session.commit()
    stage = db.session.get(Stage, task.stage_id) if task.stage_id else None
    result = compute_service.sync_stage(stage, actor) if stage else compute_service.SYNCED
    synced = result in {compute_service.SYNCED, compute_service.PACKAGING}
    invalidate_entity_cache(task.challenge_id)
    return {
        "task_id": task.id,
        "workspace_submission_path": task.workspace_submission_path,
        "workspace_notebook_path": task.workspace_notebook_path,
        "sync_ok": synced,
    }


def _competitor_stage(challenge_id: Any, stage_id: Any) -> Stage | tuple[FlaskResponse, int]:
    if not ensure_registered(request.user["user_id"], challenge_id):
        return err("ERR_NOT_REGISTERED", 403)
    return _stage(challenge_id, stage_id)


@environment_bp.route(
    "/challenges/<uuid:challenge_id>/stages/<uuid:stage_id>/environment", methods=["GET"]
)
@login_required
@role_required(["competitor"])
@api.validate(
    resp=Response(HTTP_200=EnvironmentStatusResponse, HTTP_403=ErrorResponse),
    tags=["Compute"],
    security=[{"cookieAuth": []}],
)
def get_environment(challenge_id: Any, stage_id: Any) -> dict[str, Any] | tuple[FlaskResponse, int]:
    """Report whether the competitor's notebook environment can be opened."""
    stage = _competitor_stage(challenge_id, stage_id)
    if not isinstance(stage, Stage):
        return stage
    return compute_service.environment_status(stage)


@environment_bp.route(
    "/challenges/<uuid:challenge_id>/stages/<uuid:stage_id>/environment", methods=["POST"]
)
@login_required
@role_required(["competitor"])
@rate_limit(max_requests=10, window_seconds=60)
@api.validate(
    resp=Response(
        HTTP_200=EnvironmentLaunchResponse,
        HTTP_403=ErrorResponse,
        HTTP_404=ErrorResponse,
        HTTP_409=ErrorResponse,
        HTTP_503=ErrorResponse,
    ),
    tags=["Compute"],
    security=[{"cookieAuth": []}],
)
def launch_environment(challenge_id: Any, stage_id: Any) -> Any:
    """Ensure the competitor's workspace and return a single-use launch token."""
    stage = _competitor_stage(challenge_id, stage_id)
    if not isinstance(stage, Stage):
        return stage
    result = compute_service.launch_environment(stage, request.user["user_id"])
    if isinstance(result, tuple):
        return result
    return result, 200, {"Cache-Control": "no-store"}


def _quota_blocked(user_id: Any, task: Task) -> tuple[FlaskResponse, int] | None:
    challenge = task.challenge
    today_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    daily = Submission.query.filter(
        Submission.user_id == user_id,
        Submission.challenge_id == challenge.id,
        Submission.created_at >= today_start,
    ).count()
    if daily >= challenge.max_eval_requests:
        return err("ERR_DAILY_LIMIT_REACHED", 429)
    if task.max_submissions_per_period and task.submission_period_hours:
        period_start = utcnow() - timedelta(hours=task.submission_period_hours)
        recent = Submission.query.filter(
            Submission.user_id == user_id,
            Submission.task_id == task.id,
            Submission.created_at >= period_start,
        ).count()
        if recent >= task.max_submissions_per_period:
            return err("ERR_TASK_LIMIT_REACHED", 429)
    return None


@environment_bp.route("/tasks/<uuid:task_id>/submit-from-workspace", methods=["POST"])
@login_required
@role_required(["competitor"])
@rate_limit(max_requests=10, window_seconds=60)
@api.validate(
    resp=Response(
        HTTP_202=WorkspaceSubmitResponse,
        HTTP_400=ErrorResponse,
        HTTP_403=ErrorResponse,
        HTTP_404=ErrorResponse,
        HTTP_409=ErrorResponse,
        HTTP_413=ErrorResponse,
        HTTP_429=ErrorResponse,
        HTTP_502=ErrorResponse,
        HTTP_503=ErrorResponse,
    ),
    tags=["Compute"],
    security=[{"cookieAuth": []}],
)
def submit_from_workspace(task_id: Any) -> Any:
    """Pull the declared CSV and notebook from the competitor's workspace and submit them."""
    task = db.get_or_404(Task, task_id)
    user_id = request.user["user_id"]
    if not ensure_registered(user_id, task.challenge_id):
        return err("ERR_NOT_REGISTERED", 403)
    blocked = validate_submission_allowed(user_id, "competitor", task, task.challenge)
    if blocked:
        return blocked
    stage = db.session.get(Stage, task.stage_id) if task.stage_id else None
    if stage is None:
        return err("ERR_TASK_NOT_WORKSPACE_BACKED", 400)
    with cache_lock(
        f"submit_lock:user_{user_id}:challenge_{task.challenge_id}", ttl=30
    ) as acquired:
        if not acquired:
            return err("ERR_SUBMIT_LOCKED", 429)
        quota = _quota_blocked(user_id, task)
        if quota:
            return quota
        result = compute_service.submit_from_workspace(task, stage, user_id)
    if isinstance(result, tuple):
        return result
    return result, 202
