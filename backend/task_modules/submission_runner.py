"""Celery task for executing competitor submissions in Docker sandboxes."""

import contextlib
import fcntl
import json
import logging
import math
import os
import subprocess
import tempfile
import time
import traceback
from datetime import datetime

import requests
from cache_utils import get_redis_client
from celery.signals import worker_ready
from worker_utils import (
    MockModel,
    StreamingLogList,
    _sign_worker_token,
    download_labels_parquet_to_dir,
    download_task_files_to_dir,
    report_status_to_server,
    run_command_streaming,
)

from task_modules.docker_utils import _get_client, check_docker_available
from task_modules.docker_utils import image_exists as _image_exists_docker

logger = logging.getLogger(__name__)


def _fetch_hf_key_from_server(task_id, main_server_url, worker_token):
    if not task_id or not main_server_url or not worker_token:
        logger.warning(
            "_fetch_hf_key_from_server: missing params (task=%s url=%s has_token=%s)",
            task_id,
            main_server_url,
            bool(worker_token),
        )
        return ""
    try:
        res = requests.get(
            f"{main_server_url.rstrip('/')}/api/worker/tasks/{task_id}/hf-key",
            headers={"X-Worker-Token": worker_token},
            timeout=5,
        )
        if res.status_code == 200:
            return res.json().get("hf_key", "")
        logger.warning("_fetch_hf_key_from_server: HTTP %s for task %s", res.status_code, task_id)
    except Exception as e:
        logger.warning("_fetch_hf_key_from_server: request failed: %s", e)
    return ""


def _preload_dataset(load_fn, ds_name, hf_cache_dir, hf_token, logs):
    try:
        load_fn(ds_name, cache_dir=hf_cache_dir, token=hf_token)
        logs.append(f"Successfully preloaded dataset '{ds_name}' to host cache.")
    except Exception as preload_err:
        logs.append(f"Warning: Failed to preload dataset '{ds_name}': {preload_err}")


def _preload_model(download_fn, model_name, hf_cache_dir, hf_token, logs):
    try:
        download_fn(repo_id=model_name, cache_dir=hf_cache_dir, token=hf_token)
        logs.append(f"Successfully preloaded model '{model_name}' to host cache.")
    except Exception as preload_err:
        logs.append(f"Warning: Failed to preload model '{model_name}': {preload_err}")


def preload_submission_datasets(task, challenge, temp_dir, hf_cache_dir, logs):
    """
    Preloads HuggingFace datasets and models on the host so they are available offline in docker.
    """
    datasets_to_load = []
    models_to_load = []

    # 1. Gather Datasets
    if task and hasattr(task, "hf_datasets") and task.hf_datasets:
        import json

        ds_val = task.hf_datasets
        if isinstance(ds_val, str):
            try:
                ds_val = json.loads(ds_val)
            except (json.JSONDecodeError, TypeError, ValueError):
                ds_val = []
        if isinstance(ds_val, list):
            for ds in ds_val:
                if ds and ds not in datasets_to_load:
                    datasets_to_load.append(ds)

    # 2. Gather Models
    if task and hasattr(task, "hf_models") and task.hf_models:
        import json

        md_val = task.hf_models
        if isinstance(md_val, str):
            try:
                md_val = json.loads(md_val)
            except (json.JSONDecodeError, TypeError, ValueError):
                md_val = []
        if isinstance(md_val, list):
            for md in md_val:
                if md and md not in models_to_load:
                    models_to_load.append(md)

    hf_token = None
    if task and hasattr(task, "get_hf_api_key"):
        with contextlib.suppress(Exception):
            hf_token = task.get_hf_api_key()

    if not hf_token:
        hf_token = None

    # 3. Preload datasets
    if datasets_to_load and hf_cache_dir:
        logs.append(f"Preloading datasets on host: {datasets_to_load}...")
        try:
            from datasets import load_dataset as host_load_dataset

            for ds_name in datasets_to_load:
                _preload_dataset(host_load_dataset, ds_name, hf_cache_dir, hf_token, logs)
        except Exception as import_err:
            logs.append(f"Warning: Could not import 'datasets' on host to preload: {import_err}")

    # 4. Preload models
    if models_to_load and hf_cache_dir:
        logs.append(f"Preloading HF models on host: {models_to_load}...")
        try:
            from huggingface_hub import snapshot_download

            for model_name in models_to_load:
                _preload_model(snapshot_download, model_name, hf_cache_dir, hf_token, logs)
        except Exception as import_err:
            logs.append(
                f"Warning: Could not import 'huggingface_hub' "
                f"on host to preload models: {import_err}"
            )


def calculate_weighted_score(metrics_payload, metrics_cfg):
    from models import is_metric_lower_better

    if not metrics_cfg:
        if metrics_payload:
            m_name = next(iter(metrics_payload.keys()))
            val = metrics_payload[m_name]
            if math.isnan(val) or math.isinf(val):
                return 0.0
            if is_metric_lower_better(m_name):
                if m_name.lower().strip() == "brier_score":
                    return 1.0 - val
                return 1.0 / (1.0 + val) if val != -1.0 else 0.0
            return val
        return 0.0

    total_weight = sum(float(cfg.get("weight", 1.0)) for cfg in metrics_cfg.values())
    if total_weight == 0:
        return 0.0

    weighted_sum = 0.0
    for m_name, cfg in metrics_cfg.items():
        val = metrics_payload.get(m_name, 0.0)
        if math.isnan(val) or math.isinf(val):
            val = 0.0
        if is_metric_lower_better(m_name):
            if m_name.lower().strip() == "brier_score":
                norm_val = 1.0 - val
            else:
                norm_val = 1.0 / (1.0 + val) if val != -1.0 else 0.0
        else:
            norm_val = val
        if math.isnan(norm_val) or math.isinf(norm_val):
            norm_val = 0.0
        weight = float(cfg.get("weight", 1.0))
        weighted_sum += norm_val * weight
    return weighted_sum / total_weight


def run_eval_submission(self_task, submission_id, metadata, app, db, submission_cls, challenge_cls):
    running_as_worker = app is None
    # 1. Setup mock/real models
    if metadata:
        task = MockModel(
            id=metadata.get("task_id"),
            time_limit_sec=metadata.get("time_limit"),
            ram_limit_mb=metadata.get("ram_limit"),
            gpu_required=metadata.get("gpu_required"),
            base_docker_image=metadata.get("base_docker_image"),
            apt_packages=metadata.get("apt_packages"),
            pip_requirements=metadata.get("pip_requirements"),
            metrics_config=metadata.get("metrics_config"),
            public_eval_percentage=metadata.get("public_eval_percentage"),
            hf_datasets=metadata.get("hf_datasets"),
            hf_models=metadata.get("hf_models"),
            get_hf_api_key=lambda: _fetch_hf_key_from_server(
                metadata.get("task_id"),
                metadata.get("main_server_url"),
                _sign_worker_token(metadata.get("submission_id", "unknown")),
            ),
            evaluator_script_path=None,
            custom_eval_code=metadata.get("custom_eval_code"),
        )
        challenge = MockModel(
            id=metadata.get("challenge_id"),
            time_limit_sec=metadata.get("time_limit"),
            ram_limit_mb=metadata.get("ram_limit"),
            gpu_required=metadata.get("gpu_required"),
            metric_name=metadata.get("metric_name", "accuracy"),
            hf_dataset_split=metadata.get("hf_dataset_split", "test"),
        )
        submission = MockModel(
            id=submission_id,
            task_id=task.id,
            challenge_id=challenge.id,
            code_cells=json.dumps([metadata.get("user_code")]),
            status="queued",
            detailed_status="queued",
            logs="",
            gpu_node=None,
        )
    else:
        with app.app_context():
            db_submission = db.session.get(submission_cls, submission_id)
            if not db_submission:
                return f"Submission {submission_id} not found."
            # Idempotency: skip if already in a terminal state
            if db_submission.status in ("completed", "failed"):
                return (
                    f"Submission {submission_id} already in terminal state: {db_submission.status}"
                )
            db_submission.status = "running"
            db_submission.detailed_status = "running"
            db.session.commit()
            task = MockModel(
                id=db_submission.task.id if db_submission.task else None,
                time_limit_sec=db_submission.task.time_limit_sec if db_submission.task else None,
                ram_limit_mb=db_submission.task.ram_limit_mb if db_submission.task else None,
                gpu_required=db_submission.task.gpu_required if db_submission.task else None,
                base_docker_image=(
                    db_submission.task.base_docker_image if db_submission.task else None
                ),
                apt_packages=db_submission.task.apt_packages if db_submission.task else None,
                pip_requirements=(
                    db_submission.task.pip_requirements if db_submission.task else None
                ),
                metrics_config=db_submission.task.metrics_config if db_submission.task else None,
                public_eval_percentage=(
                    db_submission.task.public_eval_percentage if db_submission.task else None
                ),
                get_hf_api_key=lambda: (
                    db_submission.task.get_hf_api_key() if db_submission.task else ""
                ),
                evaluator_script_path=(
                    db_submission.task.evaluator_script_path if db_submission.task else None
                ),
                files=db_submission.task.files if db_submission.task else None,
                custom_eval_code=(
                    db_submission.task.custom_eval_code
                    if (db_submission.task and hasattr(db_submission.task, "custom_eval_code"))
                    else None
                ),
            )
            challenge = MockModel(
                id=db_submission.challenge.id if db_submission.challenge else None,
                time_limit_sec=(
                    db_submission.challenge.time_limit_sec if db_submission.challenge else None
                ),
                ram_limit_mb=(
                    db_submission.challenge.ram_limit_mb if db_submission.challenge else None
                ),
                gpu_required=(
                    db_submission.challenge.gpu_required if db_submission.challenge else None
                ),
            )
            submission = MockModel(
                id=db_submission.id,
                task_id=db_submission.task_id,
                challenge_id=db_submission.challenge_id,
                user_id=db_submission.user_id,
                code_cells=db_submission.code_cells,
                status=db_submission.status,
                detailed_status=db_submission.detailed_status,
                logs=db_submission.logs,
                gpu_node=db_submission.gpu_node,
            )

    # 2. Define status callback helper
    def update_status(
        status_val,
        detailed_val,
        logs_list=None,
        pub_score=None,
        priv_score=None,
        time_ms=None,
        m_pub=None,
        m_priv=None,
    ):
        if metadata:
            # Safely join logs — filter out non-string items (can happen in test mocks)
            logs_str = None
            if logs_list is not None:
                safe_logs = [str(x) for x in logs_list if x is not None]
                if safe_logs:
                    logs_str = "\n".join(safe_logs)
            success = report_status_to_server(
                metadata=metadata,
                status=status_val,
                detailed_status=detailed_val,
                logs=logs_str,
                public_score=pub_score,
                private_score=priv_score,
                execution_time_ms=time_ms,
                metrics_payload_pub=m_pub,
                metrics_payload_priv=m_priv,
                gpu_node=submission.gpu_node,
            )
            if not success:
                if status_val in ("completed", "failed"):
                    # Final status: critical — must persist via Redis fallback
                    try:
                        r = get_redis_client()
                        fallback = {
                            "submission_id": submission_id,
                            "status": status_val,
                            "detailed_status": detailed_val,
                            "logs": logs_str or "",
                            "public_score": pub_score,
                            "private_score": priv_score,
                            "execution_time_ms": time_ms,
                            "metrics_payload_pub": m_pub,
                            "metrics_payload_priv": m_priv,
                        }
                        r.setex(
                            f"submission:{submission_id}:fallback",
                            7200,
                            json.dumps(fallback, default=str),
                        )
                        logs_list.append(
                            "[WARNING] Could not reach main server. Result saved "
                            "to Redis fallback — server watchdog will recover it."
                        )
                    except Exception as fallback_err:
                        logs_list.append(
                            f"[CRITICAL] Failed to store fallback result: {fallback_err}"
                        )
                        # Local file fallback instead of raising RuntimeError
                        try:
                            fallback_path = os.path.join(
                                tempfile.gettempdir(),
                                f"submission_{submission_id}_result.json",
                            )
                            with open(fallback_path, "w") as ff:
                                json.dump(fallback, ff, default=str)
                            logs_list.append(
                                f"[CRITICAL] Result saved to local file: {fallback_path}"
                            )
                        except Exception as e:
                            logger.warning(
                                ("Failed to write local fallback file for submission %s: %s"),
                                submission_id,
                                e,
                            )
                else:
                    # Intermediate status: best-effort —
                    # already logged to Redis via StreamingLogList

                    pass
        else:
            with app.app_context():
                from sse_utils import (
                    publish_leaderboard_update,
                    publish_submissions_update,
                )

                db.session.expire_all()
                sub = db.session.get(submission_cls, submission_id)
                if sub:
                    sub.status = status_val
                    sub.detailed_status = detailed_val
                    if logs_list is not None:
                        sub.logs = "\n".join(logs_list)
                    if pub_score is not None:
                        sub.public_score = pub_score
                        sub.final_weighted_score_public = pub_score
                    if priv_score is not None:
                        sub.private_score = priv_score
                        sub.final_weighted_score_private = priv_score
                    if time_ms is not None:
                        sub.execution_time_ms = time_ms
                    if m_pub is not None:
                        sub.metrics_payload_public = m_pub
                    if m_priv is not None:
                        sub.metrics_payload_private = m_priv
                    db.session.commit()

                    if status_val in ("completed", "failed"):
                        try:
                            from cache_utils import invalidate_leaderboard_cache

                            invalidate_leaderboard_cache(sub.challenge_id)
                        except Exception:
                            logger.exception(
                                "Failed to invalidate leaderboard cache in submission runner"
                            )

                    publish_submissions_update(sub.task_id, sub.user_id)
                    publish_leaderboard_update(sub.task_id)

    logs = None
    status = "queued"
    public_score = None
    private_score = None
    execution_time_ms = 0
    metrics_payload_pub = None
    metrics_payload_priv = None

    # 3. Start evaluation execution
    try:
        update_status("running", "running")

        # Extract user code
        try:
            cells_list = json.loads(submission.code_cells)
            extracted_cells = []
            for cell in cells_list:
                if isinstance(cell, dict):
                    source = cell.get("source", "")
                    if isinstance(source, list):
                        extracted_cells.append("".join(source))
                    else:
                        extracted_cells.append(str(source))
                elif isinstance(cell, str):
                    extracted_cells.append(cell)
                else:
                    extracted_cells.append(str(cell))
            user_code = "\n\n".join(extracted_cells)
        except Exception as e:
            err_msg = f"Failed to parse code cells JSON: {e!s}"
            update_status("failed", "failed", logs_list=[err_msg])
            return

        # Determine resource limits
        time_limit = 300
        if task and task.time_limit_sec is not None:
            time_limit = task.time_limit_sec
        elif challenge and challenge.time_limit_sec is not None:
            time_limit = challenge.time_limit_sec

            # Check if this is a unified evaluation plan (modalities-specific)
        is_unified_parquet = metadata.get("is_unified_parquet", True) if metadata else True

        # Write user code to temporary file / directory
        workspace_root = os.environ.get("LAVBENCH_WORKSPACE_DIR")
        temp_dir = tempfile.mkdtemp(dir=workspace_root) if workspace_root else tempfile.mkdtemp()
        os.chmod(temp_dir, 0o777)  # noqa: S103 — temp dir for Docker mount, deleted after

        # Create logs holder
        logs = StreamingLogList(submission_id)
        logs.append(f"--- Starting execution sandbox at {datetime.utcnow()} ---")
        logs.append(f"Time limit: {time_limit} seconds.")

        # Retrieve task files
        if metadata:
            download_task_files_to_dir(metadata, temp_dir, logs)
        else:
            if task and task.files:
                try:
                    files_meta = json.loads(task.files)
                    task_files_dir = os.path.join(
                        (
                            app.config["UPLOAD_FOLDER"]
                            if app
                            else os.environ.get("UPLOAD_FOLDER", "uploads")
                        ),
                        f"task_{task.id}",
                    )
                    if os.path.exists(task_files_dir):
                        import shutil

                        for f in files_meta:
                            if is_unified_parquet and f["filename"] == "labels.parquet":
                                continue  # Do NOT copy labels.parquet to sandbox
                            src_file = os.path.join(task_files_dir, f["saved_name"])
                            dest_file = os.path.join(temp_dir, f["filename"])
                            if os.path.exists(src_file):
                                shutil.copy(src_file, dest_file)
                except Exception as copy_err:
                    logs.append(f"Error copying task files: {copy_err}")

        # Determine resource requirements early
        gpu_required = False
        if task and task.gpu_required is not None:
            gpu_required = task.gpu_required
        elif challenge and challenge.gpu_required is not None:
            gpu_required = challenge.gpu_required

        # Setup environment variables
        env = os.environ.copy()
        gpu_id = os.environ.get("WORKER_GPU_ID", None)
        gpu_lock_file = None

        if gpu_required and gpu_id:
            # Comma separated list of GPU IDs
            gpus = [g.strip() for g in gpu_id.split(",") if g.strip()]
            if gpus:
                acquired_gpu = None
                logs.append("Waiting for an available GPU device...")

                while acquired_gpu is None:
                    for g_id in gpus:
                        lock_path = os.path.join(tempfile.gettempdir(), f"gpu_lock_{g_id}.lock")
                        try:
                            f = open(lock_path, "w")  # noqa: SIM115  # intentionally kept open for lock
                            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            acquired_gpu = g_id
                            gpu_lock_file = f
                            break
                        except OSError:
                            continue
                    if acquired_gpu is None:
                        time.sleep(1)

                logs.append(f"Acquired GPU device: {acquired_gpu}")
                env["CUDA_VISIBLE_DEVICES"] = acquired_gpu
                submission.gpu_node = f"gpu-worker-device-{acquired_gpu}"
                gpu_id = acquired_gpu
            else:
                submission.gpu_node = env.get("HOSTNAME", "local-worker")
        else:
            env.pop("CUDA_VISIBLE_DEVICES", None)
            submission.gpu_node = env.get("HOSTNAME", "local-worker")
            gpu_id = None

        hf_cache_dir = os.environ.get("HF_CACHE_DIR")
        if not hf_cache_dir and not running_as_worker:
            hf_cache_dir = app.config.get("HF_CACHE_DIR")

        valid_cache = False
        if hf_cache_dir:
            try:
                os.makedirs(hf_cache_dir, exist_ok=True)
                valid_cache = True
            except Exception as e:
                logger.warning("Could not create HF cache dir %s: %s", hf_cache_dir, e)

        if not valid_cache:
            relative_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "hf_cache"))
            try:
                os.makedirs(relative_path, exist_ok=True)
                hf_cache_dir = relative_path
            except Exception as e:
                logger.warning("Could not create fallback HF cache dir %s: %s", hf_cache_dir, e)

        if hf_cache_dir:
            env["HF_HOME"] = hf_cache_dir
            env["HF_DATASETS_CACHE"] = hf_cache_dir

        # Generate secret results key and write competitor actual code
        import secrets

        results_key = secrets.token_hex(16)
        with open(os.path.join(temp_dir, "competitor_actual.py"), "w") as f:
            f.write(user_code)
            os.fchmod(f.fileno(), 0o644)

        # Phase 2: Build / Prepare environment (image pre-built by worker startup)
        docker_available = check_docker_available()
        if not docker_available:
            logs.append(
                "Error: Docker is not available on the worker node. Execution blocked for security."
            )
            update_status("failed", "failed", logs_list=logs)
            report_status_to_server(metadata, "failed", "failed", logs=logs)
            return

        image_tag = f"lavbench_task_{task.id if task else 0}"

        if task and (task.base_docker_image or task.apt_packages or task.pip_requirements):
            base_image = task.base_docker_image or "python:3.10-slim"

            if _image_exists_docker(image_tag):
                logs.append(f"Docker sandbox image '{image_tag}' already exists. Skipping build.")
            else:
                logs.append(f"Docker sandbox image '{image_tag}' not found. Building now...")
                from task_modules.image_builder import build_task_image

                build_meta = {
                    "task_id": task.id,
                    "base_docker_image": base_image,
                    "pip_requirements": task.pip_requirements or "",
                    "hf_datasets": metadata.get("hf_datasets", "[]") if metadata else "[]",
                    "hf_models": metadata.get("hf_models", "[]") if metadata else "[]",
                    "hf_api_key": (
                        _fetch_hf_key_from_server(
                            task.id,
                            metadata.get("main_server_url", ""),
                            _sign_worker_token(metadata.get("submission_id", "unknown")),
                        )
                        if metadata and metadata.get("main_server_url")
                        else (task.get_hf_api_key() if hasattr(task, "get_hf_api_key") else "")
                    ),
                }
                if not build_task_image(build_meta):
                    logs.append("Docker image build failed!")
                    update_status("failed", "failed", logs_list=logs)
                    report_status_to_server(metadata, "failed", "failed", logs=logs)
                    return
                logs.append("Docker image built successfully.")

        # Update status: Running Inference
        update_status("running", "running_inference", logs_list=logs)

        exec_file = "competitor_actual.py"
        start_wall_time = time.time()
        stdout, stderr = "", ""
        process_timeout = False

        ram_limit = 8192
        if task and task.ram_limit_mb is not None:
            ram_limit = task.ram_limit_mb
        elif challenge and challenge.ram_limit_mb is not None:
            ram_limit = challenge.ram_limit_mb

        # ── RAM budget clamping ──────────────────────────────────────
        budget_gb = int(
            os.environ.get("GPU_RAM_PER_TASK_GB" if gpu_required else "CPU_RAM_PER_TASK_GB", 8)
        )
        budget_mb = budget_gb * 1024
        clamp_factor = float(os.environ.get("RAM_CLAMP_FACTOR", 1.05))

        if ram_limit <= budget_mb:
            pass
        elif ram_limit <= int(budget_mb * clamp_factor):
            logger.warning(
                "Clamping ram_limit from %d MB to %d MB (task needs %d, budget is %d, factor=%.2f)",
                ram_limit,
                budget_mb,
                ram_limit,
                budget_mb,
                clamp_factor,
            )
            ram_limit = budget_mb
        else:
            raise RuntimeError(
                f"Task requires {ram_limit} MB RAM, "
                f"worker budget is {budget_mb} MB per task "
                f"(clamp factor {clamp_factor})"
            )

        environment = {
            "HOME": "/tmp",  # noqa: S108
            "HF_HOME": "/hf_cache",
            "HF_DATASETS_CACHE": "/hf_cache",
            "HF_DATASETS_OFFLINE": "1",
            "HF_HUB_OFFLINE": "1",
            "PYTHONUNBUFFERED": "1",
            "RESULTS_KEY": results_key,
        }

        if gpu_required and gpu_id is not None:
            environment["CUDA_VISIBLE_DEVICES"] = "0"

        docker_client = _get_client()
        logs.append(
            f"Executing sandbox: image={image_tag}, "
            f"command=python -u {exec_file}, "
            f"ram={ram_limit}M, cpus=2"
        )
        retcode, stdout, stderr, process_timeout = run_command_streaming(
            docker_client,
            image_tag,
            command=["python", "-u", exec_file],
            logs_list=logs,
            time_limit=time_limit,
            mem_limit=f"{ram_limit}m",
            cpu_count=2,
            network_mode="none",
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            pids_limit=64,
            tmpfs={"/tmp": "noexec,nosuid,size=128m"},  # noqa: S108
            volumes={temp_dir: {"bind": "/app", "mode": "rw"}},
            working_dir="/app",
            environment=environment,
            gpu_required=gpu_required,
            gpu_id=gpu_id,
        )

        end_wall_time = time.time()

        # Update status: Evaluating
        update_status("running", "evaluating", logs_list=logs)

        status = "completed"
        public_score = None
        private_score = None
        execution_time_ms = 0
        metrics_payload_pub = {}
        metrics_payload_priv = {}

        if process_timeout:
            status = "failed"
            logs.append(f"TIMEOUT EXPIRED: Executed code exceeded the {time_limit}s limit.")
        elif is_unified_parquet:
            # Secure scoring for unified parquet
            sub_parquet_path = os.path.join(temp_dir, "submission.parquet")
            if not os.path.exists(sub_parquet_path):
                status = "failed"
                logs.append(
                    "Error: The submission did not generate "
                    "'submission.parquet'. Ensure your code saves predictions to this file."
                )
            else:
                # Locate labels.parquet on the host
                labels_path = None
                if metadata:
                    # Running on worker: download labels.parquet securely to a host-only directory
                    host_labels_dir = tempfile.mkdtemp()
                    labels_path = download_labels_parquet_to_dir(metadata, host_labels_dir, logs)
                else:
                    # Running locally with DB: find in task files folder
                    if task and task.files:
                        try:
                            files_meta = json.loads(task.files)
                            task_files_dir = os.path.join(
                                (
                                    app.config["UPLOAD_FOLDER"]
                                    if app
                                    else os.environ.get("UPLOAD_FOLDER", "uploads")
                                ),
                                f"task_{task.id}",
                            )
                            for f in files_meta:
                                if f["filename"] == "labels.parquet":
                                    labels_path = os.path.join(task_files_dir, f["saved_name"])
                                    break
                        except Exception as e:
                            logs.append(f"Error locating local labels.parquet: {e}")
                if not labels_path or not os.path.exists(labels_path):
                    status = "failed"
                    logs.append(
                        "Error: The task ground-truth "
                        "'labels.parquet' file could not be found or loaded."
                    )
                else:
                    try:
                        import pandas as pd
                        from evaluation_engine import (
                            evaluate_predictions,
                            validate_parquet_schema,
                        )

                        df_sub = pd.read_parquet(sub_parquet_path)

                        is_valid, err = validate_parquet_schema(df_sub, is_submission=True)
                        if not is_valid:
                            status = "failed"
                            logs.append(f"Submission schema validation failed: {err}")
                            update_status("failed", "failed", logs_list=logs)
                            return

                        df_labels = pd.read_parquet(labels_path)

                        # Split into public/private sets based on public_eval_percentage
                        metrics_cfg = task.metrics_config
                        if isinstance(metrics_cfg, str):
                            try:
                                metrics_cfg = json.loads(metrics_cfg)
                            except (json.JSONDecodeError, TypeError, ValueError):
                                metrics_cfg = None

                        # Strip metadata keys (e.g., _columns) that are not metrics
                        if isinstance(metrics_cfg, dict):
                            metrics_cfg = {
                                k: v for k, v in metrics_cfg.items() if not k.startswith("_")
                            }

                        pub_pct = (
                            task.public_eval_percentage
                            if task.public_eval_percentage is not None
                            else 30
                        )

                        if "query_id" in df_labels.columns:
                            unique_queries = sorted(df_labels["query_id"].unique())
                            num_public = int(len(unique_queries) * (pub_pct / 100.0))
                            num_public = max(0, min(num_public, len(unique_queries)))
                            public_queries = set(unique_queries[:num_public])

                            df_labels_pub = (
                                df_labels[df_labels["query_id"].isin(public_queries)]
                                if num_public > 0
                                else pd.DataFrame(columns=df_labels.columns)
                            )
                            df_labels_priv = (
                                df_labels[~df_labels["query_id"].isin(public_queries)]
                                if num_public < len(unique_queries)
                                else pd.DataFrame(columns=df_labels.columns)
                            )

                            df_sub_pub = (
                                df_sub[df_sub["query_id"].isin(public_queries)]
                                if num_public > 0
                                else pd.DataFrame(columns=df_sub.columns)
                            )
                            df_sub_priv = (
                                df_sub[~df_sub["query_id"].isin(public_queries)]
                                if num_public < len(unique_queries)
                                else pd.DataFrame(columns=df_sub.columns)
                            )
                        else:
                            df_labels = df_labels.sort_values("id").reset_index(drop=True)
                            n_total = len(df_labels)
                            num_public = int(n_total * (pub_pct / 100.0))
                            num_public = max(0, min(num_public, n_total))

                            df_labels_pub = (
                                df_labels.iloc[:num_public]
                                if num_public > 0
                                else pd.DataFrame(columns=df_labels.columns)
                            )
                            df_labels_priv = (
                                df_labels.iloc[num_public:]
                                if num_public < n_total
                                else pd.DataFrame(columns=df_labels.columns)
                            )

                            df_sub_pub = (
                                df_sub[df_sub["id"].isin(df_labels_pub["id"])]
                                if num_public > 0
                                else pd.DataFrame(columns=df_sub.columns)
                            )
                            df_sub_priv = (
                                df_sub[df_sub["id"].isin(df_labels_priv["id"])]
                                if num_public < n_total
                                else pd.DataFrame(columns=df_sub.columns)
                            )

                        # Compute metrics (skip empty splits)
                        m_pub = (
                            evaluate_predictions(df_sub_pub, df_labels_pub, metrics_cfg)
                            if len(df_labels_pub) > 0
                            else {}
                        )
                        m_priv = (
                            evaluate_predictions(df_sub_priv, df_labels_priv, metrics_cfg)
                            if len(df_labels_priv) > 0
                            else {}
                        )

                        public_score = calculate_weighted_score(m_pub, metrics_cfg)
                        private_score = calculate_weighted_score(m_priv, metrics_cfg)
                        metrics_payload_pub = m_pub
                        metrics_payload_priv = m_priv
                        execution_time_ms = int((end_wall_time - start_wall_time) * 1000)
                        status = "completed"
                        logs.append("Evaluation completed successfully.")
                    except Exception as eval_err:
                        status = "failed"
                        logs.append(f"Error during parquet metric calculation: {eval_err!s}")
                        logs.append(f"Traceback: {traceback.format_exc()}")

            # Clean up securely downloaded labels directory on host if created
            if metadata and "host_labels_dir" in locals() and host_labels_dir:
                try:
                    import shutil

                    shutil.rmtree(host_labels_dir, ignore_errors=True)
                except OSError as e:
                    logger.debug("Could not remove host labels dir %s: %s", host_labels_dir, e)

        try:
            import shutil

            shutil.rmtree(temp_dir, ignore_errors=True)
        except OSError as e:
            logger.debug("Could not remove temp dir %s: %s", temp_dir, e)

        # Write final results status back to server or DB
        update_status(
            status_val=status,
            detailed_val=status,
            logs_list=logs,
            pub_score=public_score,
            priv_score=private_score,
            time_ms=execution_time_ms,
            m_pub=metrics_payload_pub,
            m_priv=metrics_payload_priv,
        )

        try:
            from sse_utils import clear_submission_logs

            clear_submission_logs(submission_id)
        except Exception as e:
            logger.warning("Failed to clear SSE logs for submission %s: %s", submission_id, e)

    except Exception as e:
        status = "failed"
        if "logs" in locals() and logs is not None:
            logs.append(f"[FATAL] Unhandled worker crash: {e}")
            logs.append(traceback.format_exc())
            logs_list = logs
        else:
            logger.error(f"[FATAL] Unhandled worker crash: {e}\n{traceback.format_exc()}")
            logs_list = [f"[FATAL] Unhandled worker crash: {e}"]
        with contextlib.suppress(Exception):
            update_status("failed", "failed", logs_list=logs_list)
        raise
    finally:
        if "gpu_lock_file" in locals() and gpu_lock_file:
            with contextlib.suppress(Exception):
                gpu_lock_file.close()
        if "temp_dir" in locals() and temp_dir:
            import shutil

            shutil.rmtree(temp_dir, ignore_errors=True)

    return f"Submission {submission_id} evaluated with status {status}"


@worker_ready.connect
def register_worker_specs(sender, **kwargs):
    try:
        import platform

        r = get_redis_client()
        if not r:
            return

        worker_name = getattr(sender, "hostname", str(sender))
        cpu_cores = os.cpu_count() or 1

        ram_gb = 8.0
        try:
            if platform.system() == "Linux":
                with open("/proc/meminfo") as f:
                    for line in f:
                        if "MemTotal" in line:
                            ram_kb = int(line.split()[1])
                            ram_gb = round(ram_kb / (1024 * 1024), 1)
                            break
            elif platform.system() == "Darwin":
                total_bytes = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip())  # noqa: S607
                ram_gb = round(total_bytes / (1024**3), 1)
        except Exception as e:
            logger.warning("Failed to detect system RAM, using default 8.0 GB: %s", e)

        gpu_id = os.environ.get("WORKER_GPU_ID", None)
        has_gpu = gpu_id is not None or "gpu" in worker_name.lower()
        gpu_type = "N/A"
        vram_gb = "N/A"

        if has_gpu:
            gpu_type = "NVIDIA GPU"
            try:
                gpu_name_out = (
                    subprocess.check_output(
                        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]  # noqa: S607
                    )
                    .decode("utf-8")
                    .strip()
                )
                if gpu_name_out:
                    gpu_type = gpu_name_out.split("\n")[0]
                vram_out = (
                    subprocess.check_output(
                        [  # noqa: S607
                            "nvidia-smi",
                            "--query-gpu=memory.total",
                            "--format=csv,noheader,nounits",
                        ]
                    )
                    .decode("utf-8")
                    .strip()
                )
                if vram_out:
                    vram_mb = int(vram_out.split("\n")[0])
                    vram_gb = round(vram_mb / 1024, 1)
            except Exception:
                gpu_type = "NVIDIA GPU"
                vram_gb = 8.0

        concurrency = 1
        try:
            if hasattr(sender, "pool") and hasattr(sender.pool, "limit"):
                concurrency = sender.pool.limit
            elif hasattr(sender, "app") and sender.app.conf.worker_concurrency:
                concurrency = sender.app.conf.worker_concurrency
            elif hasattr(sender, "concurrency"):
                concurrency = sender.concurrency
            else:
                concurrency = os.cpu_count() or 1
        except Exception:
            concurrency = os.cpu_count() or 1

        spec = {
            "name": worker_name,
            "type": "GPU" if has_gpu else "CPU",
            "concurrency": concurrency,
            "cpu_cores": cpu_cores,
            "gpu_type": gpu_type,
            "ram_gb": ram_gb,
            "vram_gb": vram_gb,
            "gpu_ram_per_task_gb": int(os.environ.get("GPU_RAM_PER_TASK_GB", 8)),
            "cpu_ram_per_task_gb": int(os.environ.get("CPU_RAM_PER_TASK_GB", 4)),
            "reserved_ram_gb": int(os.environ.get("RESERVED_RAM_GB", 4)),
            "reserved_cpu_cores": int(os.environ.get("RESERVED_CPU_CORES", 1)),
            "ram_clamp_factor": float(os.environ.get("RAM_CLAMP_FACTOR", 1.05)),
            "last_seen": time.time(),
        }
        r.set(f"worker_spec:{worker_name}", json.dumps(spec), ex=86400)
        logger.info("Worker specs registered: %s", spec)

        # Build Docker images for all active tasks + start rebuild listener
        try:
            from task_modules.image_builder import (
                build_all_active_tasks,
                start_rebuild_listener,
            )

            main_server_url = os.environ.get("MAIN_SERVER_URL", "http://localhost:5001")
            worker_token = _sign_worker_token("worker")
            build_all_active_tasks(main_server_url, worker_token)
            start_rebuild_listener(main_server_url, worker_token)
        except Exception as e:
            logger.warning("Failed to build active task images on startup: %s", e)
    except Exception as e:
        logger.error("Failed to register specs: %s", e)
