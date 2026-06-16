import csv
import io
from datetime import datetime
from models import db, User, Submission, AuditLog, decrypt_field
from services.submission_service import get_best_submission
from services.leaderboard_service import build_and_cache_leaderboard

def generate_scores_csv(challenge):
    tasks = challenge.tasks
    competitors = User.query.filter_by(role='competitor', challenge_id=challenge.id).all()
    
    all_subs = Submission.query.filter(
        Submission.challenge_id == challenge.id,
        Submission.status == 'completed'
    ).all()
    
    sub_by_user_task = {}
    for s in all_subs:
        key = (s.user_id, s.task_id)
        sub_by_user_task.setdefault(key, []).append(s)
    
    competitor_data = []
    for comp in competitors:
        task_scores = {}
        total_score = 0.0
        for task in tasks:
            subs = sub_by_user_task.get((comp.id, task.id), [])
            best_sub = get_best_submission(task, subs, challenge)
            score = 0.0
            if best_sub:
                score = best_sub.private_score if best_sub.private_score is not None else (best_sub.public_score or 0.0)
            
            task_scores[task.id] = score
            total_score += score
            
        competitor_data.append({
            "competitor": comp,
            "task_scores": task_scores,
            "total_score": total_score
        })
        
    competitor_data = sorted(competitor_data, key=lambda x: x["total_score"], reverse=True)
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    header = ["Rank", "Alias ID", "Name", "Surname", "Username", "Email", "School", "City", "Grade"]
    for task in tasks:
        header.append(f"Task: {task.title}")
    header.append("Total Score")
    writer.writerow(header)
    
    for rank, item in enumerate(competitor_data, 1):
        comp = item["competitor"]
        row = [
            rank,
            comp.alias_id,
            decrypt_field(comp.name) or "—",
            decrypt_field(comp.surname) or "—",
            comp.username,
            comp.email or "—",
            decrypt_field(comp.school) or "—",
            decrypt_field(comp.city) or "—",
            decrypt_field(comp.grade) or "—",
        ]
        for task in tasks:
            row.append(f"{item['task_scores'][task.id]:.4f}")
        row.append(f"{item['total_score']:.4f}")
        writer.writerow(row)
        
    return output.getvalue()

def generate_exported_results_csv(challenge):
    leaderboard = build_and_cache_leaderboard(challenge.id) or []
    tasks = challenge.tasks
    
    task_ids = [t.id for t in tasks]
    if task_ids:
        audit_logs = AuditLog.query.filter(AuditLog.task_id.in_(task_ids)).order_by(AuditLog.timestamp.asc()).all()
    else:
        audit_logs = []
        
    output = io.StringIO()
    writer = csv.writer(output)
    
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
    
    for entry in leaderboard:
        user_data = entry["user"]
        real_name = f"{user_data.get('name') or ''} {user_data.get('surname') or ''}".strip()
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
        
    return output.getvalue()
