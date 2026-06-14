import os
import json
import subprocess
import tempfile
import time
import hashlib
import threading
from datetime import datetime
from celery import Celery

# Check if running as remote worker to bypass Flask/SQLAlchemy database connection setup
RUNNING_AS_WORKER = os.environ.get("RUNNING_AS_WORKER") == "true"

if RUNNING_AS_WORKER:
    celery = Celery(
        'tasks',
        broker=os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
        backend=os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')
    )
    db = None
    Submission = None
    Challenge = None
    User = None
    Task = None
    publish_submissions_update = None
    publish_leaderboard_update = None
else:
    from models import db, Submission, Challenge, User, Task
    from app import create_app
    from sse_utils import publish_submissions_update, publish_leaderboard_update
    app = create_app()
    celery = Celery(
        'tasks',
        broker=app.config['CELERY_BROKER_URL'],
        backend=app.config['CELERY_RESULT_BACKEND']
    )

def run_command_streaming(cmd, logs_list, time_limit=None):
    """
    Runs a command and streams stdout/stderr lines to logs_list in real-time.
    Returns (returncode, stdout_str, stderr_str, is_timeout).
    """
    stdout_lines = []
    stderr_lines = []
    process_timeout = False

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        def read_pipe(pipe, collector, is_err=False):
            try:
                for line in iter(pipe.readline, ''):
                    if not isinstance(line, str):
                        break
                    collector.append(line)
                    clean_line = line.rstrip('\r\n')
                    if is_err:
                        logs_list.append(f"[stderr] {clean_line}")
                    else:
                        logs_list.append(clean_line)
            except Exception:
                pass
            finally:
                try:
                    pipe.close()
                except:
                    pass

        t_out = threading.Thread(target=read_pipe, args=(proc.stdout, stdout_lines, False))
        t_err = threading.Thread(target=read_pipe, args=(proc.stderr, stderr_lines, True))
        
        t_out.start()
        t_err.start()
        
        start_wait = time.time()
        while True:
            ret = proc.poll()
            if ret is not None:
                break
            if time_limit and (time.time() - start_wait > time_limit):
                proc.kill()
                process_timeout = True
                break
            time.sleep(0.1)
            
        t_out.join(timeout=2.0)
        t_err.join(timeout=2.0)
        
        stdout_str = "".join(stdout_lines)
        stderr_str = "".join(stderr_lines)
        return proc.returncode, stdout_str, stderr_str, process_timeout
    except Exception as exc:
        logs_list.append(f"Failed to execute command: {exc}")
        return -1, "", str(exc), False

class StreamingLogList(list):
    def __init__(self, submission_id):
        super().__init__()
        self.submission_id = submission_id
        
    def append(self, item):
        super().append(item)
        try:
            from sse_utils import publish_submission_log
            publish_submission_log(self.submission_id, str(item))
        except Exception as e:
            pass

# Set Celery configuration
celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_queue_max_priority=10,
    task_default_priority=5,
    beat_schedule={
        'recalculate-leaderboards-every-15-seconds': {
            'task': 'tasks.recalculate_all_leaderboards',
            'schedule': 15.0,
        },
        'run-automated-backup-every-10-minutes': {
            'task': 'tasks.run_automated_backup',
            'schedule': 600.0,
        },
    }
)

import requests

class MockModel:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

import time

def report_status_to_server(metadata, status, detailed_status, logs=None, public_score=None, private_score=None, execution_time_ms=None, metrics_payload_pub=None, metrics_payload_priv=None, gpu_node=None, max_retries=3, backoff_factor=2):
    if not metadata or "main_server_url" not in metadata or "worker_secret_key" not in metadata:
        return False
    url = f"{metadata['main_server_url']}/api/worker/report/{metadata['submission_id']}"
    headers = {
        "X-Worker-Token": metadata["worker_secret_key"],
        "Content-Type": "application/json"
    }
    payload = {
        "status": status,
        "detailed_status": detailed_status
    }
    if logs is not None:
        payload["logs"] = logs
    if public_score is not None:
        payload["public_score"] = public_score
    if private_score is not None:
        payload["private_score"] = private_score
    if execution_time_ms is not None:
        payload["execution_time_ms"] = execution_time_ms
    if metrics_payload_pub is not None:
        payload["metrics_payload_pub"] = metrics_payload_pub
    if metrics_payload_priv is not None:
        payload["metrics_payload_priv"] = metrics_payload_priv
    if gpu_node is not None:
        payload["gpu_node"] = gpu_node
        
    for attempt in range(max_retries):
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=10)
            if res.status_code == 200:
                return True
            print(f"Server returned status {res.status_code} for report attempt {attempt + 1}")
        except Exception as e:
            print(f"Error reporting progress to server (attempt {attempt + 1}/{max_retries}): {e}")
        
        if attempt < max_retries - 1:
            sleep_time = backoff_factor ** attempt
            time.sleep(sleep_time)
            
    return False

def download_task_files_to_dir(metadata, temp_dir, logs):
    if not metadata or "main_server_url" not in metadata or "worker_secret_key" not in metadata:
        return
    files_list = metadata.get("task_files", [])
    if not files_list:
        return
        
    task_id = metadata.get("task_id")
    for f in files_list:
        filename = f["filename"]
        url = f"{metadata['main_server_url']}/api/worker/tasks/{task_id}/files/{filename}"
        headers = {
            "X-Worker-Token": metadata["worker_secret_key"]
        }
        try:
            logs.append(f"Downloading task file '{filename}' from server...")
            res = requests.get(url, headers=headers, timeout=30)
            if res.status_code == 200:
                dest_file = os.path.join(temp_dir, filename)
                with open(dest_file, "wb") as df:
                    df.write(res.content)
                logs.append(f"Downloaded task file '{filename}' successfully.")
            else:
                logs.append(f"Failed to download task file '{filename}': Status code {res.status_code}")
        except Exception as e:
            logs.append(f"Error downloading task file '{filename}': {str(e)}")

EVALUATION_TEMPLATE = """
import os
import sys
import json
import traceback
import time
from datasets import load_dataset
from sklearn.metrics import accuracy_score, f1_score, mean_squared_error

# Inject HF cache directory if defined
if os.environ.get("HF_CACHE_DIR"):
    os.environ["HF_HOME"] = os.environ.get("HF_CACHE_DIR")
    os.environ["HF_DATASETS_CACHE"] = os.environ.get("HF_CACHE_DIR")

# --- BEGIN USER CODE ---
{user_code}
# --- END USER CODE ---

def run_evaluation():
    try:
        # Load Hugging Face dataset
        dataset_path = "{hf_dataset_path}"
        dataset_config = "{hf_dataset_config}"
        dataset_split = "{hf_dataset_split}"
        
        # Load dataset
        if dataset_config and dataset_config != "None" and dataset_config != "":
            dataset = load_dataset(dataset_path, dataset_config, split=dataset_split)
        else:
            dataset = load_dataset(dataset_path, split=dataset_split)
            
        total_len = len(dataset)
        if total_len == 0:
            raise ValueError("The Hugging Face dataset split has 0 rows.")
            
        # Define public vs private split (30% public / 70% private)
        public_size = int(total_len * 0.3)
        if public_size == 0:
            public_size = 1 # Guarantee at least 1 row for public
            
        # Determine column names (defaults to 'text' and 'label')
        input_col = "{input_col}" or "text"
        label_col = "{label_col}" or "label"
        
        # Fallbacks for column inspection if columns do not exist
        if input_col not in dataset.column_names:
            # Try to grab the first non-label column
            cols = [c for c in dataset.column_names if c != label_col]
            if cols:
                input_col = cols[0]
            else:
                input_col = dataset.column_names[0]
                
        if label_col not in dataset.column_names:
            if "label" in dataset.column_names:
                label_col = "label"
            elif "labels" in dataset.column_names:
                label_col = "labels"
            else:
                label_col = dataset.column_names[-1]
                
        # Split indexes
        public_dataset = dataset.select(range(0, public_size))
        private_dataset = dataset.select(range(public_size, total_len))
        
        # Run model predictions
        # We check if user code defines predict(inputs)
        if 'predict' not in globals():
            raise AttributeError("Your notebook code must define a function 'predict(inputs_list)' that takes a list of data points and returns predictions.")
            
        # Evaluate Public Split
        public_inputs = public_dataset[input_col]
        public_labels = public_dataset[label_col]
        
        start_time = time.time()
        public_preds = predict(public_inputs)
        public_time = time.time() - start_time
        
        if len(public_preds) != len(public_labels):
            raise ValueError(f"predict returned {{len(public_preds)}} items, but expected {{len(public_labels)}}.")
            
        # Evaluate Private Split
        private_inputs = private_dataset[input_col]
        private_labels = private_dataset[label_col]
        
        start_time = time.time()
        private_preds = predict(private_inputs)
        private_time = time.time() - start_time
        
        # Compute metrics
        metric = "{metric_name}".lower()
        
        def calculate_score(y_true, y_pred):
            if metric == "accuracy":
                return accuracy_score(y_true, y_pred)
            elif metric == "f1":
                return f1_score(y_true, y_pred, average="weighted")
            elif metric == "mse":
                return mean_squared_error(y_true, y_pred)
            else:
                # Default fallback
                return accuracy_score(y_true, y_pred)
                
        pub_score = calculate_score(public_labels, public_preds)
        priv_score = calculate_score(private_labels, private_preds)
        
        # Output results JSON directly to file
        with open("eval_results.json", "w") as f_res:
            json.dump({{
                "status": "success",
                "public_score": float(pub_score),
                "private_score": float(priv_score),
                "metrics_payload_public": {{metric: float(pub_score)}},
                "metrics_payload_private": {{metric: float(priv_score)}},
                "execution_time_ms": int((public_time + private_time) * 1000)
            }}, f_res)
        
    except Exception as e:
        with open("eval_results.json", "w") as f_res:
            json.dump({{
                "status": "error",
                "error": str(e),
                "traceback": traceback.format_exc()
            }}, f_res)

if __name__ == "__main__":
    run_evaluation()
"""

DEFAULT_EVALUATION_TEMPLATE = """
import os
import sys
import json
import traceback
import time
from datasets import load_dataset
from sklearn.metrics import accuracy_score, f1_score, mean_squared_error

# Inject HF cache directory if defined
if os.environ.get("HF_CACHE_DIR"):
    os.environ["HF_HOME"] = os.environ.get("HF_CACHE_DIR")
    os.environ["HF_DATASETS_CACHE"] = os.environ.get("HF_CACHE_DIR")

# --- BEGIN USER CODE ---
{user_code}
# --- END USER CODE ---

def run_evaluation():
    try:
        # Load Hugging Face dataset
        dataset_path = "{hf_eval_repo}"
        token = "{hf_token}"
        public_pct = {public_eval_percentage}
        
        # Load dataset
        if token:
            dataset = load_dataset(dataset_path, split="{hf_dataset_split}", token=token)
        else:
            dataset = load_dataset(dataset_path, split="{hf_dataset_split}")
            
        total_len = len(dataset)
        if total_len == 0:
            raise ValueError("The Hugging Face dataset split has 0 rows.")
            
        # Define public vs private split
        public_size = int(total_len * (public_pct / 100.0))
        if public_size == 0:
            public_size = 1
        if public_size >= total_len:
            public_size = total_len - 1
            
        # Determine column names (defaults to 'text' and 'label')
        input_col = "text"
        label_col = "label"
        
        # Fallbacks for column inspection if columns do not exist
        if input_col not in dataset.column_names:
            cols = [c for c in dataset.column_names if c != label_col]
            if cols:
                input_col = cols[0]
            else:
                input_col = dataset.column_names[0]
                
        if label_col not in dataset.column_names:
            if "label" in dataset.column_names:
                label_col = "label"
            elif "labels" in dataset.column_names:
                label_col = "labels"
            else:
                label_col = dataset.column_names[-1]
                
        # Split indexes
        public_dataset = dataset.select(range(0, public_size))
        private_dataset = dataset.select(range(public_size, total_len))
        
        if 'predict' not in globals():
            raise AttributeError("Your notebook code must define a function 'predict(inputs_list)' that takes a list of data points and returns predictions.")
            
        # Evaluate Public Split
        public_inputs = public_dataset[input_col]
        public_labels = public_dataset[label_col]
        
        start_time = time.time()
        public_preds = predict(public_inputs)
        public_time = time.time() - start_time
        
        if len(public_preds) != len(public_labels):
            raise ValueError(f"predict returned {{len(public_preds)}} items, but expected {{len(public_labels)}}.")
            
        # Evaluate Private Split
        private_inputs = private_dataset[input_col]
        private_labels = private_dataset[label_col]
        
        start_time = time.time()
        private_preds = predict(private_inputs)
        private_time = time.time() - start_time
        
        # Calculate scores
        # metrics_cfg e.g. (accuracy: (weight: 1.0, higher_is_better: true))
        metrics_cfg = {metrics_config_str}
        
        if not metrics_cfg:
            metrics_cfg = {{"accuracy": {{"weight": 1.0, "higher_is_better": True}}}}
            
        def eval_metric(metric_name, y_true, y_pred):
            m_name = metric_name.lower()
            if m_name == "accuracy":
                return accuracy_score(y_true, y_pred)
            elif m_name == "f1":
                return f1_score(y_true, y_pred, average="weighted")
            elif m_name in ["mse", "mean_squared_error"]:
                return mean_squared_error(y_true, y_pred)
            else:
                return accuracy_score(y_true, y_pred)
                
        pub_payload = {{}}
        priv_payload = {{}}
        
        pub_weighted = 0.0
        priv_weighted = 0.0
        total_weight = 0.0
        
        for m_name, m_info in metrics_cfg.items():
            weight = m_info.get("weight", 1.0)
            total_weight += weight
            
            val_pub = eval_metric(m_name, public_labels, public_preds)
            val_priv = eval_metric(m_name, private_labels, private_preds)
            
            pub_payload[m_name] = float(val_pub)
            priv_payload[m_name] = float(val_priv)
            
            pub_weighted += float(val_pub) * weight
            priv_weighted += float(val_priv) * weight
            
        if total_weight > 0:
            final_pub_score = pub_weighted / total_weight
            final_priv_score = priv_weighted / total_weight
        else:
            final_pub_score = 0.0
            final_priv_score = 0.0
            
        # Output results JSON directly to file
        with open("eval_results.json", "w") as f_res:
            json.dump({{
                "status": "success",
                "public_score": final_pub_score,
                "private_score": final_priv_score,
                "metrics_payload_public": pub_payload,
                "metrics_payload_private": priv_payload,
                "execution_time_ms": int((public_time + private_time) * 1000)
            }}, f_res)
        
    except Exception as e:
        with open("eval_results.json", "w") as f_res:
            json.dump({{
                "status": "error",
                "error": str(e),
                "traceback": traceback.format_exc()
            }}, f_res)

if __name__ == "__main__":
    run_evaluation()
"""


@celery.task(bind=True)
def evaluate_submission(self, submission_id, metadata=None):
    """
    Executes a submission in a sandboxed sub-process or docker environment.
    """
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
            hf_eval_repo=metadata.get("hf_eval_repo"),
            public_eval_percentage=metadata.get("public_eval_percentage"),
            get_hf_api_key=lambda: metadata.get("hf_token"),
            evaluator_script_path=None,
            custom_eval_code=metadata.get("custom_eval_code")
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
            task = MockModel(
                id=db_submission.task.id if db_submission.task else None,
                time_limit_sec=db_submission.task.time_limit_sec if db_submission.task else None,
                ram_limit_mb=db_submission.task.ram_limit_mb if db_submission.task else None,
                gpu_required=db_submission.task.gpu_required if db_submission.task else None,
                base_docker_image=db_submission.task.base_docker_image if db_submission.task else None,
                apt_packages=db_submission.task.apt_packages if db_submission.task else None,
                pip_requirements=db_submission.task.pip_requirements if db_submission.task else None,
                metrics_config=db_submission.task.metrics_config if db_submission.task else None,
                hf_eval_repo=db_submission.task.hf_eval_repo if db_submission.task else None,
                public_eval_percentage=db_submission.task.public_eval_percentage if db_submission.task else None,
                get_hf_api_key=lambda: db_submission.task.get_hf_api_key() if db_submission.task else "",
                evaluator_script_path=db_submission.task.evaluator_script_path if db_submission.task else None,
                files=db_submission.task.files if db_submission.task else None,
                custom_eval_code=db_submission.task.custom_eval_code if (db_submission.task and hasattr(db_submission.task, 'custom_eval_code')) else None
            )
            challenge = MockModel(
                id=db_submission.challenge.id if db_submission.challenge else None,
                time_limit_sec=db_submission.challenge.time_limit_sec if db_submission.challenge else None,
                ram_limit_mb=db_submission.challenge.ram_limit_mb if db_submission.challenge else None,
                gpu_required=db_submission.challenge.gpu_required if db_submission.challenge else None,
                metric_name=db_submission.challenge.metric_name if db_submission.challenge else "accuracy",
                hf_dataset_path=getattr(db_submission.challenge, 'hf_dataset_path', None),
                hf_dataset_config=getattr(db_submission.challenge, 'hf_dataset_config', None),
                hf_dataset_split=getattr(db_submission.challenge, 'hf_dataset_split', 'test'),
                hf_input_column=getattr(db_submission.challenge, 'hf_input_column', 'text'),
                hf_label_column=getattr(db_submission.challenge, 'hf_label_column', 'label')
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
        if status_val == 'running' and detailed_val != 'running':
            return
        if metadata:
            logs_str = "\n".join(logs_list) if logs_list is not None else None
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
            if not success and status_val in ('completed', 'failed'):
                raise RuntimeError(f"Failed to deliver final status '{status_val}' callback to server.")
        else:
            with app.app_context():
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
                task_files_dir = os.path.join(app.config['UPLOAD_FOLDER'], f"task_{task.id}")
                if os.path.exists(task_files_dir):
                    import shutil
                    for f in files_meta:
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
    if hf_cache_dir:
        env["HF_HOME"] = hf_cache_dir
        env["HF_DATASETS_CACHE"] = hf_cache_dir

    # Write evaluator script / template
    is_custom_eval = False
    if metadata:
        if metadata.get("is_custom_eval") and metadata.get("custom_eval_code"):
            with open(os.path.join(temp_dir, "evaluator.py"), "w") as f:
                f.write(metadata.get("custom_eval_code"))
            is_custom_eval = True
            with open(os.path.join(temp_dir, "submission_runner.py"), "w") as f:
                f.write(user_code)
        else:
            metrics_cfg_str = json.dumps(metadata.get("metrics_config")) if metadata.get("metrics_config") else "None"
            run_script_content = DEFAULT_EVALUATION_TEMPLATE.format(
                user_code=user_code,
                hf_eval_repo=metadata.get("hf_eval_repo") or "",
                hf_token=metadata.get("hf_token") or "",
                public_eval_percentage=metadata.get("public_eval_percentage") or 30,
                metrics_config_str=metrics_cfg_str,
                hf_dataset_split=challenge.hf_dataset_split or "test"
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
                    f.write(user_code)
            elif task.evaluator_script_path and os.path.exists(task.evaluator_script_path):
                import shutil
                shutil.copy(task.evaluator_script_path, os.path.join(temp_dir, "evaluator.py"))
                is_custom_eval = True
                with open(os.path.join(temp_dir, "submission_runner.py"), "w") as f:
                    f.write(user_code)
            else:
                hf_token = task.get_hf_api_key() or ""
                metrics_cfg_str = json.dumps(task.metrics_config) if task.metrics_config else "None"
                run_script_content = DEFAULT_EVALUATION_TEMPLATE.format(
                    user_code=user_code,
                    hf_eval_repo=task.hf_eval_repo or "",
                    hf_token=hf_token,
                    public_eval_percentage=task.public_eval_percentage or 30,
                    metrics_config_str=metrics_cfg_str,
                    hf_dataset_split=challenge.hf_dataset_split or "test"
                )
                with open(os.path.join(temp_dir, "submission_runner.py"), "w") as f:
                    f.write(run_script_content)
        else:
            input_col = getattr(challenge, 'hf_input_column', 'text')
            label_col = getattr(challenge, 'hf_label_column', 'label')
            run_script_content = EVALUATION_TEMPLATE.format(
                user_code=user_code,
                hf_dataset_path=challenge.hf_dataset_path,
                hf_dataset_config=challenge.hf_dataset_config or "",
                hf_dataset_split=challenge.hf_dataset_split or "test",
                input_col=input_col,
                label_col=label_col,
                metric_name=challenge.metric_name
            )
            with open(os.path.join(temp_dir, "submission_runner.py"), "w") as f:
                f.write(run_script_content)

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
            
            dockerfile_lines.append("RUN pip install --no-cache-dir datasets scikit-learn pandas numpy cryptography")
            
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
                logs
            )
            if retcode != 0:
                logs.append(f"Docker build failed with return code {retcode}!")
                update_status('failed', 'failed', logs_list=logs)
                report_status_to_server(metadata, 'failed', 'failed', logs=logs)
                return
            else:
                logs.append("Docker image built successfully.")

    # Update status: Running Inference
    update_status('running', 'running_inference', logs_list=logs)

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
        "--tmpfs", "/tmp",
        "-m", f"{ram_limit}m",
        "-v", f"{temp_dir}:/app",
        "-w", "/app",
    ] + gpu_args + hf_cache_mount + [
        "-e", "HF_HOME=/hf_cache",
        "-e", "HF_DATASETS_CACHE=/hf_cache",
        "-e", "HF_DATASETS_OFFLINE=1",
        "-e", "HF_HUB_OFFLINE=1",
        image_tag, "python", exec_file
    ]
    
    logs.append(f"Executing sandbox command: {' '.join(cmd)}")
    retcode, stdout, stderr, process_timeout = run_command_streaming(cmd, logs, time_limit=time_limit)
    if process_timeout:
        subprocess.run(["docker", "ps", "-q", "--filter", f"ancestor={image_tag}"], capture_output=True)
        
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
    else:
        json_output = None
        results_file_path = os.path.join(temp_dir, "eval_results.json")
        if os.path.exists(results_file_path):
            try:
                with open(results_file_path, "r") as f_res:
                    json_output = json.load(f_res)
            except Exception as e:
                logs.append(f"Failed to read secure results file 'eval_results.json': {e}")
        else:
            logs.append("Error: Secure evaluation results file 'eval_results.json' was not created.")
            
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
    except:
        pass
        
    return f"Submission {submission_id} evaluated with status {status}"


from celery.signals import worker_ready

@worker_ready.connect
def register_worker_specs(sender, **kwargs):
    try:
        import redis
        import platform
        broker_url = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
        r = redis.Redis.from_url(broker_url)
        
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
        print(f"[NAI Worker] Specs registered successfully: {spec}")
    except Exception as e:
        print(f"[NAI Worker] Failed to register specs: {e}")


@celery.task
def recalculate_all_leaderboards():
    """
    Periodically recalculates and caches leaderboards for all active challenges
    to avoid synchronous cache invalidation and rebuild spikes.
    """
    if RUNNING_AS_WORKER:
        return
    from routes.leaderboard import build_and_cache_leaderboard
    with app.app_context():
        # Get active or recent challenges
        active_challenges = Challenge.query.filter_by(is_archived=False).all()
        for challenge in active_challenges:
            # Rebuild both frozen and unfrozen versions to keep both warm!
            build_and_cache_leaderboard(challenge.id, is_frozen_view=False)
            if challenge.is_frozen:
                build_and_cache_leaderboard(challenge.id, is_frozen_view=True)


@celery.task
def run_automated_backup():
    """
    Triggers the automated database and uploads backup script.
    """
    if RUNNING_AS_WORKER:
        return
    import subprocess
    script_path = "/Users/delyan-boychev/nai-webplatform/backup_db.sh"
    try:
        res = subprocess.run(["bash", script_path], capture_output=True, text=True)
        if res.returncode != 0:
            print(f"[NAI Backup] Automated backup script failed: {res.stderr}")
        else:
            print("[NAI Backup] Automated backup completed successfully.")
    except Exception as e:
        print(f"[NAI Backup] Error running automated backup script: {e}")

