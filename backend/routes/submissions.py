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
        user = User.query.get(user_id)
        if not user or user.challenge_id != challenge_id:
            return jsonify({"error": "Access denied. You are not registered for this competition."}), 403
            
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded."}), 400
    file = request.files['file']
    if not file.filename.endswith('.ipynb'):
        return jsonify({"error": "Only Jupyter Notebook (.ipynb) files are supported."}), 400
        
    # Enforce strict 5MB file size limit to prevent memory exhaustion
    limit = 5 * 1024 * 1024
    content = file.read(limit + 1)
    if len(content) > limit:
        return jsonify({"error": "File size exceeds the 5MB limit."}), 413
        
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
        return jsonify({"error": f"Failed to parse notebook: {str(e)}"}), 400


@submissions_bp.route('/challenges/<int:challenge_id>/submit', methods=['POST'])
@login_required
def submit_code(challenge_id):
    user_id = request.user["user_id"]
    user_role = request.user["role"]
    
    # Restrict competitors to their registered challenge
    if user_role == 'competitor':
        user = User.query.get(user_id)
        if not user or user.challenge_id != challenge_id:
            return jsonify({"error": "Access denied. You are not registered for this competition."}), 403
            
    challenge = Challenge.query.get_or_404(challenge_id)
    if not challenge.is_active:
        return jsonify({"error": "This challenge is currently inactive."}), 400
    if challenge.is_archived:
        return jsonify({"error": "This challenge has been archived and no longer accepts submissions."}), 400
        
    if challenge.is_frozen:
        return jsonify({"error": "This competition is currently frozen. Submissions are temporarily blocked."}), 403
        
    if challenge.scores_finalized:
        return jsonify({"error": "Submissions are disabled for finalized competitions."}), 403
            
    data = request.json or {}
    task_id = data.get("task_id")
    selected_cells = data.get("selected_cells")
    
    # Retrieve task safely to see if it has a stage
    task = None
    if task_id:
        task = Task.query.get(task_id)
        
    if user_role == 'competitor':
        now = datetime.utcnow()
        from datetime import timedelta
        from config import Config
        grace_seconds = Config.DEADLINE_GRACE_PERIOD_SECONDS
        
        if task and task.stage_id:
            from models import Stage
            stage = Stage.query.get(task.stage_id)
            if stage:
                if now < stage.start_time:
                    return jsonify({"error": f"The stage '{stage.title}' has not started yet."}), 400
                if stage.end_time and now > (stage.end_time + timedelta(seconds=grace_seconds)):
                    return jsonify({"error": f"The deadline for the stage '{stage.title}' has passed."}), 400
        else:
            if challenge.start_time and now < challenge.start_time:
                return jsonify({"error": "This competition has not started yet."}), 400
            if challenge.end_time and now > (challenge.end_time + timedelta(seconds=grace_seconds)):
                return jsonify({"error": "This competition has ended and no longer accepts submissions."}), 400
                
    if not selected_cells or not isinstance(selected_cells, list):
        return jsonify({"error": "selected_cells list is required."}), 400
        
    if not task_id:
        return jsonify({"error": "task_id is required."}), 400
        
    if not task or task.challenge_id != challenge_id:
        return jsonify({"error": "Invalid task_id for this challenge."}), 400
        
    # AST and general rule validation
    from routes.tasks import check_execution_rules
    passed, err_msg = check_execution_rules(task, selected_cells)
    if not passed:
        return jsonify({"error": err_msg}), 400
        
    # Check rate limit (submissions count today)
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    submission_count = Submission.query.filter(
        Submission.user_id == user_id,
        Submission.challenge_id == challenge_id,
        Submission.created_at >= today_start
    ).count()
    
    if submission_count >= challenge.max_eval_requests:
        return jsonify({
            "error": f"Daily limit reached. You can only make {challenge.max_eval_requests} submissions per day."
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
    evaluate_submission.delay(submission.id)
    
    return jsonify({
        "message": "Submission received and queued for execution.",
        "submission_id": submission.id,
        "status": submission.status
    }), 202


@submissions_bp.route('/challenges/<int:challenge_id>/submissions', methods=['GET'])
@login_required
def get_submissions(challenge_id):
    challenge = Challenge.query.get_or_404(challenge_id)
    user_role = request.user["role"]
    user_id = request.user["user_id"]
    
    # Restrict competitors to their registered challenge
    if user_role == 'competitor':
        user = User.query.get(user_id)
        if not user or user.challenge_id != challenge_id:
            return jsonify({"error": "Access denied. You are not registered for this competition."}), 403
            
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
    
    submission = Submission.query.get_or_404(submission_id)
    
    if user_role == 'competitor' and submission.user_id != user_id:
        return jsonify({"error": "Access denied. You can only view your own submissions."}), 403
        
    return jsonify(submission.to_dict(view_role=user_role, current_user_id=user_id))

@submissions_bp.route('/submissions/<int:submission_id>/select-final', methods=['POST'])
@login_required
def select_final_submission(submission_id):
    user_id = request.user["user_id"]
    user_role = request.user["role"]
    
    submission = Submission.query.get_or_404(submission_id)
    
    # Only competitor owner or admin/jury can set it
    if user_role == 'competitor' and submission.user_id != user_id:
        return jsonify({"error": "Access denied. You do not own this submission."}), 403
        
    # Enforce stage select window for competitors
    if user_role == 'competitor':
        challenge = Challenge.query.get(submission.challenge_id)
        if challenge and challenge.scores_finalized:
            return jsonify({"error": "Cannot change final selection for a finalized competition."}), 403
            
        task = Task.query.get(submission.task_id)
        if task and task.stage_id:
            from models import Stage
            stage = Stage.query.get(task.stage_id)
            if stage:
                now = datetime.utcnow()
                if submission.created_at > stage.end_time:
                    return jsonify({"error": "Cannot select a submission created after the stage deadline."}), 400
                    
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
                    return jsonify({"error": "The final selection window for this stage has closed."}), 400
                    
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

