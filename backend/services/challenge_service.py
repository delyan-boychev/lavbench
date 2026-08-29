"""Service-layer functions for challenge CRUD, archiving, and export."""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import shutil
import uuid
import zipfile
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from config import Config
from models import AuditLog, Challenge, Stage, Submission, Task, User, db, decrypt_field
from schemas.exceptions import SchemaError
from services.file_validation import check_dangerous_extension
from services.leaderboard_service import build_and_cache_leaderboard
from services.submission_service import get_best_submission, uses_private_score_for_selection
from utils.dates import is_valid_timezone, utcnow

logger = logging.getLogger(__name__)


def generate_scores_csv(challenge: Challenge) -> str:
    """Build a CSV string with per-competitor scores across all tasks in a challenge."""
    tasks: list[Task] = challenge.tasks  # type: ignore[assignment]
    competitors = User.query.filter_by(role="competitor", challenge_id=challenge.id).all()

    from sqlalchemy import and_, case, func, or_

    from services.submission_service import submission_deadline

    private_score_task_ids = [
        task.id for task in tasks if uses_private_score_for_selection(task, challenge)
    ]
    if private_score_task_ids:
        selection_score = case(
            (
                Submission.task_id.in_(private_score_task_ids),
                func.coalesce(Submission.private_score, Submission.public_score),
            ),
            else_=Submission.public_score,
        )
    else:
        selection_score = Submission.public_score

    eligible_clauses = []
    for task in tasks:
        deadline = submission_deadline(task, challenge)
        if deadline is None:
            eligible_clauses.append(Submission.task_id == task.id)
        else:
            eligible_clauses.append(
                and_(Submission.task_id == task.id, Submission.created_at <= deadline)
            )

    subq = (
        db.session.query(
            Submission.id.label("sub_id"),
            func.row_number()
            .over(
                partition_by=(Submission.user_id, Submission.task_id),
                order_by=(
                    Submission.is_final_selection.desc(),
                    selection_score.desc(),
                    Submission.execution_time_ms.asc(),
                ),
            )
            .label("rn"),
        )
        .filter(
            Submission.challenge_id == challenge.id,
            Submission.status == "completed",
            or_(*eligible_clauses) if eligible_clauses else False,
        )
        .subquery()
    )

    all_subs = (
        Submission.query.join(subq, Submission.id == subq.c.sub_id).filter(subq.c.rn == 1).all()
    )

    sub_by_user_task: dict[tuple[uuid.UUID, uuid.UUID], list[Submission]] = {}
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

    header = [
        "Rank",
        "Alias ID",
        "Name",
        "Surname",
        "Username",
        "Email",
        "School",
        "City",
        "Grade",
    ]
    header.extend(f"Task: {task.title}" for task in tasks)
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
        row.extend(f"{item['task_scores'][task.id]:.4f}" for task in tasks)
        row.append(f"{item['total_score']:.4f}")
        writer.writerow(row)

    return output.getvalue()


def generate_exported_results_csv(challenge: Challenge, view_role: str = "admin") -> str:
    leaderboard = build_and_cache_leaderboard(challenge.id) or []
    tasks: list[Task] = challenge.tasks  # type: ignore[assignment]

    now = utcnow()
    has_started = challenge.start_time is not None and now >= challenge.start_time
    challenge_finalized = challenge.scores_finalized

    show_details = True
    if challenge.double_blind:
        show_details = (view_role == "admin") or (
            view_role == "jury" and (not has_started or challenge_finalized)
        )

    task_ids = [t.id for t in tasks]
    if task_ids:
        from sqlalchemy.orm import joinedload

        audit_logs = (
            AuditLog.query.filter(AuditLog.task_id.in_(task_ids))
            .options(
                joinedload(AuditLog.admin),
                joinedload(AuditLog.target_user),
                joinedload(AuditLog.task),
            )
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
                [
                    pub if pub is not None else "N/A",
                    priv if priv is not None else "N/A",
                    m_pts,
                ]
            )

        writer.writerow(row)

    writer.writerow([])
    writer.writerow(["--- SCORE CORRECTION AUDIT LOG ---"])
    writer.writerow(
        [
            "Timestamp (UTC)",
            "Admin",
            "Target Competitor",
            "Task",
            "Old Score",
            "New Score",
            "Reason",
        ]
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


def import_challenge_from_dict(
    data: dict[str, Any], zip_ref: zipfile.ZipFile | None = None
) -> Challenge:
    """Create a challenge (with stages and tasks) from an exported dict.
    Returns the created Challenge object. Raises ValueError on invalid data."""
    from flask import current_app
    from werkzeug.utils import secure_filename

    title = data.get("title")
    if not title:
        raise ValueError("Challenge title is required.")

    timezone_name = data.get("timezone", "UTC")
    if not isinstance(timezone_name, str) or not is_valid_timezone(timezone_name):
        raise SchemaError("ERR_INVALID_TIMEZONE", "Imported timezone is not a valid IANA name.")

    def _parse_dt(val: Any, field: str) -> datetime | None:
        if not val:
            return None
        try:
            if isinstance(val, str):
                parsed = datetime.fromisoformat(val.replace("Z", "+00:00"))
                if parsed.tzinfo is not None:
                    return parsed.astimezone(UTC).replace(tzinfo=None)
                return (
                    parsed.replace(tzinfo=ZoneInfo(timezone_name))
                    .astimezone(UTC)
                    .replace(tzinfo=None)
                )
            if isinstance(val, datetime):
                if val.tzinfo is not None:
                    return val.astimezone(UTC).replace(tzinfo=None)
                return (
                    val.replace(tzinfo=ZoneInfo(timezone_name)).astimezone(UTC).replace(tzinfo=None)
                )
            raise ValueError
        except Exception:
            raise ValueError(f"Invalid {field} in import: {val!r}") from None

    start_time = _parse_dt(data.get("start_time"), "start_time") or utcnow()
    end_time = _parse_dt(data.get("end_time"), "end_time") or utcnow()
    if end_time <= start_time:
        raise ValueError("end_time must be after start_time in imported challenge data.")

    parsed_stages: list[tuple[dict[str, Any], datetime, datetime]] = []
    for s_data in data.get("stages", []):
        stage_start = _parse_dt(s_data.get("start_time"), "stage start_time")
        stage_end = _parse_dt(s_data.get("end_time"), "stage end_time")
        if stage_start is None or stage_end is None:
            raise ValueError("Imported stages require start_time and end_time.")
        if stage_end <= stage_start:
            raise ValueError("Stage end_time must be after start_time in imported data.")
        if stage_start < start_time or stage_end > end_time:
            raise ValueError("Imported stage dates must be within the challenge timeframe.")
        parsed_stages.append((s_data, stage_start, stage_end))

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
        start_time=start_time,
        end_time=end_time,
        is_frozen=bool(data.get("is_frozen", False)),
        double_blind=bool(data.get("double_blind", True)),
        reveal_results=bool(data.get("reveal_results", True)),
        timezone=timezone_name,
    )
    db.session.add(challenge)
    db.session.flush()

    old_to_new_stage = {}

    for s_data, stage_start, stage_end in parsed_stages:
        stage = Stage(
            challenge_id=challenge.id,
            stage_number=int(s_data.get("stage_number", 1)),
            title=s_data.get("title", "Stage"),
            start_time=stage_start,
            end_time=stage_end,
            is_finalized=False,
            reveal_results=bool(s_data.get("reveal_results", False)),
        )
        db.session.add(stage)
        db.session.flush()
        if s_data.get("id"):
            old_to_new_stage[s_data["id"]] = stage.id

    created_task_dirs: list[str] = []
    for t_data in data.get("tasks", []):
        if not t_data.get("title"):
            continue
        files_data = t_data.get("files", [])
        if isinstance(files_data, list):
            files_str = json.dumps(files_data)
        elif isinstance(files_data, str):
            try:
                parsed = json.loads(files_data)
                files_str = files_data if isinstance(parsed, list) else json.dumps([])
            except Exception:
                files_str = json.dumps([])
        else:
            files_str = json.dumps([])

        task = Task(
            challenge_id=challenge.id,
            stage_id=old_to_new_stage.get(t_data.get("stage_id")),
            title=t_data["title"],
            description=t_data.get("description"),
            files=files_str,
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
        if t_data.get("hf_api_key"):
            task.set_hf_api_key(t_data.get("hf_api_key"))

        db.session.add(task)
        db.session.flush()

        old_task_id = t_data.get("id")
        if zip_ref and old_task_id:
            prefix = f"tasks/{old_task_id}/"
            upload_folder = current_app.config.get("UPLOAD_FOLDER")
            if upload_folder:
                task_dir = os.path.join(upload_folder, f"task_{task.id}")
                os.makedirs(task_dir, exist_ok=True)
                created_task_dirs.append(task_dir)

                for member in zip_ref.namelist():
                    if member.startswith(prefix):
                        basename = os.path.basename(member)
                        if not basename:
                            continue

                        if ".." in member or member.startswith("/") or member.startswith("\\"):
                            continue

                        safe_name = secure_filename(basename)
                        if not safe_name:
                            continue

                        target_path = os.path.join(task_dir, safe_name)
                        try:
                            info = zip_ref.getinfo(member)
                            if info.file_size > Config.CHALLENGE_ARCHIVE_MAX_MEMBER_BYTES:
                                raise ValueError(
                                    f"File {basename} in ZIP exceeds "
                                    "the configured per-file size limit."
                                )

                            if check_dangerous_extension(safe_name):
                                raise ValueError(f"Dangerous file extension: {safe_name}")

                            with (
                                zip_ref.open(member) as source,
                                open(target_path, "wb") as target,
                            ):
                                written = 0
                                while block := source.read(1024 * 1024):
                                    written += len(block)
                                    if written > Config.CHALLENGE_ARCHIVE_MAX_MEMBER_BYTES:
                                        raise ValueError(
                                            f"File {basename} exceeds the configured size limit."
                                        )
                                    target.write(block)
                        except Exception as e:
                            db.session.rollback()
                            for created_dir in created_task_dirs:
                                shutil.rmtree(created_dir, ignore_errors=True)
                            raise ValueError(f"Failed to extract {basename} from ZIP") from e

                if t_data.get("evaluator_script_path"):
                    eval_base = os.path.basename(t_data["evaluator_script_path"])
                    eval_path = os.path.join(task_dir, secure_filename(eval_base))
                    if os.path.isfile(eval_path):
                        task.evaluator_script_path = eval_path
                        try:
                            with open(eval_path, encoding="utf-8") as ef:
                                code = ef.read()
                            task.custom_eval_code = code
                            from routes.tasks import _validate_evaluator_script

                            eval_result, eval_err = _validate_evaluator_script(code)
                            if eval_result:
                                task.evaluator_metric_name = eval_result["metric_name"]
                            else:
                                logger.warning(
                                    "Evaluator script in import failed validation: %s", eval_err
                                )
                        except Exception:
                            logger.exception("Failed to read evaluator script during import")
                            pass

                if t_data.get("baseline_notebook_path"):
                    base_base = os.path.basename(t_data["baseline_notebook_path"])
                    base_path = os.path.join(task_dir, secure_filename(base_base))
                    if os.path.isfile(base_path):
                        task.baseline_notebook_path = base_path
                        task.baseline_notebook_size = os.path.getsize(base_path)

                if t_data.get("solution_notebook_path"):
                    sol_base = os.path.basename(t_data["solution_notebook_path"])
                    sol_path = os.path.join(task_dir, secure_filename(sol_base))
                    if os.path.isfile(sol_path):
                        task.solution_notebook_path = sol_path
                        task.solution_notebook_size = os.path.getsize(sol_path)

    db.session.commit()
    return challenge
