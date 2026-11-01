"""Stage compute sync, environment launch and submit-from-workspace through nano-colab."""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import os
from datetime import UTC, datetime
from typing import Any

from flask import Response

from config import Config
from models import Stage, StageCompute, StageWorkspace, Task, WorkspaceExport, db
from services import stage_package
from services.csv_submission import accept_workspace_csv
from services.nanocolab_client import NanoColabClient, NanoColabError, NanoColabUnavailableError
from utils.audit import log_audit
from utils.dates import utcnow
from utils.error_utils import err

logger = logging.getLogger(__name__)

ErrorResult = tuple[Response, int]
IMMUTABLE_AFTER_PUBLISH = (
    "compute_kind",
    "cpu_cores",
    "memory_gib",
    "disk_gib",
    "gpu_type",
    "image_id",
    "max_attendance",
    "retention_days",
)


def event_external_id(stage: Stage) -> str:
    return f"stage-{stage.id}"


def external_user_id(user_id: Any) -> str:
    return str(user_id).lower()


def _utc_iso(value: datetime) -> str:
    return value.replace(tzinfo=UTC).isoformat()


def declared_paths(stage: Stage) -> list[str]:
    paths: set[str] = set()
    for task in Task.query.filter_by(stage_id=stage.id).all():
        for path in (task.workspace_submission_path, task.workspace_notebook_path):
            if path:
                paths.add(path)
    return sorted(paths)


def event_payload(stage: Stage, compute: StageCompute, actor_id: Any) -> dict[str, Any]:
    name = f"{stage.challenge.title} - {stage.title}"[:200]
    return {
        "name": name if len(name) >= 3 else f"Stage {stage.stage_number}",
        "starts_at": _utc_iso(stage.start_time),
        "ends_at": _utc_iso(stage.end_time),
        "profile": {
            "compute_kind": compute.compute_kind,
            "cpu_cores": compute.cpu_cores,
            "memory_gib": compute.memory_gib,
            "disk_gib": compute.disk_gib,
            "gpu_type": compute.gpu_type if compute.compute_kind == "GPU" else None,
        },
        "image_id": compute.image_id,
        "asset_version": compute.asset_version,
        "max_attendance": compute.max_attendance,
        "retention_days": compute.retention_days,
        "published": compute.published,
        "export_paths": declared_paths(stage),
        "actor": str(actor_id),
    }


def compute_for(stage: Stage) -> StageCompute | None:
    return db.session.get(StageCompute, stage.id)


def is_live_compute(compute: StageCompute | None) -> bool:
    return bool(compute and compute.enabled and compute.published)


def stage_edit_blocked(stage: Stage, new_start: datetime, new_end: datetime) -> ErrorResult | None:
    if is_live_compute(compute_for(stage)) and (
        new_start != stage.start_time or new_end < stage.end_time
    ):
        return err("ERR_STAGE_COMPUTE_LOCKED", 409)
    return None


def stage_delete_blocked(stage: Stage) -> ErrorResult | None:
    if is_live_compute(compute_for(stage)):
        return err("ERR_STAGE_COMPUTE_LOCKED", 409)
    return None


def compute_update_blocked(compute: StageCompute, values: dict[str, Any]) -> ErrorResult | None:
    if not compute.published:
        return None
    if not values.get("published", True) or not values.get("enabled", True):
        return err("ERR_STAGE_COMPUTE_LOCKED", 409)
    if any(
        values.get(key, getattr(compute, key)) != getattr(compute, key)
        for key in IMMUTABLE_AFTER_PUBLISH
    ):
        return err("ERR_STAGE_COMPUTE_LOCKED", 409)
    return None


SYNCED = "SYNCED"
PACKAGING = "PACKAGING"
PACKAGE_FAILED = "PACKAGE_FAILED"
FAILED = "FAILED"
VALIDATING_STATES = frozenset({"UPLOADING", "QUEUED", "PROCESSING"})


def _apply_asset_state(compute: StageCompute, asset: dict[str, Any]) -> None:
    state = str(asset.get("state") or "")
    if state == "READY":
        compute.package_state, compute.package_error = "READY", None
    elif state in VALIDATING_STATES:
        compute.package_state, compute.package_error = "VALIDATING", None
    else:
        compute.package_state = "FAILED"
        compute.package_error = str(asset.get("error") or "Task package validation failed.")[:255]


def _publish_package(client: NanoColabClient, built: stage_package.BuiltPackage) -> dict[str, Any]:
    started = client.start_asset_upload(built.version, built.size, built.sha256)
    if started.get("upload"):
        client.upload_asset(started["upload"], built.path)
    if started.get("state") in {"UPLOADING", "QUEUED"}:
        return client.complete_asset_upload(built.version)
    return started


def ensure_package(stage: Stage, compute: StageCompute, client: NanoColabClient) -> None:
    if compute.published and compute.package_state == "READY" and compute.asset_version:
        return
    entries = stage_package.package_entries(stage)
    if not entries:
        compute.package_state, compute.package_error = "FAILED", "ERR_STAGE_PACKAGE_EMPTY"
        compute.package_fingerprint = None
        return
    current = stage_package.fingerprint(entries)
    if compute.package_fingerprint == current and compute.asset_version:
        if compute.package_state == "READY":
            return
        if compute.package_state == "VALIDATING":
            _apply_asset_state(compute, client.get_asset(compute.asset_version))
            return
    directory = os.path.join(Config.UPLOAD_FOLDER, "stage_packages")
    built = stage_package.build(entries, directory)
    try:
        asset = _publish_package(client, built)
    finally:
        os.unlink(built.path)
    compute.asset_version = built.version
    compute.package_fingerprint = current
    _apply_asset_state(compute, asset)


def sync_stage(stage: Stage, actor_id: Any) -> str:
    compute = compute_for(stage)
    if not compute or not compute.enabled:
        return SYNCED
    client = NanoColabClient.from_config()
    error: str | None = None
    result = SYNCED
    if client is None:
        error = "not_configured"
    else:
        try:
            ensure_package(stage, compute, client)
            if compute.package_state == "READY":
                event = client.put_event(
                    event_external_id(stage), event_payload(stage, compute, actor_id)
                )
                compute.nanocolab_event_id = event.get("event_id")
                compute.image_digest = str(event.get("environment_digest") or "")[:500]
            else:
                result = PACKAGE_FAILED if compute.package_state == "FAILED" else PACKAGING
        except NanoColabError as exc:
            error = f"http_{exc.status}"
            logger.warning("Stage %s compute sync failed with status %s", stage.id, exc.status)
    if error:
        result = FAILED
    compute.sync_state = {SYNCED: "SYNCED", PACKAGING: "PACKAGING"}.get(result, "FAILED")
    compute.last_sync_error = error or ("package_invalid" if result == PACKAGE_FAILED else None)
    if result == SYNCED:
        compute.last_synced_at = utcnow()
    db.session.commit()
    log_audit(
        actor_id,
        "sync",
        "stage_compute",
        target_id=stage.id,
        details={"result": compute.sync_state, "asset_version": compute.asset_version},
    )
    db.session.commit()
    return result


def task_files_locked(stage_ids: list[Any]) -> ErrorResult | None:
    for stage_id in stage_ids:
        if not stage_id:
            continue
        stage = Stage.query.filter_by(id=stage_id).first()
        if stage is not None and is_live_compute(compute_for(stage)):
            return err("ERR_TASK_FILES_LOCKED", 409)
    return None


def _client() -> NanoColabClient | ErrorResult:
    client = NanoColabClient.from_config()
    return client if client else err("ERR_COMPUTE_UNAVAILABLE", 503)


def workspace_images() -> list[dict[str, Any]] | ErrorResult:
    client = _client()
    if not isinstance(client, NanoColabClient):
        return client
    try:
        images: list[dict[str, Any]] = client.list_images().get("images", [])
    except NanoColabError:
        return err("ERR_COMPUTE_UNAVAILABLE", 503)
    return images


def image_choice_blocked(image_id: str) -> ErrorResult | None:
    if NanoColabClient.from_config() is None:
        return None
    images = workspace_images()
    if isinstance(images, tuple):
        return images
    if not any(image.get("image_id") == image_id for image in images):
        return err("ERR_INVALID_WORKSPACE_IMAGE", 400)
    return None


def environment_status(stage: Stage) -> dict[str, Any]:
    compute = compute_for(stage)
    now = utcnow()
    status = {"status": "unavailable", "retry_after_seconds": None, "message": None}
    if not is_live_compute(compute):
        return status
    if now < stage.start_time:
        return {**status, "status": "not_started"}
    if now >= stage.end_time:
        return {**status, "status": "closed"}
    client = NanoColabClient.from_config()
    if client is None:
        return status
    try:
        readiness = client.get_readiness(event_external_id(stage))
    except NanoColabError:
        return {**status, "status": "preparing", "retry_after_seconds": 10}
    mapped = {"READY": "ready", "PREPARING": "preparing", "BLOCKED": "blocked"}
    return {
        "status": mapped.get(readiness.get("status", ""), "preparing"),
        "retry_after_seconds": readiness.get("retry_after_seconds"),
        "message": readiness.get("message"),
    }


def _map_launch_error(exc: NanoColabError) -> ErrorResult:
    if isinstance(exc, NanoColabUnavailableError) and exc.retry_after:
        response, status = err("ERR_ENVIRONMENT_PREPARING", 503)
        response.headers["Retry-After"] = str(exc.retry_after)
        return response, status
    if isinstance(exc, NanoColabUnavailableError):
        return err("ERR_COMPUTE_UNAVAILABLE", 503)
    if exc.status == 409 and "maximum attendance" in str(exc.detail or ""):
        return err("ERR_ENVIRONMENT_FULL", 409)
    if exc.status in {404, 409}:
        return err("ERR_ENVIRONMENT_NOT_OPEN", 409)
    return err("ERR_COMPUTE_UNAVAILABLE", 503)


def launch_environment(stage: Stage, user_id: Any) -> dict[str, Any] | ErrorResult:
    if not is_live_compute(compute_for(stage)):
        return err("ERR_COMPUTE_NOT_ENABLED", 404)
    now = utcnow()
    if not stage.start_time <= now < stage.end_time:
        return err("ERR_ENVIRONMENT_NOT_OPEN", 409)
    client = _client()
    if not isinstance(client, NanoColabClient):
        return client
    subject = external_user_id(user_id)
    try:
        workspace = client.ensure_workspace(event_external_id(stage), subject)
        mapping = StageWorkspace.query.filter_by(stage_id=stage.id, user_id=user_id).first()
        if mapping is None:
            db.session.add(
                StageWorkspace(
                    stage_id=stage.id, user_id=user_id, workspace_id=workspace["workspace_id"]
                )
            )
            db.session.commit()
        launch = client.launch(workspace["workspace_id"], subject)
    except NanoColabError as exc:
        return _map_launch_error(exc)
    log_audit(
        user_id,
        "launch",
        "environment",
        target_id=stage.id,
        details={"workspace_id": workspace["workspace_id"]},
    )
    db.session.commit()
    return {
        "launch_url": launch["launch_url"],
        "launch_token": launch["launch_token"],
        "expires_at": launch["expires_at"],
    }


def _decoded(item: dict[str, Any]) -> bytes | None:
    try:
        data = base64.b64decode(item.get("content_base64") or "", validate=True)
    except (binascii.Error, ValueError):
        return None
    if (
        len(data) != item.get("size")
        or len(data) > Config.NANOCOLAB_EXPORT_MAX_BYTES
        or hashlib.sha256(data).hexdigest() != item.get("sha256")
    ):
        return None
    return data


def _store(directory: str, name: str, data: bytes) -> str:
    os.makedirs(directory, mode=0o700, exist_ok=True)
    path = os.path.join(directory, name)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def _map_export_error(exc: NanoColabError) -> ErrorResult:
    if exc.status == 409:
        response, status = err("ERR_WORKSPACE_EXPORT_UNAVAILABLE", 409)
        if exc.retry_after:
            response.headers["Retry-After"] = str(exc.retry_after)
        return response, status
    if exc.status == 403:
        return err("ERR_COMPUTE_SYNC_FAILED", 409)
    if exc.status in {404, 410}:
        return err("ERR_WORKSPACE_NOT_FOUND", 404)
    return err("ERR_COMPUTE_UNAVAILABLE", 503)


def submit_from_workspace(task: Task, stage: Stage, user_id: Any) -> dict[str, Any] | ErrorResult:
    if not task.workspace_submission_path or not is_live_compute(compute_for(stage)):
        return err("ERR_TASK_NOT_WORKSPACE_BACKED", 400)
    mapping = StageWorkspace.query.filter_by(stage_id=stage.id, user_id=user_id).first()
    if mapping is None:
        return err("ERR_WORKSPACE_NOT_FOUND", 404)
    client = _client()
    if not isinstance(client, NanoColabClient):
        return client
    paths = [task.workspace_submission_path]
    if task.workspace_notebook_path:
        paths.append(task.workspace_notebook_path)
    try:
        result = client.export(mapping.workspace_id, external_user_id(user_id), paths)
    except NanoColabError as exc:
        return _map_export_error(exc)
    files = {item.get("path"): item for item in result.get("files", [])}
    csv_item = files.get(task.workspace_submission_path) or {"status": "MISSING"}
    if csv_item.get("status") == "MISSING":
        return err("ERR_WORKSPACE_FILE_MISSING", 400)
    if csv_item.get("status") == "TOO_LARGE":
        return err("ERR_WORKSPACE_FILE_TOO_LARGE", 413)
    csv_bytes = _decoded(csv_item)
    notebook_item = files.get(task.workspace_notebook_path or "")
    notebook_bytes = (
        _decoded(notebook_item) if notebook_item and notebook_item.get("status") == "OK" else None
    )
    if csv_bytes is None or (
        notebook_item and notebook_item.get("status") == "OK" and notebook_bytes is None
    ):
        return err("ERR_WORKSPACE_EXPORT_INTEGRITY", 502)
    export = WorkspaceExport(
        user_id=user_id,
        task_id=task.id,
        stage_id=stage.id,
        workspace_id=mapping.workspace_id,
        source=str(result.get("source", "LIVE"))[:16],
        exported_at=utcnow(),
        csv_path="",
        csv_sha256=csv_item["sha256"],
        csv_size=len(csv_bytes),
        notebook_sha256=notebook_item["sha256"]
        if notebook_bytes is not None and notebook_item
        else None,
        notebook_size=len(notebook_bytes) if notebook_bytes is not None else None,
    )
    db.session.add(export)
    db.session.flush()
    directory = os.path.join(
        Config.UPLOAD_FOLDER, "workspace_exports", str(user_id), str(export.id)
    )
    export.csv_path = _store(directory, "submission.csv", csv_bytes)
    if notebook_bytes is not None:
        export.notebook_path = _store(directory, "notebook.ipynb", notebook_bytes)
    submission = accept_workspace_csv(
        user_id=user_id, task=task, csv_bytes=csv_bytes, export=export
    )
    export.submission_id = submission.id
    db.session.commit()
    log_audit(
        user_id,
        "submit_from_workspace",
        "task",
        target_id=task.id,
        details={
            "export_id": str(export.id),
            "csv_sha256": export.csv_sha256,
            "source": export.source,
        },
    )
    db.session.commit()
    return {"submission_id": submission.id, "status": submission.status, "export": export.to_dict()}
