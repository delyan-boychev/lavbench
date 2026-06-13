from flask import Blueprint, request, jsonify
from models import db, Challenge, User
from auth_utils import login_required, role_required

challenges_bp = Blueprint('challenges', __name__)

from datetime import datetime

def filter_challenge_for_competitor(challenge_dict):
    challenge_dict = dict(challenge_dict)
    now = datetime.utcnow()
    
    comp_start = None
    if challenge_dict.get("start_time"):
        try:
            comp_start = datetime.fromisoformat(challenge_dict["start_time"].replace('Z', '+00:00')).replace(tzinfo=None)
        except Exception:
            comp_start = None
            
    if comp_start and now < comp_start:
        challenge_dict["tasks"] = []
        challenge_dict["stages"] = []
    else:
        filtered_tasks = []
        for t in challenge_dict.get("tasks", []):
            if not t.get("stage_id"):
                filtered_tasks.append(t)
            else:
                from models import Stage
                stage = db.session.get(Stage, t["stage_id"])
                if stage and now >= stage.start_time:
                    filtered_tasks.append(t)
        challenge_dict["tasks"] = filtered_tasks
        
        filtered_stages = []
        for s in challenge_dict.get("stages", []):
            try:
                st_start = datetime.fromisoformat(s["start_time"].replace('Z', '+00:00')).replace(tzinfo=None)
            except Exception:
                st_start = None
            if not st_start or now >= st_start:
                filtered_stages.append(s)
        challenge_dict["stages"] = filtered_stages
        
    return challenge_dict

@challenges_bp.route('', methods=['GET'])
@login_required
def get_challenges():
    user_id = request.user["user_id"]
    user_role = request.user["role"]
    
    from cache_utils import get_cached, set_cached
    
    if user_role == 'competitor':
        user = db.session.get(User, user_id)
        if not user or not user.challenge_id:
            return jsonify([])
        challenge_id = user.challenge_id
        
        challenge = db.session.get(Challenge, challenge_id)
        if not challenge or challenge.is_archived:
            return jsonify([])
            
        cache_key = f"challenge:{challenge_id}:competitor"
        cached_challenge = get_cached(cache_key)
        if cached_challenge is not None:
            return jsonify([cached_challenge])
            
        challenge_dict = challenge.to_dict()
        filtered = filter_challenge_for_competitor(challenge_dict)
        set_cached(cache_key, filtered, timeout=600)
        return jsonify([filtered])
        
    page = request.args.get('page', type=int)
    if page is not None:
        per_page = request.args.get('per_page', 10, type=int)
        pagination = Challenge.query.paginate(page=page, per_page=per_page, error_out=False)
        return jsonify({
            "items": [c.to_dict() for c in pagination.items],
            "total": pagination.total,
            "page": pagination.page,
            "pages": pagination.pages
        })
        
    cache_key = "challenges:all"
    cached_all = get_cached(cache_key)
    if cached_all is not None:
        return jsonify(cached_all)
        
    challenges = Challenge.query.all()
    challenges_list = [c.to_dict() for c in challenges]
    set_cached(cache_key, challenges_list, timeout=600)
    return jsonify(challenges_list)


@challenges_bp.route('/<int:challenge_id>', methods=['GET'])
@login_required
def get_challenge(challenge_id):
    user_id = request.user["user_id"]
    user_role = request.user["role"]
    
    if user_role == 'competitor':
        user = db.session.get(User, user_id)
        if not user or user.challenge_id != challenge_id:
            return jsonify({
                "error": "Access denied. You are not registered for this competition.",
                "code": "ERR_NOT_REGISTERED"
            }), 403
            
        challenge = db.session.get(Challenge, challenge_id)
        if not challenge or challenge.is_archived:
            return jsonify({
                "error": "Challenge not found.",
                "code": "ERR_CHALLENGE_NOT_FOUND"
            }), 404
            
    from cache_utils import get_cached, set_cached
    
    if user_role == 'competitor':
        cache_key = f"challenge:{challenge_id}:competitor"
        cached_challenge = get_cached(cache_key)
        if cached_challenge is not None:
            challenge_dict = cached_challenge
        else:
            challenge = db.session.get(Challenge, challenge_id)
            if not challenge or challenge.is_archived:
                return jsonify({
                    "error": "Challenge not found.",
                    "code": "ERR_CHALLENGE_NOT_FOUND"
                }), 404
            challenge_dict = challenge.to_dict()
            challenge_dict = filter_challenge_for_competitor(challenge_dict)
            set_cached(cache_key, challenge_dict, timeout=600)
    else:
        cache_key = f"challenge:{challenge_id}"
        cached_challenge = get_cached(cache_key)
        if cached_challenge is not None:
            challenge_dict = cached_challenge
        else:
            challenge = db.get_or_404(Challenge, challenge_id)
            challenge_dict = challenge.to_dict()
            set_cached(cache_key, challenge_dict, timeout=600)
        
    return jsonify(challenge_dict)


from datetime import datetime

def parse_datetime(val):
    if not val:
        return None
    try:
        if isinstance(val, str):
            if val.endswith('Z'):
                val = val[:-1] + '+00:00'
            # Remove milliseconds/microsecond if present and fromisoformat fails
            try:
                return datetime.fromisoformat(val)
            except ValueError:
                # Try parsing with format without timezone offset first if needed
                # but fromisoformat is usually sufficient. Let's do a basic strip:
                if 'T' in val:
                    val = val.split('.')[0] # strip milliseconds
                return datetime.strptime(val, "%Y-%m-%dT%H:%M:%S")
    except Exception:
        pass
    return None

@challenges_bp.route('', methods=['POST'])
@role_required(['admin', 'jury'])
def create_challenge():
    data = request.json or {}
    title = data.get("title")
    description = data.get("description")
    max_eval_requests = int(data.get("max_eval_requests", 10))
    ram_limit_mb = int(data.get("ram_limit_mb", 8192))
    time_limit_sec = int(data.get("time_limit_sec", 300))
    gpu_required = bool(data.get("gpu_required", True))
    double_blind = data.get("double_blind")
    if double_blind is None:
        double_blind = True
    else:
        double_blind = bool(double_blind)
    
    start_time = parse_datetime(data.get("start_time"))
    end_time = parse_datetime(data.get("end_time"))
    is_frozen = bool(data.get("is_frozen", False))
    
    timezone = data.get("timezone", "UTC")
    
    if not title:
        return jsonify({
            "error": "Competition title is required.",
            "code": "ERR_TITLE_REQUIRED"
        }), 400

    if not start_time or not end_time:
        return jsonify({
            "error": "Competition start time and end time are required.",
            "code": "ERR_DATETIME_REQUIRED"
        }), 400

    if max_eval_requests is not None and max_eval_requests < 1:
        return jsonify({
            "error": "Daily submissions limit must be at least 1.",
            "code": "ERR_INVALID_LIMITS"
        }), 400

    if ram_limit_mb is not None and ram_limit_mb < 128:
        return jsonify({
            "error": "RAM limit must be at least 128 MB.",
            "code": "ERR_INVALID_LIMITS"
        }), 400

    if time_limit_sec is not None and time_limit_sec < 1:
        return jsonify({
            "error": "Time limit must be at least 1 second.",
            "code": "ERR_INVALID_LIMITS"
        }), 400

    if end_time <= start_time:
        return jsonify({
            "error": "End time must be after start time.",
            "code": "ERR_INVALID_DATES"
        }), 400
        
    challenge = Challenge(
        title=title,
        description=description,
        max_eval_requests=max_eval_requests,
        ram_limit_mb=ram_limit_mb,
        time_limit_sec=time_limit_sec,
        gpu_required=gpu_required,
        start_time=start_time,
        end_time=end_time,
        is_frozen=is_frozen,
        double_blind=double_blind,
        timezone=timezone
    )
    db.session.add(challenge)
    db.session.commit()
    
    from cache_utils import invalidate_challenge_cache
    invalidate_challenge_cache()
    
    return jsonify(challenge.to_dict()), 201


@challenges_bp.route('/<int:challenge_id>', methods=['PUT'])
@role_required(['admin', 'jury'])
def update_challenge(challenge_id):
    challenge = db.get_or_404(Challenge, challenge_id)
    data = request.json or {}
    
    title = data.get("title")
    description = data.get("description")
    max_eval_requests = data.get("max_eval_requests")
    ram_limit_mb = data.get("ram_limit_mb")
    time_limit_sec = data.get("time_limit_sec")
    gpu_required = data.get("gpu_required")
    
    if title:
        challenge.title = title
    if description is not None:
        challenge.description = description
    if max_eval_requests is not None:
        val = int(max_eval_requests)
        if val < 1:
            return jsonify({"error": "Daily submissions limit must be at least 1.", "code": "ERR_INVALID_LIMITS"}), 400
        challenge.max_eval_requests = val
    if ram_limit_mb is not None:
        val = int(ram_limit_mb)
        if val < 128:
            return jsonify({"error": "RAM limit must be at least 128 MB.", "code": "ERR_INVALID_LIMITS"}), 400
        challenge.ram_limit_mb = val
    if time_limit_sec is not None:
        val = int(time_limit_sec)
        if val < 1:
            return jsonify({"error": "Time limit must be at least 1 second.", "code": "ERR_INVALID_LIMITS"}), 400
        challenge.time_limit_sec = val
    if gpu_required is not None:
        challenge.gpu_required = bool(gpu_required)
        
    if "start_time" in data:
        st = parse_datetime(data.get("start_time"))
        if not st:
            return jsonify({
                "error": "Start time is required.",
                "code": "ERR_DATETIME_REQUIRED"
            }), 400
        challenge.start_time = st
    if "end_time" in data:
        et = parse_datetime(data.get("end_time"))
        if not et:
            return jsonify({
                "error": "End time is required.",
                "code": "ERR_DATETIME_REQUIRED"
            }), 400
        challenge.end_time = et
        
    if challenge.end_time <= challenge.start_time:
        return jsonify({
            "error": "End time must be after start time.",
            "code": "ERR_INVALID_DATES"
        }), 400
        
    if "is_frozen" in data:
        challenge.is_frozen = bool(data.get("is_frozen"))
    if "double_blind" in data:
        challenge.double_blind = bool(data.get("double_blind"))
    if "timezone" in data:
        challenge.timezone = data.get("timezone")
        
    db.session.commit()
    
    from cache_utils import invalidate_challenge_cache, invalidate_leaderboard_cache
    invalidate_challenge_cache(challenge_id)
    invalidate_leaderboard_cache(challenge_id)
    
    return jsonify(challenge.to_dict())


@challenges_bp.route('/<int:challenge_id>', methods=['DELETE'])
@role_required(['admin', 'jury'])
def delete_challenge(challenge_id):
    challenge = db.get_or_404(Challenge, challenge_id)
    
    users = User.query.filter_by(challenge_id=challenge_id).all()
    for u in users:
        if u.role == 'competitor':
            db.session.delete(u)
        else:
            u.challenge_id = None
         
    db.session.delete(challenge)
    db.session.commit()
    
    from cache_utils import invalidate_challenge_cache, invalidate_leaderboard_cache
    invalidate_challenge_cache(challenge_id)
    invalidate_leaderboard_cache(challenge_id)
    
    return jsonify({"message": f"Competition '{challenge.title}' and all its associated tasks and submissions have been deleted successfully."})


@challenges_bp.route('/<int:challenge_id>/finalize', methods=['POST'])
@role_required(['jury'])
def finalize_challenge(challenge_id):
    challenge = db.get_or_404(Challenge, challenge_id)
    
    # Check if manual points are entered for all competitors for all tasks
    competitors = User.query.filter_by(role='competitor', challenge_id=challenge_id).all()
    tasks = challenge.tasks
    
    for comp in competitors:
        manual_points_dict = {}
        if comp.manual_points:
            if isinstance(comp.manual_points, dict):
                manual_points_dict = comp.manual_points
            elif isinstance(comp.manual_points, str):
                try:
                    import json
                    manual_points_dict = json.loads(comp.manual_points)
                except Exception:
                    manual_points_dict = {}
        
        for task in tasks:
            pts = manual_points_dict.get(str(task.id))
            if pts is None:
                return jsonify({
                    "error": f"Cannot finalize. Competitor '{comp.username}' (ID: {comp.id}) is missing manual points for task '{task.title}' (ID: {task.id}).",
                    "code": "ERR_MISSING_MANUAL_POINTS"
                }), 400
                
    # Read reveal options
    data = request.get_json() or {}
    challenge.reveal_public_scores = bool(data.get("reveal_public_scores", True))
    challenge.reveal_private_scores = bool(data.get("reveal_private_scores", True))
    challenge.reveal_points = bool(data.get("reveal_points", True))
    
    challenge.scores_finalized = True
    db.session.commit()
    
    from cache_utils import invalidate_challenge_cache, invalidate_leaderboard_cache
    invalidate_challenge_cache(challenge_id)
    invalidate_leaderboard_cache(challenge_id)
    
    return jsonify({
        "message": "Competition finalized! Competitor identities and private scores are now fully revealed to everyone.",
        "challenge": challenge.to_dict()
    })


@challenges_bp.route('/<int:challenge_id>/archive', methods=['POST'])
@role_required(['admin', 'jury'])
def archive_challenge(challenge_id):
    challenge = db.get_or_404(Challenge, challenge_id)
    challenge.is_archived = not challenge.is_archived
    db.session.commit()
    
    from cache_utils import invalidate_challenge_cache
    invalidate_challenge_cache(challenge_id)
    
    action = "archived" if challenge.is_archived else "restored"
    return jsonify({
        "message": f"Competition has been successfully {action}!",
        "challenge": challenge.to_dict()
    })


@challenges_bp.route('/<int:challenge_id>/stages', methods=['POST'])
@role_required(['admin', 'jury'])
def create_stage(challenge_id):
    challenge = db.get_or_404(Challenge, challenge_id)
    data = request.json or {}
    
    title = data.get("title")
    stage_number = data.get("stage_number")
    start_time_str = data.get("start_time")
    end_time_str = data.get("end_time")
    
    if not title or not start_time_str or not end_time_str:
        return jsonify({
            "error": "Missing title, start_time or end_time.",
            "code": "ERR_MISSING_STAGE_FIELDS"
        }), 400
        
    start_time = parse_datetime(start_time_str)
    end_time = parse_datetime(end_time_str)
    
    if not start_time or not end_time:
        return jsonify({
            "error": "Invalid date format.",
            "code": "ERR_INVALID_DATE_FORMAT"
        }), 400
        
    if not stage_number:
        # Auto-increment stage number
        from models import Stage
        max_num = db.session.query(db.func.max(Stage.stage_number)).filter_by(challenge_id=challenge_id).scalar() or 0
        stage_number = max_num + 1
        
    from models import Stage
    stage = Stage(
        challenge_id=challenge_id,
        stage_number=stage_number,
        title=title,
        start_time=start_time,
        end_time=end_time
    )
    
    db.session.add(stage)
    db.session.commit()
    
    from cache_utils import invalidate_challenge_cache
    invalidate_challenge_cache(challenge_id)
    
    return jsonify(stage.to_dict()), 201


@challenges_bp.route('/<int:challenge_id>/stages/<int:stage_id>', methods=['PUT'])
@role_required(['admin', 'jury'])
def update_stage(challenge_id, stage_id):
    challenge = db.get_or_404(Challenge, challenge_id)
    from models import Stage
    stage = Stage.query.filter_by(id=stage_id, challenge_id=challenge_id).first_or_404()
    data = request.json or {}
    
    if "title" in data:
        stage.title = data["title"]
    if "stage_number" in data:
        stage.stage_number = data["stage_number"]
    if "start_time" in data:
        t = parse_datetime(data["start_time"])
        if t:
            stage.start_time = t
    if "end_time" in data:
        t = parse_datetime(data["end_time"])
        if t:
            stage.end_time = t
            
    db.session.commit()
    
    from cache_utils import invalidate_challenge_cache
    invalidate_challenge_cache(challenge_id)
    
    return jsonify(stage.to_dict())


@challenges_bp.route('/<int:challenge_id>/stages/<int:stage_id>', methods=['DELETE'])
@role_required(['admin', 'jury'])
def delete_stage(challenge_id, stage_id):
    challenge = db.get_or_404(Challenge, challenge_id)
    from models import Stage
    stage = Stage.query.filter_by(id=stage_id, challenge_id=challenge_id).first_or_404()
    
    # Nullify stage_id for tasks belonging to this stage
    from models import Task
    tasks = Task.query.filter_by(stage_id=stage_id).all()
    for t in tasks:
        t.stage_id = None
        
    db.session.delete(stage)
    db.session.commit()
    
    from cache_utils import invalidate_challenge_cache
    invalidate_challenge_cache(challenge_id)
    
    return jsonify({"message": f"Stage '{stage.title}' has been deleted."})


@challenges_bp.route('/<int:challenge_id>/stages/<int:stage_id>/finalize', methods=['POST'])
@role_required(['jury'])
def finalize_stage(challenge_id, stage_id):
    challenge = db.get_or_404(Challenge, challenge_id)
    from models import Stage
    stage = Stage.query.filter_by(id=stage_id, challenge_id=challenge_id).first_or_404()
    data = request.json or {}
    
    finalize_type = data.get("finalize_type", "visible")
    if finalize_type not in ("visible", "internal"):
        return jsonify({
            "error": "finalize_type must be either 'visible' or 'internal'.",
            "code": "ERR_INVALID_FINALIZE_TYPE"
        }), 400
        
    # Check if manual points are entered for all competitors for all tasks in this stage
    competitors = User.query.filter_by(role='competitor', challenge_id=challenge_id).all()
    from models import Task
    stage_tasks = Task.query.filter_by(stage_id=stage_id).all()
    
    for comp in competitors:
        manual_points_dict = {}
        if comp.manual_points:
            if isinstance(comp.manual_points, dict):
                manual_points_dict = comp.manual_points
            elif isinstance(comp.manual_points, str):
                try:
                    manual_points_dict = json.loads(comp.manual_points)
                except Exception:
                    manual_points_dict = {}
                    
        for task in stage_tasks:
            pts = manual_points_dict.get(str(task.id))
            if pts is None:
                name_str = comp.username
                if comp.name:
                    try:
                        from auth_utils import decrypt_field
                        dec_name = decrypt_field(comp.name)
                        dec_surname = decrypt_field(comp.surname)
                        name_str = f"{dec_name} {dec_surname}"
                    except Exception:
                        pass
                return jsonify({
                    "error": f"Cannot finalize. Competitor '{name_str}' is missing manual points for task '{task.title}'.",
                    "code": "ERR_MISSING_MANUAL_POINTS"
                }), 400
                
    stage.is_finalized = True
    stage.finalize_type = finalize_type
    stage.reveal_public = bool(data.get("reveal_public", True))
    stage.reveal_private = bool(data.get("reveal_private", False))
    stage.reveal_points = bool(data.get("reveal_points", False))
    
    db.session.commit()
    
    from cache_utils import invalidate_challenge_cache, invalidate_leaderboard_cache
    invalidate_challenge_cache(challenge_id)
    invalidate_leaderboard_cache(challenge_id)
    
    return jsonify(stage.to_dict())


@challenges_bp.route('/<int:challenge_id>/test-competition', methods=['POST'])
@login_required
@role_required(['admin', 'jury'])
def create_scheduled_test_competition(challenge_id):
    orig = db.get_or_404(Challenge, challenge_id)
    from models import Task
    
    from datetime import timedelta
    now = datetime.utcnow()
    end_time = now + timedelta(hours=2)
    
    test_title = f"Test: {orig.title} (Warm-up)"
    test_desc = f"Practice and test environment for: {orig.title}. Relaxed rules for submission connectivity and model testing."
    
    test_comp = Challenge(
        title=test_title,
        description=test_desc,
        hf_dataset_path=orig.hf_dataset_path,
        hf_dataset_config=orig.hf_dataset_config,
        hf_dataset_split=orig.hf_dataset_split,
        metric_name=orig.metric_name,
        max_eval_requests=100,
        ram_limit_mb=max(orig.ram_limit_mb, 16384),
        time_limit_sec=max(orig.time_limit_sec, 600),
        gpu_required=False,
        is_active=True,
        start_time=now,
        end_time=end_time,
        double_blind=False,
        timezone=orig.timezone
    )
    db.session.add(test_comp)
    db.session.commit()
    
    test_eval_code = """import json
import sys
try:
    import submission_runner
except Exception as e:
    with open("eval_results.json", "w") as f:
        json.dump({"status": "error", "error": "Failed to compile or import student code."}, f)
    sys.exit(1)

try:
    if hasattr(submission_runner, 'predict'):
        func = submission_runner.predict
    elif hasattr(submission_runner, 'predict_gpu'):
        func = submission_runner.predict_gpu
    else:
        raise AttributeError("Your notebook must define a function (e.g. 'predict' or 'predict_gpu').")
    
    res = func(["Test sentence"])
    with open("eval_results.json", "w") as f:
        json.dump({
            "status": "success",
            "public_score": 1.0,
            "private_score": 1.0,
            "metrics_payload_public": {"accuracy": 1.0},
            "metrics_payload_private": {"accuracy": 1.0},
            "execution_time_ms": 1
        }, f)
except Exception as e:
    with open("eval_results.json", "w") as f:
        json.dump({"status": "error", "error": str(e)}, f)
"""

    test_task = Task(
        challenge_id=test_comp.id,
        title="Warm-up Test Task",
        description="This is a simple warm-up test task. Write a Python function `predict(inputs)` or `predict_gpu(inputs)` that takes a list and returns predictions.",
        custom_eval_code=test_eval_code,
        files="[]"
    )
    db.session.add(test_task)
    db.session.commit()
    
    from cache_utils import invalidate_challenge_cache
    invalidate_challenge_cache(orig.id)
    
    return jsonify({
        "message": "Scheduled test competition created successfully!",
        "test_competition": test_comp.to_dict()
    }), 201


@challenges_bp.route('/<int:challenge_id>/export-results', methods=['GET'])
@login_required
@role_required(['admin', 'jury'])
def export_results(challenge_id):
    import csv
    import io
    from flask import Response
    from routes.leaderboard import build_and_cache_leaderboard
    from models import AuditLog, Task
    
    challenge = db.get_or_404(Challenge, challenge_id)
    
    # Get leaderboard entries
    leaderboard = build_and_cache_leaderboard(challenge_id) or []
    
    # Get all tasks for this challenge
    tasks = challenge.tasks
    
    # Get audit logs for these tasks
    task_ids = [t.id for t in tasks]
    if task_ids:
        audit_logs = AuditLog.query.filter(AuditLog.task_id.in_(task_ids)).order_by(AuditLog.timestamp.asc()).all()
    else:
        audit_logs = []
        
    output = io.StringIO()
    writer = csv.writer(output)
    
    # 1. Write Header for Results
    header = [
        "Rank", "Username", "Alias ID", "Real Name", "Email", "School", "City", "Grade", 
        "Has Submitted", "Total Points", "Aggregated Public Score", "Aggregated Private Score"
    ]
    for task in tasks:
        header.extend([
            f"Task '{task.title}' Public Score",
            f"Task '{task.title}' Private Score",
            f"Task '{task.title}' Manual Points"
        ])
    writer.writerow(header)
    
    # 2. Write Competitor Rows
    for entry in leaderboard:
        user_data = entry["user"]
        real_name = f"{user_data.get('name') or ''} {user_data.get('surname') or ''}".strip()
        
        # Parse manual points dict safely
        manual_pts = user_data.get("manual_points") or {}
        
        row = [
            entry["rank"],
            user_data.get("username"),
            user_data.get("alias_id"),
            real_name,
            user_data.get("email"),
            user_data.get("school"),
            user_data.get("city"),
            user_data.get("grade"),
            "Yes" if entry["has_submitted"] else "No",
            entry["total_points"],
            entry["public_score"] if entry["public_score"] is not None else "N/A",
            entry["private_score"] if entry["private_score"] is not None else "N/A"
        ]
        
        for task in tasks:
            task_score = entry["task_scores"].get(str(task.id)) or {}
            pub = task_score.get("public_score")
            priv = task_score.get("private_score")
            m_pts = manual_pts.get(str(task.id), 0)
            
            row.extend([
                pub if pub is not None else "N/A",
                priv if priv is not None else "N/A",
                m_pts
            ])
            
        writer.writerow(row)
        
    # 3. Add space and section for Audit Logs
    writer.writerow([])
    writer.writerow(["--- SCORE CORRECTION AUDIT LOG ---"])
    writer.writerow(["Timestamp (UTC)", "Admin", "Target Student", "Task", "Old Score", "New Score", "Reason"])
    
    for log in audit_logs:
        admin_user = log.admin.username if log.admin else f"User ID {log.admin_id}"
        target_user = log.target_user.username if log.target_user else f"User ID {log.target_user_id}"
        task_title = log.task.title if log.task else f"Task ID {log.task_id}"
        
        writer.writerow([
            log.timestamp.isoformat(),
            admin_user,
            target_user,
            task_title,
            log.old_score if log.old_score is not None else "None",
            log.new_score if log.new_score is not None else "None",
            log.reason
        ])
        
    response = Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename=challenge_{challenge_id}_export.csv"}
    )
    return response
