from flask import Blueprint, request, jsonify
import json
from datetime import datetime
from models import db, Challenge, Submission, User, decrypt_field, Task
from auth_utils import login_required, role_required

leaderboard_bp = Blueprint('leaderboard', __name__)

@leaderboard_bp.route('/challenges/<int:challenge_id>/leaderboard', methods=['GET'])
@login_required
def get_leaderboard(challenge_id):
    challenge = Challenge.query.get_or_404(challenge_id)
    user_role = request.user["role"]
    current_user_id = request.user["user_id"]
    
    # Restrict competitors to their registered challenge
    if user_role == 'competitor':
        user = User.query.get(current_user_id)
        if not user or user.challenge_id != challenge_id:
            return jsonify({"error": "Access denied. You are not registered for this competition."}), 403
            
    is_mse = (challenge.metric_name or '').lower() in ('mse', 'loss', 'error')
    challenge_finalized = challenge.scores_finalized
    
    # Check if competitor needs to see frozen leaderboard
    is_frozen_view = False
    if user_role == 'competitor' and challenge.freeze_time and datetime.utcnow() >= challenge.freeze_time and not challenge.scores_finalized:
        is_frozen_view = True
        
    from cache_utils import get_cached, set_cached
    cache_key = f"leaderboard:raw:{challenge_id}:{'frozen' if is_frozen_view else 'unfrozen'}"
    is_admin_or_jury = (user_role in ('admin', 'jury'))
    cached_entries = None if is_admin_or_jury else get_cached(cache_key)
    
    # We always need the tasks list to map over and return/calculate scores
    tasks = Task.query.filter_by(challenge_id=challenge_id).order_by(Task.id.asc()).all()
    
    if cached_entries is None:
        # Fetch completed submissions
        all_completed = Submission.query.filter_by(
            challenge_id=challenge_id,
            status='completed'
        ).all()
        
        if is_frozen_view:
            all_completed = [s for s in all_completed if s.created_at < challenge.freeze_time]
            
        competitors = User.query.filter_by(role='competitor', challenge_id=challenge_id).all()
        leaderboard_entries = []
        
        for comp in competitors:
            # Group submissions by task for this user
            task_scores = {}
            has_submitted = False
            
            for task in tasks:
                user_subs_for_task = [s for s in all_completed if s.user_id == comp.id and s.task_id == task.id]
                
                # Check for final selection in this task
                final_sub = next((s for s in user_subs_for_task if s.is_final_selection), None)
                chosen_sub = None
                
                if final_sub:
                    # check if there is a late submission for this task
                    has_late_sub = False
                    if challenge.end_time:
                        has_late_sub = any(s.executed_at and s.executed_at > challenge.end_time for s in user_subs_for_task)
                    if not has_late_sub:
                        chosen_sub = final_sub
                        
                if not chosen_sub and user_subs_for_task:
                    # Find best submission by public score for this task
                    best_sub = None
                    for s in user_subs_for_task:
                        if s.public_score is None:
                            continue
                        if best_sub is None:
                            best_sub = s
                        else:
                            if is_mse:
                                if s.public_score < best_sub.public_score:
                                    best_sub = s
                            else:
                                if s.public_score > best_sub.public_score:
                                    best_sub = s
                    chosen_sub = best_sub
                    
                if chosen_sub:
                    has_submitted = True
                    task_scores[str(task.id)] = {
                        "public_score": chosen_sub.public_score,
                        "private_score": chosen_sub.private_score,
                        "submission_id": chosen_sub.id
                    }
                else:
                    task_scores[str(task.id)] = {
                        "public_score": None,
                        "private_score": None,
                        "submission_id": None
                    }
            
            # Compute aggregates
            pub_scores_list = [v["public_score"] for v in task_scores.values() if v["public_score"] is not None]
            priv_scores_list = [v["private_score"] for v in task_scores.values() if v["private_score"] is not None]
            
            # Sum of tasks (penalizing missing ones with 0 or 999 for MSE)
            if pub_scores_list:
                tot_pub = 0.0
                for task in tasks:
                    sc = task_scores[str(task.id)]["public_score"]
                    if sc is not None:
                        tot_pub += sc
                    else:
                        tot_pub += 999.0 if is_mse else 0.0
                aggregated_public = tot_pub
            else:
                aggregated_public = None
                
            if priv_scores_list:
                tot_priv = 0.0
                for task in tasks:
                    sc = task_scores[str(task.id)]["private_score"]
                    if sc is not None:
                        tot_priv += sc
                    else:
                        tot_priv += 999.0 if is_mse else 0.0
                aggregated_private = tot_priv
            else:
                aggregated_private = None
                
            # Safely parse manual_points JSON
            manual_points_dict = {}
            if comp.manual_points:
                if isinstance(comp.manual_points, dict):
                    manual_points_dict = comp.manual_points
                elif isinstance(comp.manual_points, str):
                    try:
                        manual_points_dict = json.loads(comp.manual_points)
                    except Exception:
                        manual_points_dict = {}
                        
            # Manual points sum
            total_points = sum(manual_points_dict.get(str(t.id), 0) for t in tasks)
            
            entry_dict = {
                "user": comp.to_dict(view_role='admin', scores_finalized=False, current_user_id=None),
                "task_scores": task_scores,
                "public_score": aggregated_public,
                "private_score": aggregated_private,
                "total_points": total_points,
                "has_submitted": has_submitted
            }
            leaderboard_entries.append(entry_dict)
            
        # --- Sorting ---
        from functools import cmp_to_key
        def compare_entries(a, b):
            if challenge_finalized:
                # Sort by manual points sum descending
                pa = a["total_points"]
                pb = b["total_points"]
                if pa != pb:
                    return -1 if pa > pb else 1
            else:
                # When not finalized:
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
                if score_a is not None and score_b is not None and score_a != score_b:
                    if is_mse:
                        return -1 if score_a < score_b else 1
                    else:
                        return -1 if score_a > score_b else 1
                        
            # Final fallback to name for stable sorting
            name_a = f"{a['user'].get('name') or ''} {a['user'].get('surname') or ''}".strip().lower() or a['user'].get('username', '').lower()
            name_b = f"{b['user'].get('name') or ''} {b['user'].get('surname') or ''}".strip().lower() or b['user'].get('username', '').lower()
            if name_a != name_b:
                return -1 if name_a < name_b else 1
            return 0
            
        sorted_entries = sorted(leaderboard_entries, key=cmp_to_key(compare_entries))
        
        cached_entries = []
        if challenge_finalized:
            current_rank = 1
            for i, entry_dict in enumerate(sorted_entries):
                if i > 0 and entry_dict["total_points"] != sorted_entries[i-1]["total_points"]:
                    current_rank = i + 1
                entry_dict["rank"] = current_rank
                cached_entries.append(entry_dict)
        else:
            for rank, entry_dict in enumerate(sorted_entries, 1):
                entry_dict["rank"] = rank
                cached_entries.append(entry_dict)
                
        set_cached(cache_key, cached_entries, timeout=300)
        
    # --- Post-processing: Mask demographics and visibility configurations ---
    has_started = False
    if challenge.start_time:
        has_started = (datetime.utcnow() >= challenge.start_time)
        
    reveal_pub = challenge.reveal_public_scores
    reveal_priv = challenge.reveal_private_scores
    reveal_pts = challenge.reveal_points
    
    post_processed_leaderboard = []
    for entry in cached_entries:
        entry_copy = dict(entry)
        is_admin_or_jury = (user_role in ('admin', 'jury'))
        
        # Hide scores from competitors based on settings
        if not is_admin_or_jury:
            if not challenge_finalized:
                entry_copy["private_score"] = None
                if "task_scores" in entry_copy:
                    task_scores_copy = {}
                    for tid, s_dict in entry_copy["task_scores"].items():
                        s_copy = dict(s_dict)
                        s_copy["private_score"] = None
                        task_scores_copy[tid] = s_copy
                    entry_copy["task_scores"] = task_scores_copy
            else:
                if not reveal_pub:
                    entry_copy["public_score"] = None
                if not reveal_priv:
                    entry_copy["private_score"] = None
                
                if "task_scores" in entry_copy:
                    task_scores_copy = {}
                    for tid, s_dict in entry_copy["task_scores"].items():
                        s_copy = dict(s_dict)
                        if not reveal_pub:
                            s_copy["public_score"] = None
                        if not reveal_priv:
                            s_copy["private_score"] = None
                        task_scores_copy[tid] = s_copy
                    entry_copy["task_scores"] = task_scores_copy
                    
                if not reveal_pts:
                    entry_copy["total_points"] = None
                    if "user" in entry_copy and "manual_points" in entry_copy["user"]:
                        user_copy = dict(entry_copy["user"])
                        user_copy["manual_points"] = {}
                        entry_copy["user"] = user_copy
                        
        comp_user = entry_copy["user"]
        comp_user_id = comp_user["id"]
        
        is_self = (current_user_id is not None and current_user_id == comp_user_id)
        if challenge.double_blind:
            show_details = is_admin_or_jury or (not has_started) or challenge_finalized or is_self
        else:
            show_details = True
            
        is_anonymous = comp_user.get("is_anonymous", False)
        if is_anonymous and user_role == 'competitor' and not is_self:
            show_details = False
            
        if not show_details:
            entry_copy["user"] = {
                "id": comp_user_id,
                "alias_id": comp_user.get("alias_id"),
                "role": comp_user.get("role"),
                "challenge_id": comp_user.get("challenge_id"),
                "is_anonymous": is_anonymous,
                "manual_points": comp_user.get("manual_points", {}) if (is_admin_or_jury or (challenge_finalized and reveal_pts)) else {}
            }
        post_processed_leaderboard.append(entry_copy)
        
    return jsonify({
        "challenge_title": challenge.title,
        "metric_name": challenge.metric_name,
        "is_finalized": challenge.scores_finalized,
        "reveal_public_scores": challenge.reveal_public_scores,
        "reveal_private_scores": challenge.reveal_private_scores,
        "reveal_points": challenge.reveal_points,
        "tasks": [t.to_dict() for t in tasks],
        "leaderboard": post_processed_leaderboard
    })


@leaderboard_bp.route('/challenges/<int:challenge_id>/manual-points', methods=['POST'])
@login_required
@role_required(['admin', 'jury'])
def save_manual_points(challenge_id):
    challenge = Challenge.query.get_or_404(challenge_id)
    
    data = request.get_json() or {}
    user_id = data.get("user_id")
    points_dict = data.get("points")
    
    if not user_id or not isinstance(points_dict, dict):
        return jsonify({"error": "Missing user_id or points dictionary."}), 400
        
    user = User.query.filter_by(id=user_id, challenge_id=challenge_id).first()
    if not user:
        return jsonify({"error": "User not found or not registered in this challenge."}), 404
        
    # Validate points (0-100 integers)
    validated_points = {}
    tasks = {t.id for t in challenge.tasks}
    for k, v in points_dict.items():
        try:
            task_id = int(k)
        except ValueError:
            return jsonify({"error": f"Invalid task ID: {k}"}), 400
            
        if task_id not in tasks:
            return jsonify({"error": f"Task ID {task_id} does not belong to this challenge."}), 400
            
        try:
            pts = int(v)
        except (ValueError, TypeError):
            return jsonify({"error": f"Points for task {task_id} must be an integer."}), 400
            
        if not (0 <= pts <= 100):
            return jsonify({"error": f"Points for task {task_id} must be between 0 and 100."}), 400
            
        validated_points[str(task_id)] = pts
        
    current_points = {}
    if user.manual_points:
        if isinstance(user.manual_points, dict):
            current_points = user.manual_points
        elif isinstance(user.manual_points, str):
            try:
                current_points = json.loads(user.manual_points)
            except Exception:
                current_points = {}
                
    current_points.update(validated_points)
    user.manual_points = current_points
    db.session.commit()
    
    # Invalidate cache
    from cache_utils import invalidate_leaderboard_cache
    invalidate_leaderboard_cache(challenge_id)
    
    return jsonify({
        "message": "Manual points saved successfully.",
        "user_id": user.id,
        "manual_points": user.manual_points
    })

