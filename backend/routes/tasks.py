import os
import json
import ast
import redis
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, send_from_directory, current_app, Response, stream_with_context
from werkzeug.utils import secure_filename
from models import db, Challenge, Task, User, Submission, decrypt_field
from auth_utils import login_required, role_required
from sse_utils import publish_submissions_update, publish_leaderboard_update


tasks_bp = Blueprint('tasks', __name__)

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB limit per file

def check_competitor_access(user_id, challenge_id):
    user = db.session.get(User, user_id)
    if not user or user.challenge_id != challenge_id:
        return False
    return True

def check_task_started(task, user_role, user_id):
    if user_role == 'competitor':
        if not check_competitor_access(user_id, task.challenge_id):
            return False
        challenge = task.challenge
        if challenge and challenge.start_time:
            if datetime.utcnow() < challenge.start_time:
                return False
        if task.stage_id:
            from models import Stage
            stage = db.session.get(Stage, task.stage_id)
            if stage and datetime.utcnow() < stage.start_time:
                return False
    return True

def to_bool(val):
    if val is None:
        return None
    if isinstance(val, str):
        return val.lower() in ['true', '1', 'yes', 'on']
    return bool(val)

def to_int(val):
    if val is None or str(val).strip() == '':
        return None
    try:
        return int(val)
    except ValueError:
        return None

def extract_code_from_cells(cells_list):
    if not cells_list:
        return []
    extracted = []
    for cell in cells_list:
        if isinstance(cell, dict):
            source = cell.get("source", "")
            if isinstance(source, list):
                extracted.append("".join(source))
            else:
                extracted.append(str(source))
        elif isinstance(cell, str):
            extracted.append(cell)
        else:
            extracted.append(str(cell))
    return extracted

def check_execution_rules(task, cells_list):
    extracted_cells = extract_code_from_cells(cells_list)
    combined_code = "\n".join(extracted_cells)
    
    if task.require_submit_tag:
        if "# SUBMIT" not in combined_code:
            return False, "Rule Violation: The code is missing the required '# SUBMIT' tag."
            
    if task.ban_magic_commands:
        for line in combined_code.splitlines():
            stripped = line.strip()
            if stripped.startswith("!") or stripped.startswith("%"):
                return False, "Rule Violation: Jupyter magic commands ('!' or '%') are banned."
                
    if task.banned_imports:
        banned = [lib.strip().lower() for lib in task.banned_imports.split(",") if lib.strip()]
        if banned:
            try:
                tree = ast.parse(combined_code)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for name in node.names:
                            root_import = name.name.split(".")[0].lower()
                            if root_import in banned:
                                return False, f"Rule Violation: Import of library '{name.name}' is banned."
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            root_import = node.module.split(".")[0].lower()
                            if root_import in banned:
                                return False, f"Rule Violation: Import from library '{node.module}' is banned."
            except SyntaxError:
                pass
                
    return True, None

def calculate_submission_priority(user_id, role):
    if role in ['admin', 'jury']:
        return 9
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    submission_count = Submission.query.filter(
        Submission.user_id == user_id,
        Submission.created_at >= today_start
    ).count()
    if submission_count == 0:
        return 6
    priority = max(1, 6 - submission_count)
    return priority

def extract_code_from_notebook(filepath):
    try:
        with open(filepath, "r") as f:
            data = json.load(f)
        code_cells = []
        for cell in data.get("cells", []):
            if cell.get("cell_type") == "code":
                source = cell.get("source", [])
                if isinstance(source, list):
                    code_cells.append("".join(source))
                else:
                    code_cells.append(str(source))
        return code_cells
    except Exception as e:
        print(f"Error parsing notebook {filepath}: {e}")
        return []

def queue_system_submission(task, challenge, code_cells, admin_id, priority=8):
    submission = Submission(
        user_id=admin_id,
        challenge_id=challenge.id,
        task_id=task.id,
        status='queued',
        detailed_status='queued',
        code_cells=json.dumps(code_cells)
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
            
    hf_token = task.get_hf_api_key() or ""
    main_server_url = os.environ.get("MAIN_SERVER_URL", "http://localhost:5001")
    worker_secret_key = os.environ.get("WORKER_SECRET_KEY", "nai-worker-default-secret-token")
    
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
        
        "is_custom_eval": True if (task.custom_eval_code or (task.evaluator_script_path and os.path.exists(task.evaluator_script_path))) else False,
        "metrics_config": task.metrics_config,
        "hf_eval_repo": task.hf_eval_repo,
        "hf_token": hf_token,
        "public_eval_percentage": task.public_eval_percentage or 30,
        
        "task_files": task_files_list,
        "main_server_url": main_server_url,
        "worker_secret_key": worker_secret_key
    }
    
    if task.custom_eval_code:
        metadata["custom_eval_code"] = task.custom_eval_code
    elif task.evaluator_script_path and os.path.exists(task.evaluator_script_path):
        try:
            with open(task.evaluator_script_path, "r") as ef:
                metadata["custom_eval_code"] = ef.read()
        except:
            pass
            
    from tasks import evaluate_submission
    queue_name = 'gpu_queue' if gpu_required else 'celery'
    
    evaluate_submission.apply_async(
        args=[submission.id, metadata],
        priority=priority,
        queue=queue_name
    )

# --- TASK CRUD ---

@tasks_bp.route('/tasks/<int:task_id>', methods=['GET'])
@login_required
def get_task(task_id):
    task = db.get_or_404(Task, task_id)
    user_role = request.user["role"]
    user_id = request.user["user_id"]
    
    if not check_task_started(task, user_role, user_id):
        return jsonify({
            "error": "Access denied or task not available yet.",
            "code": "ERR_NOT_AVAILABLE"
        }), 403
        
    return jsonify(task.to_dict())

@tasks_bp.route('/challenges/<int:challenge_id>/tasks', methods=['POST'])
@role_required(['admin', 'jury'])
def create_task(challenge_id):
    challenge = db.get_or_404(Challenge, challenge_id)
    
    title = request.form.get("title")
    description = request.form.get("description")
    
    if not title:
        return jsonify({"error": "Task title is required."}), 400
        
    if 'baseline_notebook' not in request.files or request.files['baseline_notebook'].filename == '':
        return jsonify({"error": "Baseline notebook is required."}), 400
    if 'solution_notebook' not in request.files or request.files['solution_notebook'].filename == '':
        return jsonify({"error": "Solution notebook (best_sol) is required."}), 400
        
    ram_limit_mb = to_int(request.form.get("ram_limit_mb"))
    time_limit_sec = to_int(request.form.get("time_limit_sec"))
    gpu_required_raw = request.form.get("gpu_required")
    gpu_required = to_bool(gpu_required_raw) if gpu_required_raw is not None else None
    
    base_docker_image = request.form.get("base_docker_image")
    apt_packages = request.form.get("apt_packages")
    pip_requirements = request.form.get("pip_requirements")
    
    # Task parameter validations
    if ram_limit_mb is not None:
        if ram_limit_mb <= 0 or ram_limit_mb > 16384:
            return jsonify({"error": "RAM limit must be a positive integer and cannot exceed 16384 MB (16 GB)."}), 400
            
    import re
    if base_docker_image:
        DOCKER_IMAGE_REGEX = r'^[a-z0-9]+(?:[._-][a-z0-9]+)*/?[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[a-zA-Z0-9_.-]+)?$'
        if not re.match(DOCKER_IMAGE_REGEX, base_docker_image):
            return jsonify({"error": "Invalid base Docker image name format."}), 400
            
    if apt_packages:
        packages = [p.strip() for p in apt_packages.replace(",", " ").split() if p.strip()]
        for pkg in packages:
            if not re.match(r'^[a-zA-Z0-9.+-]+$', pkg):
                return jsonify({"error": f"Invalid APT package name: '{pkg}'."}), 400
                
    if pip_requirements:
        for line in pip_requirements.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if not re.match(r'^[a-zA-Z0-9_.-]+(?:\s*(?:>=|<=|==|!=|~=|>|<)\s*[a-zA-Z0-9_.-]+(?:\s*,\s*(?:>=|<=|==|!=|~=|>|<)\s*[a-zA-Z0-9_.-]+)*)?$', line):
                return jsonify({"error": f"Invalid pip requirement line format: '{line}'."}), 400
    
    require_submit_tag = to_bool(request.form.get("require_submit_tag")) or False
    ban_magic_commands = to_bool(request.form.get("ban_magic_commands")) or False
    banned_imports = request.form.get("banned_imports")
    
    metrics_config_raw = request.form.get("metrics_config")
    metrics_config = None
    if metrics_config_raw:
        try:
            metrics_config = json.loads(metrics_config_raw)
        except:
            pass
            
    hf_train_repo = request.form.get("hf_train_repo")
    hf_eval_repo = request.form.get("hf_eval_repo")
    hf_api_key = request.form.get("hf_api_key")
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
        require_submit_tag=require_submit_tag,
        ban_magic_commands=ban_magic_commands,
        banned_imports=banned_imports,
        metrics_config=metrics_config,
        hf_train_repo=hf_train_repo,
        hf_eval_repo=hf_eval_repo,
        public_eval_percentage=public_eval_percentage,
        max_submissions_per_period=max_submissions_per_period,
        submission_period_hours=submission_period_hours,
        files="[]"
    )
    if hf_api_key:
        task.set_hf_api_key(hf_api_key)
        
    db.session.add(task)
    db.session.commit()
    
    uploaded_files_meta = []
    files_keys = [k for k in request.files.keys() if k.startswith('file')]
    
    if len(files_keys) > 5:
        db.session.delete(task)
        db.session.commit()
        return jsonify({"error": "You can upload a maximum of 5 files per task."}), 400
        
    task_upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], f"task_{task.id}")
    os.makedirs(task_upload_dir, exist_ok=True)
    
    if 'evaluator_script' in request.files:
        f = request.files['evaluator_script']
        if f and f.filename != '':
            safe_name = "evaluator.py"
            save_path = os.path.join(task_upload_dir, safe_name)
            f.save(save_path)
            task.evaluator_script_path = save_path
            
    if 'baseline_notebook' in request.files:
        f = request.files['baseline_notebook']
        if f and f.filename != '':
            safe_name = "baseline_" + secure_filename(f.filename)
            save_path = os.path.join(task_upload_dir, safe_name)
            f.save(save_path)
            task.baseline_notebook_path = save_path
            
    if 'solution_notebook' in request.files:
        f = request.files['solution_notebook']
        if f and f.filename != '':
            safe_name = "solution_" + secure_filename(f.filename)
            save_path = os.path.join(task_upload_dir, safe_name)
            f.save(save_path)
            task.solution_notebook_path = save_path
            
    for key in files_keys:
        uploaded_file = request.files[key]
        if uploaded_file and uploaded_file.filename != '':
            uploaded_file.seek(0, os.SEEK_END)
            size = uploaded_file.tell()
            uploaded_file.seek(0)
            
            if size > MAX_FILE_SIZE_BYTES:
                db.session.delete(task)
                db.session.commit()
                import shutil
                shutil.rmtree(task_upload_dir, ignore_errors=True)
                return jsonify({"error": f"File '{uploaded_file.filename}' exceeds the maximum allowed size of 25MB."}), 400
                
            safe_name = secure_filename(uploaded_file.filename)
            save_path = os.path.join(task_upload_dir, safe_name)
            uploaded_file.save(save_path)
            
            uploaded_files_meta.append({
                "filename": uploaded_file.filename,
                "saved_name": safe_name,
                "size_bytes": size
            })
            
    task.files = json.dumps(uploaded_files_meta)
    db.session.commit()
    
    from cache_utils import invalidate_challenge_cache
    invalidate_challenge_cache(challenge_id)
    
    # Parse code cells from notebooks
    baseline_cells = []
    if task.baseline_notebook_path and os.path.exists(task.baseline_notebook_path):
        baseline_cells = extract_code_from_notebook(task.baseline_notebook_path)
        
    solution_cells = []
    if task.solution_notebook_path and os.path.exists(task.solution_notebook_path):
        solution_cells = extract_code_from_notebook(task.solution_notebook_path)
        
    admin_id = request.user["user_id"]
    if baseline_cells:
        queue_system_submission(task, challenge, baseline_cells, admin_id, priority=8)
    if solution_cells:
        queue_system_submission(task, challenge, solution_cells, admin_id, priority=8)
        
    return jsonify(task.to_dict()), 201

@tasks_bp.route('/tasks/<int:task_id>', methods=['PUT'])
@role_required(['admin', 'jury'])
def update_task(task_id):
    task = db.get_or_404(Task, task_id)
    
    title = request.form.get("title")
    description = request.form.get("description")
    
    if title:
        task.title = title
    if description is not None:
        task.description = description
        
    # Task parameter validation on update
    import re
    if "ram_limit_mb" in request.form:
        ram_val = to_int(request.form.get("ram_limit_mb"))
        if ram_val is not None and (ram_val <= 0 or ram_val > 16384):
            return jsonify({"error": "RAM limit must be a positive integer and cannot exceed 16384 MB (16 GB)."}), 400
            
    if "base_docker_image" in request.form:
        base_img = request.form.get("base_docker_image")
        if base_img:
            DOCKER_IMAGE_REGEX = r'^[a-z0-9]+(?:[._-][a-z0-9]+)*/?[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[a-zA-Z0-9_.-]+)?$'
            if not re.match(DOCKER_IMAGE_REGEX, base_img):
                return jsonify({"error": "Invalid base Docker image name format."}), 400
                
    if "apt_packages" in request.form:
        apt_pkgs = request.form.get("apt_packages")
        if apt_pkgs:
            packages = [p.strip() for p in apt_pkgs.replace(",", " ").split() if p.strip()]
            for pkg in packages:
                if not re.match(r'^[a-zA-Z0-9.+-]+$', pkg):
                    return jsonify({"error": f"Invalid APT package name: '{pkg}'."}), 400
                    
    if "pip_requirements" in request.form:
        pip_reqs = request.form.get("pip_requirements")
        if pip_reqs:
            for line in pip_reqs.splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if not re.match(r'^[a-zA-Z0-9_.-]+(?:\s*(?:>=|<=|==|!=|~=|>|<)\s*[a-zA-Z0-9_.-]+(?:\s*,\s*(?:>=|<=|==|!=|~=|>|<)\s*[a-zA-Z0-9_.-]+)*)?$', line):
                    return jsonify({"error": f"Invalid pip requirement line format: '{line}'."}), 400

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
        
    if "require_submit_tag" in request.form:
        task.require_submit_tag = to_bool(request.form.get("require_submit_tag"))
    if "ban_magic_commands" in request.form:
        task.ban_magic_commands = to_bool(request.form.get("ban_magic_commands"))
    if "banned_imports" in request.form:
        task.banned_imports = request.form.get("banned_imports")
        
    if "metrics_config" in request.form:
        metrics_config_raw = request.form.get("metrics_config")
        try:
            task.metrics_config = json.loads(metrics_config_raw) if metrics_config_raw else None
        except:
            pass
            
    if "hf_train_repo" in request.form:
        task.hf_train_repo = request.form.get("hf_train_repo")
    if "hf_eval_repo" in request.form:
        task.hf_eval_repo = request.form.get("hf_eval_repo")
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
        
    task_upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], f"task_{task.id}")
    os.makedirs(task_upload_dir, exist_ok=True)
    
    if 'evaluator_script' in request.files:
        f = request.files['evaluator_script']
        if f and f.filename != '':
            safe_name = "evaluator.py"
            save_path = os.path.join(task_upload_dir, safe_name)
            f.save(save_path)
            task.evaluator_script_path = save_path
            
    if 'baseline_notebook' in request.files:
        f = request.files['baseline_notebook']
        if f and f.filename != '':
            safe_name = "baseline_" + secure_filename(f.filename)
            save_path = os.path.join(task_upload_dir, safe_name)
            f.save(save_path)
            task.baseline_notebook_path = save_path
            
    if 'solution_notebook' in request.files:
        f = request.files['solution_notebook']
        if f and f.filename != '':
            safe_name = "solution_" + secure_filename(f.filename)
            save_path = os.path.join(task_upload_dir, safe_name)
            f.save(save_path)
            task.solution_notebook_path = save_path
            
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
            
    new_files_keys = [k for k in request.files.keys() if k.startswith('file')]
    if len(current_files) + len(new_files_keys) > 5:
        return jsonify({"error": "A task can contain a maximum of 5 files."}), 400
        
    for key in new_files_keys:
        uploaded_file = request.files[key]
        if uploaded_file and uploaded_file.filename != '':
            uploaded_file.seek(0, os.SEEK_END)
            size = uploaded_file.tell()
            uploaded_file.seek(0)
            
            if size > MAX_FILE_SIZE_BYTES:
                return jsonify({"error": f"File '{uploaded_file.filename}' exceeds the maximum allowed size of 25MB."}), 400
                
            safe_name = secure_filename(uploaded_file.filename)
            save_path = os.path.join(task_upload_dir, safe_name)
            uploaded_file.save(save_path)
            
            current_files.append({
                "filename": uploaded_file.filename,
                "saved_name": safe_name,
                "size_bytes": size
            })
            
    task.files = json.dumps(current_files)
    db.session.commit()
    
    from cache_utils import invalidate_challenge_cache
    invalidate_challenge_cache(task.challenge_id)
    
    return jsonify(task.to_dict())

@tasks_bp.route('/tasks/<int:task_id>', methods=['DELETE'])
@role_required(['admin', 'jury'])
def delete_task(task_id):
    task = db.get_or_404(Task, task_id)
    challenge_id = task.challenge_id
    task_upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], f"task_{task.id}")
    import shutil
    shutil.rmtree(task_upload_dir, ignore_errors=True)
    db.session.delete(task)
    db.session.commit()
    
    from cache_utils import invalidate_challenge_cache
    invalidate_challenge_cache(challenge_id)
    
    return jsonify({"message": f"Task '{task.title}' has been deleted successfully."})

# --- DOWNLOAD FILE ---

@tasks_bp.route('/tasks/<int:task_id>/download/<string:filename>', methods=['GET'])
@login_required
def download_task_file(task_id, filename):
    task = db.get_or_404(Task, task_id)
    user_role = request.user["role"]
    user_id = request.user["user_id"]
    
    if user_role == 'competitor':
        if not check_task_started(task, user_role, user_id):
            return jsonify({
                "error": "Access denied or task not available yet.",
                "code": "ERR_NOT_AVAILABLE"
            }), 403
            
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
        return jsonify({
            "error": "File not found in task metadata.",
            "code": "ERR_FILE_NOT_FOUND"
        }), 404
        
    task_upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], f"task_{task.id}")
    return send_from_directory(
        task_upload_dir,
        saved_name,
        as_attachment=True,
        download_name=filename
    )

# --- TASK SUBMISSIONS & EVALUATIONS ---

@tasks_bp.route('/tasks/<int:task_id>/submit', methods=['POST'])
@login_required
def submit_task_code(task_id):
    task = db.get_or_404(Task, task_id)
    challenge = task.challenge
    
    if not challenge.is_active:
        return jsonify({"error": "This competition is currently inactive."}), 400
    if challenge.is_archived:
        return jsonify({"error": "This competition has been archived and no longer accepts submissions."}), 400
        
    user_id = request.user["user_id"]
    user_role = request.user["role"]
    
    if user_role == 'competitor':
        if not check_competitor_access(user_id, task.challenge_id):
            return jsonify({"error": "Access denied. You are not registered for this competition."}), 403
            
        if challenge.scores_finalized:
            return jsonify({"error": "Submissions are disabled for finalized competitions."}), 403
            
        now = datetime.utcnow()
        if task.stage_id:
            from models import Stage
            stage = db.session.get(Stage, task.stage_id)
            if stage:
                if now < stage.start_time:
                    return jsonify({"error": f"The stage '{stage.title}' has not started yet."}), 400
                if now > stage.end_time:
                    return jsonify({"error": f"The deadline for the stage '{stage.title}' has passed."}), 400
        else:
            if challenge.start_time and now < challenge.start_time:
                return jsonify({"error": "This competition has not started yet."}), 400
            if challenge.end_time and now > challenge.end_time:
                return jsonify({"error": "This competition has ended and no longer accepts submissions."}), 400
            
    data = request.json or {}
    selected_cells = data.get("selected_cells")
    
    if not selected_cells or not isinstance(selected_cells, list):
        return jsonify({"error": "selected_cells list is required."}), 400
        
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    submission_count = Submission.query.filter(
        Submission.user_id == user_id,
        Submission.challenge_id == challenge.id,
        Submission.created_at >= today_start
    ).count()
    
    if submission_count >= challenge.max_eval_requests:
        return jsonify({
            "error": f"Daily limit reached. You can only make {challenge.max_eval_requests} submissions per day."
        }), 429
        
    if task.max_submissions_per_period and task.submission_period_hours:
        period_start = datetime.utcnow() - timedelta(hours=task.submission_period_hours)
        sub_count = Submission.query.filter(
            Submission.user_id == user_id,
            Submission.task_id == task.id,
            Submission.created_at >= period_start
        ).count()
        if sub_count >= task.max_submissions_per_period:
            return jsonify({
                "error": f"Task limit reached. You can only make {task.max_submissions_per_period} submissions per {task.submission_period_hours} hours."
            }), 429
            
    passed, err_msg = check_execution_rules(task, selected_cells)
    if not passed:
        submission = Submission(
            user_id=user_id,
            challenge_id=challenge.id,
            task_id=task.id,
            status='failed',
            detailed_status='failed',
            code_cells=json.dumps(selected_cells),
            public_score=0.0,
            private_score=0.0,
            logs=f"--- Rule Check Failed ---\n{err_msg}",
            execution_time_ms=0
        )
        db.session.add(submission)
        db.session.commit()
        publish_submissions_update(submission.task_id, submission.user_id)
        publish_leaderboard_update(submission.task_id)
        return jsonify({
            "message": "Submission received but failed rule check.",
            "submission_id": submission.id,
            "status": submission.status,
            "error": err_msg
        }), 200
        
    priority = calculate_submission_priority(user_id, user_role)
    
    submission = Submission(
        user_id=user_id,
        challenge_id=challenge.id,
        task_id=task.id,
        status='queued',
        detailed_status='queued',
        code_cells=json.dumps(selected_cells)
    )
    db.session.add(submission)
    db.session.commit()
    publish_submissions_update(submission.task_id, submission.user_id)
    publish_leaderboard_update(submission.task_id)
    
    from tasks import evaluate_submission
    
    gpu_required = False
    if task.gpu_required is not None:
        gpu_required = task.gpu_required
    elif challenge.gpu_required is not None:
        gpu_required = challenge.gpu_required
        
    queue_name = 'gpu_queue' if gpu_required else 'celery'
    
    # Compile complete metadata dictionary for remote workers (avoids DB exposure on remote nodes)
    task_files_list = []
    if task.files:
        try:
            task_files_list = json.loads(task.files)
        except:
            pass
            
    hf_token = task.get_hf_api_key() or ""
    main_server_url = os.environ.get("MAIN_SERVER_URL", "http://localhost:5001")
    worker_secret_key = os.environ.get("WORKER_SECRET_KEY", "nai-worker-default-secret-token")
    
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
        
        "is_custom_eval": True if (task.custom_eval_code or (task.evaluator_script_path and os.path.exists(task.evaluator_script_path))) else False,
        "metrics_config": task.metrics_config,
        "hf_eval_repo": task.hf_eval_repo,
        "hf_token": hf_token,
        "public_eval_percentage": task.public_eval_percentage or 30,
        
        "task_files": task_files_list,
        "main_server_url": main_server_url,
        "worker_secret_key": worker_secret_key
    }
    
    if task.custom_eval_code:
        metadata["custom_eval_code"] = task.custom_eval_code
    elif task.evaluator_script_path and os.path.exists(task.evaluator_script_path):
        try:
            with open(task.evaluator_script_path, "r") as ef:
                metadata["custom_eval_code"] = ef.read()
        except Exception as ef_err:
            print(f"Error reading evaluator script: {ef_err}")
            
    evaluate_submission.apply_async(
        args=[submission.id, metadata],
        priority=priority,
        queue=queue_name
    )
    
    return jsonify({
        "message": "Submission received and queued for execution.",
        "submission_id": submission.id,
        "status": submission.status
    }), 202

def _get_task_submissions_data(task_id, user_role, user_id, page=None, per_page=10):
    task = db.session.get(Task, task_id)
    if not task:
        return {"error": "Task not found."}
        
    if user_role == 'competitor':
        if not check_task_started(task, user_role, user_id):
            return {"error": "Access denied or task not available yet."}
        challenge = task.challenge
        if challenge and challenge.scores_finalized:
            return {"error": "Access denied. Submissions are hidden for finalized competitions."}
        query = Submission.query.filter_by(task_id=task_id, user_id=user_id)
    else:
        query = Submission.query.filter_by(task_id=task_id)
        
    if page is not None:
        pagination = query.order_by(Submission.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
        return {
            "items": [s.to_dict_light(view_role=user_role, current_user_id=user_id) for s in pagination.items],
            "total": pagination.total,
            "page": pagination.page,
            "pages": pagination.pages
        }
        
    submissions = query.order_by(Submission.created_at.desc()).all()
    return [s.to_dict_light(view_role=user_role, current_user_id=user_id) for s in submissions]

@tasks_bp.route('/tasks/<int:task_id>/submissions', methods=['GET'])
@login_required
def get_task_submissions(task_id):
    user_role = request.user["role"]
    user_id = request.user["user_id"]
    page = request.args.get('page', type=int)
    per_page = request.args.get('per_page', 10, type=int)
    
    data = _get_task_submissions_data(task_id, user_role, user_id, page, per_page)
    if isinstance(data, dict) and "error" in data:
        return jsonify(data), 403
    return jsonify(data)

def _get_task_leaderboard_data(task_id, user_role, current_user_id):
    task = db.session.get(Task, task_id)
    if not task:
        return {"error": "Task not found."}
    challenge = task.challenge
    
    if user_role == 'competitor':
        if not check_task_started(task, user_role, current_user_id):
            return {"error": "Access denied or task not available yet."}
            
    all_completed = Submission.query.filter_by(
        task_id=task_id,
        status='completed'
    ).all()
    
    if user_role == 'competitor' and challenge.is_frozen and not challenge.scores_finalized:
        # Under manual freeze, new submissions are blocked. The leaderboard displays the current state.
        pass
    
    is_lower_better = False
    if task.metrics_config:
        try:
            m_config = json.loads(task.metrics_config) if isinstance(task.metrics_config, str) else task.metrics_config
            for m_name, m_info in m_config.items():
                if m_info.get("higher_is_better") is False:
                    is_lower_better = True
                break
        except Exception:
            pass
    else:
        metric_name = challenge.metric_name or ''
        if 'mse' in metric_name.lower() or 'error' in metric_name.lower() or 'loss' in metric_name.lower():
            is_lower_better = True
            
    final_selections = {s.user_id: s for s in all_completed if s.is_final_selection}
    
    user_best = {}
    for sub in all_completed:
        uid = sub.user_id
        
        # Override manual selection if competition ended and there were late-processed runs
        use_best = True
        if challenge.end_time and datetime.utcnow() > challenge.end_time:
            user_subs = [s for s in all_completed if s.user_id == uid]
            has_late_sub = any(s.executed_at and s.executed_at > challenge.end_time for s in user_subs)
            if not has_late_sub and uid in final_selections:
                use_best = False
        else:
            if uid in final_selections:
                use_best = False
                
        if not use_best:
            user_best[uid] = final_selections[uid]
            continue
            
        score = sub.public_score
        if score is None:
            continue
            
        if uid not in user_best:
            user_best[uid] = sub
        else:
            current_best = user_best[uid]
            is_better = False
            if is_lower_better:
                if score < current_best.public_score:
                    is_better = True
                elif score == current_best.public_score:
                    t_new = sub.execution_time_ms if sub.execution_time_ms is not None else 999999
                    t_curr = current_best.execution_time_ms if current_best.execution_time_ms is not None else 999999
                    if t_new < t_curr:
                        is_better = True
            else:
                if score > current_best.public_score:
                    is_better = True
                elif score == current_best.public_score:
                    t_new = sub.execution_time_ms if sub.execution_time_ms is not None else 999999
                    t_curr = current_best.execution_time_ms if current_best.execution_time_ms is not None else 999999
                    if t_new < t_curr:
                        is_better = True
            if is_better:
                user_best[uid] = sub
                
    # Include all competitors, even those with no submissions
    competitors = User.query.filter_by(role='competitor', challenge_id=task.challenge_id).all()
    leaderboard_entries = []
    
    for comp in competitors:
        sub = user_best.get(comp.id)
        if sub:
            entry_dict = sub.to_dict(view_role=user_role, current_user_id=current_user_id)
            entry_dict["has_submitted"] = True
        else:
            entry_dict = {
                "id": None,
                "challenge_id": task.challenge_id,
                "task_id": task_id,
                "task_title": task.title,
                "status": None,
                "detailed_status": None,
                "code_cells": "[]",
                "public_score": None,
                "private_score": None,
                "logs": None,
                "gpu_node": None,
                "execution_time_ms": None,
                "created_at": None,
                "executed_at": None,
                "user": comp.to_dict(view_role=user_role, scores_finalized=challenge.scores_finalized, current_user_id=current_user_id),
                "metrics_payload_public": {},
                "metrics_payload_private": {},
                "final_weighted_score_public": None,
                "final_weighted_score_private": None,
                "is_final_selection": False,
                "is_disqualified": False,
                "celery_task_id": None,
                "has_submitted": False
            }
        leaderboard_entries.append(entry_dict)
        
    from functools import cmp_to_key
    def compare_entries(a, b):
        if a["has_submitted"] != b["has_submitted"]:
            return -1 if a["has_submitted"] else 1
            
        if not a["has_submitted"]:
            name_a = f"{a['user'].get('name') or ''} {a['user'].get('surname') or ''}".strip().lower() or a['user'].get('username', '').lower()
            name_b = f"{b['user'].get('name') or ''} {b['user'].get('surname') or ''}".strip().lower() or b['user'].get('username', '').lower()
            if name_a != name_b:
                return -1 if name_a < name_b else 1
            return 0
            
        score_a = a["public_score"]
        score_b = b["public_score"]
        
        if score_a != score_b:
            if is_lower_better:
                return -1 if score_a < score_b else 1
            else:
                return -1 if score_a > score_b else 1
                
        ta = a["execution_time_ms"] if a["execution_time_ms"] is not None else 999999
        tb = b["execution_time_ms"] if b["execution_time_ms"] is not None else 999999
        if ta != tb:
            return -1 if ta < tb else 1
            
        ca = a["created_at"] or ""
        cb = b["created_at"] or ""
        if ca != cb:
            return -1 if ca < cb else 1
        return 0

    sorted_entries = sorted(leaderboard_entries, key=cmp_to_key(compare_entries))
    
    leaderboard = []
    for rank, entry_dict in enumerate(sorted_entries, 1):
        entry_dict["rank"] = rank
        leaderboard.append(entry_dict)
        
    return {
        "challenge_title": challenge.title,
        "task_title": task.title,
        "metric_name": challenge.metric_name,
        "is_finalized": challenge.scores_finalized,
        "leaderboard": leaderboard
    }

@tasks_bp.route('/tasks/<int:task_id>/leaderboard', methods=['GET'])
@login_required
def get_task_leaderboard(task_id):
    user_role = request.user["role"]
    current_user_id = request.user["user_id"]
    data = _get_task_leaderboard_data(task_id, user_role, current_user_id)
    if "error" in data:
        return jsonify(data), 403
    return jsonify(data)

@tasks_bp.route('/tasks/<int:task_id>/leaderboard/live', methods=['GET'])
@login_required
def get_task_leaderboard_live(task_id):
    user_role = request.user["role"]
    current_user_id = request.user["user_id"]
    if user_role == 'competitor':
        task = db.session.get(Task, task_id)
        if not task or not check_task_started(task, user_role, current_user_id):
            return jsonify({
                "error": "Access denied or task not available yet.",
                "code": "ERR_NOT_AVAILABLE"
            }), 403
    
    def event_generator():
        with current_app.app_context():
            data = _get_task_leaderboard_data(task_id, user_role, current_user_id)
            yield f"data: {json.dumps(data)}\n\n"
            
        broker_url = current_app.config.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
        r = redis.Redis.from_url(broker_url)
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
            print(f"Leaderboard SSE error: {e}")
            
    return Response(stream_with_context(event_generator()), mimetype="text/event-stream")

@tasks_bp.route('/tasks/<int:task_id>/submissions/live', methods=['GET'])
@login_required
def get_task_submissions_live(task_id):
    user_role = request.user["role"]
    current_user_id = request.user["user_id"]
    page = request.args.get('page', type=int)
    per_page = request.args.get('per_page', 10, type=int)
    
    if user_role == 'competitor':
        task = db.session.get(Task, task_id)
        if not task or not check_task_started(task, user_role, current_user_id):
            return jsonify({
                "error": "Access denied or task not available yet.",
                "code": "ERR_NOT_AVAILABLE"
            }), 403
        if task.challenge and task.challenge.scores_finalized:
            return jsonify({
                "error": "Access denied. Submissions are hidden for finalized competitions.",
                "code": "ERR_COMPETITION_FINALIZED"
            }), 403
            
    def event_generator():
        with current_app.app_context():
            data = _get_task_submissions_data(task_id, user_role, current_user_id, page, per_page)
            yield f"data: {json.dumps(data)}\n\n"
            
        broker_url = current_app.config.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
        r = redis.Redis.from_url(broker_url)
        pubsub = r.pubsub()
        
        if user_role in ['admin', 'jury']:
            pubsub.psubscribe(f"task_{task_id}_user_*_submissions")
        else:
            pubsub.subscribe(f"task_{task_id}_user_{current_user_id}_submissions")
            
        try:
            while True:
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=2.0)
                if message:
                    with current_app.app_context():
                        data = _get_task_submissions_data(task_id, user_role, current_user_id, page, per_page)
                        yield f"data: {json.dumps(data)}\n\n"
                else:
                    yield ": keep-alive\n\n"
        except GeneratorExit:
            try:
                if user_role in ['admin', 'jury']:
                    pubsub.punsubscribe()
                else:
                    pubsub.unsubscribe()
                pubsub.close()
            except:
                pass
        except Exception as e:
            print(f"Submissions SSE error: {e}")
            
    return Response(stream_with_context(event_generator()), mimetype="text/event-stream")


@tasks_bp.route('/worker-status', methods=['GET'])
@login_required
def get_worker_status():
    from flask import current_app
    from cache_utils import get_cached, set_cached
    
    is_testing = current_app.config.get("TESTING", False)
    cache_key = "worker:status:summary"
    if not is_testing:
        cached_val = get_cached(cache_key)
        if cached_val is not None:
            return jsonify(cached_val), 200

    try:
        from tasks import celery
        import redis
        import json
        
        inspect = celery.control.inspect(timeout=1.0)
        pings = inspect.ping() or {}
        stats = inspect.stats() or {}
        
        is_online = pings is not None and len(pings) > 0
        
        r = None
        try:
            broker_url = current_app.config.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
            r = redis.Redis.from_url(broker_url)
        except Exception:
            pass
            
        clusters = []
        for worker_name in pings.keys():
            spec = None
            if r:
                try:
                    spec_data = r.get(f"worker_spec:{worker_name}")
                    if spec_data:
                        spec = json.loads(spec_data)
                except Exception:
                    pass
                    
            if not spec:
                w_stats = stats.get(worker_name, {}) if stats else {}
                pool = w_stats.get("pool", {}) if w_stats else {}
                concurrency = pool.get("max-concurrency", 1) if pool else 1
                
                # Resilient numeric conversion (handles MagicMocks in testing)
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
                    "vram_gb": 8.0 if has_gpu else "N/A"
                }
            clusters.append(spec)
            
        res_data = {
            "status": "online" if is_online else "offline",
            "clusters": clusters
        }
        if not is_testing:
            set_cached(cache_key, res_data, timeout=10)
        return jsonify(res_data), 200
    except Exception as e:
        return jsonify({"status": "offline", "error": str(e), "clusters": []}), 200


@tasks_bp.route('/worker/report/<int:submission_id>', methods=['POST'])
def report_worker_progress(submission_id):
    token = request.headers.get("X-Worker-Token")
    expected_token = os.environ.get("WORKER_SECRET_KEY", "nai-worker-default-secret-token")
    if not token or token != expected_token:
        return jsonify({"error": "Unauthorized"}), 401
        
    data = request.json or {}
    submission = db.get_or_404(Submission, submission_id)
    
    if "status" in data:
        submission.status = data["status"]
    if "detailed_status" in data:
        submission.detailed_status = data["detailed_status"]
    if "logs" in data:
        submission.logs = data["logs"]
    if "public_score" in data:
        submission.public_score = data["public_score"]
        submission.final_weighted_score_public = data["public_score"]
    if "private_score" in data:
        submission.private_score = data["private_score"]
        submission.final_weighted_score_private = data["private_score"]
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


@tasks_bp.route('/worker/tasks/<int:task_id>/files/<string:filename>', methods=['GET'])
def worker_download_task_file(task_id, filename):
    token = request.headers.get("X-Worker-Token")
    expected_token = os.environ.get("WORKER_SECRET_KEY", "nai-worker-default-secret-token")
    if not token or token != expected_token:
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
        
    task_upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], f"task_{task.id}")
    return send_from_directory(task_upload_dir, saved_name)



