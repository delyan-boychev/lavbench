"""Pre-build one Docker image per task with its packages and public files.

Each task gets a persistent directory at ``TASK_IMAGES_DIR/task_{id}/``
containing the public files, a generated Dockerfile, and requirements.txt.
The image is tagged ``lavbench_task_{task_id}`` and rebuilt only when the
task config changes. Hugging Face data is not baked in: the runner mounts
the worker's extracted HF cache read-only.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import shlex
import shutil
import socket
import time
from collections.abc import Callable
from typing import Any

from config import Config
from utils.cache_utils import get_coordination_client, renewing_lock
from utils.files import task_file_visibility
from utils.worker_auth import worker_request_headers
from utils.worker_utils import (
    DOWNLOAD_TEMP_PREFIX,
    SANDBOX_GID,
    SANDBOX_UID,
    SANDBOX_WORKING_DIRS,
    copy_file_verified,
    download_file,
    entry_size,
)

from .docker_utils import _get_client
from .docker_utils import image_exists as _image_exists

MIN_BUILD_DISK_GB = 5
# The builder renews its lock every third of this, so a dead builder frees it within it
BUILD_LOCK_TTL = 120
BUILD_LOCK_RETRY_INTERVAL = 10  # Seconds between checks while another run builds

logger = logging.getLogger(__name__)

# The base of a task image without its own; pinned by digest so every worker builds the same
DEFAULT_BASE_IMAGE = (
    "python:3.10-slim@sha256:6ff506466f8b1e981719b468cc0023b8ef000b983cdec0eafe119d01f379e31d"
)

TASK_IMAGES_DIR = Config.TASK_IMAGES_DIR
# The config hash of the last successful build of a task's image
BUILD_META = "build_meta.json"

# Used to namespace Redis build locks per machine
_WORKER_HOSTNAME = socket.gethostname()


def _report_build_error(
    task_id: str | None,
    error_msg: str,
    main_server_url: str | None = None,
    worker_metadata: dict[str, Any] | None = None,
    problem_codes: list[str] | None = None,
) -> None:
    if not task_id or not main_server_url or not worker_metadata:
        return
    try:
        import requests

        payload: dict[str, Any] = {"error": error_msg}
        if problem_codes:
            payload["problem_codes"] = problem_codes
        requests.post(
            f"{main_server_url.rstrip('/')}/api/worker/tasks/{task_id}/report-build-error",
            json=payload,
            headers=worker_request_headers(worker_metadata, "report_build_error"),
            timeout=10,
        )
    except Exception:
        logger.debug("Failed to report build error for task %s", task_id)


def _config_hash(
    base_image: str,
    pip_packages: str,
    apt_packages: str,
    task_files_hash: str,
    eval_code_hash: str,
) -> str:
    """Stable hash of the task configuration for cache invalidation.

    Covers every *semantic* input to the image: base image, pip/apt packages,
    task resource files and evaluator dependency changes. Runtime-only fields
    (ram/time/gpu limits, metrics config, imports) deliberately do not
    participate — changing them must not trigger a rebuild.
    """
    h = hashlib.sha256()
    # Bump when the generated Dockerfile changes, so cached images are rebuilt
    h.update(b"v5")
    h.update(base_image.encode())
    h.update(pip_packages.encode())
    h.update(apt_packages.encode())
    h.update(task_files_hash.encode())
    h.update(eval_code_hash.encode())
    return h.hexdigest()[:16]


def _task_files_hash(task_files: list[dict[str, Any]]) -> str:
    if not task_files:
        return ""
    return hashlib.sha256(
        json.dumps(sorted(task_files, key=lambda x: x.get("filename", "")), sort_keys=True).encode()
    ).hexdigest()[:16]


def _eval_code_hash(custom_eval_code: str | None) -> str:
    return hashlib.sha256((custom_eval_code or "").encode()).hexdigest()[:16]


def _download_task_file_for_build(
    task_id: Any,
    entry: dict[str, Any],
    dest_dir: str,
    metadata: dict[str, Any],
) -> None:
    filename = entry.get("filename", "")
    main_server_url = metadata.get("_main_server_url", "")
    worker_metadata = metadata.get("_worker_metadata", {})
    if not main_server_url or not worker_metadata:
        raise RuntimeError(
            f"Cannot download task file '{filename}' for build: missing server URL or token"
        )
    url = f"{main_server_url.rstrip('/')}/api/worker/tasks/{task_id}/files/{filename}"
    try:
        download_file(
            url,
            worker_request_headers(worker_metadata, "task_file"),
            os.path.join(dest_dir, os.path.basename(filename)),
            size_bytes=entry_size(entry),
            sha256=entry.get("sha256"),
            lock=True,
        )
    except Exception as e:
        raise RuntimeError(f"Failed to download task file '{filename}' for build: {e}") from e


def _write_dockerignore(task_dir: str) -> None:
    """Keep locks, partial downloads and the host-only labels out of the build context."""
    with open(os.path.join(task_dir, ".dockerignore"), "w") as f:
        f.write(f".locks\nlabels\ndata/{DOWNLOAD_TEMP_PREFIX}*\n")


def _build_lock_key(task_id: int) -> str:
    return f"docker_build:lock:{_WORKER_HOSTNAME}:{task_id}"


def _check_build_disk_space() -> bool:
    task_images_dir = TASK_IMAGES_DIR
    try:
        os.makedirs(task_images_dir, exist_ok=True)
        usage = shutil.disk_usage(task_images_dir)
        free_gb = usage.free / (1024**3)
        if free_gb < MIN_BUILD_DISK_GB:
            logger.error(
                "Insufficient disk space for Docker build: %.1fGB free in %s (min %dGB required)",
                free_gb,
                task_images_dir,
                MIN_BUILD_DISK_GB,
            )
            return False
    except OSError as e:
        logger.warning("Disk space check failed: %s", e)
    return True


def _image_up_to_date(tag: str, task_id: Any, metadata: dict[str, Any]) -> bool:
    """Whether the task image exists and was built from the configuration in *metadata*."""
    if not _image_exists(tag):
        return False
    meta_path = os.path.join(TASK_IMAGES_DIR, f"task_{task_id}", BUILD_META)
    existing_hash = ""
    if os.path.isfile(meta_path):
        with contextlib.suppress(Exception), open(meta_path) as f:
            existing_hash = json.load(f).get("hash", "")
    if not existing_hash:
        return False
    task_files_raw = metadata.get("task_files", [])
    if isinstance(task_files_raw, str):
        with contextlib.suppress(json.JSONDecodeError, TypeError, ValueError):
            task_files_raw = json.loads(task_files_raw)
    task_files_list = task_files_raw if isinstance(task_files_raw, list) else []
    new_hash = _config_hash(
        metadata.get("base_docker_image") or DEFAULT_BASE_IMAGE,
        metadata.get("pip_requirements", ""),
        metadata.get("apt_packages", ""),
        _task_files_hash(task_files_list),
        _eval_code_hash(metadata.get("custom_eval_code")),
    )
    return bool(existing_hash == new_hash)


def build_task_image(
    metadata: dict[str, Any],
    log_callback: Callable[[str], None] | None = None,
    force_rebuild: bool = False,
    wait_seconds: float | None = None,
) -> bool:
    """Make the task image match *metadata*: skip, build, or wait for another run's build.

    ``False`` when the build failed or no current image appeared within *wait_seconds*
    (default ``IMAGE_BUILD_WAIT_SECONDS``). *log_callback* receives each build line.
    """
    task_id = metadata.get("task_id")
    if not task_id:
        logger.warning("build_task_image: no task_id in metadata")
        return False
    tag = f"lavbench_task_{task_id}"
    budget = Config.IMAGE_BUILD_WAIT_SECONDS if wait_seconds is None else wait_seconds
    deadline = time.monotonic() + budget
    told_waiting = False
    while True:
        if not force_rebuild and _image_up_to_date(tag, task_id, metadata):
            logger.info("Task %s image up-to-date, skipping build", task_id)
            return True
        with renewing_lock(_build_lock_key(task_id), ttl=BUILD_LOCK_TTL) as got:
            if got:
                # _do_build checks the configuration again: a build may have just finished
                return _do_build(metadata, log_callback=log_callback, force_rebuild=force_rebuild)
        if time.monotonic() >= deadline:
            logger.warning(
                "No current image for task %s after waiting %ss for another build",
                task_id,
                int(budget),
            )
            return False
        if not told_waiting:
            logger.info("Image of task %s is being built by another run; waiting", task_id)
            if log_callback:
                log_callback("Waiting for the task image that another run is building...")
            told_waiting = True
        time.sleep(BUILD_LOCK_RETRY_INTERVAL)


def ensure_task_image(
    metadata: dict[str, Any],
    log_callback: Callable[[str], None] | None = None,
) -> bool:
    """Up to 3 ``build_task_image`` attempts within ``IMAGE_BUILD_WAIT_SECONDS``; no older image."""
    deadline = time.monotonic() + Config.IMAGE_BUILD_WAIT_SECONDS
    for attempt in range(3):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if attempt > 0:
            logger.info(
                "Retrying image build for task %s (attempt %s/3)",
                metadata.get("task_id"),
                attempt + 1,
            )
        if build_task_image(metadata, log_callback=log_callback, wait_seconds=remaining):
            return True
        if attempt < 2:
            time.sleep(BUILD_LOCK_RETRY_INTERVAL)
    return False


def _do_build(
    metadata: dict[str, Any],
    log_callback: Callable[[str], None] | None = None,
    force_rebuild: bool = False,
) -> bool:
    task_id = metadata.get("task_id")
    tag = f"lavbench_task_{task_id}"

    base_image = metadata.get("base_docker_image") or DEFAULT_BASE_IMAGE
    pip_packages = metadata.get("pip_requirements", "")
    apt_packages = metadata.get("apt_packages", "")

    task_files_raw = metadata.get("task_files", [])
    if isinstance(task_files_raw, str):
        try:
            task_files_raw = json.loads(task_files_raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            task_files_raw = []
    task_files_list = task_files_raw if isinstance(task_files_raw, list) else []
    custom_eval_code = metadata.get("custom_eval_code", "") or ""

    config_hash = _config_hash(
        base_image,
        pip_packages,
        apt_packages,
        _task_files_hash(task_files_list),
        _eval_code_hash(custom_eval_code),
    )
    task_dir = os.path.join(TASK_IMAGES_DIR, f"task_{task_id}")
    meta_path = os.path.join(task_dir, BUILD_META)

    existing_hash = ""
    if os.path.isfile(meta_path):
        try:
            with open(meta_path) as f:
                existing_hash = json.load(f).get("hash", "")
        except Exception as e:
            logger.warning("Failed to read metadata file %s: %s", meta_path, e)

    if not force_rebuild and existing_hash == config_hash and _image_exists(tag):
        logger.info("Task %s image up-to-date (hash %s), skipping build", task_id, config_hash)
        return True

    logger.info("Building image for task %s (hash %s → %s)", task_id, existing_hash, config_hash)

    # Pre-build disk space check
    if not _check_build_disk_space():
        if log_callback:
            log_callback("Error: insufficient disk space for image build.")
        _report_build_error(
            task_id,
            "Insufficient disk space for build",
            metadata.get("_main_server_url"),
            metadata.get("_worker_metadata"),
        )
        return False

    os.makedirs(task_dir, exist_ok=True)

    # Download task resource files into build context
    task_data_dir = os.path.join(task_dir, "data")
    os.makedirs(task_data_dir, exist_ok=True)
    try:
        for tf in task_files_list:
            tf_filename = tf.get("filename", "")
            # Hidden files (labels, the baseline submission) never reach student code
            if task_file_visibility(tf) == "hidden":
                continue
            tf_saved = tf.get("saved_name", tf_filename)
            upload_folder = getattr(Config, "UPLOAD_FOLDER", "")
            src_local = (
                os.path.join(upload_folder, f"task_{task_id}", tf_saved) if upload_folder else ""
            )
            if src_local and os.path.exists(src_local):
                copy_file_verified(
                    src_local,
                    os.path.join(task_data_dir, os.path.basename(tf_filename)),
                    size_bytes=entry_size(tf),
                    sha256=tf.get("sha256"),
                )
                logger.debug("Copied task file '%s' from local storage", tf_filename)
            else:
                _download_task_file_for_build(task_id, tf, task_data_dir, metadata)
    except Exception as e:
        err_msg = f"Task file synchronization failed: {e}"
        logger.error("Task %s %s", task_id, err_msg)
        if log_callback:
            log_callback(err_msg)
        _report_build_error(
            task_id,
            err_msg,
            metadata.get("_main_server_url"),
            metadata.get("_worker_metadata"),
            problem_codes=["ERR_TASK_FILE_SYNC_FAILED"],
        )
        return False

    # Evaluator source is injected only into the later trusted evaluator sandbox
    with contextlib.suppress(FileNotFoundError):
        os.remove(os.path.join(task_dir, "evaluator_script.py"))

    req_path = os.path.join(task_dir, "requirements.txt")
    with open(req_path, "w") as f:
        f.write(pip_packages.strip() or "# no extra packages")
    os.chmod(req_path, 0o644)

    dockerfile_lines = [f"FROM {shlex.quote(base_image)}"]
    if apt_packages.strip():
        pkgs = " ".join(shlex.split(apt_packages))
        dockerfile_lines.append(
            "RUN apt-get update && apt-get install -y --no-install-recommends "
            f"{pkgs} && rm -rf /var/lib/apt/lists/*"
        )
    if pip_packages.strip():
        dockerfile_lines.extend(
            [
                "COPY requirements.txt /tmp/requirements.txt",
                "RUN pip install --no-cache-dir -r /tmp/requirements.txt"
                " && rm /tmp/requirements.txt",
            ]
        )
    if task_files_list:
        dockerfile_lines.append("COPY data/ /app/data/")
    # The sandbox mounts a fresh volume on each working directory, and Docker gives
    # An empty volume the ownership of the image directory it covers. Owning them
    # Here keeps them writable on Docker versions that ignore tar root metadata
    work_dirs = " ".join(SANDBOX_WORKING_DIRS)
    dockerfile_lines.append(
        f"RUN mkdir -p {work_dirs} && chown {SANDBOX_UID}:{SANDBOX_GID} {work_dirs}"
        f" && chmod 0755 {work_dirs}"
    )
    dockerfile_path = os.path.join(task_dir, "Dockerfile")
    with open(dockerfile_path, "w") as f:
        f.write("\n".join(dockerfile_lines) + "\n")
    os.chmod(dockerfile_path, 0o644)
    _write_dockerignore(task_dir)

    logs: list[str] = []
    start = time.time()
    try:
        retcode, _stdout, _stderr, _ = _run_docker_build(tag, task_dir, logs, log_callback)
        elapsed = time.time() - start
        if retcode == 0:
            with open(meta_path, "w") as f:
                json.dump(
                    {"hash": config_hash, "build_features": 3},
                    f,
                )
            logger.info(
                "Task %s image built successfully in %.1fs (tag: %s)",
                task_id,
                elapsed,
                tag,
            )
            _report_build_error(
                task_id,
                "",
                metadata.get("_main_server_url"),
                metadata.get("_worker_metadata"),
            )
            return True
        err_msg = logs[-1] if logs else f"Build failed (rc={retcode})"
        logger.error("Task %s image build failed (rc=%s): %s", task_id, retcode, err_msg)
        _report_build_error(
            task_id,
            err_msg,
            metadata.get("_main_server_url"),
            metadata.get("_worker_metadata"),
        )
        return False
    except Exception as e:
        err_msg = f"Build crashed: {e}"
        logger.exception("Task %s %s", task_id, err_msg)
        _report_build_error(
            task_id,
            err_msg,
            metadata.get("_main_server_url"),
            metadata.get("_worker_metadata"),
        )
        return False


def _run_docker_build(
    tag: str,
    build_dir: str,
    logs: list[str],
    log_callback: Callable[[str], None] | None = None,
) -> tuple[int, str, str, bool]:
    """Build Docker image using the SDK and capture output.

    Each build output line is logged via ``logger.info`` and forwarded
    to *log_callback* (if provided) so callers can stream progress to
    submission logs or other real-time channels.
    """
    client = _get_client()
    try:
        for entry in client.api.build(path=build_dir, tag=tag, rm=True, decode=True):
            if "stream" in entry:
                line = entry["stream"].rstrip("\n")
                if line:
                    logs.append(line)
                    logger.info("[build %s] %s", tag, line)
                    if log_callback:
                        log_callback(line)
            elif "status" in entry:
                status = entry["status"].rstrip(".")
                layer = entry.get("id", "")
                # Skip fine-grained progress detail to avoid log spam
                if layer or status not in ("Downloading", "Extracting"):
                    msg = f"{status} {layer}" if layer else status
                    logger.info("[build %s] %s", tag, msg)
            elif "error" in entry:
                err = entry["error"]
                logs.append(f"Docker build error: {err}")
                logger.error("[build %s] Error: %s", tag, err)
                return -1, "", err, False
        return 0, "", "", False
    except Exception as e:
        logs.append(f"Docker build failed: {e}")
        return -1, "", str(e), False


def clear_build_lock(task_id: int) -> bool:
    """Force-clear a stuck build lock for *task_id*.

    Intended for manual/admin use when a worker crashes mid-build.
    Returns ``True`` if a lock was actually held and cleared.
    """
    r = get_coordination_client()
    if not r:
        return False
    lock_key = _build_lock_key(task_id)
    try:
        deleted = r.delete(lock_key)
        if deleted:
            logger.info("Cleared stale build lock for task %s", task_id)
            return True
        logger.info("No build lock found for task %s", task_id)
        return False
    except Exception as e:
        logger.warning("Failed to clear build lock for task %s: %s", task_id, e)
        return False


def _clear_stale_build_locks() -> None:
    """Clear any build locks left by a previous instance of this worker."""
    r = get_coordination_client()
    if not r:
        return
    prefix = f"docker_build:lock:{_WORKER_HOSTNAME}:"
    try:
        cleared = 0
        for key in r.scan_iter(f"{prefix}*"):
            r.delete(key)
            cleared += 1
        if cleared:
            logger.info("Cleared %s stale build lock(s) for %s", cleared, _WORKER_HOSTNAME)
    except Exception as e:
        logger.warning("Failed to clear stale build locks: %s", e)
