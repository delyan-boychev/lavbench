import json
from datetime import datetime
from flask import Blueprint, request, jsonify
from models import db, Challenge, Submission, User
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
        
    try:
        notebook_content = file.read().decode('utf-8')
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
        
    if user_role == 'competitor':
        now = datetime.utcnow()
        if challenge.start_time and now < challenge.start_time:
            return jsonify({"error": "This competition has not started yet."}), 400
        if challenge.end_time and now > challenge.end_time:
            return jsonify({"error": "This competition has ended and no longer accepts submissions."}), 400
        
    data = request.json or {}
    selected_cells = data.get("selected_cells")
    
    if not selected_cells or not isinstance(selected_cells, list):
        return jsonify({"error": "selected_cells list is required."}), 400
        
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
        
    return jsonify([s.to_dict(view_role=user_role, current_user_id=user_id) for s in submissions])

@submissions_bp.route('/submissions/<int:submission_id>/select-final', methods=['POST'])
@login_required
def select_final_submission(submission_id):
    user_id = request.user["user_id"]
    user_role = request.user["role"]
    
    submission = Submission.query.get_or_404(submission_id)
    
    # Only competitor owner or admin/jury can set it
    if user_role == 'competitor' and submission.user_id != user_id:
        return jsonify({"error": "Access denied. You do not own this submission."}), 403
        
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

