from flask import Blueprint, request, jsonify
from datetime import datetime
from models import db, Challenge, Submission, User, decrypt_field
from auth_utils import login_required

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
    
    # Check if competitor needs to see frozen leaderboard
    is_frozen_view = False
    if user_role == 'competitor' and challenge.freeze_time and datetime.utcnow() >= challenge.freeze_time and not challenge.scores_finalized:
        is_frozen_view = True
        
    from cache_utils import get_cached, set_cached
    cache_key = f"leaderboard:raw:{challenge_id}:{'frozen' if is_frozen_view else 'unfrozen'}"
    cached_entries = get_cached(cache_key)
    
    if cached_entries is None:
        all_completed = Submission.query.filter_by(
            challenge_id=challenge_id,
            status='completed'
        ).all()
        
        if is_frozen_view:
            all_completed = [s for s in all_completed if s.created_at < challenge.freeze_time]
            
        final_selections = {s.user_id: s for s in all_completed if s.is_final_selection}
        
        user_best = {}
        for sub in all_completed:
            uid = sub.user_id
            
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
                current_best_score = user_best[uid].public_score
                if is_mse:
                    if score < current_best_score:
                        user_best[uid] = sub
                else:
                    if score > current_best_score:
                        user_best[uid] = sub
                        
        # Include all competitors, even those with no submissions
        competitors = User.query.filter_by(role='competitor', challenge_id=challenge_id).all()
        leaderboard_entries = []
        
        for comp in competitors:
            sub = user_best.get(comp.id)
            if sub:
                entry_dict = sub.to_dict(view_role='admin', current_user_id=None)
                entry_dict["has_submitted"] = True
            else:
                entry_dict = {
                    "id": None,
                    "challenge_id": challenge_id,
                    "task_id": None,
                    "task_title": None,
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
                    "user": comp.to_dict(view_role='admin', scores_finalized=False, current_user_id=None),
                    "metrics_payload_public": {},
                    "metrics_payload_private": {},
                    "final_weighted_score_public": None,
                    "final_weighted_score_private": None,
                    "is_final_selection": False,
                    "is_disqualified": False,
                    "celery_task_id": None,
                    "plagiarism_score": None,
                    "llm_probability": None,
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
                if is_mse:
                    return -1 if score_a < score_b else 1
                else:
                    return -1 if score_a > score_b else 1
                    
            ta = a.get("execution_time_ms")
            tb = b.get("execution_time_ms")
            if ta is not None and tb is not None and ta != tb:
                return -1 if ta < tb else 1
                
            ca = a["created_at"] or ""
            cb = b["created_at"] or ""
            if ca != cb:
                return -1 if ca < cb else 1
            return 0

        sorted_entries = sorted(leaderboard_entries, key=cmp_to_key(compare_entries))
        
        cached_entries = []
        for rank, entry_dict in enumerate(sorted_entries, 1):
            entry_dict["rank"] = rank
            cached_entries.append(entry_dict)
            
        set_cached(cache_key, cached_entries, timeout=300)
        
    # --- Post-processing: Mask demographics for competitors ---
    has_started = False
    if challenge.start_time:
        has_started = (datetime.utcnow() >= challenge.start_time)
    challenge_finalized = challenge.scores_finalized
    
    post_processed_leaderboard = []
    for entry in cached_entries:
        entry_copy = dict(entry)
        comp_user = entry_copy["user"]
        comp_user_id = comp_user["id"]
        
        is_self = (current_user_id is not None and current_user_id == comp_user_id)
        show_details = (user_role == 'admin') or (not has_started) or challenge_finalized or is_self
        
        if not show_details:
            entry_copy["user"] = {
                "id": comp_user_id,
                "alias_id": comp_user.get("alias_id"),
                "role": comp_user.get("role"),
                "challenge_id": comp_user.get("challenge_id")
            }
        post_processed_leaderboard.append(entry_copy)
        
    return jsonify({
        "challenge_title": challenge.title,
        "metric_name": challenge.metric_name,
        "is_finalized": challenge.scores_finalized,
        "leaderboard": post_processed_leaderboard
    })

