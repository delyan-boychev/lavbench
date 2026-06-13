from flask import Blueprint, request, jsonify
import json
from datetime import datetime
from models import db, Challenge, Submission, User, decrypt_field, Task
from auth_utils import login_required, role_required

leaderboard_bp = Blueprint('leaderboard', __name__)

def build_and_cache_leaderboard(challenge_id, is_frozen_view=False):
    from cache_utils import set_cached
    challenge = Challenge.query.get(challenge_id)
    if not challenge:
        return None
        
    is_mse = (challenge.metric_name or '').lower() in ('mse', 'loss', 'error')
    challenge_finalized = challenge.scores_finalized
    
    tasks = Task.query.filter_by(challenge_id=challenge_id).order_by(Task.id.asc()).all()
    all_completed = Submission.query.filter_by(
        challenge_id=challenge_id,
        status='completed'
    ).all()
    
    competitors = User.query.filter_by(role='competitor', challenge_id=challenge_id).all()
    leaderboard_entries = []
    
    for comp in competitors:
        task_scores = {}
        has_submitted = False
        
        for task in tasks:
            user_subs_for_task = [s for s in all_completed if s.user_id == comp.id and s.task_id == task.id]
            
            final_sub = next((s for s in user_subs_for_task if s.is_final_selection), None)
            chosen_sub = None
            
            if final_sub:
                has_late_sub = False
                if challenge.end_time:
                    has_late_sub = any(s.executed_at and s.executed_at > challenge.end_time for s in user_subs_for_task)
                if not has_late_sub:
                    chosen_sub = final_sub
                    
            if not chosen_sub and user_subs_for_task:
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
                    "submission_id": chosen_sub.id,
                    "execution_time_ms": chosen_sub.execution_time_ms or 0,
                    "created_at": chosen_sub.created_at
                }
            else:
                task_scores[str(task.id)] = {
                    "public_score": None,
                    "private_score": None,
                    "submission_id": None,
                    "execution_time_ms": 0,
                    "created_at": None
                }
        
        pub_scores_list = [v["public_score"] for v in task_scores.values() if v["public_score"] is not None]
        priv_scores_list = [v["private_score"] for v in task_scores.values() if v["private_score"] is not None]
        
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
            
        manual_points_dict = {}
        if comp.manual_points:
            if isinstance(comp.manual_points, dict):
                manual_points_dict = comp.manual_points
            elif isinstance(comp.manual_points, str):
                try:
                    manual_points_dict = json.loads(comp.manual_points)
                except Exception:
                    manual_points_dict = {}
                    
        total_points = sum(manual_points_dict.get(str(t.id), 0) for t in tasks)
        
        total_exec_time = 0
        sub_dates = []
        for v in task_scores.values():
            if v.get("submission_id") is not None:
                total_exec_time += v.get("execution_time_ms") or 0
                if v.get("created_at"):
                    sub_dates.append(v.get("created_at"))
        
        earliest_sub_date = min(sub_dates) if sub_dates else datetime.max
        
        entry_dict = {
            "user": comp.to_dict(view_role='admin', scores_finalized=False, current_user_id=None),
            "task_scores": task_scores,
            "public_score": aggregated_public,
            "private_score": aggregated_private,
            "total_points": total_points,
            "has_submitted": has_submitted,
            "total_execution_time_ms": total_exec_time,
            "earliest_submission_time": earliest_sub_date
        }
        leaderboard_entries.append(entry_dict)
        
    from functools import cmp_to_key
    def compare_entries(a, b):
        if challenge_finalized:
            pa = a["total_points"]
            pb = b["total_points"]
            if pa != pb:
                return -1 if pa > pb else 1
        else:
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
                    
        eta = a.get("total_execution_time_ms", 0)
        etb = b.get("total_execution_time_ms", 0)
        if eta != etb:
            return -1 if eta < etb else 1
            
        cda = a.get("earliest_submission_time", datetime.max)
        cdb = b.get("earliest_submission_time", datetime.max)
        if cda != cdb:
            return -1 if cda < cdb else 1
            
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
            
    # Convert datetime objects to string for JSON serialization
    for entry in cached_entries:
        if isinstance(entry.get("earliest_submission_time"), datetime):
            entry["earliest_submission_time"] = entry["earliest_submission_time"].isoformat() if entry["earliest_submission_time"] != datetime.max else None
        for ts_score in entry["task_scores"].values():
            if isinstance(ts_score.get("created_at"), datetime):
                ts_score["created_at"] = ts_score["created_at"].isoformat()

    cache_key = f"leaderboard:raw:{challenge_id}:{'frozen' if is_frozen_view else 'unfrozen'}"
    set_cached(cache_key, cached_entries, timeout=300)
    return cached_entries


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
    if user_role == 'competitor' and challenge.is_frozen and not challenge.scores_finalized:
        is_frozen_view = True
        
    from cache_utils import get_cached
    cache_key = f"leaderboard:raw:{challenge_id}:{'frozen' if is_frozen_view else 'unfrozen'}"
    is_admin_or_jury = (user_role in ('admin', 'jury'))
    cached_entries = None if is_admin_or_jury else get_cached(cache_key)
    
    if cached_entries is None:
        cached_entries = build_and_cache_leaderboard(challenge_id, is_frozen_view)
        
    tasks = Task.query.filter_by(challenge_id=challenge_id).order_by(Task.id.asc()).all()
    
    if user_role == 'competitor':
        now = datetime.utcnow()
        from models import Stage
        
        # 1. Filter tasks
        visible_tasks = []
        for t in tasks:
            if not t.stage_id:
                visible_tasks.append(t)
            else:
                stage = Stage.query.get(t.stage_id)
                if stage and now >= stage.start_time:
                    visible_tasks.append(t)
        
        # 2. Filter entries
        post_processed_leaderboard = []
        for entry in cached_entries:
            entry_copy = dict(entry)
            comp_user = entry_copy["user"]
            comp_user_id = comp_user["id"]
            is_self = (current_user_id is not None and current_user_id == comp_user_id)
            
            # Recalculate sums based only on visible task scores for competitors
            filtered_task_scores = {}
            tot_pub = 0.0
            tot_priv = 0.0
            tot_pts = 0
            
            has_pub_sum = False
            has_priv_sum = False
            
            # Parse manual points safely
            manual_points_dict = {}
            if comp_user.get("manual_points"):
                if isinstance(comp_user["manual_points"], dict):
                    manual_points_dict = comp_user["manual_points"]
                elif isinstance(comp_user["manual_points"], str):
                    try:
                        manual_points_dict = json.loads(comp_user["manual_points"])
                    except Exception:
                        manual_points_dict = {}
                        
            for t in visible_tasks:
                tid_str = str(t.id)
                sc_dict = entry.get("task_scores", {}).get(tid_str, {
                    "public_score": None,
                    "private_score": None,
                    "submission_id": None
                })
                
                s_copy = dict(sc_dict)
                stage = Stage.query.get(t.stage_id) if t.stage_id else None
                
                # Determine score visibility for this task
                reveal_task_pub = False
                reveal_task_priv = False
                reveal_task_pts = False
                
                if challenge.scores_finalized:
                    reveal_task_pub = True
                    reveal_task_priv = True
                    reveal_task_pts = True
                elif stage:
                    if stage.is_finalized:
                        if stage.finalize_type == 'visible':
                            reveal_task_pub = stage.reveal_public
                            reveal_task_priv = stage.reveal_private
                            reveal_task_pts = stage.reveal_points
                    else:
                        reveal_task_pub = challenge.reveal_public_scores
                else:
                    reveal_task_pub = challenge.reveal_public_scores
                    
                if is_self:
                    reveal_task_pub = True
                    reveal_task_priv = True
                    reveal_task_pts = True
                    
                if not reveal_task_pub:
                    s_copy["public_score"] = None
                if not reveal_task_priv:
                    s_copy["private_score"] = None
                    
                filtered_task_scores[tid_str] = s_copy
                
                if reveal_task_pub and s_copy["public_score"] is not None:
                    tot_pub += s_copy["public_score"]
                    has_pub_sum = True
                else:
                    tot_pub += 999.0 if is_mse else 0.0
                    
                if reveal_task_priv and s_copy["private_score"] is not None:
                    tot_priv += s_copy["private_score"]
                    has_priv_sum = True
                else:
                    tot_priv += 999.0 if is_mse else 0.0
                    
                if reveal_task_pts:
                    tot_pts += manual_points_dict.get(tid_str, 0)
            
            entry_copy["task_scores"] = filtered_task_scores
            entry_copy["public_score"] = tot_pub if has_pub_sum else None
            entry_copy["private_score"] = tot_priv if has_priv_sum else None
            entry_copy["total_points"] = tot_pts
            
            if challenge.double_blind:
                show_details = challenge.scores_finalized or is_self
            else:
                show_details = True
                
            is_anonymous = comp_user.get("is_anonymous", False)
            if is_anonymous and not is_self:
                show_details = False
                
            if not show_details:
                entry_copy["user"] = {
                    "id": comp_user_id,
                    "alias_id": comp_user.get("alias_id"),
                    "role": comp_user.get("role"),
                    "challenge_id": comp_user.get("challenge_id"),
                    "is_anonymous": is_anonymous,
                    "manual_points": manual_points_dict if is_self else {}
                }
            else:
                user_copy = dict(comp_user)
                user_copy["manual_points"] = manual_points_dict
                entry_copy["user"] = user_copy
                
            post_processed_leaderboard.append(entry_copy)
            
        from functools import cmp_to_key
        def compare_competitor_entries(a, b):
            if challenge.scores_finalized:
                pa = a["total_points"]
                pb = b["total_points"]
                if pa != pb:
                    return -1 if pa > pb else 1
            else:
                score_a = a["public_score"]
                score_b = b["public_score"]
                if score_a is not None and score_b is not None and score_a != score_b:
                    if is_mse:
                        return -1 if score_a < score_b else 1
                    else:
                        return -1 if score_a > score_b else 1
            name_a = (a['user'].get('alias_id') or '').lower()
            name_b = (b['user'].get('alias_id') or '').lower()
            if name_a != name_b:
                return -1 if name_a < name_b else 1
            return 0
            
        sorted_competitor = sorted(post_processed_leaderboard, key=cmp_to_key(compare_competitor_entries))
        
        if challenge.scores_finalized:
            current_rank = 1
            for idx, entry_dict in enumerate(sorted_competitor):
                if idx > 0 and entry_dict["total_points"] != sorted_competitor[idx-1]["total_points"]:
                    current_rank = idx + 1
                entry_dict["rank"] = current_rank
        else:
            current_rank = 1
            for idx, entry_dict in enumerate(sorted_competitor):
                if idx > 0 and entry_dict["public_score"] != sorted_competitor[idx-1]["public_score"]:
                    current_rank = idx + 1
                entry_dict["rank"] = current_rank
                
        post_processed_leaderboard = sorted_competitor
        tasks_list = [t.to_dict() for t in visible_tasks]
    else:
        post_processed_leaderboard = []
        for entry in cached_entries:
            entry_copy = dict(entry)
            
            comp_user = entry_copy["user"]
            comp_user_id = comp_user["id"]
            is_self = (current_user_id is not None and current_user_id == comp_user_id)
            
            if challenge.double_blind:
                show_details = (user_role in ('admin', 'jury')) or (not has_started) or challenge_finalized or is_self
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
                    "manual_points": comp_user.get("manual_points", {}) if (challenge_finalized and reveal_pts) else {}
                }
            post_processed_leaderboard.append(entry_copy)
        tasks_list = [t.to_dict() for t in tasks]
        
    return jsonify({
        "challenge_title": challenge.title,
        "metric_name": challenge.metric_name,
        "is_finalized": challenge.scores_finalized,
        "reveal_public_scores": challenge.reveal_public_scores,
        "reveal_private_scores": challenge.reveal_private_scores,
        "reveal_points": challenge.reveal_points,
        "tasks": tasks_list,
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
    reason = data.get("reason")
    
    if not user_id or not isinstance(points_dict, dict):
        return jsonify({"error": "Missing user_id or points dictionary."}), 400
        
    user = User.query.filter_by(id=user_id, challenge_id=challenge_id).first()
    if not user:
        return jsonify({"error": "User not found or not registered in this challenge."}), 404
        
    if challenge.scores_finalized and not reason:
        return jsonify({"error": "A justification reason is mandatory to modify manual points after the competition is finalized."}), 400
        
    # Validate points (0-100 integers) and completed submissions count
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
            
        # Check completed submissions count
        completed_count = Submission.query.filter_by(
            user_id=user_id,
            task_id=task_id,
            status='completed'
        ).count()
        if completed_count == 0:
            return jsonify({"error": f"Cannot assign manual points. User {user.username} has no completed submissions for task ID {task_id}."}), 400
            
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
                
    # Create audit logs for changed points
    admin_id = request.user["user_id"]
    from models import AuditLog
    for task_id_str, pts in validated_points.items():
        task_id = int(task_id_str)
        old_score = current_points.get(task_id_str)
        if old_score != pts:
            audit_entry = AuditLog(
                admin_id=admin_id,
                target_user_id=user.id,
                task_id=task_id,
                old_score=old_score,
                new_score=pts,
                reason=reason or "Initial scoring before finalization"
            )
            db.session.add(audit_entry)
                
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

