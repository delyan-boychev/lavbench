"""Service-layer functions for challenge CRUD, archiving, and export."""

import csv
import io
import json
from datetime import datetime
from models import db, User, Submission, AuditLog, Challenge, Task, Stage, decrypt_field
from services.submission_service import get_best_submission
from services.leaderboard_service import build_and_cache_leaderboard


def generate_scores_csv(challenge):
    """Build a CSV string with per-competitor scores across all tasks in a challenge."""
    tasks = challenge.tasks
    competitors = User.query.filter_by(role="competitor", challenge_id=challenge.id).all()

    all_subs = Submission.query.filter(
        Submission.challenge_id == challenge.id, Submission.status == "completed"
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
                score = (
                    best_sub.private_score
                    if best_sub.private_score is not None
                    else (best_sub.public_score or 0.0)
                )

            task_scores[task.id] = score
            total_score += score

        competitor_data.append(
            {"competitor": comp, "task_scores": task_scores, "total_score": total_score}
        )

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


def generate_exported_results_csv(challenge, view_role="admin"):
    leaderboard = build_and_cache_leaderboard(challenge.id) or []
    tasks = challenge.tasks

    now = datetime.utcnow()
    has_started = challenge.start_time is not None and now >= challenge.start_time
    challenge_finalized = challenge.scores_finalized

    show_details = True
    if challenge.double_blind:
        show_details = (view_role == "admin") or (
            view_role == "jury" and (not has_started or challenge_finalized)
        )

    task_ids = [t.id for t in tasks]
    if task_ids:
        audit_logs = (
            AuditLog.query.filter(AuditLog.task_id.in_(task_ids))
            .order_by(AuditLog.timestamp.asc())
            .all()
        )
    else:
        audit_logs = []

    output = io.StringIO()
    writer = csv.writer(output)

    header = [
        "Rank",
        "Username",
        "Alias ID",
        "Real Name",
        "Email",
        "School",
        "City",
        "Grade",
        "Has Submitted",
        "Total Points",
        "Aggregated Public Score",
        "Aggregated Private Score",
    ]
    for task in tasks:
        header.extend(
            [
                f"Task '{task.title}' Public Score",
                f"Task '{task.title}' Private Score",
                f"Task '{task.title}' Manual Points",
            ]
        )
    writer.writerow(header)

    for entry in leaderboard:
        user_data = entry["user"]
        manual_pts = user_data.get("manual_points") or {}

        if show_details:
            username_val = user_data.get("username")
            real_name_val = (
                f"{user_data.get('name') or ''} {user_data.get('surname') or ''}".strip()
            )
            email_val = user_data.get("email")
            school_val = user_data.get("school")
            city_val = user_data.get("city")
            grade_val = user_data.get("grade")
        else:
            username_val = user_data.get("alias_id")
            real_name_val = user_data.get("alias_id")
            email_val = "N/A"
            school_val = "N/A"
            city_val = "N/A"
            grade_val = "N/A"

        row = [
            entry["rank"],
            username_val,
            user_data.get("alias_id"),
            real_name_val,
            email_val,
            school_val,
            city_val,
            grade_val,
            "Yes" if entry["has_submitted"] else "No",
            entry["total_points"],
            entry["public_score"] if entry["public_score"] is not None else "N/A",
            entry["private_score"] if entry["private_score"] is not None else "N/A",
        ]

        for task in tasks:
            task_score = entry["task_scores"].get(str(task.id)) or {}
            pub = task_score.get("public_score")
            priv = task_score.get("private_score")
            m_pts = manual_pts.get(str(task.id), 0)

            row.extend(
                [pub if pub is not None else "N/A", priv if priv is not None else "N/A", m_pts]
            )

        writer.writerow(row)

    writer.writerow([])
    writer.writerow(["--- SCORE CORRECTION AUDIT LOG ---"])
    writer.writerow(
        ["Timestamp (UTC)", "Admin", "Target Student", "Task", "Old Score", "New Score", "Reason"]
    )

    for log in audit_logs:
        admin_user = log.admin.username if log.admin else f"User ID {log.admin_id}"
        if show_details:
            target_user = (
                log.target_user.username if log.target_user else f"User ID {log.target_user_id}"
            )
        else:
            target_user = (
                log.target_user.alias_id if log.target_user else f"User ID {log.target_user_id}"
            )
        task_title = log.task.title if log.task else f"Task ID {log.task_id}"

        writer.writerow(
            [
                log.timestamp.isoformat(),
                admin_user,
                target_user,
                task_title,
                log.old_score if log.old_score is not None else "None",
                log.new_score if log.new_score is not None else "None",
                log.reason,
            ]
        )

    return output.getvalue()


def import_challenge_from_dict(data):
    """Create a challenge (with stages and tasks) from an exported dict.
    Returns the created Challenge object. Raises ValueError on invalid data."""
    title = data.get("title")
    if not title:
        raise ValueError("Challenge title is required.")

    def _parse_dt(val):
        if not val:
            return None
        try:
            if isinstance(val, str):
                return datetime.fromisoformat(val.replace("Z", "+00:00")).replace(tzinfo=None)
            return val
        except Exception:
            return None

    challenge = Challenge(
        title=title,
        description=data.get("description"),
        max_eval_requests=int(data.get("max_eval_requests", 10)),
        ram_limit_mb=int(data.get("ram_limit_mb", 8192)),
        time_limit_sec=int(data.get("time_limit_sec", 300)),
        gpu_required=bool(data.get("gpu_required", True)),
        is_active=bool(data.get("is_active", True)),
        is_archived=False,
        scores_finalized=False,
        start_time=_parse_dt(data.get("start_time")) or datetime.utcnow(),
        end_time=_parse_dt(data.get("end_time")) or datetime.utcnow(),
        is_frozen=bool(data.get("is_frozen", False)),
        double_blind=bool(data.get("double_blind", True)),
        reveal_results=bool(data.get("reveal_results", True)),
        timezone=data.get("timezone", "UTC"),
    )
    db.session.add(challenge)
    db.session.flush()

    old_to_new_stage = {}

    for s_data in data.get("stages", []):
        stage = Stage(
            challenge_id=challenge.id,
            stage_number=int(s_data.get("stage_number", 1)),
            title=s_data.get("title", "Stage"),
            start_time=_parse_dt(s_data.get("start_time")) or datetime.utcnow(),
            end_time=_parse_dt(s_data.get("end_time")) or datetime.utcnow(),
            is_finalized=False,
            finalize_type=s_data.get("finalize_type"),
            reveal_results=bool(s_data.get("reveal_results", False)),
        )
        db.session.add(stage)
        db.session.flush()
        if s_data.get("id"):
            old_to_new_stage[s_data["id"]] = stage.id

    for t_data in data.get("tasks", []):
        if not t_data.get("title"):
            continue
        task = Task(
            challenge_id=challenge.id,
            stage_id=old_to_new_stage.get(t_data.get("stage_id")),
            title=t_data["title"],
            description=t_data.get("description"),
            files=json.dumps(t_data.get("files", [])),
            ram_limit_mb=t_data.get("ram_limit_mb"),
            time_limit_sec=t_data.get("time_limit_sec"),
            gpu_required=t_data.get("gpu_required"),
            base_docker_image=t_data.get("base_docker_image"),
            apt_packages=t_data.get("apt_packages"),
            pip_requirements=t_data.get("pip_requirements"),
            ban_magic_commands=bool(t_data.get("ban_magic_commands", False)),
            banned_imports=t_data.get("banned_imports"),
            whitelisted_imports=t_data.get("whitelisted_imports"),
            metrics_config=t_data.get("metrics_config"),
            hf_datasets=t_data.get("hf_datasets"),
            hf_models=t_data.get("hf_models"),
            public_eval_percentage=int(t_data.get("public_eval_percentage", 30)),
            max_submissions_per_period=t_data.get("max_submissions_per_period"),
            submission_period_hours=t_data.get("submission_period_hours"),
        )
        db.session.add(task)

    db.session.commit()
    return challenge
