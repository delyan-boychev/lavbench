import os
import json
import ast
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
from flask import (
    Blueprint,
    request,
    jsonify,
    send_file,
    send_from_directory,
    current_app,
    Response,
    stream_with_context,
)
from werkzeug.utils import secure_filename
from models import db, Challenge, Task, User, Submission, decrypt_field, is_metric_lower_better
from auth_utils import login_required, role_required, rate_limit
from sse_utils import publish_submissions_update, publish_leaderboard_update


tasks_bp = Blueprint("tasks", __name__)

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB limit per file


def check_competitor_access(user_id, challenge_id):
    user = db.session.get(User, user_id)
    if not user or user.challenge_id != challenge_id:
        return False
    return True


def check_task_started(task, user_role, user_id):
    if user_role == "competitor":
        if not check_competitor_access(user_id, task.challenge_id):
            return False
        challenge = task.challenge
        if challenge and not challenge.is_started:
            return False
        if task.stage_id:
            from models import Stage

            stage = db.session.get(Stage, task.stage_id)
            if stage:
                try:
                    import zoneinfo

                    tz = zoneinfo.ZoneInfo(challenge.timezone or "UTC")
                    now_local = datetime.now(tz).replace(tzinfo=None)
                except Exception:
                    now_local = datetime.utcnow()
                if now_local < stage.start_time:
                    return False
    return True


def to_bool(val):
    if val is None:
        return None
    if isinstance(val, str):
        return val.lower() in ["true", "1", "yes", "on"]
    return bool(val)


def to_int(val):
    if val is None or str(val).strip() == "":
        return None
    try:
        return int(val)
    except ValueError:
        return None


from services.submission_service import (
    extract_code_from_cells,
    extract_code_from_notebook,
    check_execution_rules,
    calculate_submission_priority,
)


def queue_system_submission(task, challenge, code_cells, admin_id, priority=8):
    submission = Submission(
        user_id=admin_id,
        challenge_id=challenge.id,
        task_id=task.id,
        status="queued",
        detailed_status="queued",
        is_baseline=True,
        code_cells=json.dumps(code_cells),
    )
    db.session.add(submission)
    db.session.commit()

    publish_submissions_update(submission.task_id, submission.user_id)
    publish_leaderboard_update(submission.task_id)

    task_files_list = []
    if task.files:
        try:
            task_files_list = json.loads(task.files)
        except:
            pass

    main_server_url = os.environ.get("MAIN_SERVER_URL", "http://localhost:5001")

    from auth_utils import generate_worker_token
    from tasks import evaluate_submission

    time_limit = task.time_limit_sec or challenge.time_limit_sec or 300
    worker_secret_key = generate_worker_token(submission.id, task.id, time_limit + 600)

    gpu_required = False
    if task.gpu_required is not None:
        gpu_required = task.gpu_required
    elif challenge.gpu_required is not None:
        gpu_required = challenge.gpu_required

    metadata = {
        "submission_id": submission.id,
        "task_id": task.id,
        "challenge_id": challenge.id,
        "user_code": "\n\n".join(extract_code_from_cells(code_cells)),
        "time_limit": task.time_limit_sec or challenge.time_limit_sec or 300,
        "ram_limit": task.ram_limit_mb or challenge.ram_limit_mb or 8192,
        "gpu_required": gpu_required,
        "base_docker_image": task.base_docker_image,
        "apt_packages": task.apt_packages,
        "pip_requirements": task.pip_requirements,
        "is_custom_eval": (
            True
            if (
                task.custom_eval_code
                or (task.evaluator_script_path and os.path.exists(task.evaluator_script_path))
            )
            else False
        ),
        "metrics_config": task.metrics_config,
        "hf_datasets": (
            task.hf_datasets
            if isinstance(task.hf_datasets, str)
            else (json.dumps(task.hf_datasets) if task.hf_datasets else None)
        ),
        "hf_models": (
            task.hf_models
            if isinstance(task.hf_models, str)
            else (json.dumps(task.hf_models) if task.hf_models else None)
        ),
        "public_eval_percentage": task.public_eval_percentage or 30,
        "task_files": task_files_list,
        "main_server_url": main_server_url,
        "celery_broker_url": os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"),
        "worker_secret_key": worker_secret_key,
    }

    if task.custom_eval_code:
        metadata["custom_eval_code"] = task.custom_eval_code
    elif task.evaluator_script_path and os.path.exists(task.evaluator_script_path):
        try:
            with open(task.evaluator_script_path, "r") as ef:
                metadata["custom_eval_code"] = ef.read()
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "Failed to read evaluator script for task %s", task.id
            )

    # Dispatch the submission via Celery
    queue_name = "gpu_queue" if gpu_required else "celery"

    evaluate_submission.apply_async(
        args=[submission.id, metadata], priority=priority, queue=queue_name
    )


def _maybe_queue_baseline(task, challenge, admin_id):
    """Delete old baseline submissions and queue a new one if a baseline notebook exists."""
    # Remove old baseline submissions for this task and their physical files
    import os

    old_baselines = Submission.query.filter_by(task_id=task.id, is_baseline=True).all()
    paths_to_delete = [(s.code_storage_path, s.log_storage_path) for s in old_baselines]

    Submission.query.filter_by(task_id=task.id, is_baseline=True).delete(synchronize_session=False)
    db.session.commit()

    for code_path, log_path in paths_to_delete:
        if code_path and os.path.exists(code_path):
            try:
                os.remove(code_path)
            except OSError:
                pass
        if log_path and os.path.exists(log_path):
            try:
                os.remove(log_path)
            except OSError:
                pass

    # Parse and submit new baseline if notebook exists
    baseline_cells = []
    if task.baseline_notebook_path and os.path.exists(task.baseline_notebook_path):
        baseline_cells = extract_code_from_notebook(task.baseline_notebook_path)

    if baseline_cells:
        queue_system_submission(task, challenge, baseline_cells, admin_id, priority=8)


# --- TASK CRUD ---


@tasks_bp.route("/tasks/<int:task_id>", methods=["GET"])
@login_required
def get_task(task_id):
    """
    API endpoint.
    ---
    tags:
      - Tasks
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: task_id
        required: true
        type: string
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    task = db.get_or_404(Task, task_id)
    user_role = request.user["role"]
    user_id = request.user["user_id"]

    if not check_task_started(task, user_role, user_id):
        return (
            jsonify(
                {"error": "Access denied or task not available yet.", "code": "ERR_NOT_AVAILABLE"}
            ),
            403,
        )

    return jsonify(task.to_dict())


@tasks_bp.route("/challenges/<int:challenge_id>/tasks", methods=["POST"])
@role_required(["admin", "jury"])
def create_task(challenge_id):
    """
    Create a new evaluation task with resource limits, metrics, and test data files.
    ---
    tags:
      - Tasks
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: challenge_id
        required: true
        type: string
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    challenge = db.get_or_404(Challenge, challenge_id)

    title = request.form.get("title")
    description = request.form.get("description")

    if not title:
        return jsonify({"error": "Task title is required."}), 400

    if (
        "baseline_notebook" not in request.files
        or request.files["baseline_notebook"].filename == ""
    ):
        return jsonify({"error": "Baseline notebook is required."}), 400

    ram_limit_mb = to_int(request.form.get("ram_limit_mb"))
    time_limit_sec = to_int(request.form.get("time_limit_sec"))
    gpu_required_raw = request.form.get("gpu_required")
    gpu_required = to_bool(gpu_required_raw) if gpu_required_raw is not None else None

    base_docker_image = request.form.get("base_docker_image")
    apt_packages = request.form.get("apt_packages")
    pip_requirements = request.form.get("pip_requirements")

    if request.user.get("role") != "admin":
        if base_docker_image or apt_packages or pip_requirements:
            return (
                jsonify(
                    {
                        "error": "Only administrators are allowed to configure custom environments.",
                        "code": "ERR_FORBIDDEN",
                    }
                ),
                403,
            )

    # Task parameter validations
    if ram_limit_mb is not None:
        if ram_limit_mb <= 0 or ram_limit_mb > 16384:
            return (
                jsonify(
                    {
                        "error": "RAM limit must be a positive integer and cannot exceed 16384 MB (16 GB)."
                    }
                ),
                400,
            )

    import re

    if base_docker_image:
        DOCKER_IMAGE_REGEX = (
            r"^[a-z0-9]+(?:[._-][a-z0-9]+)*/?[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[a-zA-Z0-9_.-]+)?$"
        )
        if not re.match(DOCKER_IMAGE_REGEX, base_docker_image):
            return jsonify({"error": "Invalid base Docker image name format."}), 400

    if apt_packages:
        packages = [p.strip() for p in apt_packages.replace(",", " ").split() if p.strip()]
        for pkg in packages:
            if not re.match(r"^[a-zA-Z0-9.+-]+$", pkg):
                return jsonify({"error": f"Invalid APT package name: '{pkg}'."}), 400

    if pip_requirements:
        for line in pip_requirements.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not re.match(
                r"^[a-zA-Z0-9_.-]+(?:\s*(?:>=|<=|==|!=|~=|>|<)\s*[a-zA-Z0-9_.-]+(?:\s*,\s*(?:>=|<=|==|!=|~=|>|<)\s*[a-zA-Z0-9_.-]+)*)?$",
                line,
            ):
                return jsonify({"error": f"Invalid pip requirement line format: '{line}'."}), 400

    ban_magic_commands = to_bool(request.form.get("ban_magic_commands")) or False
    banned_imports = request.form.get("banned_imports")
    whitelisted_imports = request.form.get("whitelisted_imports")

    hf_datasets_raw = request.form.get("hf_datasets")
    hf_datasets = None
    if hf_datasets_raw:
        try:
            hf_datasets = json.loads(hf_datasets_raw)
        except:
            return jsonify({"error": "hf_datasets must be valid JSON array."}), 400
        if not isinstance(hf_datasets, list):
            return jsonify({"error": "hf_datasets must be a list."}), 400
        if len(hf_datasets) > 5:
            return jsonify({"error": "You can configure up to 5 Hugging Face datasets."}), 400
        for item in hf_datasets:
            if not isinstance(item, str):
                return jsonify({"error": "Dataset names must be strings."}), 400

    hf_models_raw = request.form.get("hf_models")
    hf_models = None
    if hf_models_raw:
        try:
            hf_models = json.loads(hf_models_raw)
        except:
            return jsonify({"error": "hf_models must be valid JSON array."}), 400
        if not isinstance(hf_models, list):
            return jsonify({"error": "hf_models must be a list."}), 400
        if len(hf_models) > 5:
            return jsonify({"error": "You can configure up to 5 Hugging Face models."}), 400
        for item in hf_models:
            if not isinstance(item, str):
                return jsonify({"error": "Model names must be strings."}), 400

    metrics_config_raw = request.form.get("metrics_config")
    metrics_config = None
    if metrics_config_raw:
        try:
            metrics_config = json.loads(metrics_config_raw)
        except:
            return jsonify({"error": "metrics_config must be valid JSON."}), 400

    if metrics_config:
        from evaluation_engine import AVAILABLE_METRICS

        allowed_metrics = list(AVAILABLE_METRICS.keys())
        for metric_name in metrics_config.keys():
            if metric_name == "_columns":
                continue
            if metric_name not in allowed_metrics:
                return (
                    jsonify(
                        {
                            "error": f"Invalid metric '{metric_name}'. Allowed metrics: {allowed_metrics}"
                        }
                    ),
                    400,
                )
            cfg = metrics_config[metric_name]
            if not isinstance(cfg, dict) or "weight" not in cfg:
                return (
                    jsonify(
                        {
                            "error": f"Metric '{metric_name}' configuration must be a dictionary and include a 'weight'."
                        }
                    ),
                    400,
                )
            try:
                float(cfg["weight"])
            except (ValueError, TypeError):
                return (
                    jsonify(
                        {"error": f"Weight for metric '{metric_name}' must be a numeric value."}
                    ),
                    400,
                )
            if "options" in cfg and not isinstance(cfg["options"], dict):
                return (
                    jsonify(
                        {
                            "error": f"Options for metric '{metric_name}' must be a dictionary/JSON object."
                        }
                    ),
                    400,
                )

    public_eval_percentage = to_int(request.form.get("public_eval_percentage")) or 30
    max_submissions_per_period = to_int(request.form.get("max_submissions_per_period"))
    submission_period_hours = to_int(request.form.get("submission_period_hours"))
    stage_id = to_int(request.form.get("stage_id"))
    if stage_id:
        from models import Stage

        st = Stage.query.filter_by(id=stage_id, challenge_id=challenge_id).first()
        if not st:
            return jsonify({"error": "Invalid stage_id for this challenge."}), 400

    task = Task(
        challenge_id=challenge_id,
        stage_id=stage_id,
        title=title,
        description=description,
        ram_limit_mb=ram_limit_mb,
        time_limit_sec=time_limit_sec,
        gpu_required=gpu_required,
        base_docker_image=base_docker_image,
        apt_packages=apt_packages,
        pip_requirements=pip_requirements,
        ban_magic_commands=ban_magic_commands,
        banned_imports=banned_imports,
        whitelisted_imports=whitelisted_imports,
        metrics_config=metrics_config,
        hf_datasets=hf_datasets,
        hf_models=hf_models,
        public_eval_percentage=public_eval_percentage,
        max_submissions_per_period=max_submissions_per_period,
        submission_period_hours=submission_period_hours,
        files="[]",
    )

    hf_api_key = request.form.get("hf_api_key")
    if hf_api_key:
        task.set_hf_api_key(hf_api_key)

    db.session.add(task)
    db.session.commit()

    uploaded_files_meta = []
    files_keys = [k for k in request.files.keys() if k.startswith("file")]

    if len(files_keys) > 5:
        db.session.delete(task)
        db.session.commit()
        return jsonify({"error": "You can upload a maximum of 5 files per task."}), 400

    task_upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], f"task_{task.id}")
    os.makedirs(task_upload_dir, exist_ok=True)

    if "evaluator_script" in request.files:
        f = request.files["evaluator_script"]
        if f and f.filename != "":
            safe_name = "evaluator.py"
            save_path = os.path.join(task_upload_dir, safe_name)
            f.save(save_path)
            task.evaluator_script_path = save_path

    if "baseline_notebook" in request.files:
        f = request.files["baseline_notebook"]
        if f and f.filename != "":
            from services.file_validation import validate_extension

            valid_ext, ext_err = validate_extension(f.filename, {".ipynb"})
            if not valid_ext:
                db.session.delete(task)
                db.session.commit()
                import shutil

                shutil.rmtree(task_upload_dir, ignore_errors=True)
                return jsonify({"error": ext_err}), 400
            safe_name = "baseline_" + secure_filename(f.filename)
            save_path = os.path.join(task_upload_dir, safe_name)
            f.save(save_path)
            task.baseline_notebook_path = save_path

    for key in files_keys:
        uploaded_file = request.files[key]
        if uploaded_file and uploaded_file.filename != "":
            from services.file_validation import check_dangerous_extension

            if check_dangerous_extension(uploaded_file.filename):
                db.session.delete(task)
                db.session.commit()
                import shutil

                shutil.rmtree(task_upload_dir, ignore_errors=True)
                return (
                    jsonify({"error": f"File type '{uploaded_file.filename}' is not allowed."}),
                    400,
                )

            uploaded_file.seek(0, os.SEEK_END)
            size = uploaded_file.tell()
            uploaded_file.seek(0)

            if size > MAX_FILE_SIZE_BYTES:
                db.session.delete(task)
                db.session.commit()
                import shutil

                shutil.rmtree(task_upload_dir, ignore_errors=True)
                return (
                    jsonify(
                        {
                            "error": f"File '{uploaded_file.filename}' exceeds the maximum allowed size of 25MB."
                        }
                    ),
                    400,
                )

            safe_name = secure_filename(uploaded_file.filename)
            save_path = os.path.join(task_upload_dir, safe_name)
            uploaded_file.save(save_path)

            if uploaded_file.filename == "labels.parquet":

                try:
                    import pandas as pd
                    from evaluation_engine import validate_parquet_schema_columns
                    import pyarrow.parquet as pq

                    schema = pq.read_schema(save_path)
                    columns = [col.name for col in schema]
                    is_valid, err = validate_parquet_schema_columns(columns, is_submission=False)
                    if not is_valid:
                        db.session.delete(task)
                        db.session.commit()
                        import shutil

                        shutil.rmtree(task_upload_dir, ignore_errors=True)
                        return jsonify({"error": f"Invalid labels.parquet schema: {err}"}), 400
                except Exception as e:
                    db.session.delete(task)
                    db.session.commit()
                    import shutil

                    shutil.rmtree(task_upload_dir, ignore_errors=True)
                    return jsonify({"error": f"Failed to parse labels.parquet: {str(e)}"}), 400

            uploaded_files_meta.append(
                {"filename": uploaded_file.filename, "saved_name": safe_name, "size_bytes": size}
            )

    task.files = json.dumps(uploaded_files_meta)
    db.session.commit()

    # Parse code cells from notebooks and queue baseline submission
    admin_id = request.user["user_id"]
    _maybe_queue_baseline(task, challenge, admin_id)

    from services.audit_service import log_action

    log_action(
        request.user["user_id"],
        "create",
        "task",
        target_id=task.id,
        details={"title": task.title, "challenge_id": challenge_id},
    )

    from cache_utils import invalidate_challenge_cache

    invalidate_challenge_cache(challenge_id)

    return jsonify(task.to_dict()), 201


@tasks_bp.route("/tasks/<int:task_id>", methods=["PUT"])
@role_required(["admin", "jury"])
def update_task(task_id):
    """
    Update an existing task configuration including files and evaluator scripts.
    ---
    tags:
      - Tasks
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: task_id
        required: true
        type: string
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    task = db.get_or_404(Task, task_id)

    title = request.form.get("title")
    description = request.form.get("description")

    if request.user.get("role") != "admin":
        for field in ["base_docker_image", "apt_packages", "pip_requirements"]:
            if field in request.form:
                val = request.form.get(field)
                current_val = getattr(task, field)
                if (val or "").strip() != (current_val or "").strip():
                    return (
                        jsonify(
                            {
                                "error": "Only administrators are allowed to configure custom environments.",
                                "code": "ERR_FORBIDDEN",
                            }
                        ),
                        403,
                    )

    if title:
        task.title = title
    if description is not None:
        task.description = description

    # Task parameter validation on update
    import re

    if "ram_limit_mb" in request.form:
        ram_val = to_int(request.form.get("ram_limit_mb"))
        if ram_val is not None and (ram_val <= 0 or ram_val > 16384):
            return (
                jsonify(
                    {
                        "error": "RAM limit must be a positive integer and cannot exceed 16384 MB (16 GB)."
                    }
                ),
                400,
            )

    if "base_docker_image" in request.form:
        base_img = request.form.get("base_docker_image")
        if base_img:
            DOCKER_IMAGE_REGEX = (
                r"^[a-z0-9]+(?:[._-][a-z0-9]+)*/?[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[a-zA-Z0-9_.-]+)?$"
            )
            if not re.match(DOCKER_IMAGE_REGEX, base_img):
                return jsonify({"error": "Invalid base Docker image name format."}), 400

    if "apt_packages" in request.form:
        apt_pkgs = request.form.get("apt_packages")
        if apt_pkgs:
            packages = [p.strip() for p in apt_pkgs.replace(",", " ").split() if p.strip()]
            for pkg in packages:
                if not re.match(r"^[a-zA-Z0-9.+-]+$", pkg):
                    return jsonify({"error": f"Invalid APT package name: '{pkg}'."}), 400

    if "pip_requirements" in request.form:
        pip_reqs = request.form.get("pip_requirements")
        if pip_reqs:
            for line in pip_reqs.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if not re.match(
                    r"^[a-zA-Z0-9_.-]+(?:\s*(?:>=|<=|==|!=|~=|>|<)\s*[a-zA-Z0-9_.-]+(?:\s*,\s*(?:>=|<=|==|!=|~=|>|<)\s*[a-zA-Z0-9_.-]+)*)?$",
                    line,
                ):
                    return (
                        jsonify({"error": f"Invalid pip requirement line format: '{line}'."}),
                        400,
                    )

    if "ram_limit_mb" in request.form:
        task.ram_limit_mb = to_int(request.form.get("ram_limit_mb"))
    if "time_limit_sec" in request.form:
        task.time_limit_sec = to_int(request.form.get("time_limit_sec"))
    if "gpu_required" in request.form:
        gpu_required_raw = request.form.get("gpu_required")
        task.gpu_required = to_bool(gpu_required_raw) if gpu_required_raw is not None else None

    if "base_docker_image" in request.form:
        task.base_docker_image = request.form.get("base_docker_image")
    if "apt_packages" in request.form:
        task.apt_packages = request.form.get("apt_packages")
    if "pip_requirements" in request.form:
        task.pip_requirements = request.form.get("pip_requirements")

    if "ban_magic_commands" in request.form:
        task.ban_magic_commands = to_bool(request.form.get("ban_magic_commands"))
    if "banned_imports" in request.form:
        task.banned_imports = request.form.get("banned_imports")

    if "metrics_config" in request.form:
        metrics_config_raw = request.form.get("metrics_config")
        if metrics_config_raw:
            try:
                metrics_config = json.loads(metrics_config_raw)
            except:
                return jsonify({"error": "metrics_config must be valid JSON."}), 400

            if metrics_config:
                for metric_name in metrics_config.keys():
                    if metric_name == "_columns":
                        continue
                    cfg = metrics_config[metric_name]
                    if not isinstance(cfg, dict) or "weight" not in cfg:
                        return (
                            jsonify(
                                {
                                    "error": f"Metric '{metric_name}' configuration must be a dictionary and include a 'weight'."
                                }
                            ),
                            400,
                        )
                    try:
                        float(cfg["weight"])
                    except (ValueError, TypeError):
                        return (
                            jsonify(
                                {
                                    "error": f"Weight for metric '{metric_name}' must be a numeric value."
                                }
                            ),
                            400,
                        )
                    if "options" in cfg and not isinstance(cfg["options"], dict):
                        return (
                            jsonify(
                                {
                                    "error": f"Options for metric '{metric_name}' must be a dictionary/JSON object."
                                }
                            ),
                            400,
                        )
            task.metrics_config = metrics_config
        else:
            task.metrics_config = None

    if "whitelisted_imports" in request.form:
        task.whitelisted_imports = request.form.get("whitelisted_imports")

    if "hf_datasets" in request.form:
        hf_datasets_raw = request.form.get("hf_datasets")
        if hf_datasets_raw:
            try:
                hf_datasets = json.loads(hf_datasets_raw)
            except:
                return jsonify({"error": "hf_datasets must be valid JSON array."}), 400
            if not isinstance(hf_datasets, list):
                return jsonify({"error": "hf_datasets must be a list."}), 400
            if len(hf_datasets) > 5:
                return jsonify({"error": "You can configure up to 5 Hugging Face datasets."}), 400
            for item in hf_datasets:
                if not isinstance(item, str):
                    return jsonify({"error": "Dataset names must be strings."}), 400
            task.hf_datasets = hf_datasets
        else:
            task.hf_datasets = None

    if "hf_models" in request.form:
        hf_models_raw = request.form.get("hf_models")
        if hf_models_raw:
            try:
                hf_models = json.loads(hf_models_raw)
            except:
                return jsonify({"error": "hf_models must be valid JSON array."}), 400
            if not isinstance(hf_models, list):
                return jsonify({"error": "hf_models must be a list."}), 400
            if len(hf_models) > 5:
                return jsonify({"error": "You can configure up to 5 Hugging Face models."}), 400
            for item in hf_models:
                if not isinstance(item, str):
                    return jsonify({"error": "Model names must be strings."}), 400
            task.hf_models = hf_models
        else:
            task.hf_models = None

    if "hf_api_key" in request.form:
        hf_api_key = request.form.get("hf_api_key")
        if hf_api_key:
            task.set_hf_api_key(hf_api_key)
    if "public_eval_percentage" in request.form:
        task.public_eval_percentage = to_int(request.form.get("public_eval_percentage")) or 30
    if "max_submissions_per_period" in request.form:
        task.max_submissions_per_period = to_int(request.form.get("max_submissions_per_period"))
    if "submission_period_hours" in request.form:
        task.submission_period_hours = to_int(request.form.get("submission_period_hours"))
    if "stage_id" in request.form:
        stage_id_val = to_int(request.form.get("stage_id"))
        if stage_id_val:
            from models import Stage

            st = Stage.query.filter_by(id=stage_id_val, challenge_id=task.challenge_id).first()
            if not st:
                return jsonify({"error": "Invalid stage_id for this challenge."}), 400
            task.stage_id = stage_id_val
        else:
            task.stage_id = None

    task_upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], f"task_{task.id}")
    os.makedirs(task_upload_dir, exist_ok=True)

    if "evaluator_script" in request.files:
        f = request.files["evaluator_script"]
        if f and f.filename != "":
            safe_name = "evaluator.py"
            save_path = os.path.join(task_upload_dir, safe_name)
            f.save(save_path)
            task.evaluator_script_path = save_path

    if "baseline_notebook" in request.files:
        f = request.files["baseline_notebook"]
        if f and f.filename != "":
            from services.file_validation import validate_extension

            valid_ext, ext_err = validate_extension(f.filename, {".ipynb"})
            if not valid_ext:
                return jsonify({"error": ext_err}), 400
            safe_name = "baseline_" + secure_filename(f.filename)
            save_path = os.path.join(task_upload_dir, safe_name)
            f.save(save_path)
            task.baseline_notebook_path = save_path

    try:
        current_files = json.loads(task.files)
    except:
        current_files = []

    deleted_files_raw = request.form.get("deleted_files")
    if deleted_files_raw:
        try:
            deleted_filenames = json.loads(deleted_files_raw)
            updated_files = []
            for f in current_files:
                if f["filename"] in deleted_filenames:
                    file_path = os.path.join(task_upload_dir, f["saved_name"])
                    if os.path.exists(file_path):
                        os.remove(file_path)
                else:
                    updated_files.append(f)
            current_files = updated_files
        except:
            pass

    # Handle evaluator script and baseline notebook deletion
    if request.form.get("delete_evaluator") == "true" and task.evaluator_script_path:
        if os.path.exists(task.evaluator_script_path):
            os.remove(task.evaluator_script_path)
        task.evaluator_script_path = None
    if request.form.get("delete_baseline") == "true" and task.baseline_notebook_path:
        if os.path.exists(task.baseline_notebook_path):
            os.remove(task.baseline_notebook_path)
        task.baseline_notebook_path = None

    new_files_keys = [k for k in request.files.keys() if k.startswith("file")]
    if len(current_files) + len(new_files_keys) > 5:
        return jsonify({"error": "A task can contain a maximum of 5 files."}), 400

    newly_saved_paths = []

    for key in new_files_keys:
        uploaded_file = request.files[key]
        if uploaded_file and uploaded_file.filename != "":
            from services.file_validation import check_dangerous_extension

            if check_dangerous_extension(uploaded_file.filename):
                for p in newly_saved_paths:
                    if os.path.exists(p):
                        os.remove(p)
                return (
                    jsonify({"error": f"File type '{uploaded_file.filename}' is not allowed."}),
                    400,
                )

            uploaded_file.seek(0, os.SEEK_END)
            size = uploaded_file.tell()
            uploaded_file.seek(0)

            if size > MAX_FILE_SIZE_BYTES:
                for p in newly_saved_paths:
                    if os.path.exists(p):
                        os.remove(p)
                return (
                    jsonify(
                        {
                            "error": f"File '{uploaded_file.filename}' exceeds the maximum allowed size of 25MB."
                        }
                    ),
                    400,
                )

            safe_name = secure_filename(uploaded_file.filename)
            save_path = os.path.join(task_upload_dir, safe_name)
            uploaded_file.save(save_path)
            newly_saved_paths.append(save_path)

            if uploaded_file.filename == "labels.parquet":
                try:
                    import pandas as pd
                    from evaluation_engine import validate_parquet_schema_columns
                    import pyarrow.parquet as pq

                    schema = pq.read_schema(save_path)
                    columns = [col.name for col in schema]
                    is_valid, err = validate_parquet_schema_columns(columns, is_submission=False)
                    if not is_valid:
                        for p in newly_saved_paths:
                            if os.path.exists(p):
                                os.remove(p)
                        return jsonify({"error": f"Invalid labels.parquet schema: {err}"}), 400
                except Exception as e:
                    for p in newly_saved_paths:
                        if os.path.exists(p):
                            os.remove(p)
                    return jsonify({"error": f"Failed to parse labels.parquet: {str(e)}"}), 400

            current_files.append(
                {"filename": uploaded_file.filename, "saved_name": safe_name, "size_bytes": size}
            )
    task.files = json.dumps(current_files)
    db.session.commit()

    from services.audit_service import log_action

    log_action(
        request.user["user_id"],
        "update",
        "task",
        target_id=task.id,
        details={"title": task.title, "challenge_id": task.challenge_id},
    )

    from cache_utils import invalidate_challenge_cache

    invalidate_challenge_cache(task.challenge_id)
    _maybe_queue_baseline(task, task.challenge, request.user["user_id"])

    return jsonify(task.to_dict())


@tasks_bp.route("/tasks/<int:task_id>", methods=["DELETE"])
@role_required(["admin", "jury"])
def delete_task(task_id):
    """
    Remove a task and all its submissions from a challenge.
    ---
    tags:
      - Tasks
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: task_id
        required: true
        type: string
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    task = db.get_or_404(Task, task_id)
    challenge_id = task.challenge_id
    task_upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], f"task_{task.id}")
    import shutil

    shutil.rmtree(task_upload_dir, ignore_errors=True)
    # Collect file paths before bulk delete for cleanup
    subs = Submission.query.filter_by(task_id=task_id).all()
    paths = [(s.code_storage_path, s.log_storage_path) for s in subs]
    Submission.query.filter_by(task_id=task_id).delete(synchronize_session=False)
    for code_path, log_path in paths:
        if code_path and os.path.exists(code_path):
            try:
                os.remove(code_path)
            except OSError:
                pass
        if log_path and os.path.exists(log_path):
            try:
                os.remove(log_path)
            except OSError:
                pass
    db.session.delete(task)
    db.session.commit()

    from services.audit_service import log_action

    log_action(
        request.user["user_id"],
        "delete",
        "task",
        target_id=task.id,
        details={"title": task.title, "challenge_id": challenge_id},
    )

    from cache_utils import invalidate_challenge_cache

    invalidate_challenge_cache(challenge_id)

    return jsonify({"message": f"Task '{task.title}' has been deleted successfully."})


# --- DOWNLOAD FILE ---


@tasks_bp.route("/tasks/<int:task_id>/download/<string:filename>", methods=["GET"])
@login_required
def download_task_file(task_id, filename):
    """
    Download a resource file attached to a task.
    ---
    tags:
      - Tasks
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: task_id
        required: true
        type: string
      - in: path
        name: filename
        required: true
        type: string
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    task = db.get_or_404(Task, task_id)
    user_role = request.user["role"]
    user_id = request.user["user_id"]

    if user_role == "competitor":
        if filename == "labels.parquet":
            return jsonify({"error": "Access denied.", "code": "ERR_ACCESS_DENIED"}), 403
        if not check_task_started(task, user_role, user_id):
            return (
                jsonify(
                    {
                        "error": "Access denied or task not available yet.",
                        "code": "ERR_NOT_AVAILABLE",
                    }
                ),
                403,
            )

    try:
        files_meta = json.loads(task.files)
    except:
        files_meta = []

    saved_name = None
    for f in files_meta:
        if f["filename"] == filename:
            saved_name = f["saved_name"]
            break

    if saved_name:
        task_upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], f"task_{task.id}")
        return send_from_directory(
            task_upload_dir, saved_name, as_attachment=True, download_name=filename
        )

    if task.baseline_notebook_path:
        baseline_basename = os.path.basename(task.baseline_notebook_path)
        if filename == baseline_basename:
            return send_file(
                task.baseline_notebook_path, as_attachment=True, download_name=filename
            )

    return jsonify({"error": "File not found in task metadata.", "code": "ERR_FILE_NOT_FOUND"}), 404


# --- TASK SUBMISSIONS & EVALUATIONS ---


@tasks_bp.route("/tasks/<int:task_id>/submit", methods=["POST"])
@login_required
@rate_limit(max_requests=30, window_seconds=60)
def submit_task_code(task_id):
    """
    Submit code cells for execution under a specific task.
    ---
    tags:
      - Tasks
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: task_id
        required: true
        type: string
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    task = db.get_or_404(Task, task_id)
    challenge = task.challenge

    if not challenge.is_active:
        return jsonify({"error": "This competition is currently inactive."}), 400
    if challenge.is_archived:
        return (
            jsonify(
                {"error": "This competition has been archived and no longer accepts submissions."}
            ),
            400,
        )

    user_id = request.user["user_id"]
    user_role = request.user["role"]

    if user_role == "competitor":
        if not check_competitor_access(user_id, task.challenge_id):
            return (
                jsonify({"error": "Access denied. You are not registered for this competition."}),
                403,
            )

        if challenge.scores_finalized:
            return jsonify({"error": "Submissions are disabled for finalized competitions."}), 403

        if task.stage_id:
            from models import Stage

            stage = db.session.get(Stage, task.stage_id)
            if stage:
                try:
                    import zoneinfo

                    tz = zoneinfo.ZoneInfo(challenge.timezone or "UTC")
                    now_local = datetime.now(tz).replace(tzinfo=None)
                except Exception:
                    now_local = datetime.utcnow()
                if now_local < stage.start_time:
                    return (
                        jsonify({"error": f"The stage '{stage.title}' has not started yet."}),
                        400,
                    )
                if now_local > stage.end_time:
                    return (
                        jsonify(
                            {"error": f"The deadline for the stage '{stage.title}' has passed."}
                        ),
                        400,
                    )
        else:
            if not challenge.is_started:
                return jsonify({"error": "This competition has not started yet."}), 400
            if challenge.is_ended:
                return (
                    jsonify(
                        {"error": "This competition has ended and no longer accepts submissions."}
                    ),
                    400,
                )

    data = request.json or {}
    selected_cells = data.get("selected_cells")

    if not selected_cells or not isinstance(selected_cells, list):
        return jsonify({"error": "selected_cells list is required."}), 400

    from cache_utils import cache_lock

    lock_key = f"submit_lock:user_{user_id}:task_{task_id}"

    with cache_lock(lock_key, ttl=10):
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        submission_count = Submission.query.filter(
            Submission.user_id == user_id,
            Submission.challenge_id == challenge.id,
            Submission.created_at >= today_start,
        ).count()

        if submission_count >= challenge.max_eval_requests:
            return (
                jsonify(
                    {
                        "error": f"Daily limit reached. You can only make {challenge.max_eval_requests} submissions per day."
                    }
                ),
                429,
            )

        if task.max_submissions_per_period and task.submission_period_hours:
            period_start = datetime.utcnow() - timedelta(hours=task.submission_period_hours)
            sub_count = Submission.query.filter(
                Submission.user_id == user_id,
                Submission.task_id == task.id,
                Submission.created_at >= period_start,
            ).count()
            if sub_count >= task.max_submissions_per_period:
                return (
                    jsonify(
                        {
                            "error": f"Task limit reached. You can only make {task.max_submissions_per_period} submissions per {task.submission_period_hours} hours."
                        }
                    ),
                    429,
                )

        passed, err_msg = check_execution_rules(task, selected_cells)
        if not passed:
            submission = Submission(
                user_id=user_id,
                challenge_id=challenge.id,
                task_id=task.id,
                status="failed",
                detailed_status="failed",
                code_cells=json.dumps(selected_cells),
                public_score=0.0,
                private_score=0.0,
                logs=f"--- Rule Check Failed ---\n{err_msg}",
                execution_time_ms=0,
            )
            db.session.add(submission)
            db.session.commit()
            publish_submissions_update(submission.task_id, submission.user_id)
            publish_leaderboard_update(submission.task_id)
            return (
                jsonify(
                    {
                        "message": "Submission received but failed rule check.",
                        "submission_id": submission.id,
                        "status": submission.status,
                        "error": err_msg,
                    }
                ),
                200,
            )

        priority = calculate_submission_priority(user_id, user_role)

        submission = Submission(
            user_id=user_id,
            challenge_id=challenge.id,
            task_id=task.id,
            status="queued",
            detailed_status="queued",
            code_cells=json.dumps(selected_cells),
        )
        db.session.add(submission)
        db.session.commit()

    from cache_utils import invalidate_leaderboard_cache

    invalidate_leaderboard_cache(submission.challenge_id)

    publish_submissions_update(submission.task_id, submission.user_id)
    publish_leaderboard_update(submission.task_id)
    from tasks import evaluate_submission

    gpu_required = False
    if task.gpu_required is not None:
        gpu_required = task.gpu_required
    elif challenge.gpu_required is not None:
        gpu_required = challenge.gpu_required

    queue_name = "gpu_queue" if gpu_required else "celery"

    # Compile complete metadata dictionary for remote workers (avoids DB exposure on remote nodes)
    task_files_list = []
    if task.files:
        try:
            task_files_list = json.loads(task.files)
        except:
            pass

    main_server_url = os.environ.get("MAIN_SERVER_URL", "http://localhost:5001")

    from auth_utils import generate_worker_token

    time_limit = task.time_limit_sec or challenge.time_limit_sec or 300
    worker_secret_key = generate_worker_token(submission.id, task.id, time_limit + 600)

    metadata = {
        "submission_id": submission.id,
        "task_id": task.id,
        "challenge_id": challenge.id,
        "user_code": "\n\n".join(extract_code_from_cells(selected_cells)),
        "time_limit": task.time_limit_sec or challenge.time_limit_sec or 300,
        "ram_limit": task.ram_limit_mb or challenge.ram_limit_mb or 8192,
        "gpu_required": gpu_required,
        "base_docker_image": task.base_docker_image,
        "apt_packages": task.apt_packages,
        "pip_requirements": task.pip_requirements,
        "is_custom_eval": (
            True
            if (
                task.custom_eval_code
                or (task.evaluator_script_path and os.path.exists(task.evaluator_script_path))
            )
            else False
        ),
        "metrics_config": task.metrics_config,
        "hf_datasets": (
            task.hf_datasets
            if isinstance(task.hf_datasets, str)
            else (json.dumps(task.hf_datasets) if task.hf_datasets else None)
        ),
        "hf_models": (
            task.hf_models
            if isinstance(task.hf_models, str)
            else (json.dumps(task.hf_models) if task.hf_models else None)
        ),
        "public_eval_percentage": task.public_eval_percentage or 30,
        "task_files": task_files_list,
        "main_server_url": main_server_url,
        "celery_broker_url": os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"),
        "worker_secret_key": worker_secret_key,
    }

    if task.custom_eval_code:
        metadata["custom_eval_code"] = task.custom_eval_code
    elif task.evaluator_script_path and os.path.exists(task.evaluator_script_path):
        try:
            with open(task.evaluator_script_path, "r") as ef:
                metadata["custom_eval_code"] = ef.read()
        except Exception as ef_err:
            logger.error("Failed to read evaluator script for task %s: %s", task.id, ef_err)
            submission.status = "failed"
            submission.detailed_status = "failed"
            submission.logs = f"Evaluator script read error: {ef_err}"
            db.session.commit()
            return (
                jsonify(
                    {"error": "Failed to load evaluator script.", "submission_id": submission.id}
                ),
                500,
            )

    try:
        evaluate_submission.apply_async(
            args=[submission.id, metadata], priority=priority, queue=queue_name, countdown=1
        )
    except Exception as e:
        submission.status = "failed"
        submission.detailed_status = "failed"
        submission.logs = f"Submission queue unavailable: {e}"
        db.session.commit()
        return (
            jsonify(
                {
                    "error": "Submission queue is temporarily unavailable. Please try again.",
                    "submission_id": submission.id,
                }
            ),
            503,
        )

    return (
        jsonify(
            {
                "message": "Submission received and queued for execution.",
                "submission_id": submission.id,
                "status": submission.status,
            }
        ),
        202,
    )


def _get_task_submissions_data(task_id, user_role, user_id, page=None, per_page=10):
    task = db.session.get(Task, task_id)
    if not task:
        return {"error": "Task not found."}

    if user_role == "competitor":
        if not check_task_started(task, user_role, user_id):
            return {"error": "Access denied or task not available yet."}
        challenge = task.challenge
        if challenge and challenge.scores_finalized:
            return {"error": "Access denied. Submissions are hidden for finalized competitions."}
        query = Submission.query.filter_by(task_id=task_id, user_id=user_id)
    else:
        query = Submission.query.filter_by(task_id=task_id)

    from sqlalchemy.orm import joinedload

    query = query.options(
        joinedload(Submission.challenge), joinedload(Submission.user), joinedload(Submission.task)
    )

    if page is not None:
        pagination = query.order_by(Submission.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        return {
            "items": [
                s.to_dict_light(view_role=user_role, current_user_id=user_id)
                for s in pagination.items
            ],
            "total": pagination.total,
            "page": pagination.page,
            "pages": pagination.pages,
        }

    submissions = query.order_by(Submission.created_at.desc()).all()
    return [s.to_dict_light(view_role=user_role, current_user_id=user_id) for s in submissions]


@tasks_bp.route("/tasks/<int:task_id>/submissions", methods=["GET"])
@login_required
def get_task_submissions(task_id):
    """
    List submissions for a specific task with pagination.
    ---
    tags:
      - Tasks
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: task_id
        required: true
        type: string
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    user_role = request.user["role"]
    user_id = request.user["user_id"]
    page = request.args.get("page", type=int)
    per_page = min(request.args.get("per_page", 10, type=int), 100)

    data = _get_task_submissions_data(task_id, user_role, user_id, page, per_page)
    if isinstance(data, dict) and "error" in data:
        return jsonify(data), 403
    return jsonify(data)


def _get_task_leaderboard_data(task_id, user_role, current_user_id):
    from services.leaderboard_service import get_task_leaderboard_data

    return get_task_leaderboard_data(task_id, user_role, current_user_id)


@tasks_bp.route("/tasks/<int:task_id>/leaderboard", methods=["GET"])
@login_required
def get_task_leaderboard(task_id):
    """
    Get cached leaderboard data for a specific task.
    ---
    tags:
      - Tasks
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: task_id
        required: true
        type: string
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    user_role = request.user["role"]
    current_user_id = request.user["user_id"]
    data = _get_task_leaderboard_data(task_id, user_role, current_user_id)
    if "error" in data:
        return jsonify(data), 403
    return jsonify(data)


@tasks_bp.route("/tasks/<int:task_id>/leaderboard/live", methods=["GET"])
@login_required
def get_task_leaderboard_live(task_id):
    """
    Stream live task leaderboard updates via SSE.
    ---
    tags:
      - SSE Streaming
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: task_id
        required: true
        type: string
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    user_role = request.user["role"]
    current_user_id = request.user["user_id"]
    if user_role == "competitor":
        task = db.session.get(Task, task_id)
        if not task or not check_task_started(task, user_role, current_user_id):
            return (
                jsonify(
                    {
                        "error": "Access denied or task not available yet.",
                        "code": "ERR_NOT_AVAILABLE",
                    }
                ),
                403,
            )

    def event_generator():
        with current_app.app_context():
            data = _get_task_leaderboard_data(task_id, user_role, current_user_id)
            yield f"data: {json.dumps(data)}\n\n"

        from cache_utils import get_redis_client

        r = get_redis_client()
        pubsub = r.pubsub()
        pubsub.subscribe(f"task_{task_id}_leaderboard")

        try:
            while True:
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=2.0)
                if message:
                    with current_app.app_context():
                        data = _get_task_leaderboard_data(task_id, user_role, current_user_id)
                        yield f"data: {json.dumps(data)}\n\n"
                else:
                    yield ": keep-alive\n\n"
        except GeneratorExit:
            try:
                pubsub.unsubscribe()
                pubsub.close()
            except:
                pass
        except Exception as e:
            logger.error("Leaderboard SSE error: %s", e)
            try:
                pubsub.unsubscribe()
                pubsub.close()
            except:
                pass

    return Response(stream_with_context(event_generator()), mimetype="text/event-stream")


@tasks_bp.route("/tasks/<int:task_id>/submissions/live", methods=["GET"])
@login_required
def get_task_submissions_live(task_id):
    """
    Stream live task submission updates via SSE.
    ---
    tags:
      - SSE Streaming
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: task_id
        required: true
        type: string
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    user_role = request.user["role"]
    current_user_id = request.user["user_id"]
    page = request.args.get("page", type=int)
    per_page = min(request.args.get("per_page", 10, type=int), 100)

    if user_role == "competitor":
        task = db.session.get(Task, task_id)
        if not task or not check_task_started(task, user_role, current_user_id):
            return (
                jsonify(
                    {
                        "error": "Access denied or task not available yet.",
                        "code": "ERR_NOT_AVAILABLE",
                    }
                ),
                403,
            )
        if task.challenge and task.challenge.scores_finalized:
            return (
                jsonify(
                    {
                        "error": "Access denied. Submissions are hidden for finalized competitions.",
                        "code": "ERR_COMPETITION_FINALIZED",
                    }
                ),
                403,
            )

    def event_generator():
        with current_app.app_context():
            data = _get_task_submissions_data(task_id, user_role, current_user_id, page, per_page)
            yield f"data: {json.dumps(data)}\n\n"

        from cache_utils import get_redis_client

        r = get_redis_client()
        pubsub = r.pubsub()

        if user_role in ["admin", "jury"]:
            pubsub.psubscribe(f"task_{task_id}_user_*_submissions")
        else:
            pubsub.subscribe(f"task_{task_id}_user_{current_user_id}_submissions")

        try:
            while True:
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=2.0)
                if message:
                    with current_app.app_context():
                        data = _get_task_submissions_data(
                            task_id, user_role, current_user_id, page, per_page
                        )
                        yield f"data: {json.dumps(data)}\n\n"
                else:
                    yield ": keep-alive\n\n"
        except GeneratorExit:
            try:
                if user_role in ["admin", "jury"]:
                    pubsub.punsubscribe()
                else:
                    pubsub.unsubscribe()
                pubsub.close()
            except:
                pass
        except Exception as e:
            logger.error("Submissions SSE error: %s", e)
            try:
                if user_role in ["admin", "jury"]:
                    pubsub.punsubscribe()
                else:
                    pubsub.unsubscribe()
                pubsub.close()
            except:
                pass

    return Response(stream_with_context(event_generator()), mimetype="text/event-stream")


@tasks_bp.route("/worker-status", methods=["GET"])
@login_required
def get_worker_status():
    """
    Get current worker cluster health status with specs.
    ---
    tags:
      - Tasks
    security:
      - cookieAuth: []
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    return jsonify(_get_worker_status_data())


@tasks_bp.route("/worker-status/live", methods=["GET"])
@login_required
def stream_worker_status():
    """
    Stream worker cluster health status via SSE.
    ---
    tags:
      - SSE Streaming
    security:
      - cookieAuth: []
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    from flask import current_app, Response, stream_with_context

    def event_generator():
        with current_app.app_context():
            res_data = _get_worker_status_data()
            yield f"data: {json.dumps(res_data)}\n\n"

        from cache_utils import get_redis_client

        r = get_redis_client()
        pubsub = r.pubsub()
        pubsub.subscribe("worker_status_live")

        last_sent = datetime.utcnow()
        try:
            while True:
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=5.0)
                now = datetime.utcnow()
                if message:
                    with current_app.app_context():
                        res_data = _get_worker_status_data()
                        yield f"data: {json.dumps(res_data)}\n\n"
                        last_sent = now
                elif (now - last_sent).total_seconds() >= 10:
                    with current_app.app_context():
                        res_data = _get_worker_status_data()
                        yield f"data: {json.dumps(res_data)}\n\n"
                        last_sent = now
                else:
                    yield ": keep-alive\n\n"
        except GeneratorExit:
            pass
        finally:
            try:
                pubsub.unsubscribe()
                pubsub.close()
            except Exception:
                pass

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return Response(
        stream_with_context(event_generator()), mimetype="text/event-stream", headers=headers
    )


def _get_worker_status_data():
    from flask import current_app
    from cache_utils import get_cached, set_cached

    is_testing = current_app.config.get("TESTING", False)
    cache_key = "worker:status:summary"
    if not is_testing:
        cached_val = get_cached(cache_key)
        if cached_val is not None:
            return cached_val

    from tasks import celery
    import json as json_lib

    inspect = celery.control.inspect(timeout=1.0)
    pings = inspect.ping() or {}
    stats = inspect.stats() or {}

    is_online = pings is not None and len(pings) > 0

    r = None
    try:
        from cache_utils import get_redis_client

        r = get_redis_client()
    except Exception:
        pass

    clusters = []
    for worker_name in pings.keys():
        spec = None
        if r:
            try:
                spec_data = r.get(f"worker_spec:{worker_name}")
                if spec_data:
                    spec = json_lib.loads(spec_data)
            except Exception:
                pass

        if not spec:
            w_stats = stats.get(worker_name, {}) if stats else {}
            pool = w_stats.get("pool", {}) if w_stats else {}
            concurrency = pool.get("max-concurrency", 1) if pool else 1
            try:
                concurrency = int(concurrency)
            except Exception:
                concurrency = 1
            has_gpu = "gpu" in worker_name.lower()
            spec = {
                "name": worker_name,
                "type": "GPU" if has_gpu else "CPU",
                "concurrency": concurrency,
                "gpu_type": "NVIDIA GPU" if has_gpu else "N/A",
                "ram_gb": 16.0 if has_gpu else 8.0,
                "vram_gb": 8.0 if has_gpu else "N/A",
            }
        clusters.append(spec)

    res_data = {"status": "online" if is_online else "offline", "clusters": clusters}
    if not is_testing:
        set_cached(cache_key, res_data, timeout=10)
    return res_data


@tasks_bp.route("/worker/report/<int:submission_id>", methods=["POST"])
def report_worker_progress(submission_id):
    """
    Worker callback to report submission status and scores.
    ---
    tags:
      - Tasks
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: submission_id
        required: true
        type: string
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    token = request.headers.get("X-Worker-Token") or os.environ.get("WORKER_BOOTSTRAP_TOKEN")
    from auth_utils import verify_worker_token

    if not verify_worker_token(token):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json or {}
    submission = db.get_or_404(Submission, submission_id)

    VALID_STATUSES = {"queued", "running", "completed", "failed"}
    MAX_LOG_SIZE = 100 * 1024

    if "status" in data:
        status_val = data["status"]
        if not isinstance(status_val, str) or status_val not in VALID_STATUSES:
            return jsonify({"error": f"Invalid status value: {status_val}"}), 400
        submission.status = status_val
    if submission.executed_at is None:
        submission.executed_at = datetime.utcnow()
    if "detailed_status" in data:
        submission.detailed_status = data["detailed_status"]
    if "logs" in data:
        logs_val = data["logs"]
        if isinstance(logs_val, list):
            logs_val = "\n".join(str(line) for line in logs_val)
        if isinstance(logs_val, str) and len(logs_val.encode("utf-8")) > MAX_LOG_SIZE:
            logs_val = logs_val[: MAX_LOG_SIZE // 2]
        submission.logs = logs_val
    if "public_score" in data:
        val = data["public_score"]
        if val is not None and not isinstance(val, (int, float)):
            return jsonify({"error": "public_score must be numeric or null"}), 400
        submission.public_score = val
        submission.final_weighted_score_public = val
    if "private_score" in data:
        val = data["private_score"]
        if val is not None and not isinstance(val, (int, float)):
            return jsonify({"error": "private_score must be numeric or null"}), 400
        submission.private_score = val
        submission.final_weighted_score_private = val
    if "execution_time_ms" in data:
        submission.execution_time_ms = data["execution_time_ms"]
    if "metrics_payload_public" in data:
        submission.metrics_payload_public = data["metrics_payload_public"]
    if "metrics_payload_private" in data:
        submission.metrics_payload_private = data["metrics_payload_private"]
    if "final_weighted_score_public" in data:
        submission.final_weighted_score_public = data["final_weighted_score_public"]
    if "final_weighted_score_private" in data:
        submission.final_weighted_score_private = data["final_weighted_score_private"]
    db.session.commit()

    publish_submissions_update(submission.task_id, submission.user_id)
    publish_leaderboard_update(submission.task_id)

    return jsonify({"message": "Status updated successfully"}), 200


@tasks_bp.route("/worker/tasks/<int:task_id>/files/<string:filename>", methods=["GET"])
def worker_download_task_file(task_id, filename):
    """
    Worker endpoint to securely download task resource files.
    ---
    tags:
      - Tasks
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: task_id
        required: true
        type: string
      - in: path
        name: filename
        required: true
        type: string
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    token = request.headers.get("X-Worker-Token")
    from auth_utils import verify_worker_token

    if not verify_worker_token(token, task_id=task_id):
        return jsonify({"error": "Unauthorized"}), 401

    task = db.get_or_404(Task, task_id)
    try:
        files_meta = json.loads(task.files)
    except:
        files_meta = []

    saved_name = None
    for f in files_meta:
        if f["filename"] == filename:
            saved_name = f["saved_name"]
            break

    if not saved_name:
        return jsonify({"error": "File not found"}), 404

    task_upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], f"task_{task.id}")
    return send_from_directory(task_upload_dir, saved_name)


@tasks_bp.route("/worker/bootstrap-token", methods=["POST"])
def worker_bootstrap_token():
    """
    Exchange a WORKER_SECRET_KEY for a short-lived JWT for bootstrap endpoints.
    ---
    tags:
      - Tasks
    parameters:
      - in: header
        name: X-Worker-Secret
        schema:
          type: string
        required: true
        description: Worker secret key from environment
    responses:
      200:
        description: JWT token returned
      401:
        description: Invalid secret
    """
    worker_secret = request.headers.get("X-Worker-Secret") or (request.json or {}).get("secret")
    expected_secret = os.environ.get("WORKER_SECRET_KEY")
    if not expected_secret or worker_secret != expected_secret:
        return jsonify({"error": "Unauthorized"}), 401
    from auth_utils import generate_worker_bootstrap_token

    token = generate_worker_bootstrap_token()
    return jsonify({"token": token, "expires_in": 3600}), 200


@tasks_bp.route("/worker/active-datasets", methods=["GET"])
def get_active_datasets():
    """
    List all HuggingFace datasets used by active challenges for worker preloading.
    ---
    tags:
      - Tasks
    security:
      - cookieAuth: []
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    token = request.headers.get("X-Worker-Token")
    from auth_utils import verify_worker_token

    if not verify_worker_token(token):
        return jsonify({"error": "Unauthorized"}), 401

    active_challenges = Challenge.query.filter_by(is_archived=False).all()
    datasets_set = set()
    import re

    for challenge in active_challenges:
        for task in challenge.tasks:
            # Extract from custom evaluation code
            eval_code = ""
            if task.custom_eval_code:
                eval_code = task.custom_eval_code
            elif task.evaluator_script_path and os.path.exists(task.evaluator_script_path):
                try:
                    with open(task.evaluator_script_path, "r") as f:
                        eval_code = f.read()
                except:
                    pass

            if eval_code:
                matches = re.findall(
                    r'(?:datasets\.)?load_dataset\(\s*[\'"]([^\'"]+)[\'"]', eval_code
                )
                for m in matches:
                    datasets_set.add(m)

    return jsonify({"datasets": list(datasets_set)}), 200


@tasks_bp.route("/worker/tasks/<int:task_id>/hf-key", methods=["GET"])
def get_task_hf_key(task_id):
    """
    Worker endpoint to fetch the HuggingFace API key for a task.
    ---
    tags:
      - Tasks
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: task_id
        required: true
        type: string
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    token = request.headers.get("X-Worker-Token") or os.environ.get("WORKER_BOOTSTRAP_TOKEN")
    from auth_utils import verify_worker_token

    if not verify_worker_token(token):
        return jsonify({"error": "Unauthorized"}), 401
    task = db.session.get(Task, task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    return jsonify({"hf_key": task.get_hf_api_key() or ""}), 200
