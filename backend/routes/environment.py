"""nanoColab environments: admin publish and extension, jury read-only views, student launch."""

from __future__ import annotations

from typing import Any

from flask import Blueprint, abort, request
from flask import Response as FlaskResponse
from spectree import Response

from models import Challenge, Environment, Task, db
from routes.tasks import check_task_started
from schemas.environment import (
    WORKSPACE_DEFAULT_GIB,
    WORKSPACE_MAX_GIB,
    WORKSPACE_MIN_GIB,
    ExtendEnvironmentSchema,
)
from schemas.responses import ErrorResponse
from schemas.responses.environment import (
    EnvironmentLaunchResponse,
    EnvironmentListResponse,
    EnvironmentResponse,
    TaskEnvironmentResponse,
    WorkspaceImagesResponse,
    WorkspaceListResponse,
)
from services import environment_service as envs
from services.environment_package import solution_path
from utils.access import ensure_registered
from utils.auth_utils import jury_access_required, login_required, rate_limit, role_required
from utils.cache import invalidate_entity_cache
from utils.dates import to_tz_iso, to_utc
from utils.error_utils import err
from utils.spec import api
from utils.sse import signal_stream, sse_response
from utils.sse_utils import environment_channel

environment_bp = Blueprint("environment", __name__)

ErrorResult = tuple[FlaskResponse, int]


@environment_bp.before_request
def _require_nanocolab() -> ErrorResult | None:
    # The image list answers when nanoColab is off too, so the setting form can hide itself
    if request.endpoint == "environment.list_workspace_images":
        return None
    if not envs.nanocolab_enabled():
        return err("ERR_NANOCOLAB_DISABLED", 404)
    return None


def _environment(challenge_id: Any, environment_id: Any) -> tuple[Environment, envs.Owner]:
    env: Environment = db.get_or_404(Environment, environment_id)
    owner = envs.owner_of(env)
    if str(owner.challenge.id) != str(challenge_id):
        abort(404)
    return env, owner


@environment_bp.route("/environment/images", methods=["GET"])
@role_required(["admin"])
@api.validate(
    resp=Response(HTTP_200=WorkspaceImagesResponse, HTTP_503=ErrorResponse),
    tags=["Environment"],
    security=[{"cookieAuth": []}],
)
def list_workspace_images() -> dict[str, Any] | ErrorResult:
    """List the workspace images and compute profiles nanoColab offers, and the size limits."""
    sizes = {"min": WORKSPACE_MIN_GIB, "max": WORKSPACE_MAX_GIB, "default": WORKSPACE_DEFAULT_GIB}
    if not envs.nanocolab_enabled():
        return {"available": False, "images": [], "profiles": [], "workspace_gib": sizes}
    catalog = envs.workspace_catalog()
    if isinstance(catalog, tuple):
        return catalog
    return {"available": True, **catalog, "workspace_gib": sizes}


@environment_bp.route("/challenges/<uuid:challenge_id>/environments", methods=["GET"])
@role_required(["admin", "jury"])
@jury_access_required
@api.validate(
    resp=Response(HTTP_200=EnvironmentListResponse, HTTP_404=ErrorResponse),
    tags=["Environment"],
    security=[{"cookieAuth": []}],
)
def list_environments(challenge_id: Any) -> dict[str, Any]:
    """Each stage's environment, or the competition's when it has no stages, with its status."""
    challenge = db.get_or_404(Challenge, challenge_id)
    show_message = request.user["role"] == "admin"
    return {
        "environments": [
            envs.environment_dict(owner.environment(), owner, show_message)
            for owner in envs.workspace_owners(challenge)
        ]
    }


@environment_bp.route(
    "/challenges/<uuid:challenge_id>/environments/<uuid:environment_id>/publish",
    methods=["POST"],
)
@role_required(["admin"])
@api.validate(
    resp=Response(
        HTTP_200=EnvironmentResponse,
        HTTP_404=ErrorResponse,
        HTTP_409=ErrorResponse,
        HTTP_413=ErrorResponse,
        HTTP_422=ErrorResponse,
        HTTP_502=ErrorResponse,
        HTTP_503=ErrorResponse,
    ),
    tags=["Environment"],
    security=[{"cookieAuth": []}],
)
def publish_environment(challenge_id: Any, environment_id: Any) -> dict[str, Any] | ErrorResult:
    """Publish the environment to nanoColab; this cannot be undone."""
    env, owner = _environment(challenge_id, environment_id)
    error = envs.publish_environment(env, request.user["user_id"])
    if error:
        return error
    invalidate_entity_cache(owner.challenge.id)
    return envs.environment_dict(env, owner)


@environment_bp.route(
    "/challenges/<uuid:challenge_id>/environments/<uuid:environment_id>/extension",
    methods=["POST"],
)
@role_required(["admin"])
@api.validate(
    json=ExtendEnvironmentSchema,
    resp=Response(
        HTTP_200=EnvironmentResponse,
        HTTP_400=ErrorResponse,
        HTTP_404=ErrorResponse,
        HTTP_409=ErrorResponse,
        HTTP_422=ErrorResponse,
        HTTP_502=ErrorResponse,
        HTTP_503=ErrorResponse,
    ),
    tags=["Environment"],
    security=[{"cookieAuth": []}],
)
def extend_environment(
    challenge_id: Any, environment_id: Any, json: ExtendEnvironmentSchema
) -> dict[str, Any] | ErrorResult:
    """Move the end of the stage or competition later, with a reason."""
    env, owner = _environment(challenge_id, environment_id)
    new_end = to_utc(json.end_time, owner.challenge.timezone or "UTC")
    error = envs.extend_environment(env, new_end, json.reason, request.user["user_id"])
    if error:
        return error
    invalidate_entity_cache(owner.challenge.id)
    return envs.environment_dict(env, owner)


@environment_bp.route(
    "/challenges/<uuid:challenge_id>/environments/<uuid:environment_id>/workspaces",
    methods=["GET"],
)
@role_required(["admin", "jury"])
@jury_access_required
@api.validate(
    resp=Response(HTTP_200=WorkspaceListResponse, HTTP_404=ErrorResponse),
    tags=["Environment"],
    security=[{"cookieAuth": []}],
)
def list_workspaces(challenge_id: Any, environment_id: Any) -> dict[str, Any]:
    """List every student with their workspace and latest submission; aliases while blind."""
    env, owner = _environment(challenge_id, environment_id)
    show_identity = request.user["role"] == "admin" or not owner.challenge.double_blind
    return {"workspaces": envs.workspace_rows(env, owner, show_identity)}


@environment_bp.route("/challenges/<uuid:challenge_id>/environment/live", methods=["GET"])
@login_required
@jury_access_required
@api.validate(
    resp=Response(HTTP_200=None, HTTP_403=ErrorResponse, HTTP_404=ErrorResponse),
    tags=["SSE Streaming"],
    security=[{"cookieAuth": []}],
)
def stream_environment(
    challenge_id: Any,
) -> tuple[FlaskResponse, int, dict[str, str]] | ErrorResult:
    """Signal ``{"event": "update"}`` when an environment of the competition changes (SSE)."""
    db.get_or_404(Challenge, challenge_id)
    user_id = request.user["user_id"]
    if request.user["role"] == "competitor" and not ensure_registered(user_id, challenge_id):
        return err("ERR_NOT_REGISTERED", 403)
    db.session.remove()
    return sse_response(signal_stream(environment_channel(challenge_id), user_id))


def _student_task(task_id: Any) -> Task | ErrorResult:
    task: Task = db.get_or_404(Task, task_id)
    user_id = request.user["user_id"]
    if not ensure_registered(user_id, task.challenge_id):
        return err("ERR_NOT_REGISTERED", 403)
    if not check_task_started(task, "competitor", user_id):
        return err("ERR_NOT_AVAILABLE", 403)
    return task


@environment_bp.route("/tasks/<uuid:task_id>/environment", methods=["GET"])
@login_required
@role_required(["competitor"])
@api.validate(
    resp=Response(
        HTTP_200=TaskEnvironmentResponse,
        HTTP_403=ErrorResponse,
        HTTP_404=ErrorResponse,
        HTTP_409=ErrorResponse,
    ),
    tags=["Environment"],
    security=[{"cookieAuth": []}],
)
def get_task_environment(task_id: Any) -> dict[str, Any] | ErrorResult:
    """Return the task card's workspace status: not_open, preparing, ready, unknown or closed."""
    task = _student_task(task_id)
    if not isinstance(task, Task):
        return task
    owner = envs.owner_of_task(task)
    env = owner.environment()
    if env is None or not env.enabled:
        return err("ERR_ENVIRONMENT_NOT_ENABLED", 409)
    timezone = owner.challenge.timezone or "UTC"
    return {
        "status": envs.student_status(env, owner),
        "folder_name": task.folder_name,
        "open_path": solution_path(task),
        "starts_at": to_tz_iso(owner.start, timezone),
        "ends_at": to_tz_iso(owner.ends_at, timezone),
    }


@environment_bp.route("/tasks/<uuid:task_id>/environment/launch", methods=["POST"])
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
    tags=["Environment"],
    security=[{"cookieAuth": []}],
)
def launch_task_environment(
    task_id: Any,
) -> tuple[dict[str, Any], int, dict[str, str]] | ErrorResult:
    """Create the student's workspace on first use and return a single-use launch token."""
    task = _student_task(task_id)
    if not isinstance(task, Task):
        return task
    result = envs.launch_workspace(task, request.user["user_id"])
    if isinstance(result, tuple):
        return result
    return result, 200, {"Cache-Control": "no-store"}
