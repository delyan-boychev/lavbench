import os
import json
from datetime import datetime
from flask import Blueprint, request, jsonify
from models import db, Challenge, Submission, User, Task
from auth_utils import login_required
from sse_utils import publish_submissions_update, publish_leaderboard_update


submissions_bp = Blueprint('submissions', __name__)

@submissions_bp.route('/challenges/<int:challenge_id>/parse-notebook', methods=['POST'])
@login_required
def parse_notebook(challenge_id):
    user_id = request.user["user_id"]
    user_role = request.user["role"]
    
    # Restrict competitors to their registered challenge
    if user_role == 'competitor':
        user = db.session.get(User, user_id)
        if not user or user.challenge_id != challenge_id:
            return jsonify({
                "error": "Access denied. You are not registered for this competition.",
                "code": "ERR_NOT_REGISTERED"
            }), 403
            
    if 'file' not in request.files:
        return jsonify({
            "error": "No file uploaded.",
            "code": "ERR_NO_FILE_UPLOADED"
        }), 400
    file = request.files['file']
    if not file.filename.endswith('.ipynb'):
        return jsonify({
            "error": "Only Jupyter Notebook (.ipynb) files are supported.",
            "code": "ERR_INVALID_FILE_TYPE"
        }), 400
        
    # Enforce strict 5MB file size limit to prevent memory exhaustion
    limit = 5 * 1024 * 1024
    content = file.read(limit + 1)
    if len(content) > limit:
        return jsonify({
            "error": "File size exceeds the 5MB limit.",
            "code": "ERR_FILE_TOO_LARGE"
        }), 413
        
    try:
        notebook_content = content.decode('utf-8')
        notebook = json.loads(notebook_content)
        
        cells = []
        for idx, cell in enumerate(notebook.get("cells", [])):
            cell_type = cell.get("cell_type", "code")
            source_lines = cell.get("source", [])
            source = "".join(source_lines) if isinstance(source_lines, list) else source_lines
            
            cells.append({
                "id": idx,
                "type": cell_type,
                "source": source
            })
            
        return jsonify({
            "filename": file.filename,
            "cells": cells
        })
    except Exception as e:
        return jsonify({
            "error": f"Failed to parse notebook: {str(e)}",
            "code": "ERR_PARSING_FAILED"
        }), 400


@submissions_bp.route('/challenges/<int:challenge_id>/submit', methods=['POST'])
@login_required
def submit_code(challenge_id):
    user_id = request.user["user_id"]
    user_role = request.user["role"]
    
    # Restrict competitors to their registered challenge
    if user_role == 'competitor':
        user = db.session.get(User, user_id)
        if not user or user.challenge_id != challenge_id:
            return jsonify({
                "error": "Access denied. You are not registered for this competition.",
                "code": "ERR_NOT_REGISTERED"
            }), 403
            
    challenge = db.get_or_404(Challenge, challenge_id)
    if not challenge.is_active:
        return jsonify({
            "error": "This challenge is currently inactive.",
            "code": "ERR_CHALLENGE_INACTIVE"
        }), 400
    if challenge.is_archived:
        return jsonify({
            "error": "This challenge has been archived and no longer accepts submissions.",
            "code": "ERR_CHALLENGE_ARCHIVED"
        }), 400
        
    if challenge.is_frozen:
        return jsonify({
            "error": "This competition is currently frozen. Submissions are temporarily blocked.",
            "code": "ERR_COMPETITION_FROZEN"
        }), 403
        
    if challenge.scores_finalized:
        return jsonify({
            "error": "Submissions are disabled for finalized competitions.",
            "code": "ERR_COMPETITION_FINALIZED"
        }), 403
            
    data = request.json or {}
    task_id = data.get("task_id")
    selected_cells = data.get("selected_cells")
    
    # Retrieve task safely to see if it has a stage
    task = None
    if task_id:
        task = db.session.get(Task, task_id)
        
    if user_role == 'competitor':
        now = datetime.utcnow()
        from datetime import timedelta
        from config import Config
        grace_seconds = Config.DEADLINE_GRACE_PERIOD_SECONDS
        
        if task and task.stage_id:
            from models import Stage
            stage = db.session.get(Stage, task.stage_id)
            if stage:
                if now < stage.start_time:
                    return jsonify({
                        "error": f"The stage '{stage.title}' has not started yet.",
                        "code": "ERR_STAGE_NOT_STARTED"
                    }), 400
                if stage.end_time and now > (stage.end_time + timedelta(seconds=grace_seconds)):
                    return jsonify({
                        "error": f"The deadline for the stage '{stage.title}' has passed.",
                        "code": "ERR_STAGE_DEADLINE_PASSED"
                    }), 400
        else:
            if challenge.start_time and now < challenge.start_time:
                return jsonify({
                    "error": "This competition has not started yet.",
                    "code": "ERR_COMPETITION_NOT_STARTED"
                }), 400
            if challenge.end_time and now > (challenge.end_time + timedelta(seconds=grace_seconds)):
                return jsonify({
                    "error": "This competition has ended and no longer accepts submissions.",
                    "code": "ERR_COMPETITION_ENDED"
                }), 400
                
    if not selected_cells or not isinstance(selected_cells, list):
        return jsonify({
            "error": "selected_cells list is required.",
            "code": "ERR_MISSING_SELECTED_CELLS"
        }), 400
        
    if not task_id:
        return jsonify({
            "error": "task_id is required.",
            "code": "ERR_MISSING_TASK_ID"
        }), 400
        
    if not task or task.challenge_id != challenge_id:
        return jsonify({
            "error": "Invalid task_id for this challenge.",
            "code": "ERR_INVALID_TASK_ID"
        }), 400
        
    # AST and general rule validation
    from services.submission_service import check_execution_rules
    passed, err_msg = check_execution_rules(task, selected_cells)
    if not passed:
        return jsonify({
            "error": err_msg,
            "code": "ERR_AST_RULE_FAILED"
        }), 400
        
    # Check rate limit (submissions count today)
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    submission_count = Submission.query.filter(
        Submission.user_id == user_id,
        Submission.challenge_id == challenge_id,
        Submission.created_at >= today_start
    ).count()
    
    if submission_count >= challenge.max_eval_requests:
        return jsonify({
            "error": f"Daily limit reached. You can only make {challenge.max_eval_requests} submissions per day.",
            "code": "ERR_DAILY_LIMIT_REACHED"
        }), 429
        
    # Create submission
    submission = Submission(
        user_id=user_id,
        challenge_id=challenge_id,
        task_id=task.id,
        status='queued',
        code_cells=json.dumps(selected_cells)
    )
    db.session.add(submission)
    db.session.commit()
    
    # Trigger Celery Task asynchronously
    from tasks import evaluate_submission
    from services.submission_service import extract_code_from_cells, calculate_submission_priority
    from auth_utils import generate_worker_token

    task_files_list = []
    if task.files:
        try:
            task_files_list = json.loads(task.files)
        except:
            pass

    hf_token = task.get_hf_api_key() or ""
    main_server_url = os.environ.get("MAIN_SERVER_URL", "http://localhost:5001")
    
    time_limit = task.time_limit_sec or challenge.time_limit_sec or 300
    worker_token = generate_worker_token(submission.id, task.id, time_limit + 600)

    gpu_required = False
    if task.gpu_required is not None:
        gpu_required = task.gpu_required
    elif challenge.gpu_required is not None:
        gpu_required = challenge.gpu_required

    metadata = {
        "submission_id": submission.id,
        "task_id": task.id,
        "challenge_id": challenge.id,
        "user_code": "\n\n".join(extract_code_from_cells(selected_cells)),
        "time_limit": time_limit,
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
        "worker_secret_key": worker_token
    }

    priority = calculate_submission_priority(user_id, user_role)
    queue_name = 'gpu_queue' if gpu_required else 'celery'

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


@submissions_bp.route('/challenges/<int:challenge_id>/submissions', methods=['GET'])
@login_required
def get_submissions(challenge_id):
    challenge = db.get_or_404(Challenge, challenge_id)
    user_role = request.user["role"]
    user_id = request.user["user_id"]
    
    # Restrict competitors to their registered challenge
    if user_role == 'competitor':
        user = db.session.get(User, user_id)
        if not user or user.challenge_id != challenge_id:
            return jsonify({
                "error": "Access denied. You are not registered for this competition.",
                "code": "ERR_NOT_REGISTERED"
            }), 403
            
        submissions = Submission.query.filter_by(
            challenge_id=challenge_id, 
            user_id=user_id
        ).order_by(Submission.created_at.desc()).all()
    else:
        submissions = Submission.query.filter_by(
            challenge_id=challenge_id
        ).order_by(Submission.created_at.desc()).all()
        
    return jsonify([s.to_dict_light(view_role=user_role, current_user_id=user_id) for s in submissions])

@submissions_bp.route('/submissions/<int:submission_id>', methods=['GET'])
@login_required
def get_submission_detail(submission_id):
    user_id = request.user["user_id"]
    user_role = request.user["role"]
    
    submission = db.get_or_404(Submission, submission_id)
    
    if user_role == 'competitor' and submission.user_id != user_id:
        return jsonify({
            "error": "Access denied. You can only view your own submissions.",
            "code": "ERR_NOT_OWNER"
        }), 403
        
    return jsonify(submission.to_dict(view_role=user_role, current_user_id=user_id))

@submissions_bp.route('/submissions/<int:submission_id>/select-final', methods=['POST'])
@login_required
def select_final_submission(submission_id):
    user_id = request.user["user_id"]
    user_role = request.user["role"]
    
    submission = db.get_or_404(Submission, submission_id)
    
    # Only competitor owner or admin/jury can set it
    if user_role == 'competitor' and submission.user_id != user_id:
        return jsonify({
            "error": "Access denied. You do not own this submission.",
            "code": "ERR_NOT_OWNER"
        }), 403
        
    # Enforce stage select window for competitors
    if user_role == 'competitor':
        challenge = db.session.get(Challenge, submission.challenge_id)
        if challenge and challenge.scores_finalized:
            return jsonify({
                "error": "Cannot change final selection for a finalized competition.",
                "code": "ERR_COMPETITION_FINALIZED"
            }), 403
            
        task = db.session.get(Task, submission.task_id)
        if task and task.stage_id:
            from models import Stage
            stage = db.session.get(Stage, task.stage_id)
            if stage:
                now = datetime.utcnow()
                if submission.created_at > stage.end_time:
                    return jsonify({
                        "error": "Cannot select a submission created after the stage deadline.",
                        "code": "ERR_SUBMISSION_LATE"
                    }), 400
                    
                from datetime import timedelta
                t_base_select = stage.end_time + timedelta(seconds=300)
                
                # Fetch all pre-deadline submissions for this task
                user_subs = Submission.query.filter(
                    Submission.user_id == user_id,
                    Submission.task_id == submission.task_id,
                    Submission.created_at <= stage.end_time
                ).all()
                
                t_final_select = t_base_select
                for s in user_subs:
                    if s.executed_at:
                        t_select = s.executed_at + timedelta(seconds=300)
                        if t_select > t_final_select:
                            t_final_select = t_select
                            
                if now > t_final_select:
                    return jsonify({
                        "error": "The final selection window for this stage has closed.",
                        "code": "ERR_SELECTION_WINDOW_CLOSED"
                    }), 400
                    
    # Unset is_final_selection for all other submissions by this user for this task
    Submission.query.filter_by(
        user_id=submission.user_id,
        task_id=submission.task_id
    ).update({Submission.is_final_selection: False})
    
    submission.is_final_selection = True
    db.session.commit()
    
    from cache_utils import invalidate_leaderboard_cache
    invalidate_leaderboard_cache(submission.challenge_id)
    
    publish_submissions_update(submission.task_id, submission.user_id)
    publish_leaderboard_update(submission.task_id)
    
    return jsonify({
        "message": "Submission selected as final.",
        "submission": submission.to_dict(view_role=user_role, current_user_id=user_id)
    })

@submissions_bp.route('/submissions/<int:submission_id>/logs/live', methods=['GET'])
@login_required
def stream_submission_logs(submission_id):
    from flask import current_app, Response, stream_with_context
    import redis
    
    user_id = request.user["user_id"]
    user_role = request.user["role"]
    
    submission = db.session.get(Submission, submission_id)
    if not submission:
        return jsonify({"error": "Submission not found.", "code": "ERR_NOT_FOUND"}), 404
        
    if user_role == 'competitor' and submission.user_id != user_id:
        return jsonify({"error": "Access denied.", "code": "ERR_ACCESS_DENIED"}), 403
        
    def event_generator():
        broker_url = current_app.config.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
        r = redis.Redis.from_url(broker_url)
        
        # Yield an initial message to flush headers immediately and establish connection
        yield f"data: {json.dumps({'info': 'connected'})}\n\n"
        
        log_key = f"submission:{submission_id}:logs"
        existing_logs = r.lrange(log_key, 0, -1)
        if existing_logs:
            for log_bin in existing_logs:
                log_line = log_bin.decode("utf-8")
                yield f"data: {json.dumps({'log': log_line})}\n\n"
                
        with current_app.app_context():
            sub = db.session.get(Submission, submission_id)
            if sub and sub.status in ('completed', 'failed'):
                yield f"data: {json.dumps({'status': sub.status})}\n\n"
                return
                
        pubsub = r.pubsub()
        pubsub.subscribe(f"submission_{submission_id}_logs")
        
        try:
            while True:
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=2.0)
                if message:
                    yield f"data: {message['data'].decode('utf-8')}\n\n"
                else:
                    yield ": keep-alive\n\n"
                    
                with current_app.app_context():
                    db.session.expire_all()
                    sub = db.session.get(Submission, submission_id)
                    if sub and sub.status in ('completed', 'failed'):
                        yield f"data: {json.dumps({'status': sub.status})}\n\n"
                        break
        except GeneratorExit:
            try:
                pubsub.unsubscribe()
                pubsub.close()
            except:
                pass
        except Exception as e:
            print(f"SSE logs streaming error: {e}")
            
    headers = {
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
        'Connection': 'keep-alive',
    }
    return Response(stream_with_context(event_generator()), mimetype="text/event-stream", headers=headers)

