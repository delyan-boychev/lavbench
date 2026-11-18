"""Streamed task data uploads: one data file or the Hugging Face ZIP per request."""

from __future__ import annotations

import contextlib
import json
import logging
import os
from typing import Any

from flask import Blueprint, request
from flask import Response as FlaskResponse
from spectree import Response

from config import Config
from models import Task, db
from schemas.responses import ErrorResponse, TaskAdminResponse
from schemas.task import TaskFileDeleteQuery, TaskFileQuery
from services import environment_service, hf_zip
from services.audit_service import log_action
from services.baseline_service import schedule_baseline, set_problems
from services.environment_package import PackageError, check_projected, hf_source
from services.file_submission import (
    CheckBusyError,
    CheckFailedError,
    baseline_unreadable,
    check_baseline_file,
    check_labels,
    check_parquet,
    labels_sha256,
    parquet_rules,
    prune_label_cache,
    task_file_path,
)
from services.file_validation import check_dangerous_extension
from services.task_data import (
    hf_lock,
    owner_lock,
    remove_hf_zip_if_unreferenced,
    remove_unreferenced_hf_zip,
)
from utils.auth_utils import jury_access_required, rate_limit, role_required
from utils.cache import invalidate_entity_cache
from utils.error_utils import err, format_size
from utils.files import (
    BASELINE_SUBMISSION_FILE,
    LABELS_FILE,
    task_file_visibility,
    unique_saved_name,
    upload_root,
)
from utils.json_utils import safe_json_loads
from utils.spec import api
from utils.sse_utils import publish_environment_update
from utils.text import is_safe_path
from utils.uploads import ReceivedBody, busy, receive_body, store_lock

logger = logging.getLogger(__name__)
task_data_bp = Blueprint("task_data", __name__)

ErrorResult = tuple[FlaskResponse, int]
MAX_TASK_FILES = 5
MAX_FILENAME_CHARS = 255

_UPLOAD_ERRORS = {
    "HTTP_400": ErrorResponse,
    "HTTP_403": ErrorResponse,
    "HTTP_404": ErrorResponse,
    "HTTP_409": ErrorResponse,
    "HTTP_411": ErrorResponse,
    "HTTP_413": ErrorResponse,
    "HTTP_415": ErrorResponse,
    "HTTP_422": ErrorResponse,
    "HTTP_503": ErrorResponse,
    "HTTP_507": ErrorResponse,
}


def _task_dir(task_id: Any) -> str:
    return os.path.join(upload_root(), f"task_{task_id}")


def _files(task: Task) -> list[dict[str, Any]]:
    return [f for f in safe_json_loads(task.files, []) if isinstance(f, dict)]


def _after_change(task: Task, *, requeue: bool) -> None:
    """Caches, the admin's environment view (disk size, package) and the baseline."""
    challenge = task.challenge
    invalidate_entity_cache(task.challenge_id)
    if environment_service.environments_on(challenge):
        publish_environment_update(task.challenge_id)
    if requeue:
        schedule_baseline(task, request.user["user_id"])


def _published(task: Task) -> ErrorResult | None:
    return environment_service.task_files_locked(task.challenge, [task.stage_id])


def _change_blocked(task: Task, visibilities: set[str], reason: str | None) -> ErrorResult | None:
    """Public files freeze with the published package; hidden ones need an admin and a reason."""
    published = _published(task)
    if published is None:
        return None
    if "public" in visibilities:
        return published
    if request.user.get("role") != "admin":
        return err(
            "ERR_FORBIDDEN",
            403,
            message="Only an administrator can replace hidden files after publish.",
        )
    if not (reason or "").strip():
        return err(
            "ERR_REASON_REQUIRED",
            400,
            message="Give a reason for changing hidden files after publish.",
        )
    return None


def _projected(task: Task, **change: Any) -> ErrorResult | None:
    """The package caps and HF conflicts after this change, when environments are on."""
    if not environment_service.environments_on(task.challenge):
        return None
    owner = environment_service.owner_of_task(task)
    try:
        check_projected(owner.tasks(), task, **change)
    except PackageError as exc:
        if exc.code in ("ERR_ENVIRONMENT_PACKAGE_TOO_LARGE", "ERR_HF_FOLDER_CONFLICT"):
            return environment_service.package_error(exc)
        logger.info("Projected package of task %s not checked: %s", task.id, exc.message)
    return None


def _audit(task: Task, details: dict[str, Any], reason: str | None) -> None:
    log_action(
        admin_id=request.user["user_id"],
        action_type="update",
        target_type="task",
        target_id=task.id,
        details={"title": task.title, "challenge_id": str(task.challenge_id), **details},
        reason=(reason or "").strip() or None,
    )


# ── Task data files ──


def _name_refused(filename: str, visibility: str) -> ErrorResult | None:
    if (
        not filename.strip()
        or len(filename) > MAX_FILENAME_CHARS
        or "/" in filename
        or "\\" in filename
        or filename in (".", "..")
        or any(ord(c) < 32 for c in filename)
    ):
        return err("ERR_INVALID_FILENAME", 400, message=f"The file name '{filename}' is invalid.")
    if visibility == "public" and not is_safe_path(filename):
        return err(
            "ERR_INVALID_FILENAME",
            400,
            message=f"The file name '{filename}' cannot be used in a workspace.",
        )
    if check_dangerous_extension(filename):
        return err("ERR_INVALID_FILE_TYPE", 400, message=f"File type '{filename}' is not allowed.")
    return None


def _file_too_large(filename: str) -> ErrorResult:
    limit = format_size(Config.TASK_FILE_MAX_BYTES)
    return err(
        "ERR_FILE_TOO_LARGE", 413, message=f"{filename} exceeds the {limit} limit.", limit=limit
    )


def _file_checks(task: Task, filename: str, received: ReceivedBody) -> ErrorResult | None:
    """Labels in the limited child; a file task's baseline against the current labels.

    New labels are never refused because of the stored baseline: they install, and the
    baseline is re-checked after (``ERR_BASELINE_SUBMISSION_MISMATCH``).
    """
    rules = parquet_rules(task)
    file_mode = task.is_file_mode
    # No transaction stays open while the child process reads the files
    db.session.commit()
    try:
        if filename == LABELS_FILE:
            return check_labels(received.path, received.sha256)
        if filename == BASELINE_SUBMISSION_FILE and file_mode and rules.labels_path:
            return check_baseline_file(received.path, rules)
    except Exception:
        logger.exception("Checking %s of task %s failed", filename, task.id)
        db.session.rollback()
        if filename == LABELS_FILE:
            return err("ERR_LABELS_PARSE_FAILED", 400)
        return baseline_unreadable()
    return None


def _mismatch(task: Task, *, present: bool, fields: dict[str, Any] | None = None) -> None:
    set_problems(
        task, problem_codes=["ERR_BASELINE_SUBMISSION_MISMATCH"], present=present, fields=fields
    )


def _recheck_baseline(task: Task) -> None:
    """After new labels: flag a file task whose stored baseline no longer fits them."""
    baseline = task_file_path(task, BASELINE_SUBMISSION_FILE) if task.is_file_mode else None
    if baseline is None:
        _mismatch(task, present=False)
        return
    rules = parquet_rules(task)
    db.session.commit()
    try:
        problem = check_parquet(baseline, rules)
    except (CheckBusyError, CheckFailedError):
        # The debounced baseline run scores the file anyway and reports a failure
        logger.warning("The baseline of task %s was not re-checked against new labels", task.id)
        return
    if problem is None:
        _mismatch(task, present=False)
        return
    logger.info("Baseline of task %s does not fit the new labels: %s", task.id, problem[0])
    detail, counts = problem
    _mismatch(task, present=True, fields={"detail": detail, **counts})


def _install_file(
    task_id: Any, filename: str, visibility: str, received: ReceivedBody, reason: str | None
) -> Task | ErrorResult:
    """Under the task's lock: re-check the rules, rename into place and record the file."""
    with store_lock(owner_lock(db.get_or_404(Task, task_id))) as got:
        if not got:
            return busy()
        task = db.get_or_404(Task, task_id)
        files = _files(task)
        previous = next((f for f in files if f.get("filename") == filename), None)
        visibilities = {visibility}
        if previous is not None:
            visibilities.add(task_file_visibility(previous))
        blocked = _change_blocked(task, visibilities, reason)
        if blocked:
            return blocked
        if previous is None and len(files) >= MAX_TASK_FILES:
            return err("ERR_TOO_MANY_FILES", 400)
        if visibility == "public":
            refused = _projected(task, public_file=(filename, received.path))
            if refused:
                return refused
        saved_name = unique_saved_name(filename)
        os.makedirs(_task_dir(task_id), exist_ok=True)
        os.replace(received.path, os.path.join(_task_dir(task_id), saved_name))
        entry = {
            "filename": filename,
            "saved_name": saved_name,
            "size_bytes": received.size,
            "sha256": received.sha256,
            "visibility": visibility,
        }
        task.files = json.dumps([f for f in files if f.get("filename") != filename] + [entry])
        _audit(
            task,
            {
                "file": filename,
                "visibility": visibility,
                "sha256": received.sha256,
                "replaced_sha256": previous.get("sha256") if previous else None,
                "replaced_visibility": task_file_visibility(previous) if previous else None,
                "replaced_size_bytes": previous.get("size_bytes") if previous else None,
                "hidden_files_after_publish": _published(task) is not None,
            },
            reason,
        )
        db.session.commit()
    if previous is not None:
        with contextlib.suppress(OSError):
            os.remove(os.path.join(_task_dir(task_id), os.path.basename(previous["saved_name"])))
        if filename == LABELS_FILE and previous.get("sha256") != received.sha256:
            prune_label_cache(previous.get("sha256"))
    return task


@task_data_bp.route("/tasks/<uuid:task_id>/files/<string:filename>", methods=["PUT"])
@role_required(["admin", "jury"])
@jury_access_required
@rate_limit(max_requests=30, window_seconds=60)
@api.validate(
    query=TaskFileQuery,
    resp=Response(HTTP_200=TaskAdminResponse, **_UPLOAD_ERRORS),
    tags=["Tasks"],
    security=[{"cookieAuth": []}],
)
def upload_task_file(
    task_id: Any, filename: str, query: TaskFileQuery
) -> dict[str, Any] | ErrorResult:
    """Stream one public or hidden task data file as the raw request body."""
    task = db.get_or_404(Task, task_id)
    visibility = task_file_visibility({"filename": filename, "visibility": query.visibility})
    refused = _name_refused(filename, visibility)
    if refused:
        return refused
    files = _files(task)
    previous = next((f for f in files if f.get("filename") == filename), None)
    if previous is None and len(files) >= MAX_TASK_FILES:
        return err("ERR_TOO_MANY_FILES", 400)
    visibilities = {visibility} | ({task_file_visibility(previous)} if previous else set())
    blocked = _change_blocked(task, visibilities, query.reason)
    if blocked:
        return blocked
    received = receive_body(Config.TASK_FILE_MAX_BYTES, lambda: _file_too_large(filename))
    if not isinstance(received, ReceivedBody):
        return received
    try:
        refused = _file_checks(task, filename, received)
        result = refused or _install_file(task_id, filename, visibility, received, query.reason)
    finally:
        received.discard()
    if not isinstance(result, Task):
        if filename == LABELS_FILE:
            prune_label_cache(received.sha256)
        return result
    if filename == LABELS_FILE:
        _recheck_baseline(result)
    elif filename == BASELINE_SUBMISSION_FILE:
        _mismatch(result, present=False)
    _after_change(result, requeue=True)
    return result.to_dict(view_role=request.user["role"])


@task_data_bp.route("/tasks/<uuid:task_id>/files/<string:filename>", methods=["DELETE"])
@role_required(["admin", "jury"])
@jury_access_required
@rate_limit(max_requests=30, window_seconds=60)
@api.validate(
    query=TaskFileDeleteQuery,
    resp=Response(HTTP_200=TaskAdminResponse, **_UPLOAD_ERRORS),
    tags=["Tasks"],
    security=[{"cookieAuth": []}],
)
def delete_task_file(
    task_id: Any, filename: str, query: TaskFileDeleteQuery
) -> dict[str, Any] | ErrorResult:
    """Remove one task data file."""
    with store_lock(owner_lock(db.get_or_404(Task, task_id))) as got:
        if not got:
            return busy()
        task = db.get_or_404(Task, task_id)
        files = _files(task)
        previous = next((f for f in files if f.get("filename") == filename), None)
        if previous is None:
            return err("ERR_FILE_NOT_FOUND", 404)
        visibility = task_file_visibility(previous)
        blocked = _change_blocked(task, {visibility}, query.reason)
        if blocked:
            return blocked
        old_labels = labels_sha256(task.files)
        task.files = json.dumps([f for f in files if f.get("filename") != filename])
        _audit(
            task,
            {
                "file": filename,
                "visibility": visibility,
                "removed_sha256": previous.get("sha256"),
                "removed_size_bytes": previous.get("size_bytes"),
                "hidden_files_after_publish": _published(task) is not None,
            },
            query.reason,
        )
        db.session.commit()
    with contextlib.suppress(OSError):
        os.remove(os.path.join(_task_dir(task_id), os.path.basename(previous["saved_name"])))
    if filename == LABELS_FILE:
        prune_label_cache(old_labels)
    if filename in (LABELS_FILE, BASELINE_SUBMISSION_FILE):
        _mismatch(task, present=False)
    _after_change(task, requeue=True)
    return task.to_dict(view_role=request.user["role"])


# ── Hugging Face ZIP ──


def _hf_too_large(message: str | None = None) -> ErrorResult:
    limit = format_size(Config.HF_ZIP_MAX_BYTES)
    return err(
        "ERR_HF_ZIP_TOO_LARGE",
        413,
        message=message or f"The ZIP exceeds the {limit} limit.",
        limit=limit,
    )


def _set_hf(
    task: Task, summary: hf_zip.HfZipSummary | None, sha256: str | None, size: int | None
) -> None:
    task.hf_zip_sha256 = sha256
    task.hf_zip_size = size
    task.hf_unpacked_bytes = summary.unpacked_bytes if summary else None
    task.hf_file_count = summary.file_count if summary else None
    task.hf_folders = summary.folders if summary else None
    task.hf_skipped_count = summary.skipped_count if summary else None
    task.hf_zip_not_imported = False


def _install_hf(
    task_id: Any, received: ReceivedBody, summary: hf_zip.HfZipSummary
) -> Task | ErrorResult:
    """Under the owner's and the ZIP's locks: re-check, place the ZIP by hash, check the
    package and record it."""
    with store_lock(owner_lock(db.get_or_404(Task, task_id))) as got:
        if not got:
            return busy()
        task = db.get_or_404(Task, task_id)
        locked = environment_service.task_files_locked(task.challenge, [task.stage_id])
        if locked:
            return locked
        sha256 = received.sha256
        with store_lock(hf_lock(sha256)) as got_zip:
            if not got_zip:
                return busy()
            final = hf_zip.hf_zip_path(sha256)
            # The same bytes may be stored already: keep that file (and its mtime)
            placed = not os.path.exists(final)
            if placed:
                os.makedirs(hf_zip.hf_store_dir(), exist_ok=True)
                os.replace(received.path, final)
            refused = _projected(task, hf=hf_source(task, sha256, summary))
            if refused:
                if placed:
                    remove_hf_zip_if_unreferenced(sha256)
                return refused
            old = task.hf_zip_sha256
            _set_hf(task, summary, sha256, received.size)
            _audit(task, {"hf_zip": {"old_sha256": old, "new_sha256": sha256}}, None)
            db.session.commit()
    if old and old != sha256:
        remove_unreferenced_hf_zip(old)
    return task


def _hf_invalid(exc: hf_zip.HfZipError) -> ErrorResult:
    fields = {"file": exc.path} if exc.path else {}
    return err("ERR_HF_ZIP_INVALID", 422, message=exc.message, detail=exc.message, **fields)


@task_data_bp.route("/tasks/<uuid:task_id>/hf-zip", methods=["PUT"])
@role_required(["admin", "jury"])
@jury_access_required
@rate_limit(max_requests=10, window_seconds=60)
@api.validate(
    resp=Response(HTTP_200=TaskAdminResponse, **_UPLOAD_ERRORS),
    tags=["Tasks"],
    security=[{"cookieAuth": []}],
)
def upload_hf_zip(task_id: Any) -> dict[str, Any] | ErrorResult:
    """Stream the task's Hugging Face ZIP (``models/`` and ``datasets/``) as the raw body."""
    task = db.get_or_404(Task, task_id)
    locked = environment_service.task_files_locked(task.challenge, [task.stage_id])
    if locked:
        return locked
    received = receive_body(Config.HF_ZIP_MAX_BYTES, _hf_too_large)
    if not isinstance(received, ReceivedBody):
        return received
    try:
        try:
            summary = hf_zip.inspect_zip(received.path, max_unpacked=Config.HF_ZIP_MAX_BYTES)
        except hf_zip.HfZipError as exc:
            if exc.too_large:
                limit = format_size(Config.HF_ZIP_MAX_BYTES)
                return _hf_too_large(f"The unpacked files are larger than {limit}.")
            return _hf_invalid(exc)
        installed = _install_hf(task_id, received, summary)
    finally:
        received.discard()
    if not isinstance(installed, Task):
        return installed
    _after_change(installed, requeue=not installed.is_file_mode)
    return installed.to_dict(view_role=request.user["role"])


@task_data_bp.route("/tasks/<uuid:task_id>/hf-zip", methods=["DELETE"])
@role_required(["admin", "jury"])
@jury_access_required
@rate_limit(max_requests=10, window_seconds=60)
@api.validate(
    resp=Response(HTTP_200=TaskAdminResponse, **_UPLOAD_ERRORS),
    tags=["Tasks"],
    security=[{"cookieAuth": []}],
)
def delete_hf_zip(task_id: Any) -> dict[str, Any] | ErrorResult:
    """Remove the task's Hugging Face data and clear the not-imported flag."""
    with store_lock(owner_lock(db.get_or_404(Task, task_id))) as got:
        if not got:
            return busy()
        task = db.get_or_404(Task, task_id)
        locked = environment_service.task_files_locked(task.challenge, [task.stage_id])
        if locked:
            return locked
        old = task.hf_zip_sha256
        _set_hf(task, None, None, None)
        _audit(task, {"hf_zip": {"old_sha256": old, "new_sha256": None}}, None)
        db.session.commit()
    if old:
        remove_unreferenced_hf_zip(old)
    _after_change(task, requeue=bool(old) and not task.is_file_mode)
    return task.to_dict(view_role=request.user["role"])
