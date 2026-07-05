from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import shutil
import zipfile
import zoneinfo
from datetime import datetime
from typing import Any

from flask import Blueprint, current_app, request
from flask import Response as FlaskResponse
from spectree import Response
from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename

from auth_utils import jury_access_required, login_required, rate_limit, role_required
from cache_utils import invalidate_challenge_cache, invalidate_leaderboard_cache
from config import Config
from error_utils import err
from models import AuditLog, Challenge, Stage, Submission, Task, User, db, decrypt_field
from schemas.challenge import CreateChallengeSchema, UpdateChallengeSchema
from schemas.responses import (
    ArchiveResponse,
    ChallengeResponse,
    ErrorResponse,
    FinalizeChallengeResponse,
    MessageResponse,
    PaginatedResponse,
    RevealResultsResponse,
    StageResponse,
)
from schemas.stage import (
    CreateStageSchema,
    CreateTestStageSchema,
    RevealResultsSchema,
    UpdateStageSchema,
)
from services.challenge_service import generate_exported_results_csv
from services.file_validation import validate_extension
from spec import api
from utils.audit import log_audit
from utils.cache import invalidate_entity_cache
from utils.cache_helpers import cached_or_compute
from utils.dates import to_utc as _to_utc
from utils.dates import utcnow
from utils.json_utils import safe_json_loads
from utils.pagination import extract_pagination, paginated_response

logger = logging.getLogger(__name__)
challenges_bp = Blueprint("challenges", __name__)


def _check_and_add_active_stage(
    stage: dict[str, Any], now: datetime, active_stage_ids: list[str]
) -> None:
    st_start_str = stage.get("start_time")
    st_start = None
    try:
        if st_start_str:
            st_start = (
                datetime.fromisoformat(st_start_str.replace("Z", "+00:00"))
                .astimezone(zoneinfo.ZoneInfo("UTC"))
                .replace(tzinfo=None)
            )
        if st_start and st_start <= now:
            active_stage_ids.append(str(stage["id"]))
    except Exception as e:
        logger.warning("Failed to parse regular stage dates: %s", e)


def filter_challenge_for_competitor(challenge_dict: dict[str, Any]) -> dict[str, Any]:
    challenge_dict = dict(challenge_dict)
    now = utcnow()

    comp_start = None
    if challenge_dict.get("start_time"):
        try:
            val = challenge_dict["start_time"]
            if val.endswith("Z"):
                val = val[:-1] + "+00:00"
            comp_start = (
                datetime.fromisoformat(val)
                .astimezone(zoneinfo.ZoneInfo("UTC"))
                .replace(tzinfo=None)
            )
        except Exception:
            comp_start = None

    # Check if there's an active test stage (before competition start)
    test_stage = None
    for s in challenge_dict.get("stages", []):
        if s.get("is_test"):
            try:
                st_start_str = s.get("start_time")
                st_end_str = s.get("end_time")
                if st_start_str and st_end_str:
                    st_start = (
                        datetime.fromisoformat(st_start_str.replace("Z", "+00:00"))
                        .astimezone(zoneinfo.ZoneInfo("UTC"))
                        .replace(tzinfo=None)
                    )
                    st_end = (
                        datetime.fromisoformat(st_end_str.replace("Z", "+00:00"))
                        .astimezone(zoneinfo.ZoneInfo("UTC"))
                        .replace(tzinfo=None)
                    )
                    if st_start and st_end and st_start <= now <= st_end:
                        test_stage = s
            except Exception as e:
                logger.warning("Failed to parse test stage dates: %s", e)

    if comp_start and now < comp_start:
        if test_stage:
            challenge_dict["tasks"] = [
                t
                for t in challenge_dict.get("tasks", [])
                if str(t.get("stage_id")) == str(test_stage["id"])
            ]
        else:
            challenge_dict["tasks"] = []
        challenge_dict["stages"] = []
        return challenge_dict

    regular_stages = [s for s in challenge_dict.get("stages", []) if not s.get("is_test")]
    has_stages = len(regular_stages) > 0
    active_stage_ids: list[str] = []
    if has_stages:
        for s in regular_stages:
            _check_and_add_active_stage(s, now, active_stage_ids)

    filtered_tasks = []
    for t in challenge_dict.get("tasks", []):
        # Hide labels.parquet from competitor file list
        if t.get("files"):
            t["files"] = [f for f in t["files"] if f.get("filename") != "labels.parquet"]
        if not has_stages:
            filtered_tasks.append(t)
        else:
            t_stage_id = t.get("stage_id")
            if t_stage_id and str(t_stage_id) in active_stage_ids:
                filtered_tasks.append(t)
    challenge_dict["tasks"] = filtered_tasks

    return challenge_dict


@challenges_bp.route("", methods=["GET"])
@login_required
@api.validate(
    resp=Response(HTTP_200=PaginatedResponse[ChallengeResponse]),
    tags=["Challenges"],
    security=[{"cookieAuth": []}],
)
def get_challenges() -> dict[str, Any] | tuple[FlaskResponse, int]:
    """List all available challenges with their tasks and stages."""
    user_id = request.user["user_id"]
    user_role = request.user["role"]

    if user_role == "competitor":
        user = db.session.get(User, user_id)
        if not user or not user.challenge_id:
            return paginated_response(items=[], total=0, page=1, pages=0)
        challenge_id = user.challenge_id

        challenge = db.session.get(Challenge, challenge_id)
        if not challenge or challenge.is_archived:
            return paginated_response(items=[], total=0, page=1, pages=0)

        cache_key = f"challenge:{challenge_id}:competitor"
        items = [
            cached_or_compute(
                cache_key,
                lambda: filter_challenge_for_competitor(challenge.to_dict()),
                timeout=600,
            )
        ]
        return paginated_response(items=items, total=len(items), page=1, pages=1)

    if user_role == "jury":
        from models import JuryChallenge

        assigned_challenges = JuryChallenge.query.filter_by(jury_id=user_id).all()
        assigned_ids = [jc.challenge_id for jc in assigned_challenges]
        if not assigned_ids:
            return paginated_response(items=[], total=0, page=1, pages=0)

        page_arg = request.args.get("page", type=int)
        if page_arg is not None:
            _, per_page = extract_pagination(request, default_per_page=10, max_per_page=100)
            pagination = (
                Challenge.query.filter(Challenge.id.in_(assigned_ids))
                .options(joinedload(Challenge.tasks), joinedload(Challenge.stages))
                .paginate(page=page_arg, per_page=per_page, error_out=False)
            )
            return paginated_response(
                items=[c.to_dict() for c in pagination.items],
                total=pagination.total,
                page=pagination.page,
                pages=pagination.pages,
            )

        items = [
            c.to_dict()
            for c in Challenge.query.filter(Challenge.id.in_(assigned_ids))
            .options(joinedload(Challenge.tasks), joinedload(Challenge.stages))
            .all()
        ]
        return paginated_response(items=items, total=len(items), page=1, pages=1)

    page_arg = request.args.get("page", type=int)
    if page_arg is not None:
        _, per_page = extract_pagination(request, default_per_page=10, max_per_page=100)
        pagination = Challenge.query.options(
            joinedload(Challenge.tasks), joinedload(Challenge.stages)
        ).paginate(page=page_arg, per_page=per_page, error_out=False)
        return paginated_response(
            items=[c.to_dict() for c in pagination.items],
            total=pagination.total,
            page=pagination.page,
            pages=pagination.pages,
        )

    items = [
        c.to_dict()
        for c in Challenge.query.options(
            joinedload(Challenge.tasks), joinedload(Challenge.stages)
        ).all()
    ]
    return paginated_response(items=items, total=len(items), page=1, pages=1)


@challenges_bp.route("/<uuid:challenge_id>", methods=["GET"])
@login_required
@jury_access_required
@api.validate(
    resp=Response(HTTP_200=ChallengeResponse, HTTP_403=ErrorResponse, HTTP_404=ErrorResponse),
    tags=["Challenges"],
    security=[{"cookieAuth": []}],
)
def get_challenge(challenge_id: Any) -> dict[str, Any] | tuple[FlaskResponse, int]:
    """Get detailed information about a specific challenge."""
    user_id = request.user["user_id"]
    user_role = request.user["role"]

    if user_role == "competitor":
        from utils.access import ensure_registered

        if not ensure_registered(user_id, challenge_id):
            return err(
                "ERR_NOT_REGISTERED",
                403,
                message="Access denied. You are not registered for this competition.",
            )

        challenge = db.session.get(Challenge, challenge_id)
        if not challenge or challenge.is_archived:
            return err("ERR_CHALLENGE_NOT_FOUND", 404, message="Challenge not found.")

    if user_role == "competitor":
        cache_key = f"challenge:{challenge_id}:competitor"
        challenge_dict = cached_or_compute(
            cache_key, lambda: filter_challenge_for_competitor(challenge.to_dict()), timeout=600
        )
    else:
        cache_key = f"challenge:{challenge_id}"
        challenge_dict = cached_or_compute(
            cache_key, lambda: db.get_or_404(Challenge, challenge_id).to_dict(), timeout=600
        )

    return challenge_dict


@challenges_bp.route("", methods=["POST"])
@role_required(["admin", "jury"])
@api.validate(
    json=CreateChallengeSchema,
    resp=Response(HTTP_201=ChallengeResponse, HTTP_400=ErrorResponse),
    tags=["Challenges"],
    security=[{"cookieAuth": []}],
)
def create_challenge(json: CreateChallengeSchema) -> dict[str, Any] | tuple[FlaskResponse, int]:
    """Create a new competition with start/end times, resource limits, and privacy settings."""
    title, description = json.title, json.description
    max_eval_requests, ram_limit_mb, time_limit_sec = (
        json.max_eval_requests,
        json.ram_limit_mb,
        json.time_limit_sec,
    )
    gpu_required, double_blind, is_frozen = json.gpu_required, json.double_blind, json.is_frozen
    start_time, end_time = (
        _to_utc(json.start_time, json.timezone),
        _to_utc(json.end_time, json.timezone),
    )

    if not start_time or not end_time:
        return err(
            "ERR_DATETIME_REQUIRED",
            400,
            message="Competition start time and end time are required.",
        )

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
        timezone=json.timezone,
    )
    db.session.add(challenge)
    db.session.commit()

    log_audit(
        request.user["user_id"],
        "create",
        "challenge",
        target_id=challenge.id,
        details={"title": challenge.title},
    )

    invalidate_challenge_cache()

    test_stage_start = json.test_stage_start_time
    test_stage_end = json.test_stage_end_time
    if test_stage_start and test_stage_end:
        _create_test_stage_for_challenge(challenge, test_stage_start, test_stage_end)
        return challenge.to_dict(), 201

    return challenge.to_dict(), 201


def _create_test_stage_for_challenge(challenge: Any, start_time: Any, end_time: Any) -> Any:
    """Create a test stage with warm-up task for the given challenge."""
    tz = challenge.timezone or "UTC"
    start_time = _to_utc(start_time, tz)
    end_time = _to_utc(end_time, tz)

    if end_time > challenge.start_time:
        raise ValueError("Test stage must end before the competition starts.")

    existing = Stage.query.filter_by(challenge_id=challenge.id, is_test=True).first()
    if existing:
        existing.start_time = start_time
        existing.end_time = end_time
        db.session.commit()
        return existing

    stage = Stage(
        challenge_id=challenge.id,
        stage_number=0,
        title="Test Stage",
        start_time=start_time,
        end_time=end_time,
        is_test=True,
    )
    db.session.add(stage)
    db.session.commit()

    routes_dir = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.dirname(routes_dir)
    templates_dir = os.path.join(backend_dir, "test_stage_templates")
    config_path = os.path.join(templates_dir, "task_config.json")

    with open(config_path, encoding="utf-8") as f:
        task_config = json.load(f)

    test_task = Task(
        challenge_id=challenge.id,
        stage_id=stage.id,
        title=task_config.get("title", "Warm-up Test Task"),
        description=task_config.get("description"),
        custom_eval_code=None,
        gpu_required=task_config.get("gpu_required"),
        base_docker_image=task_config.get("base_docker_image"),
        pip_requirements=task_config.get("pip_requirements"),
        ram_limit_mb=task_config.get("ram_limit_mb"),
        time_limit_sec=task_config.get("time_limit_sec"),
        public_eval_percentage=task_config.get("public_eval_percentage", 30),
        ban_magic_commands=task_config.get("ban_magic_commands", True),
        whitelisted_imports=task_config.get("whitelisted_imports"),
        hf_datasets=task_config.get("hf_datasets"),
        metrics_config=task_config.get("metrics_config"),
        files="[]",
    )
    db.session.add(test_task)
    db.session.commit()

    upload_folder = current_app.config.get("UPLOAD_FOLDER")
    if upload_folder:
        task_upload_dir = os.path.join(upload_folder, f"task_{test_task.id}")
        os.makedirs(task_upload_dir, exist_ok=True)

        # Copy baseline notebook
        baseline_filename = "baseline_warmup.ipynb"
        src_baseline = os.path.join(templates_dir, baseline_filename)
        dest_baseline = os.path.join(task_upload_dir, baseline_filename)
        shutil.copy(src_baseline, dest_baseline)
        test_task.baseline_notebook_path = dest_baseline

        # Copy labels.parquet
        labels_filename = "labels.parquet"
        src_labels = os.path.join(templates_dir, labels_filename)
        dest_labels = os.path.join(task_upload_dir, labels_filename)
        shutil.copy(src_labels, dest_labels)

        # Set files metadata
        labels_size = os.path.getsize(dest_labels)
        files_meta = [
            {
                "filename": labels_filename,
                "saved_name": labels_filename,
                "size_bytes": labels_size,
            }
        ]
        test_task.files = json.dumps(files_meta)
        db.session.commit()

        # Queue baseline submission
        from routes.tasks import _maybe_queue_baseline

        _maybe_queue_baseline(test_task, challenge, request.user["user_id"])

    log_audit(
        request.user["user_id"],
        "create",
        "stage",
        target_id=stage.id,
        details={"title": stage.title, "challenge_id": challenge.id, "type": "test"},
    )

    return stage


@challenges_bp.route("/<uuid:challenge_id>", methods=["PUT"])
@role_required(["admin", "jury"])
@jury_access_required
@api.validate(
    json=UpdateChallengeSchema,
    resp=Response(HTTP_200=ChallengeResponse, HTTP_400=ErrorResponse),
    tags=["Challenges"],
    security=[{"cookieAuth": []}],
)
def update_challenge(
    challenge_id: Any, json: UpdateChallengeSchema
) -> dict[str, Any] | tuple[FlaskResponse, int]:
    """Update the configuration of an existing challenge."""
    challenge = db.get_or_404(Challenge, challenge_id)

    fields = json.model_fields_set

    if "title" in fields:
        challenge.title = json.title
    if "description" in fields:
        challenge.description = json.description
    if "max_eval_requests" in fields and json.max_eval_requests is not None:
        challenge.max_eval_requests = json.max_eval_requests
    if "ram_limit_mb" in fields and json.ram_limit_mb is not None:
        challenge.ram_limit_mb = json.ram_limit_mb
    if "time_limit_sec" in fields and json.time_limit_sec is not None:
        challenge.time_limit_sec = json.time_limit_sec
    if "gpu_required" in fields:
        challenge.gpu_required = json.gpu_required

    timezone = json.timezone if "timezone" in fields else (challenge.timezone or "UTC")
    if "start_time" in fields:
        st = json.start_time
        if not st:
            return err("ERR_DATETIME_REQUIRED", 400, message="Start time is required.")
        challenge.start_time = _to_utc(st, timezone)
    if "end_time" in fields:
        et = json.end_time
        if not et:
            return err("ERR_DATETIME_REQUIRED", 400, message="End time is required.")
        challenge.end_time = _to_utc(et, timezone)

    if "is_frozen" in fields:
        challenge.is_frozen = json.is_frozen
    if "double_blind" in fields:
        challenge.double_blind = json.double_blind
    if "timezone" in fields:
        challenge.timezone = json.timezone

    if "test_stage_start_time" in fields or "test_stage_end_time" in fields:
        test_stage_start = json.test_stage_start_time
        test_stage_end = json.test_stage_end_time
        if test_stage_start and test_stage_end:
            _create_test_stage_for_challenge(challenge, test_stage_start, test_stage_end)
        else:
            existing = Stage.query.filter_by(challenge_id=challenge.id, is_test=True).first()
            if existing:
                db.session.delete(existing)
                db.session.commit()

    db.session.commit()

    log_audit(
        request.user["user_id"],
        "update",
        "challenge",
        target_id=challenge.id,
        details={"title": challenge.title},
    )

    invalidate_entity_cache(challenge_id)

    return challenge.to_dict()


@challenges_bp.route("/<uuid:challenge_id>", methods=["DELETE"])
@role_required(["admin"])
@api.validate(
    resp=Response(HTTP_200=MessageResponse), tags=["Challenges"], security=[{"cookieAuth": []}]
)
def delete_challenge(challenge_id: Any) -> MessageResponse | tuple[FlaskResponse, int]:
    """Permanently delete a challenge and all its tasks, submissions, and backups."""
    challenge = db.get_or_404(Challenge, challenge_id)

    # Remove competition backups
    backup_dir = os.path.join("/backups", f"challenge_{challenge_id}")
    if os.path.isdir(backup_dir):
        shutil.rmtree(backup_dir, ignore_errors=True)

    User.query.filter_by(challenge_id=challenge_id, role="competitor").delete(
        synchronize_session=False
    )
    User.query.filter_by(challenge_id=challenge_id).filter(User.role != "competitor").update(
        {User.challenge_id: None}, synchronize_session=False
    )

    db.session.delete(challenge)
    db.session.commit()

    log_audit(
        request.user["user_id"],
        "delete",
        "challenge",
        target_id=challenge.id,
        details={"title": challenge.title},
    )

    invalidate_entity_cache(challenge_id, leaderboard_delete_only=True)

    return MessageResponse(
        message=(
            f"Competition '{challenge.title}' and all its associated "
            f"tasks and submissions have been deleted successfully."
        )
    )


@challenges_bp.route("/<uuid:challenge_id>/finalize", methods=["POST"])
@role_required(["jury"])
@jury_access_required
@api.validate(
    json=RevealResultsSchema,
    resp=Response(HTTP_200=FinalizeChallengeResponse, HTTP_400=ErrorResponse),
    tags=["Challenges"],
    security=[{"cookieAuth": []}],
)
def finalize_challenge(
    challenge_id: Any, json: RevealResultsSchema
) -> dict[str, Any] | tuple[FlaskResponse, int]:
    """Finalize the competition scores. Locks rankings and reveals competitor identities."""
    challenge = db.get_or_404(Challenge, challenge_id)
    if challenge.scores_finalized:
        return err("ERR_ALREADY_FINALIZED", 400, message="Competition is already finalized.")

    if not challenge.is_ended:
        return err(
            "ERR_COMPETITION_NOT_ENDED",
            400,
            message="Cannot finalize the competition before its end time.",
        )

    # Check if manual points are entered for all competitors for all tasks
    competitors = User.query.filter_by(role="competitor", challenge_id=challenge_id).all()
    if not competitors:
        return err(
            "ERR_NO_COMPETITORS", 400, message="Cannot finalize a competition with no competitors."
        )
    tasks = challenge.tasks

    for comp in competitors:
        manual_points_dict = safe_json_loads(comp.manual_points, {})

        for task in tasks:
            # Check if this competitor has any submissions for this task
            total_subs = Submission.query.filter_by(user_id=comp.id, task_id=task.id).count()
            if total_subs > 0:
                pts = manual_points_dict.get(str(task.id))
                if pts is None:
                    return err(
                        "ERR_MISSING_MANUAL_POINTS",
                        400,
                        message=(
                            f"Cannot finalize. Competitor '{comp.username}'"
                            f" (ID: {comp.id}) is "
                            f"missing manual points for"
                            f" task '{task.title}' (ID: {task.id})."
                        ),
                    )

    challenge.scores_finalized = True
    challenge.reveal_results = json.reveal_results if json.reveal_results is not None else False
    db.session.commit()

    log_audit(
        request.user["user_id"],
        "finalize",
        "challenge",
        target_id=challenge.id,
        details={"title": challenge.title},
    )

    invalidate_entity_cache(challenge_id)

    return {
        "message": (
            "Competition finalized! Competitor identities and "
            "private scores are now fully revealed to everyone."
        ),
        "challenge": challenge.to_dict(),
    }


@challenges_bp.route("/<uuid:challenge_id>/reveal-results", methods=["PUT"])
@role_required(["admin", "jury"])
@jury_access_required
@api.validate(
    json=RevealResultsSchema,
    resp=Response(HTTP_200=RevealResultsResponse, HTTP_400=ErrorResponse),
    tags=["Challenges"],
    security=[{"cookieAuth": []}],
)
def toggle_reveal_results(
    challenge_id: Any, json: RevealResultsSchema
) -> dict[str, Any] | tuple[FlaskResponse, int]:
    """Toggle reveal of private scores and manual points to competitors."""
    challenge = db.get_or_404(Challenge, challenge_id)
    if not challenge.scores_finalized:
        return err(
            "ERR_SCORES_NOT_FINALIZED",
            400,
            message="Must finalize scores before revealing results.",
        )
    challenge.reveal_results = json.reveal_results if json.reveal_results is not None else True
    db.session.commit()

    invalidate_leaderboard_cache(challenge_id)
    return {"reveal_results": challenge.reveal_results, "challenge": challenge.to_dict()}


@challenges_bp.route("/<uuid:challenge_id>/archive", methods=["POST"])
@role_required(["admin", "jury"])
@jury_access_required
@api.validate(
    resp=Response(HTTP_200=ArchiveResponse), tags=["Challenges"], security=[{"cookieAuth": []}]
)
def archive_challenge(challenge_id: Any) -> dict[str, Any] | tuple[FlaskResponse, int]:
    """Toggle archive state. Archived challenges are hidden from competitors."""
    challenge = db.get_or_404(Challenge, challenge_id)
    challenge.is_archived = not challenge.is_archived
    db.session.commit()

    log_audit(
        request.user["user_id"],
        "archive",
        "challenge" if challenge.is_archived else "restore",
        target_id=challenge.id,
        details={"title": challenge.title},
    )

    invalidate_challenge_cache(challenge_id)

    action = "archived" if challenge.is_archived else "restored"
    return {
        "message": f"Competition has been successfully {action}!",
        "challenge": challenge.to_dict(),
    }


@challenges_bp.route("/<uuid:challenge_id>/stages", methods=["POST"])
@role_required(["admin", "jury"])
@jury_access_required
@api.validate(
    json=CreateStageSchema,
    resp=Response(HTTP_201=StageResponse, HTTP_400=ErrorResponse),
    tags=["Challenges"],
    security=[{"cookieAuth": []}],
)
def create_stage(
    challenge_id: Any, json: CreateStageSchema
) -> tuple[dict[str, Any], int] | tuple[FlaskResponse, int]:
    """Add a new stage to a challenge with its own deadline and score visibility rules."""
    challenge = db.get_or_404(Challenge, challenge_id)

    start_time = _to_utc(json.start_time, challenge.timezone or "UTC")
    end_time = _to_utc(json.end_time, challenge.timezone or "UTC")

    if not start_time or not end_time:
        return err("ERR_INVALID_DATE_FORMAT", 400, message="Invalid date format.")

    if challenge.start_time and start_time < challenge.start_time:
        return err(
            "ERR_STAGE_OUT_OF_COMPETITION_BOUNDS",
            400,
            message="Stage start time must be within the competition timeframe.",
        )

    if challenge.end_time and end_time > challenge.end_time:
        return err(
            "ERR_STAGE_OUT_OF_COMPETITION_BOUNDS",
            400,
            message="Stage end time must be within the competition timeframe.",
        )

    stage_number = json.stage_number
    if not stage_number:
        max_num = (
            db.session.query(db.func.max(Stage.stage_number))
            .filter_by(challenge_id=challenge_id)
            .scalar()
            or 0
        )
        stage_number = max_num + 1

    stage = Stage(
        challenge_id=challenge_id,
        stage_number=stage_number,
        title=json.title,
        start_time=start_time,
        end_time=end_time,
    )

    db.session.add(stage)
    db.session.commit()

    log_audit(
        request.user["user_id"],
        "create",
        "stage",
        target_id=stage.id,
        details={"title": stage.title, "challenge_id": challenge_id},
    )

    invalidate_entity_cache(challenge_id)

    return stage.to_dict(), 201


@challenges_bp.route("/<uuid:challenge_id>/stages/<uuid:stage_id>", methods=["PUT"])
@role_required(["admin", "jury"])
@jury_access_required
@api.validate(
    json=UpdateStageSchema,
    resp=Response(HTTP_200=StageResponse, HTTP_400=ErrorResponse),
    tags=["Challenges"],
    security=[{"cookieAuth": []}],
)
def update_stage(
    challenge_id: Any, stage_id: Any, json: UpdateStageSchema
) -> dict[str, Any] | tuple[FlaskResponse, int]:
    """Update an existing stage configuration."""
    challenge = db.get_or_404(Challenge, challenge_id)

    stage = Stage.query.filter_by(id=stage_id, challenge_id=challenge_id).first_or_404()
    fields = json.model_fields_set

    if "title" in fields:
        stage.title = json.title
    if "stage_number" in fields:
        stage.stage_number = json.stage_number
    if "start_time" in fields and json.start_time:
        stage.start_time = _to_utc(json.start_time, challenge.timezone or "UTC")
    if "end_time" in fields and json.end_time:
        stage.end_time = _to_utc(json.end_time, challenge.timezone or "UTC")
    if "reveal_results" in fields:
        stage.reveal_results = json.reveal_results
    if "is_finalized" in fields:
        stage.is_finalized = json.is_finalized

    if challenge.start_time and stage.start_time < challenge.start_time:
        return err(
            "ERR_STAGE_OUT_OF_COMPETITION_BOUNDS",
            400,
            message="Stage start time must be within the competition timeframe.",
        )

    if challenge.end_time and stage.end_time > challenge.end_time:
        return err(
            "ERR_STAGE_OUT_OF_COMPETITION_BOUNDS",
            400,
            message="Stage end time must be within the competition timeframe.",
        )

    db.session.commit()

    log_audit(
        request.user["user_id"],
        "update",
        "stage",
        target_id=stage.id,
        details={"title": stage.title, "challenge_id": challenge_id},
    )

    invalidate_entity_cache(challenge_id)

    return stage.to_dict()


@challenges_bp.route("/<uuid:challenge_id>/stages/<uuid:stage_id>/reveal-results", methods=["PUT"])
@login_required
@role_required(["admin", "jury"])
@jury_access_required
@api.validate(
    json=RevealResultsSchema,
    resp=Response(HTTP_200=RevealResultsResponse, HTTP_400=ErrorResponse),
    tags=["Challenges"],
    security=[{"cookieAuth": []}],
)
def toggle_stage_reveal_results(
    challenge_id: Any, stage_id: Any, json: RevealResultsSchema
) -> dict[str, Any] | tuple[FlaskResponse, int]:
    """Toggle reveal_results on a finalized stage."""
    db.get_or_404(Challenge, challenge_id)

    stage = Stage.query.filter_by(id=stage_id, challenge_id=challenge_id).first_or_404()
    if not stage.is_finalized:
        return err(
            "ERR_NOT_FINALIZED", 400, message="Stage must be finalized before toggling reveal."
        )
    stage.reveal_results = (
        json.reveal_results if json.reveal_results is not None else not stage.reveal_results
    )
    db.session.commit()

    invalidate_entity_cache(challenge_id)
    return stage.to_dict()


@challenges_bp.route("/<uuid:challenge_id>/stages/<uuid:stage_id>", methods=["DELETE"])
@role_required(["admin", "jury"])
@jury_access_required
@api.validate(
    resp=Response(HTTP_200=MessageResponse), tags=["Challenges"], security=[{"cookieAuth": []}]
)
def delete_stage(challenge_id: Any, stage_id: Any) -> MessageResponse | tuple[FlaskResponse, int]:
    """Remove a stage from a challenge."""
    db.get_or_404(Challenge, challenge_id)

    stage = Stage.query.filter_by(id=stage_id, challenge_id=challenge_id).first_or_404()

    # Nullify stage_id for tasks belonging to this stage
    tasks = Task.query.filter_by(stage_id=stage_id).all()
    for t in tasks:
        t.stage_id = None

    db.session.delete(stage)
    db.session.commit()

    log_audit(
        request.user["user_id"],
        "delete",
        "stage",
        target_id=stage.id,
        details={"title": stage.title, "challenge_id": challenge_id},
    )

    invalidate_entity_cache(challenge_id)

    return MessageResponse(message=f"Stage '{stage.title}' has been deleted.")


@challenges_bp.route("/<uuid:challenge_id>/stages/<uuid:stage_id>/finalize", methods=["POST"])
@role_required(["jury"])
@jury_access_required
@api.validate(
    json=RevealResultsSchema,
    resp=Response(HTTP_200=StageResponse, HTTP_400=ErrorResponse),
    tags=["Challenges"],
    security=[{"cookieAuth": []}],
)
def finalize_stage(
    challenge_id: Any, stage_id: Any, json: RevealResultsSchema
) -> dict[str, Any] | tuple[FlaskResponse, int]:
    """Finalize a specific stage. Locks stage scores."""
    challenge = db.get_or_404(Challenge, challenge_id)

    stage = Stage.query.filter_by(id=stage_id, challenge_id=challenge_id).first_or_404()
    if stage.is_finalized:
        return err("ERR_ALREADY_FINALIZED", 400, message="Stage is already finalized.")

    now_local = challenge._now_local()
    if now_local < stage.end_time:
        return err(
            "ERR_STAGE_NOT_ENDED", 400, message="Cannot finalize the stage before its end time."
        )

    # Check if manual points are entered for all competitors for all tasks in this stage
    competitors = User.query.filter_by(role="competitor", challenge_id=challenge_id).all()
    if not competitors:
        return err(
            "ERR_NO_COMPETITORS", 400, message="Cannot finalize a stage with no competitors."
        )
    stage_tasks = Task.query.filter_by(stage_id=stage_id).all()

    for comp in competitors:
        manual_points_dict = safe_json_loads(comp.manual_points, {})

        for task in stage_tasks:
            # Check if this competitor has any submissions for this task
            total_subs = Submission.query.filter_by(user_id=comp.id, task_id=task.id).count()
            if total_subs > 0:
                pts = manual_points_dict.get(str(task.id))
                if pts is None:
                    name_str = comp.username
                    if comp.name:
                        try:
                            dec_name = decrypt_field(comp.name)
                            dec_surname = decrypt_field(comp.surname)
                            name_str = f"{dec_name} {dec_surname}"
                        except Exception as e:
                            logger.warning(
                                ("Failed to decrypt competitor name for user %s: %s"), comp.id, e
                            )
                    return err(
                        "ERR_MISSING_MANUAL_POINTS",
                        400,
                        message=(
                            f"Cannot finalize. Competitor '{name_str}' is "
                            f"missing manual points for task '{task.title}'."
                        ),
                    )

    stage.is_finalized = True
    stage.reveal_results = json.reveal_results if json.reveal_results is not None else False

    db.session.commit()

    log_audit(
        request.user["user_id"],
        "finalize",
        "stage",
        target_id=stage.id,
        details={"title": stage.title, "challenge_id": challenge_id},
    )

    invalidate_entity_cache(challenge_id)

    return stage.to_dict()


@challenges_bp.route("/<uuid:challenge_id>/test-stage", methods=["POST"])
@login_required
@role_required(["admin", "jury"])
@jury_access_required
@api.validate(
    json=CreateTestStageSchema,
    resp=Response(HTTP_201=StageResponse, HTTP_400=ErrorResponse),
    tags=["Challenges"],
    security=[{"cookieAuth": []}],
)
def create_test_stage(
    challenge_id: Any, json: CreateTestStageSchema
) -> tuple[dict[str, Any], int] | tuple[FlaskResponse, int]:
    """Create a test stage before the competition starts for testing purposes."""
    challenge = db.get_or_404(Challenge, challenge_id)

    start_time = json.start_time
    end_time = json.end_time

    if not start_time or not end_time:
        return err("ERR_MISSING_DATES", 400, message="start_time and end_time are required.")

    if start_time.tzinfo is not None:
        start_time = start_time.astimezone(zoneinfo.ZoneInfo("UTC")).replace(tzinfo=None)
    if end_time.tzinfo is not None:
        end_time = end_time.astimezone(zoneinfo.ZoneInfo("UTC")).replace(tzinfo=None)

    now = utcnow()

    if now >= challenge.start_time:
        return err(
            "ERR_COMPETITION_STARTED",
            400,
            message="Cannot create a test stage after the competition has started.",
        )

    if end_time > challenge.start_time:
        return err(
            "ERR_TEST_STAGE_AFTER_COMP_START",
            400,
            message="Test stage must end before the competition starts.",
        )

    if any(s.is_test for s in challenge.stages):
        return err(
            "ERR_TEST_STAGE_EXISTS",
            400,
            message="A test stage already exists for this competition.",
        )

    try:
        stage = _create_test_stage_for_challenge(challenge, start_time, end_time)
    except ValueError as e:
        return err("ERR_INVALID_DATE", 400, message=str(e))

    invalidate_challenge_cache(challenge_id)

    return stage.to_dict(), 201


@challenges_bp.route("/<uuid:challenge_id>/export-results", methods=["GET"])
@login_required
@role_required(["admin", "jury"])
@jury_access_required
@api.validate(resp=Response(HTTP_200=None), tags=["Challenges"], security=[{"cookieAuth": []}])
def export_results(challenge_id: Any) -> FlaskResponse | tuple[FlaskResponse, int]:
    """Export comprehensive competition results as CSV with ranks, scores, and audit log."""
    challenge = db.get_or_404(Challenge, challenge_id)
    csv_data = generate_exported_results_csv(challenge, view_role=request.user["role"])

    response = FlaskResponse(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-disposition": f"attachment; filename=challenge_{challenge_id}_export.csv"
        },
    )
    return response


@challenges_bp.route("/<uuid:challenge_id>/export", methods=["GET"])
@role_required(["admin", "jury"])
@jury_access_required
@api.validate(resp=Response(HTTP_200=None), tags=["Challenges"], security=[{"cookieAuth": []}])
def export_challenge(
    challenge_id: Any,
) -> tuple[bytes, int, dict[str, str]] | tuple[FlaskResponse, int]:
    """Export a challenge configuration as ZIP, including tasks, stages, and uploaded files."""

    challenge = db.get_or_404(Challenge, challenge_id)
    data = challenge.to_dict()

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("challenge.json", json.dumps(data, default=str, indent=2))

        upload_folder = current_app.config.get("UPLOAD_FOLDER")
        if upload_folder:
            for task in challenge.tasks:
                task_dir = os.path.join(upload_folder, f"task_{task.id}")
                if os.path.isdir(task_dir):
                    for filename in os.listdir(task_dir):
                        file_path = os.path.join(task_dir, filename)
                        if os.path.isfile(file_path):
                            zf.write(file_path, f"tasks/{task.id}/{filename}")

    zip_buffer.seek(0)
    safe_title = secure_filename(challenge.title) or "challenge"
    download_name = f"challenge_{safe_title}.zip"

    return (
        zip_buffer.read(),
        200,
        {
            "Content-Type": "application/zip",
            "Content-Disposition": f'attachment; filename="{download_name}"',
        },
    )


@challenges_bp.route("/import", methods=["POST"])
@role_required(["admin"])
@rate_limit(max_requests=5, window_seconds=120)
@api.validate(
    resp=Response(HTTP_201=ChallengeResponse, HTTP_400=ErrorResponse),
    tags=["Challenges"],
    security=[{"cookieAuth": []}],
)
def import_challenge() -> tuple[dict[str, Any], int] | tuple[FlaskResponse, int]:
    """Import a challenge configuration from a ZIP archive."""
    if not request.content_type or "multipart/form-data" not in request.content_type:
        return err("ERR_INVALID_UPLOAD_FORMAT", 400)

    if "file" not in request.files:
        return err("ERR_FILE_REQUIRED", 400)

    f = request.files["file"]
    valid_ext, ext_err = validate_extension(f.filename, {".zip"})
    if not valid_ext:
        return err("ERR_INVALID_FILE_TYPE", 400, message=ext_err)

    if f.content_length and f.content_length > 200 * 1024 * 1024:
        return err("ERR_FILE_TOO_LARGE", 400, message="ZIP file exceeds 200MB limit")

    raw = f.read()
    if len(raw) > 200 * 1024 * 1024:
        return err("ERR_FILE_TOO_LARGE", 400, message="ZIP file exceeds 200MB limit")
    if not raw:
        return err("ERR_NO_DATA_PROVIDED", 400)

    import_data = None
    zip_ref = None
    zip_buffer = None

    try:
        if raw.startswith(b"PK\x03\x04"):
            import io
            import zipfile

            zip_buffer = io.BytesIO(raw)
            try:
                zip_ref = zipfile.ZipFile(zip_buffer, "r")
                if "challenge.json" not in zip_ref.namelist():
                    return err(
                        "ERR_INVALID_ARCHIVE",
                        400,
                        message="challenge.json not found in the ZIP archive.",
                    )
                challenge_json_content = zip_ref.read("challenge.json").decode("utf-8")
                import_data = json.loads(challenge_json_content)
            except Exception as e:
                return err(
                    "ERR_INVALID_ARCHIVE", 400, message=f"Invalid or corrupt ZIP archive: {e!s}"
                )
        else:
            return err(
                "ERR_INVALID_ARCHIVE", 400, message="Uploaded file is not a valid ZIP archive."
            )

        if not isinstance(import_data, dict):
            return err("ERR_INVALID_IMPORT_DATA", 400)

        from services.challenge_service import import_challenge_from_dict

        try:
            challenge = import_challenge_from_dict(import_data, zip_ref=zip_ref)
        except ValueError as e:
            return err("ERR_INVALID_DATE", 400, message=str(e))

    finally:
        if zip_ref:
            with contextlib.suppress(Exception):
                zip_ref.close()

    log_audit(
        request.user["user_id"],
        "import",
        "challenge",
        target_id=challenge.id,
        details={"title": challenge.title},
    )

    return challenge.to_dict(), 201


@challenges_bp.route("/<uuid:challenge_id>/audit-logs/download", methods=["GET"])
@role_required(["admin"])
@rate_limit(max_requests=5, window_seconds=60)
@api.validate(
    resp=Response(HTTP_200=None, HTTP_404=ErrorResponse),
    tags=["Challenges"],
    security=[{"cookieAuth": []}],
)
def download_audit_logs(
    challenge_id: Any,
) -> tuple[bytes, int, dict[str, str]] | tuple[FlaskResponse, int]:
    """Download challenge audit logs dynamically as a JSON stream."""
    import json
    import tempfile

    challenge = db.get_or_404(Challenge, challenge_id)

    stage_ids = [s.id for s in challenge.stages]
    task_ids = [t.id for t in challenge.tasks]

    # Use subquery to avoid loading all competitor IDs into memory
    competitor_subq = (
        select(User.id)
        .where(User.role == "competitor", User.challenge_id == challenge.id)
        .scalar_subquery()
    )

    conditions = [(AuditLog.target_type == "challenge") & (AuditLog.target_id == challenge.id)]
    if stage_ids:
        conditions.append((AuditLog.target_type == "stage") & (AuditLog.target_id.in_(stage_ids)))
    if task_ids:
        conditions.append((AuditLog.target_type == "task") & (AuditLog.target_id.in_(task_ids)))
        conditions.append(AuditLog.task_id.in_(task_ids))
    conditions.append((AuditLog.target_type == "user") & (AuditLog.target_id.in_(competitor_subq)))
    conditions.append(AuditLog.target_user_id.in_(competitor_subq))

    def audit_to_dict(log):
        return {
            "id": str(log.id),
            "admin_id": str(log.admin_id) if log.admin_id else None,
            "action_type": log.action_type,
            "target_type": log.target_type,
            "target_id": str(log.target_id) if log.target_id else None,
            "details": log.details,
            "ip_address": log.ip_address,
            "target_user_id": str(log.target_user_id) if log.target_user_id else None,
            "task_id": str(log.task_id) if log.task_id else None,
            "old_score": log.old_score,
            "new_score": log.new_score,
            "reason": log.reason,
            "timestamp": log.timestamp.isoformat() + "Z" if log.timestamp else None,
        }

    # Stream audit logs to a temp file in batches
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w") as tmp:
        tmp.write("[")
        first = True
        for log in (
            AuditLog.query.filter(or_(*conditions))
            .order_by(AuditLog.timestamp.desc())
            .yield_per(Config.AUDIT_LOG_YIELD_PER)
        ):
            if not first:
                tmp.write(",\n")
            tmp.write(json.dumps(audit_to_dict(log), indent=2))
            first = False
        tmp.write("\n]")

    with open(tmp.name, "rb") as fh:
        json_bytes = fh.read()
    os.unlink(tmp.name)
    return (
        json_bytes,
        200,
        {
            "Content-Type": "application/json",
            "Content-Disposition": f'attachment; filename="audit_logs_{challenge_id}.json"',
        },
    )
