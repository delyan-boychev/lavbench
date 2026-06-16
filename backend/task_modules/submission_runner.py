import os
import json
import subprocess
import tempfile
import time
import traceback
import hashlib
import requests
from datetime import datetime

from worker_utils import (
    run_command_streaming, 
    StreamingLogList, 
    MockModel, 
    report_status_to_server, 
    download_task_files_to_dir, 
    download_labels_parquet_to_dir
)
from task_modules.templates import DEFAULT_EVALUATION_TEMPLATE, CUSTOM_EVAL_WRAPPER, render_eval_template

def _fetch_hf_key_from_server(task_id, main_server_url, worker_token):
    if not task_id or not main_server_url or not worker_token:
        return ""
    try:
        res = requests.get(
            f"{main_server_url.rstrip('/')}/api/worker/tasks/{task_id}/hf-key",
            headers={"X-Worker-Token": worker_token},
            timeout=5
        )
        if res.status_code == 200:
            return res.json().get("hf_key", "")
    except Exception:
        pass
    return ""

def preload_submission_datasets(task, challenge, temp_dir, hf_cache_dir, logs):
    """
    Preloads HuggingFace datasets and models on the host so they are available offline in docker.
    """
    datasets_to_load = []
    models_to_load = []
    
    # 1. Gather Datasets
    if task and hasattr(task, 'hf_datasets') and task.hf_datasets:
        import json
        ds_val = task.hf_datasets
        if isinstance(ds_val, str):
            try:
                ds_val = json.loads(ds_val)
            except:
                ds_val = []
        if isinstance(ds_val, list):
            for ds in ds_val:
                if ds and ds not in datasets_to_load:
                    datasets_to_load.append(ds)

    # 2. Gather Models
    if task and hasattr(task, 'hf_models') and task.hf_models:
        import json
        md_val = task.hf_models
        if isinstance(md_val, str):
            try:
                md_val = json.loads(md_val)
            except:
                md_val = []
        if isinstance(md_val, list):
            for md in md_val:
                if md and md not in models_to_load:
                    models_to_load.append(md)

    hf_token = None
    if task and hasattr(task, 'get_hf_api_key'):
        try:
            hf_token = task.get_hf_api_key()
        except:
            pass

    if not hf_token:
        hf_token = None

    # 3. Preload datasets
    if datasets_to_load and hf_cache_dir:
        logs.append(f"Preloading datasets on host: {datasets_to_load}...")
        try:
            from datasets import load_dataset as host_load_dataset
            for ds_name in datasets_to_load:
                try:
                    host_load_dataset(ds_name, cache_dir=hf_cache_dir, token=hf_token)
                    logs.append(f"Successfully preloaded dataset '{ds_name}' to host cache.")
                except Exception as preload_err:
                    logs.append(f"Warning: Failed to preload dataset '{ds_name}': {preload_err}")
        except Exception as import_err:
            logs.append(f"Warning: Could not import 'datasets' on host to preload: {import_err}")

    # 4. Preload models
    if models_to_load and hf_cache_dir:
        logs.append(f"Preloading HF models on host: {models_to_load}...")
        try:
            from huggingface_hub import snapshot_download
            for model_name in models_to_load:
                try:
                    snapshot_download(repo_id=model_name, cache_dir=hf_cache_dir, token=hf_token)
                    logs.append(f"Successfully preloaded model '{model_name}' to host cache.")
                except Exception as preload_err:
                    logs.append(f"Warning: Failed to preload model '{model_name}': {preload_err}")
        except Exception as import_err:
            logs.append(f"Warning: Could not import 'huggingface_hub' on host to preload models: {import_err}")





def run_eval_submission(self_task, submission_id, metadata, app, db, Submission, Challenge):
    RUNNING_AS_WORKER = app is None
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
            get_hf_api_key=lambda: _fetch_hf_key_from_server(metadata.get("task_id"), metadata.get("main_server_url"), metadata.get("worker_secret_key")),
            evaluator_script_path=None,
            custom_eval_code=metadata.get("custom_eval_code"),
        )
        challenge = MockModel(
            id=metadata.get("challenge_id"),
            time_limit_sec=metadata.get("time_limit"),
            ram_limit_mb=metadata.get("ram_limit"),
            gpu_required=metadata.get("gpu_required"),
            metric_name=metadata.get("metric_name", "accuracy"),
            hf_dataset_split=metadata.get("hf_dataset_split", "test")
        )
        submission = MockModel(
            id=submission_id,
            task_id=task.id,
            challenge_id=challenge.id,
            code_cells=json.dumps([metadata.get("user_code")]),
            status='queued',
            detailed_status='queued',
            logs="",
            gpu_node=None
        )
    else:
        with app.app_context():
            db_submission = db.session.get(Submission, submission_id)
            if not db_submission:
                return f"Submission {submission_id} not found."
            # Idempotency: skip if already in a terminal state
            if db_submission.status in ('completed', 'failed'):
                return f"Submission {submission_id} already in terminal state: {db_submission.status}"
            db_submission.status = 'running'
            db_submission.detailed_status = 'running'
            db.session.commit()
            task = MockModel(
                id=db_submission.task.id if db_submission.task else None,
                time_limit_sec=db_submission.task.time_limit_sec if db_submission.task else None,
                ram_limit_mb=db_submission.task.ram_limit_mb if db_submission.task else None,
                gpu_required=db_submission.task.gpu_required if db_submission.task else None,
                base_docker_image=db_submission.task.base_docker_image if db_submission.task else None,
                apt_packages=db_submission.task.apt_packages if db_submission.task else None,
                pip_requirements=db_submission.task.pip_requirements if db_submission.task else None,
                metrics_config=db_submission.task.metrics_config if db_submission.task else None,
                public_eval_percentage=db_submission.task.public_eval_percentage if db_submission.task else None,
                get_hf_api_key=lambda: db_submission.task.get_hf_api_key() if db_submission.task else "",
                evaluator_script_path=db_submission.task.evaluator_script_path if db_submission.task else None,
                files=db_submission.task.files if db_submission.task else None,
                custom_eval_code=db_submission.task.custom_eval_code if (db_submission.task and hasattr(db_submission.task, 'custom_eval_code')) else None,
            )
            challenge = MockModel(
                id=db_submission.challenge.id if db_submission.challenge else None,
                time_limit_sec=db_submission.challenge.time_limit_sec if db_submission.challenge else None,
                ram_limit_mb=db_submission.challenge.ram_limit_mb if db_submission.challenge else None,
                gpu_required=db_submission.challenge.gpu_required if db_submission.challenge else None
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
                gpu_node=db_submission.gpu_node
            )

    # 2. Define status callback helper
    def update_status(status_val, detailed_val, logs_list=None, pub_score=None, priv_score=None, time_ms=None, m_pub=None, m_priv=None):
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
                gpu_node=submission.gpu_node
            )
            if not success:
                if status_val in ('completed', 'failed'):
                    # Final status: critical — must persist via Redis fallback
                    try:
                        from cache_utils import get_redis_client
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
                        r.setex(f"submission:{submission_id}:fallback", 7200, json.dumps(fallback, default=str))
                        logs_list.append("[WARNING] Could not reach main server. Result saved to Redis fallback — server watchdog will recover it.")
                    except Exception as fallback_err:
                        logs_list.append(f"[CRITICAL] Failed to store fallback result: {fallback_err}")
                        raise RuntimeError(f"Failed to deliver final status '{status_val}' to server and fallback.") from fallback_err
                else:
                    # Intermediate status: best-effort — already logged to Redis via StreamingLogList
                    pass
        else:
            with app.app_context():
                from sse_utils import publish_submissions_update, publish_leaderboard_update
                db.session.expire_all()
                sub = db.session.get(Submission, submission_id)
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
                    
                    publish_submissions_update(sub.task_id, sub.user_id)
                    publish_leaderboard_update(sub.task_id)

    # 3. Start evaluation execution
    update_status('running', 'running')

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
        err_msg = f"Failed to parse code cells JSON: {str(e)}"
        update_status('failed', 'failed', logs_list=[err_msg])
        return

    # Determine resource limits
    time_limit = 300
    if task and task.time_limit_sec is not None:
        time_limit = task.time_limit_sec
    elif challenge and challenge.time_limit_sec is not None:
        time_limit = challenge.time_limit_sec

                    # Check if this is a unified evaluation plan (modalities-specific)
    if metadata:
        is_unified_parquet = metadata.get("is_unified_parquet", True)
    else:
        is_unified_parquet = True


    # Write user code to temporary file / directory
    temp_dir = tempfile.mkdtemp()

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
                task_files_dir = os.path.join(app.config['UPLOAD_FOLDER'] if app else os.environ.get('UPLOAD_FOLDER', 'uploads'), f"task_{task.id}")
                if os.path.exists(task_files_dir):
                    import shutil
                    for f in files_meta:
                        if is_unified_parquet and f["filename"] == "labels.parquet":
                            continue # Do NOT copy labels.parquet to sandbox
                        src_file = os.path.join(task_files_dir, f["saved_name"])
                        dest_file = os.path.join(temp_dir, f["filename"])
                        if os.path.exists(src_file):
                            shutil.copy(src_file, dest_file)
            except Exception as copy_err:
                logs.append(f"Error copying task files: {copy_err}")

    # Setup environment variables
    env = os.environ.copy()
    gpu_id = os.environ.get("WORKER_GPU_ID", None)
    if gpu_id is not None:
        env["CUDA_VISIBLE_DEVICES"] = gpu_id
        submission.gpu_node = f"gpu-worker-device-{gpu_id}"
    else:
        submission.gpu_node = env.get("HOSTNAME", "local-worker")
        
    hf_cache_dir = os.environ.get("HF_CACHE_DIR")
    if not hf_cache_dir and not RUNNING_AS_WORKER:
        hf_cache_dir = app.config.get("HF_CACHE_DIR")
        
    valid_cache = False
    if hf_cache_dir:
        try:
            os.makedirs(hf_cache_dir, exist_ok=True)
            valid_cache = True
        except Exception:
            pass
            
    if not valid_cache:
        relative_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'hf_cache'))
        try:
            os.makedirs(relative_path, exist_ok=True)
            hf_cache_dir = relative_path
        except Exception as e:
            pass
            
    if hf_cache_dir:
        env["HF_HOME"] = hf_cache_dir
        env["HF_DATASETS_CACHE"] = hf_cache_dir

    # Generate secret results key and write student actual code
    import secrets
    results_key = secrets.token_hex(16)
    with open(os.path.join(temp_dir, "student_actual.py"), "w") as f:
        f.write(user_code)

    # Write evaluator script / template
    is_custom_eval = False
    if metadata:
        if metadata.get("is_custom_eval") and metadata.get("custom_eval_code"):
            with open(os.path.join(temp_dir, "evaluator.py"), "w") as f:
                f.write(metadata.get("custom_eval_code"))
            is_custom_eval = True
            with open(os.path.join(temp_dir, "submission_runner.py"), "w") as f:
                f.write(CUSTOM_EVAL_WRAPPER)
        else:
            metrics_cfg_str = json.dumps(metadata.get("metrics_config")) if metadata.get("metrics_config") else "None"
            run_script_content = render_eval_template(
                DEFAULT_EVALUATION_TEMPLATE,
                user_code="",
                hf_token=metadata.get("hf_token") or "",
                public_eval_percentage=metadata.get("public_eval_percentage") or 30,
                metrics_config_str=metrics_cfg_str,
                hf_dataset_split="test"
            )
            with open(os.path.join(temp_dir, "submission_runner.py"), "w") as f:
                f.write(run_script_content)
    else:
        if task:
            if task.custom_eval_code:
                with open(os.path.join(temp_dir, "evaluator.py"), "w") as f:
                    f.write(task.custom_eval_code)
                is_custom_eval = True
                with open(os.path.join(temp_dir, "submission_runner.py"), "w") as f:
                    f.write(CUSTOM_EVAL_WRAPPER)
            elif task.evaluator_script_path and os.path.exists(task.evaluator_script_path):
                import shutil
                shutil.copy(task.evaluator_script_path, os.path.join(temp_dir, "evaluator.py"))
                is_custom_eval = True
                with open(os.path.join(temp_dir, "submission_runner.py"), "w") as f:
                    f.write(CUSTOM_EVAL_WRAPPER)
            else:
                hf_token = task.get_hf_api_key() or ""
                metrics_cfg_str = json.dumps(task.metrics_config) if task.metrics_config else "None"
                run_script_content = render_eval_template(
                    DEFAULT_EVALUATION_TEMPLATE,
                    user_code="",
                    hf_token=hf_token,
                    public_eval_percentage=task.public_eval_percentage or 30,
                    metrics_config_str=metrics_cfg_str,
                    hf_dataset_split="test"
                )
                with open(os.path.join(temp_dir, "submission_runner.py"), "w") as f:
                    f.write(run_script_content)
        else:
            raise ValueError("Legacy evaluation path is no longer supported.")

    # Preload HuggingFace datasets on the host so they are available offline in docker
    preload_submission_datasets(task, challenge, temp_dir, hf_cache_dir, logs)

    # Phase 2: Build / Prepare environment
    docker_available = False
    try:
        res = subprocess.run(["docker", "--version"], capture_output=True, text=True)
        if res.returncode == 0:
            docker_available = True
    except:
        pass

    if not docker_available:
        logs.append("Error: Docker is not available on the worker node. Execution blocked for security.")
        update_status('failed', 'failed', logs_list=logs)
        report_status_to_server(metadata, 'failed', 'failed', logs=logs)
        return

    if task and (task.base_docker_image or task.apt_packages or task.pip_requirements):
        base_image = task.base_docker_image or "python:3.10-slim"
        
        # Calculate a stable config hash to make builds fast!
        import hashlib
        config_str = f"{base_image}|{task.apt_packages or ''}|{task.pip_requirements or ''}"
        config_hash = hashlib.sha256(config_str.encode()).hexdigest()[:12]
        image_tag = f"nai_task_{task.id}_{config_hash}".lower()
        
        image_exists = False
        try:
            res_check = subprocess.run(["docker", "images", "-q", image_tag], capture_output=True, text=True)
            if res_check.stdout.strip():
                image_exists = True
        except:
            pass
            
        if image_exists:
            logs.append(f"Docker sandbox image '{image_tag}' already exists. Skipping build step for speed.")
        else:
            logs.append("Docker sandbox available. Building custom task image...")
            dockerfile_lines = [f"FROM {base_image}"]
            
            if task.apt_packages:
                apt_list = " ".join([p.strip() for p in task.apt_packages.replace(",", " ").split() if p.strip()])
                if apt_list:
                    dockerfile_lines.extend([
                        "RUN apt-get update && apt-get install -y --no-install-recommends \\",
                        f"    {apt_list} && \\",
                        "    rm -rf /var/lib/apt/lists/*"
                    ])
            
            # Core ML/deps — add more via task's pip_requirements field
            
            if task.pip_requirements:
                req_path = os.path.join(temp_dir, "requirements.txt")
                with open(req_path, "w") as rf:
                    rf.write(task.pip_requirements)
                dockerfile_lines.extend([
                    "COPY requirements.txt /requirements.txt",
                    "RUN pip install --no-cache-dir -r /requirements.txt"
                ])
                
            dockerfile_path = os.path.join(temp_dir, "Dockerfile")
            with open(dockerfile_path, "w") as df:
                df.write("\n".join(dockerfile_lines))
                
            logs.append(f"Building docker image '{image_tag}'...")
            retcode, stdout, stderr, is_timeout = run_command_streaming(
                ["docker", "build", "-t", image_tag, temp_dir],
                logs,
                time_limit=300
            )
            if is_timeout:
                logs.append("Docker build timed out after 300 seconds!")
                update_status('failed', 'failed', logs_list=logs)
                report_status_to_server(metadata, 'failed', 'failed', logs=logs)
                return
            elif retcode != 0:
                logs.append(f"Docker build failed with return code {retcode}!")
                update_status('failed', 'failed', logs_list=logs)
                report_status_to_server(metadata, 'failed', 'failed', logs=logs)
                return
            else:
                logs.append("Docker image built successfully.")

    # Update status: Running Inference
    update_status('running', 'running_inference', logs_list=logs)

    if is_unified_parquet:
        exec_file = "student_actual.py"
    else:
        exec_file = "evaluator.py" if is_custom_eval else "submission_runner.py"
    start_wall_time = time.time()
    stdout, stderr = "", ""
    process_timeout = False

    base_image = task.base_docker_image or "python:3.10-slim"
    import hashlib
    config_str = f"{base_image}|{task.apt_packages or ''}|{task.pip_requirements or ''}"
    config_hash = hashlib.sha256(config_str.encode()).hexdigest()[:12]
    image_tag = f"nai_task_{task.id}_{config_hash}".lower() if (task and (task.base_docker_image or task.apt_packages or task.pip_requirements)) else "python:3.10-slim"
    
    hf_cache_mount = []
    if hf_cache_dir and os.path.exists(hf_cache_dir):
        hf_cache_mount = ["-v", f"{hf_cache_dir}:/hf_cache"]
        
    ram_limit = 8192
    if task and task.ram_limit_mb is not None:
        ram_limit = task.ram_limit_mb
    elif challenge and challenge.ram_limit_mb is not None:
        ram_limit = challenge.ram_limit_mb
        
    gpu_args = []
    gpu_required = False
    if task and task.gpu_required is not None:
        gpu_required = task.gpu_required
    elif challenge and challenge.gpu_required is not None:
        gpu_required = challenge.gpu_required
        
    if gpu_required:
        gpu_id = os.environ.get("WORKER_GPU_ID", None)
        if gpu_id is not None:
            gpu_args = ["--gpus", f"device={gpu_id}", "-e", f"CUDA_VISIBLE_DEVICES={gpu_id}"]
        else:
            gpu_args = ["--gpus", "all"]
            
    cmd = [
        "docker", "run", "--rm",
        "--network", "none",
        "--pids-limit", "64",
        "--cpus", "2",
        "--ulimit", "nofile=256:256",
        "--ulimit", "nproc=64:64",
        "--tmpfs", "/tmp",
        "-m", f"{ram_limit}m",
        "-v", f"{temp_dir}:/app",
        "-w", "/app",
    ] + gpu_args + hf_cache_mount + [
        "-e", "HF_HOME=/hf_cache",
        "-e", "HF_DATASETS_CACHE=/hf_cache",
        "-e", "HF_DATASETS_OFFLINE=1",
        "-e", "HF_HUB_OFFLINE=1",
        "-e", "PYTHONUNBUFFERED=1",
        "-e", f"RESULTS_KEY={results_key}",
        image_tag, "python", "-u", exec_file
    ]
    
    logs.append(f"Executing sandbox command: {' '.join(cmd)}")
    retcode, stdout, stderr, process_timeout = run_command_streaming(cmd, logs, time_limit=time_limit)
    if process_timeout:
        result = subprocess.run(["docker", "ps", "-q", "--filter", f"ancestor={image_tag}"], capture_output=True, text=True)
        container_id = result.stdout.strip()
        if container_id:
            subprocess.run(["docker", "kill", container_id], capture_output=True)
        
    end_wall_time = time.time()

    # Update status: Evaluating
    update_status('running', 'evaluating', logs_list=logs)

    status = 'completed'
    public_score = None
    private_score = None
    execution_time_ms = 0
    metrics_payload_pub = {}
    metrics_payload_priv = {}
        
    if process_timeout:
        status = 'failed'
        logs.append(f"TIMEOUT EXPIRED: Executed code exceeded the {time_limit}s limit.")
        if is_custom_eval:
            logs.append("Jury Evaluator Error: The custom evaluation script failed to produce a valid results file.")
    elif is_unified_parquet:
        # Secure scoring for unified parquet
        sub_parquet_path = os.path.join(temp_dir, "submission.parquet")
        if not os.path.exists(sub_parquet_path):
            status = 'failed'
            logs.append("Error: The submission did not generate 'submission.parquet'. Ensure your code saves predictions to this file.")
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
                        task_files_dir = os.path.join(app.config['UPLOAD_FOLDER'] if app else os.environ.get('UPLOAD_FOLDER', 'uploads'), f"task_{task.id}")
                        for f in files_meta:
                            if f["filename"] == "labels.parquet":
                                labels_path = os.path.join(task_files_dir, f["saved_name"])
                                break
                    except Exception as e:
                        logs.append(f"Error locating local labels.parquet: {e}")
            if not labels_path or not os.path.exists(labels_path):
                status = 'failed'
                logs.append("Error: The task ground-truth 'labels.parquet' file could not be found or loaded.")
            else:
                try:
                    import pandas as pd
                    from evaluation_engine import evaluate_predictions, validate_parquet_schema
                    
                    df_sub = pd.read_parquet(sub_parquet_path)

                    is_valid, err = validate_parquet_schema(df_sub, is_submission=True)
                    if not is_valid:
                        status = 'failed'
                        logs.append(f"Submission schema validation failed: {err}")
                        update_status('failed', 'failed', logs_list=logs)
                        return
                        
                    df_labels = pd.read_parquet(labels_path)
                    
                    # Split into public/private sets based on public_eval_percentage
                    metrics_cfg = task.metrics_config
                    if isinstance(metrics_cfg, str):
                        try:
                            metrics_cfg = json.loads(metrics_cfg)
                        except:
                            metrics_cfg = None
                    
                    # Strip metadata keys (e.g., _columns) that are not metrics
                    if isinstance(metrics_cfg, dict):
                        metrics_cfg = {k: v for k, v in metrics_cfg.items() if not k.startswith("_")}
                    
                    pub_pct = task.public_eval_percentage if task.public_eval_percentage is not None else 30
                    
                    if "query_id" in df_labels.columns:
                        unique_queries = sorted(df_labels["query_id"].unique())
                        num_public = int(len(unique_queries) * (pub_pct / 100.0))
                        num_public = max(0, min(num_public, len(unique_queries)))
                        public_queries = set(unique_queries[:num_public])
                        
                        df_labels_pub = df_labels[df_labels["query_id"].isin(public_queries)] if num_public > 0 else pd.DataFrame(columns=df_labels.columns)
                        df_labels_priv = df_labels[~df_labels["query_id"].isin(public_queries)] if num_public < len(unique_queries) else pd.DataFrame(columns=df_labels.columns)
                        
                        df_sub_pub = df_sub[df_sub["query_id"].isin(public_queries)] if num_public > 0 else pd.DataFrame(columns=df_sub.columns)
                        df_sub_priv = df_sub[~df_sub["query_id"].isin(public_queries)] if num_public < len(unique_queries) else pd.DataFrame(columns=df_sub.columns)
                    else:
                        df_labels = df_labels.sort_values('id').reset_index(drop=True)
                        n_total = len(df_labels)
                        num_public = int(n_total * (pub_pct / 100.0))
                        num_public = max(0, min(num_public, n_total))
                        
                        df_labels_pub = df_labels.iloc[:num_public] if num_public > 0 else pd.DataFrame(columns=df_labels.columns)
                        df_labels_priv = df_labels.iloc[num_public:] if num_public < n_total else pd.DataFrame(columns=df_labels.columns)
                        
                        df_sub_pub = df_sub[df_sub["id"].isin(df_labels_pub["id"])] if num_public > 0 else pd.DataFrame(columns=df_sub.columns)
                        df_sub_priv = df_sub[df_sub["id"].isin(df_labels_priv["id"])] if num_public < n_total else pd.DataFrame(columns=df_sub.columns)
                    
                    # Compute metrics (skip empty splits)
                    m_pub = evaluate_predictions(df_sub_pub, df_labels_pub, metrics_cfg) if len(df_labels_pub) > 0 else {}
                    m_priv = evaluate_predictions(df_sub_priv, df_labels_priv, metrics_cfg) if len(df_labels_priv) > 0 else {}
                    
                    # Calculate weighted scores with NaN/Inf sanitization
                    import math
                    def calculate_weighted_score(metrics_payload, metrics_cfg):
                        if not metrics_cfg:
                            if metrics_payload:
                                m_name = list(metrics_payload.keys())[0]
                                val = metrics_payload[m_name]
                                if math.isnan(val) or math.isinf(val):
                                    return 0.0
                                if m_name.lower().strip() in {"logloss", "brier_score", "rmse", "mae", "mse", "mel_lsd", "fid", "lpips", "niqe", "ter", "mape", "median_ae"}:
                                    if m_name.lower().strip() == "brier_score":
                                        return 1.0 - val
                                    return 1.0 / (1.0 + val)
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
                            m_name_clean = m_name.lower().strip()
                            if m_name_clean in {"logloss", "brier_score", "rmse", "mae", "mse", "mel_lsd", "fid", "lpips", "niqe", "ter", "mape", "median_ae"}:
                                if m_name_clean == "brier_score":
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
                    
                    public_score = calculate_weighted_score(m_pub, metrics_cfg)
                    private_score = calculate_weighted_score(m_priv, metrics_cfg)
                    metrics_payload_pub = m_pub
                    metrics_payload_priv = m_priv
                    execution_time_ms = int((end_wall_time - start_wall_time) * 1000)
                    status = 'completed'
                    logs.append("Evaluation completed successfully.")
                except Exception as eval_err:
                    import traceback
                    status = 'failed'
                    logs.append(f"Error during parquet metric calculation: {str(eval_err)}")
                    logs.append(f"Traceback: {traceback.format_exc()}")
                    
            # Clean up securely downloaded labels directory on host if created
            if metadata and 'host_labels_dir' in locals() and host_labels_dir:
                try:
                    import shutil
                    shutil.rmtree(host_labels_dir, ignore_errors=True)
                except:
                    pass
    else:
        json_output = None
        results_file_path = os.path.join(temp_dir, f"eval_results_{results_key}.json")
        if not os.path.exists(results_file_path):
            results_file_path = os.path.join(temp_dir, "eval_results.json")
            
        if os.path.exists(results_file_path):
            try:
                with open(results_file_path, "r") as f_res:
                    json_output = json.load(f_res)
            except Exception as e:
                logs.append(f"Failed to read secure results file '{os.path.basename(results_file_path)}': {e}")
        else:
            logs.append("Error: Secure evaluation results file was not created.")
            
        is_schema_valid = True
        if is_custom_eval:
            if json_output is None:
                is_schema_valid = False
            elif not isinstance(json_output, dict):
                is_schema_valid = False
            else:
                eval_status = json_output.get("status")
                if eval_status not in ["success", "error"]:
                    is_schema_valid = False
                elif eval_status == "success":
                    pub = json_output.get("public_score")
                    priv = json_output.get("private_score")
                    if not (isinstance(pub, (int, float)) and not isinstance(pub, bool)):
                        is_schema_valid = False
                    if not (isinstance(priv, (int, float)) and not isinstance(priv, bool)):
                        is_schema_valid = False

        if is_custom_eval and not is_schema_valid:
            status = 'failed'
            logs.append("Jury Evaluator Error: The custom evaluation script failed to produce a valid results file.")
        else:
            if json_output:
                if json_output.get("status") == "success":
                    public_score = json_output.get("public_score")
                    private_score = json_output.get("private_score")
                    execution_time_ms = json_output.get("execution_time_ms")
                    metrics_payload_pub = json_output.get("metrics_payload_public") or {}
                    metrics_payload_priv = json_output.get("metrics_payload_private") or {}
                    
                    if execution_time_ms is None:
                        execution_time_ms = int((end_wall_time - start_wall_time) * 1000)
                    logs.append("Evaluation completed successfully.")
                else:
                    status = 'failed'
                    logs.append(f"Evaluation script returned error: {json_output.get('error')}")
                    if json_output.get("traceback"):
                        logs.append(json_output.get("traceback"))
            else:
                status = 'failed'
                logs.append("Evaluation failed: No structured JSON output received from secure results file.")
            
    try:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
    except:
        pass

    # Write final results status back to server or DB
    update_status(
        status_val=status,
        detailed_val=status,
        logs_list=logs,
        pub_score=public_score,
        priv_score=private_score,
        time_ms=execution_time_ms,
        m_pub=metrics_payload_pub,
        m_priv=metrics_payload_priv
    )
    
    try:
        from sse_utils import clear_submission_logs
        clear_submission_logs(submission_id)
    except Exception:
        pass
        
    return f"Submission {submission_id} evaluated with status {status}"


from celery.signals import worker_ready

@worker_ready.connect
def register_worker_specs(sender, **kwargs):
    try:
        import platform
        from cache_utils import get_redis_client
        r = get_redis_client()
        if not r:
            return
        
        worker_name = getattr(sender, 'hostname', str(sender))
        cpu_cores = os.cpu_count() or 1
        
        ram_gb = 8.0
        try:
            if platform.system() == "Linux":
                with open('/proc/meminfo', 'r') as f:
                    for line in f:
                        if "MemTotal" in line:
                            ram_kb = int(line.split()[1])
                            ram_gb = round(ram_kb / (1024 * 1024), 1)
                            break
            elif platform.system() == "Darwin":
                total_bytes = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip())
                ram_gb = round(total_bytes / (1024**3), 1)
        except Exception:
            pass
            
        gpu_id = os.environ.get("WORKER_GPU_ID", None)
        has_gpu = gpu_id is not None or "gpu" in worker_name.lower()
        gpu_type = "N/A"
        vram_gb = "N/A"
        
        if has_gpu:
            gpu_type = "NVIDIA GPU"
            try:
                gpu_name_out = subprocess.check_output(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]).decode("utf-8").strip()
                if gpu_name_out:
                    gpu_type = gpu_name_out.split('\n')[0]
                vram_out = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"]).decode("utf-8").strip()
                if vram_out:
                    vram_mb = int(vram_out.split('\n')[0])
                    vram_gb = round(vram_mb / 1024, 1)
            except Exception:
                gpu_type = "NVIDIA GPU"
                vram_gb = 8.0
                
        concurrency = 1
        try:
            if hasattr(sender, 'concurrency'):
                concurrency = sender.concurrency
        except Exception:
            pass
            
        spec = {
            "name": worker_name,
            "type": "GPU" if has_gpu else "CPU",
            "concurrency": concurrency,
            "cpu_cores": cpu_cores,
            "gpu_type": gpu_type,
            "ram_gb": ram_gb,
            "vram_gb": vram_gb,
            "last_seen": time.time()
        }
        r.set(f"worker_spec:{worker_name}", json.dumps(spec), ex=86400)
        print(f"[NeuroBench] Specs registered successfully: {spec}")
        
        # Call main server to retrieve active datasets and preload them on worker startup
        main_server_url = os.environ.get("MAIN_SERVER_URL", "http://localhost:5001")
        worker_secret_key = os.environ.get("WORKER_SECRET_KEY") or ""
        
        try:
            url = f"{main_server_url.rstrip('/')}/api/worker/active-datasets"
            headers = {"X-Worker-Token": worker_secret_key}
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                datasets_to_preload = data.get("datasets", [])
                if datasets_to_preload:
                    print(f"[NeuroBench] Active datasets to preload on startup: {datasets_to_preload}")
                    
                    # Resolve cache directory on worker
                    hf_cache_dir = os.environ.get("HF_CACHE_DIR")
                    if not hf_cache_dir:
                        hf_cache_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'hf_cache'))
                    
                    try:
                        os.makedirs(hf_cache_dir, exist_ok=True)
                    except:
                        pass
                        
                    if os.path.exists(hf_cache_dir):
                        try:
                            from datasets import load_dataset as host_load_dataset
                            for ds_name in datasets_to_preload:
                                try:
                                    print(f"[NeuroBench] Preloading dataset '{ds_name}' to '{hf_cache_dir}'...")
                                    host_load_dataset(ds_name, cache_dir=hf_cache_dir)
                                    print(f"[NeuroBench] Successfully preloaded dataset '{ds_name}' on worker startup.")
                                except Exception as e:
                                    print(f"[NeuroBench] Failed preloading dataset '{ds_name}': {e}")
                        except Exception as import_err:
                            print(f"[NeuroBench] Could not import 'datasets' to preload: {import_err}")
            else:
                print(f"[NeuroBench] Failed to fetch active datasets from main server: HTTP {res.status_code}")
        except Exception as e:
            print(f"[NeuroBench] Error fetching/preloading active datasets: {e}")
    except Exception as e:
        print(f"[NeuroBench] Failed to register specs: {e}")

