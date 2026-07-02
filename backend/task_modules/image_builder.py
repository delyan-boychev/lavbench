"""Pre-build Docker images with HuggingFace datasets baked in.

Each task gets a persistent directory at ``TASK_IMAGES_DIR/task_{id}/``
containing downloaded HF datasets, a generated Dockerfile, and
requirements.txt.  The image is tagged ``lavbench_task_{task_id}`` and
rebuilt only when the task config changes.

Datasets are downloaded ONCE per task, not per submission.  The image
owns the cache — no volume mounts, no cross-user lock file issues.
"""

import contextlib
import hashlib
import json
import logging
import os
import shlex
import shutil
import time

from cache_utils import get_redis_client
from config import Config

from task_modules.docker_utils import _get_client
from task_modules.docker_utils import image_exists as _image_exists

MIN_BUILD_DISK_GB = 5

logger = logging.getLogger(__name__)

TASK_IMAGES_DIR = Config.TASK_IMAGES_DIR


def _config_hash(base_image, pip_packages, hf_datasets, hf_models):
    """Stable hash of the task configuration for cache invalidation."""
    h = hashlib.sha256()
    h.update(base_image.encode())
    h.update(pip_packages.encode())
    h.update(json.dumps(sorted(hf_datasets), sort_keys=True).encode())
    h.update(json.dumps(sorted(hf_models), sort_keys=True).encode())
    return h.hexdigest()[:16]


def _download_dataset(ds_name, task_id, hf_cache_dir, hf_api_key):
    try:
        logger.info("Downloading dataset '%s' for task %s...", ds_name, task_id)
        from datasets import load_dataset

        load_dataset(ds_name, cache_dir=hf_cache_dir, token=hf_api_key or None)
        logger.info("Successfully downloaded dataset '%s' for task %s", ds_name, task_id)
    except Exception as e:
        logger.warning("Failed to download dataset '%s' for task %s: %s", ds_name, task_id, e)


def _download_model(model_name, task_id, hf_cache_dir, hf_api_key):
    try:
        logger.info("Downloading model '%s' for task %s...", model_name, task_id)
        from huggingface_hub import snapshot_download

        snapshot_download(repo_id=model_name, cache_dir=hf_cache_dir, token=hf_api_key or None)
        logger.info("Successfully downloaded model '%s' for task %s", model_name, task_id)
    except Exception as e:
        logger.warning("Failed to download model '%s' for task %s: %s", model_name, task_id, e)


def _build_lock_key(task_id):
    return f"docker_build:lock:{task_id}"


def _check_build_disk_space():
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


def build_task_image(metadata):
    """Build (or skip) a Docker image for a single task.

    Parameters are read from *metadata* (the same dict dispatched via
    Celery to ``evaluate_submission``):

    - ``task_id``
    - ``base_docker_image``
    - ``pip_requirements``
    - ``hf_datasets``   (JSON string or list)
    - ``hf_models``     (JSON string or list)
    - ``hf_api_key``    (optional, needed for private datasets)
    """
    task_id = metadata.get("task_id")
    if not task_id:
        logger.warning("build_task_image: no task_id in metadata")
        return False

    # Acquire Redis lock to prevent concurrent builds for the same task
    r = get_redis_client()
    lock_key = _build_lock_key(task_id)
    lock_acquired = False
    if r:
        with contextlib.suppress(Exception):
            lock_acquired = r.set(lock_key, "1", nx=True, ex=3600)

    if not lock_acquired:
        logger.info("Build already in progress for task %s, skipping", task_id)
        return False

    try:
        return _do_build(metadata)
    finally:
        with contextlib.suppress(Exception):
            r.delete(lock_key)


def _do_build(metadata):
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

    config_hash = _config_hash(base_image, pip_packages, hf_datasets_list, hf_models_list)
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

    dockerfile_path = os.path.join(task_dir, "Dockerfile")
    with open(dockerfile_path, "w") as f:
        f.write("\n".join(dockerfile_lines) + "\n")
    os.chmod(dockerfile_path, 0o644)

    logs = []
    start = time.time()
    try:
        retcode, _stdout, _stderr, _ = _run_docker_build(tag, task_dir, logs)
        elapsed = time.time() - start
        if retcode == 0:
            with open(meta_path, "w") as f:
                json.dump(
                    {"hash": config_hash, "datasets": hf_datasets_list, "models": hf_models_list},
                    f,
                )
            logger.info(
                "Task %s image built successfully in %.1fs (tag: %s)",
                task_id,
                elapsed,
                tag,
            )
            return True
        logger.error("Task %s image build failed (rc=%s)\n%s", task_id, retcode, "\n".join(logs))
        return False
    except Exception as e:
        logger.exception("Task %s image build crashed: %s", task_id, e)
        return False


def _run_docker_build(tag, build_dir, logs):
    """Build Docker image using the SDK and capture output."""
    client = _get_client()
    try:
        build_logs = []
        _image, build_logs = client.images.build(path=build_dir, tag=tag, rm=True)
        for entry in build_logs:
            if "stream" in entry:
                line = entry["stream"].rstrip("\n")
                if line:
                    logs.append(line)
        return 0, "", "", False
    except Exception as e:
        logs.append(f"Docker build failed: {e}")
        return -1, "", str(e), False


def build_all_active_tasks(main_server_url, worker_token):
    """Fetch active tasks from the server and build images for all of them."""
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
            }
            try:
                build_task_image(metadata)
            except Exception as e:
                logger.warning("Error building task %s image: %s", task_config.get("id"), e)
    except Exception as e:
        logger.warning("Error in build_all_active_tasks: %s", e)


def start_rebuild_listener(main_server_url, worker_token):
    """Start a background thread that listens for Redis task-rebuild notifications."""
    import threading

    t = threading.Thread(
        target=_rebuild_listener, args=(main_server_url, worker_token), daemon=True
    )
    t.start()
    logger.info("Rebuild listener thread started")


def _rebuild_listener(main_server_url, worker_token):
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
