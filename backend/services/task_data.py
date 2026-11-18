"""Task data on the web host: streamed data files and the shared Hugging Face ZIP store."""

from __future__ import annotations

import contextlib
import logging
import os
import time
from typing import Any

from models import Submission, Task, db
from services import hf_zip
from utils.cache_utils import cache_lock
from utils.files import BASELINE_SUBMISSION_FILE, LABELS_FILE, upload_root
from utils.json_utils import safe_json_loads
from utils.uploads import INCOMING_MAX_AGE_SECONDS, store_lock

logger = logging.getLogger(__name__)

ACTIVE_RUN_STATUSES = ("queued", "running")


def owner_lock(task: Task, stage_id: Any = None) -> str:
    """One lock per environment owner (stage, or the competition without stages): file and
    HF installs of its tasks run one at a time, so their package projections cannot race.

    ``stage_id`` names the owner a task moves to instead of its current one.
    """
    stage = stage_id if stage_id is not None else task.stage_id
    return f"owner:{task.challenge_id}:{stage or '-'}"


def hf_lock(sha256: str) -> str:
    """Placing and deleting one stored ZIP, which tasks of any owner may share."""
    return f"hf:{sha256}"


def hf_zip_referenced(sha256: str) -> bool:
    """A task holds the ZIP, or a queued or running notebook run recorded it at dispatch."""
    if Task.query.filter_by(hf_zip_sha256=sha256).first() is not None:
        return True
    active = Submission.query.filter(
        Submission.hf_zip_sha256 == sha256, Submission.status.in_(ACTIVE_RUN_STATUSES)
    ).first()
    return active is not None


def remove_hf_zip_if_unreferenced(sha256: str) -> bool:
    """Delete a stored ZIP nothing uses; call while holding its ``hf_lock``."""
    if hf_zip_referenced(sha256):
        return False
    try:
        os.remove(hf_zip.hf_zip_path(sha256))
    except OSError:
        return False
    return True


def remove_unreferenced_hf_zip(sha256: str) -> None:
    """Take the ZIP's lock, then delete it if nothing references it any more."""
    with store_lock(hf_lock(sha256)) as got:
        if not got:
            logger.warning("HF store busy; %s.zip stays until the daily sweep", sha256)
            return
        remove_hf_zip_if_unreferenced(sha256)


def sweep_hf_store() -> int:
    """Delete stored ZIPs superseded while runs still used them, once nothing does."""
    directory = hf_zip.hf_store_dir()
    if not os.path.isdir(directory):
        return 0
    removed = 0
    for entry in os.scandir(directory):
        sha256 = entry.name.removesuffix(".zip")
        if not entry.name.endswith(".zip") or not hf_zip.SHA256_RE.fullmatch(sha256):
            continue
        with cache_lock(f"upload_store:{hf_lock(sha256)}", ttl=60) as got:
            if got and remove_hf_zip_if_unreferenced(sha256):
                removed += 1
    return removed


def _entries(task: Task) -> list[dict[str, Any]]:
    return [entry for entry in safe_json_loads(task.files, []) if isinstance(entry, dict)]


def _task_dir(task: Task) -> str:
    return os.path.join(upload_root(), f"task_{task.id}")


def export_files(task: Task) -> list[tuple[str, str]]:
    """``(path, path inside the task folder)`` of every file the task's row points at."""
    task_dir = _task_dir(task)
    found: dict[str, str] = {}
    for entry in _entries(task):
        saved = os.path.basename(str(entry.get("saved_name") or ""))
        if saved:
            found[os.path.join(task_dir, saved)] = saved
    for path in (
        task.evaluator_script_path,
        task.baseline_notebook_path,
        task.solution_notebook_path,
    ):
        relative = os.path.relpath(path, task_dir) if path else ".."
        if not relative.startswith(".."):
            found[str(path)] = relative.replace(os.sep, "/")
    return [
        (path, relative)
        for path, relative in found.items()
        if os.path.isfile(path) and not os.path.islink(path)
    ]


def sweep_task_dirs(now: float | None = None) -> int:
    """Delete top-level files a crash left between their rename and the commit listing them."""
    cutoff = (now or time.time()) - INCOMING_MAX_AGE_SECONDS
    removed = 0
    for task in Task.query.all():
        task_dir = _task_dir(task)
        if not os.path.isdir(task_dir):
            continue
        keep = {relative.split("/")[0] for _, relative in export_files(task)}
        for entry in os.scandir(task_dir):
            with contextlib.suppress(OSError):
                if (
                    entry.name not in keep
                    and entry.is_file(follow_symlinks=False)
                    and entry.stat().st_mtime < cutoff
                ):
                    os.remove(entry.path)
                    removed += 1
    return removed


def problem_codes(task: Task) -> list[str]:
    """Stored readiness codes plus the ones read from the task's files: a missing hidden
    file, and an HF ZIP missing from the server (e.g. after a restore)."""
    codes = {c for c in task.problem_codes or [] if isinstance(c, str)}
    names = {entry.get("filename") for entry in _entries(task)}
    if LABELS_FILE not in names:
        codes.add("ERR_TASK_LABELS_MISSING")
    if task.is_file_mode and BASELINE_SUBMISSION_FILE not in names:
        codes.add("ERR_BASELINE_SUBMISSION_MISSING")
    if task.hf_zip_sha256 and not os.path.isfile(hf_zip.hf_zip_path(str(task.hf_zip_sha256))):
        codes.add("ERR_HF_ZIP_MISSING")
    return sorted(codes)


def sweep_upload_store() -> dict[str, int]:
    """The daily sweep: dead upload temps, unlisted task files and unused HF ZIPs."""
    from utils.uploads import sweep_incoming

    result = {
        "incoming": sweep_incoming(),
        "task_files": sweep_task_dirs(),
        "hf_zips": sweep_hf_store(),
    }
    db.session.remove()
    return result
