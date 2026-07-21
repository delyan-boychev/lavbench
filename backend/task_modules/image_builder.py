"""Pre-build Docker images with HuggingFace datasets baked in.

Each task gets a persistent directory at ``TASK_IMAGES_DIR/task_{id}/``
containing downloaded HF datasets, a generated Dockerfile, and
requirements.txt.  The image is tagged ``lavbench_task_{task_id}`` and
rebuilt only when the task config changes.

Datasets are downloaded ONCE per task, not per submission.  The image
owns the cache — no volume mounts, no cross-user lock file issues.
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

from cache_utils import get_redis_client
from config import Config
from task_modules.docker_utils import _get_client
from task_modules.docker_utils import image_exists as _image_exists

MIN_BUILD_DISK_GB = 5
BUILD_LOCK_TTL = 900  # 15 minutes — plenty for any build, short enough for stale locks
BUILD_LOCK_RETRY_INTERVAL = 10  # seconds between retries
BUILD_LOCK_MAX_WAIT = 300  # max seconds to block waiting for lock

logger = logging.getLogger(__name__)

TASK_IMAGES_DIR = Config.TASK_IMAGES_DIR

# Used to namespace Redis build locks per machine.
_WORKER_HOSTNAME = socket.gethostname()


def _report_build_error(
    task_id: str | None,
    error_msg: str,
    main_server_url: str | None = None,
    worker_token: str | None = None,
) -> None:
    if not task_id or not main_server_url or not worker_token:
        return
    try:
        import requests

        requests.post(
            f"{main_server_url.rstrip('/')}/api/worker/tasks/{task_id}/report-build-error",
            json={"error": error_msg},
            headers={"X-Worker-Token": worker_token},
            timeout=10,
        )
    except Exception:
        logger.debug("Failed to report build error for task %s", task_id)


# Used to namespace Redis build locks per machine.
_WORKER_HOSTNAME = socket.gethostname()


def _config_hash(
    base_image: str,
    pip_packages: str,
    hf_datasets: list[str],
    hf_models: list[str],
    task_files_hash: str,
    eval_code_hash: str,
) -> str:
    """Stable hash of the task configuration for cache invalidation."""
    h = hashlib.sha256()
    h.update(b"v2")
    h.update(base_image.encode())
    h.update(pip_packages.encode())
    h.update(json.dumps(sorted(hf_datasets), sort_keys=True).encode())
    h.update(json.dumps(sorted(hf_models), sort_keys=True).encode())
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
    filename: str,
    saved_name: str,
    dest_dir: str,
    metadata: dict[str, Any],
) -> None:
    main_server_url = metadata.get("_main_server_url", "")
    worker_token = metadata.get("_worker_token", "")
    if not main_server_url or not worker_token:
        logger.warning("Cannot download task file '%s': missing server URL or token", filename)
        return
    try:
        import requests

        url = f"{main_server_url.rstrip('/')}/api/worker/tasks/{task_id}/files/{filename}"
        res = requests.get(
            url,
            headers={"X-Worker-Token": worker_token},
            timeout=Config.WORKER_DOWNLOAD_TIMEOUT,
        )
        if res.status_code == 200:
            dest = os.path.join(dest_dir, filename)
            with open(dest, "wb") as f:
                f.write(res.content)
            os.chmod(dest, 0o644)
        else:
            logger.warning("Failed to download task file '%s': HTTP %s", filename, res.status_code)
    except Exception as e:
        logger.warning("Error downloading task file '%s': %s", filename, e)


def _download_dataset(
    ds_name: str, task_id: Any, hf_cache_dir: str, hf_api_key: str | None
) -> None:
    logger.info("Downloading dataset '%s' for task %s...", ds_name, task_id)

    # 1. Try the standard load_dataset — handles Parquet, CSV, JSONL, etc.
    try:
        from datasets import load_dataset  # type: ignore[import-untyped]

        load_dataset(ds_name, cache_dir=hf_cache_dir, token=hf_api_key or None)
        logger.info("load_dataset succeeded for '%s'", ds_name)
    except Exception as e:
        logger.warning("load_dataset failed for '%s': %s", ds_name, e)

    # 2. Snapshot-download the full repo — picks up .pkl, .yaml, and any
    #    other files that load_dataset doesn't recognise.
    #    Duplicate files are deduplicated by HF's cache layer (no extra cost).
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=ds_name,
            repo_type="dataset",
            cache_dir=os.path.join(hf_cache_dir, "hub"),
            token=hf_api_key or None,
        )
        logger.info("snapshot_download succeeded for '%s'", ds_name)
    except Exception as e:
        logger.warning("snapshot_download failed for '%s': %s", ds_name, e)


def _download_model(
    model_name: str, task_id: Any, hf_cache_dir: str, hf_api_key: str | None
) -> None:
    try:
        logger.info("Downloading model '%s' for task %s...", model_name, task_id)
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=model_name,
            cache_dir=os.path.join(hf_cache_dir, "hub"),
            token=hf_api_key or None,
        )
        logger.info("Successfully downloaded model '%s' for task %s", model_name, task_id)
    except Exception as e:
        logger.warning("Failed to download model '%s' for task %s: %s", model_name, task_id, e)


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


def _try_acquire_build_lock(task_id: int, timeout: int = 0) -> bool:
    """Try to acquire the build lock, optionally retrying up to *timeout* seconds."""
    r = get_redis_client()
    if not r:
        return False
    lock_key = _build_lock_key(task_id)
    deadline = time.time() + timeout if timeout > 0 else 0
    warned = False
    while True:
        acquired = False
        with contextlib.suppress(Exception):
            result = r.set(lock_key, _WORKER_HOSTNAME, nx=True, ex=BUILD_LOCK_TTL)
            if result is not None:
                acquired = bool(result)
        if acquired:
            return True
        if not warned:
            holder = ""
            with contextlib.suppress(Exception):
                val = r.get(lock_key)
                if val is not None:
                    holder = val.decode() if isinstance(val, bytes) else str(val)
            logger.info(
                "Build lock for task %s held by %s, waiting up to %ss...",
                task_id,
                holder or "unknown",
                int(deadline - time.time()) if deadline else 0,
            )
            warned = True
        if deadline and time.time() < deadline:
            time.sleep(BUILD_LOCK_RETRY_INTERVAL)
            continue
        return False


def _release_build_lock(task_id: int) -> None:
    r = get_redis_client()
    if r is None:
        return
    with contextlib.suppress(Exception):
        r.delete(_build_lock_key(task_id))


def build_task_image(
    metadata: dict[str, Any],
    log_callback: Callable[[str], None] | None = None,
) -> bool:
    """Build (or skip) a Docker image for a single task.

    Returns ``True`` if the image is ready (built or already up-to-date),
    ``False`` on build failure.

    If another build is in progress and returns within
    ``BUILD_LOCK_MAX_WAIT`` seconds, this call blocks waiting for it
    rather than immediately failing.

    Parameters are read from *metadata* (the same dict dispatched via
    Celery to ``evaluate_submission``):

    - ``task_id``
    - ``base_docker_image``
    - ``pip_requirements``
    - ``hf_datasets``   (JSON string or list)
    - ``hf_models``     (JSON string or list)
    - ``hf_api_key``    (optional, needed for private datasets)

    *log_callback* is called with each Docker build output line
    as it is produced, enabling real-time progress reporting.
    """
    task_id = metadata.get("task_id")
    if not task_id:
        logger.warning("build_task_image: no task_id in metadata")
        return False

    # Fast path: image already exists and is up-to-date
    tag = f"lavbench_task_{task_id}"
    if _image_exists(tag):
        existing_hash = ""
        meta_path = os.path.join(TASK_IMAGES_DIR, f"task_{task_id}", "hf_meta.json")
        if os.path.isfile(meta_path):
            with contextlib.suppress(Exception), open(meta_path) as f:
                existing_hash = json.load(f).get("hash", "")
        if existing_hash:
            _task_files_raw = metadata.get("task_files", [])
            if isinstance(_task_files_raw, str):
                with contextlib.suppress(json.JSONDecodeError, TypeError, ValueError):
                    _task_files_raw = json.loads(_task_files_raw)
            _task_files_list = _task_files_raw if isinstance(_task_files_raw, list) else []
            new_hash = _config_hash(
                metadata.get("base_docker_image", ""),
                metadata.get("pip_requirements", ""),
                metadata.get("hf_datasets", "[]"),
                metadata.get("hf_models", "[]"),
                _task_files_hash(_task_files_list),
                _eval_code_hash(metadata.get("custom_eval_code")),
            )
            if existing_hash == new_hash:
                logger.info("Task %s image up-to-date, skipping build", task_id)
                return True

    # Acquire lock — wait for another build to finish if one is in progress
    acquired = _try_acquire_build_lock(task_id, timeout=BUILD_LOCK_MAX_WAIT)
    if not acquired:
        logger.warning(
            "Build lock for task %s could not be acquired within %ss — another build may be stuck",
            task_id,
            BUILD_LOCK_MAX_WAIT,
        )
        # Final fallback: check if image now exists (the other build may have finished)
        return _image_exists(tag)

    try:
        return _do_build(metadata, log_callback=log_callback)
    finally:
        _release_build_lock(task_id)


def ensure_task_image(
    metadata: dict[str, Any],
    log_callback: Callable[[str], None] | None = None,
) -> bool:
    """Blocking build: retry until the image exists or the build fails.

    Unlike ``build_task_image`` (which skips if the lock is held),
    this function blocks for up to ``BUILD_LOCK_MAX_WAIT`` seconds,
    retries on transient failures, and only returns ``False`` when
    the build truly cannot succeed.
    """
    task_id = metadata.get("task_id")
    if not task_id:
        return False
    tag = f"lavbench_task_{task_id}"

    # Give the build up to 3 attempts
    for attempt in range(3):
        if attempt > 0:
            logger.info("Retrying image build for task %s (attempt %s/3)", task_id, attempt + 1)
        if build_task_image(metadata, log_callback=log_callback):
            return True
        if _image_exists(tag):
            return True
        time.sleep(BUILD_LOCK_RETRY_INTERVAL)
    return _image_exists(tag)


def _do_build(
    metadata: dict[str, Any],
    log_callback: Callable[[str], None] | None = None,
) -> bool:
    task_id = metadata.get("task_id")
    tag = f"lavbench_task_{task_id}"

    base_image = metadata.get("base_docker_image", "pytorch/pytorch:2.6.0-cuda12.6-cudnn9-runtime")
    pip_packages = metadata.get("pip_requirements", "")
    hf_datasets_raw = metadata.get("hf_datasets", "[]")
    hf_models_raw = metadata.get("hf_models", "[]")
    hf_api_key = metadata.get("hf_api_key", "") or ""

    if isinstance(hf_datasets_raw, str):
        try:
            hf_datasets_raw = json.loads(hf_datasets_raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            hf_datasets_raw = []
    hf_datasets_list = hf_datasets_raw if isinstance(hf_datasets_raw, list) else []

    if isinstance(hf_models_raw, str):
        try:
            hf_models_raw = json.loads(hf_models_raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            hf_models_raw = []
    hf_models_list = hf_models_raw if isinstance(hf_models_raw, list) else []

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
        hf_datasets_list,
        hf_models_list,
        _task_files_hash(task_files_list),
        _eval_code_hash(custom_eval_code),
    )
    task_dir = os.path.join(TASK_IMAGES_DIR, f"task_{task_id}")
    meta_path = os.path.join(task_dir, "hf_meta.json")
    hf_cache_dir = os.path.join(task_dir, "hf_cache")

    existing_hash = ""
    if os.path.isfile(meta_path):
        try:
            with open(meta_path) as f:
                existing_hash = json.load(f).get("hash", "")
        except Exception as e:
            logger.warning("Failed to read metadata file %s: %s", meta_path, e)

    if existing_hash == config_hash and _image_exists(tag):
        logger.info("Task %s image up-to-date (hash %s), skipping build", task_id, config_hash)
        return True

    logger.info("Building image for task %s (hash %s → %s)", task_id, existing_hash, config_hash)

    # Pre-build disk space check
    if not _check_build_disk_space():
        _report_build_error(
            task_id,
            "Insufficient disk space for build",
            metadata.get("_main_server_url"),
            metadata.get("_worker_token"),
        )
        return False

    os.makedirs(task_dir, exist_ok=True)

    # Clear previous datasets so we download fresh
    if os.path.isdir(hf_cache_dir):
        shutil.rmtree(hf_cache_dir, ignore_errors=True)
    os.makedirs(hf_cache_dir, exist_ok=True)

    for ds_name in hf_datasets_list:
        _download_dataset(ds_name, task_id, hf_cache_dir, hf_api_key)
    for model_name in hf_models_list:
        _download_model(model_name, task_id, hf_cache_dir, hf_api_key)

    # Download task resource files into build context
    task_data_dir = os.path.join(task_dir, "data")
    os.makedirs(task_data_dir, exist_ok=True)
    for tf in task_files_list:
        tf_filename = tf.get("filename", "")
        if tf_filename == "labels.parquet":
            continue
        tf_saved = tf.get("saved_name", tf_filename)
        upload_folder = getattr(Config, "UPLOAD_FOLDER", "")
        src_local = (
            os.path.join(upload_folder, f"task_{task_id}", tf_saved) if upload_folder else ""
        )
        if src_local and os.path.exists(src_local):
            shutil.copy2(src_local, os.path.join(task_data_dir, tf_filename))
            logger.debug("Copied task file '%s' from local storage", tf_filename)
        else:
            _download_task_file_for_build(task_id, tf_filename, tf_saved, task_data_dir, metadata)

    # Write evaluator script into build context
    if custom_eval_code:
        eval_path = os.path.join(task_dir, "evaluator_script.py")
        with open(eval_path, "w") as f:
            f.write(custom_eval_code)
        os.chmod(eval_path, 0o644)

    req_path = os.path.join(task_dir, "requirements.txt")
    with open(req_path, "w") as f:
        f.write(pip_packages.strip() or "# no extra packages")
    os.chmod(req_path, 0o644)

    dockerfile_lines = [f"FROM {shlex.quote(base_image)}"]
    if pip_packages.strip():
        dockerfile_lines.extend(
            [
                "COPY requirements.txt /tmp/requirements.txt",
                "RUN pip install --no-cache-dir -r /tmp/requirements.txt"
                " && rm /tmp/requirements.txt",
            ]
        )
    dockerfile_lines.append("COPY hf_cache /hf_cache")
    if task_files_list:
        dockerfile_lines.append("COPY data/ /app/data/")
    if custom_eval_code:
        dockerfile_lines.append("COPY evaluator_script.py /app/evaluator_script.py")

    dockerfile_path = os.path.join(task_dir, "Dockerfile")
    with open(dockerfile_path, "w") as f:
        f.write("\n".join(dockerfile_lines) + "\n")
    os.chmod(dockerfile_path, 0o644)

    logs: list[str] = []
    start = time.time()
    try:
        retcode, _stdout, _stderr, _ = _run_docker_build(tag, task_dir, logs, log_callback)
        elapsed = time.time() - start
        if retcode == 0:
            with open(meta_path, "w") as f:
                json.dump(
                    {
                        "hash": config_hash,
                        "datasets": hf_datasets_list,
                        "models": hf_models_list,
                        "build_features": 2,
                    },
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
                metadata.get("_worker_token"),
            )
            return True
        err_msg = logs[-1] if logs else f"Build failed (rc={retcode})"
        logger.error("Task %s image build failed (rc=%s): %s", task_id, retcode, err_msg)
        _report_build_error(
            task_id,
            err_msg,
            metadata.get("_main_server_url"),
            metadata.get("_worker_token"),
        )
        return False
    except Exception as e:
        err_msg = f"Build crashed: {e}"
        logger.exception("Task %s %s", task_id, err_msg)
        _report_build_error(
            task_id,
            err_msg,
            metadata.get("_main_server_url"),
            metadata.get("_worker_token"),
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
    r = get_redis_client()
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
    r = get_redis_client()
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


def build_all_active_tasks(main_server_url: str, worker_token: str) -> None:
    """Fetch active tasks from the server and build images for all of them."""
    _clear_stale_build_locks()
    import requests

    try:
        url = f"{main_server_url.rstrip('/')}/api/worker/active-tasks"
        res = requests.get(url, headers={"X-Worker-Token": worker_token}, timeout=30)
        if res.status_code != 200:
            logger.warning("Failed to fetch active tasks (HTTP %s)", res.status_code)
            return
        data = res.json()
        tasks = data.get("tasks", [])
        logger.info("Fetched %s active task(s) for image building", len(tasks))
        for task_config in tasks:
            metadata = {
                "task_id": task_config["id"],
                "base_docker_image": task_config.get("base_docker_image", ""),
                "pip_requirements": task_config.get("pip_requirements", ""),
                "hf_datasets": task_config.get("hf_datasets", "[]"),
                "hf_models": task_config.get("hf_models", "[]"),
                "hf_api_key": task_config.get("hf_api_key", ""),
                "task_files": task_config.get("task_files", []),
                "custom_eval_code": task_config.get("custom_eval_code", ""),
                "_main_server_url": main_server_url,
                "_worker_token": worker_token,
            }
            try:
                build_task_image(metadata)
            except Exception as e:
                logger.warning("Error building task %s image: %s", task_config.get("id"), e)
    except Exception as e:
        logger.warning("Error in build_all_active_tasks: %s", e)


def start_rebuild_listener(main_server_url: str, worker_token: str) -> None:
    """Start a background thread that listens for Redis task-rebuild notifications."""
    import threading

    t = threading.Thread(
        target=_rebuild_listener, args=(main_server_url, worker_token), daemon=True
    )
    t.start()
    logger.info("Rebuild listener thread started")


def _rebuild_listener(main_server_url: str, worker_token: str) -> None:
    """Background thread: subscribe to Redis 'task_rebuild' channel."""

    r = get_redis_client()
    if not r:
        logger.warning("Rebuild listener: no Redis client available")
        return
    try:
        pubsub = r.pubsub()
        pubsub.subscribe("task_rebuild")
        logger.info("Subscribed to Redis 'task_rebuild' channel")
        while True:
            msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=60)
            if msg and msg.get("type") == "message":
                try:
                    raw_data = msg.get("data")
                    task_id = (
                        raw_data.decode("utf-8") if isinstance(raw_data, bytes) else str(raw_data)
                    ).strip()
                    logger.info("Rebuild notification for task %s", task_id)
                    # Fetch updated config from the server
                    import requests

                    from worker_utils import _sign_worker_token

                    url = f"{main_server_url.rstrip('/')}/api/worker/active-tasks"
                    fresh_token = _sign_worker_token("worker")
                    res = requests.get(url, headers={"X-Worker-Token": fresh_token}, timeout=30)
                    if res.status_code == 200:
                        tasks = res.json().get("tasks", [])
                        for t in tasks:
                            if t["id"] == task_id:
                                metadata = {
                                    "task_id": t["id"],
                                    "base_docker_image": t.get("base_docker_image", ""),
                                    "pip_requirements": t.get("pip_requirements", ""),
                                    "hf_datasets": t.get("hf_datasets", "[]"),
                                    "hf_models": t.get("hf_models", "[]"),
                                    "hf_api_key": t.get("hf_api_key", ""),
                                    "task_files": t.get("task_files", []),
                                    "custom_eval_code": t.get("custom_eval_code", ""),
                                    "_main_server_url": main_server_url,
                                    "_worker_token": worker_token,
                                }
                                build_task_image(metadata)
                                break
                except Exception as e:
                    logger.warning("Error handling rebuild notification: %s", e)
    except Exception as e:
        logger.warning("Rebuild listener crashed: %s", e)
    finally:
        try:
            pubsub.unsubscribe()
            pubsub.close()
        except Exception as e:
            logger.debug("Error during Redis pubsub cleanup: %s", e)
