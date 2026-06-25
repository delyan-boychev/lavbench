import os
from flask import Blueprint, request, jsonify
from models import db, Challenge, User, decrypt_field
from auth_utils import login_required, role_required, jury_access_required

challenges_bp = Blueprint("challenges", __name__)

from datetime import datetime
import zoneinfo


def _now_local_for_timezone(timezone_str):
    try:
        tz = zoneinfo.ZoneInfo(timezone_str or "UTC")
        return datetime.now(tz).replace(tzinfo=None)
    except Exception:
        return datetime.utcnow()


def filter_challenge_for_competitor(challenge_dict):
    challenge_dict = dict(challenge_dict)
    now = datetime.utcnow()

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
            except Exception:
                pass

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
    active_stage_ids = []
    if has_stages:
        for s in regular_stages:
            try:
                st_start_str = s.get("start_time")
                st_end_str = s.get("end_time")
                st_start = None
                st_end = None
                if st_start_str:
                    st_start = (
                        datetime.fromisoformat(st_start_str.replace("Z", "+00:00"))
                        .astimezone(zoneinfo.ZoneInfo("UTC"))
                        .replace(tzinfo=None)
                    )
                if st_end_str:
                    st_end = (
                        datetime.fromisoformat(st_end_str.replace("Z", "+00:00"))
                        .astimezone(zoneinfo.ZoneInfo("UTC"))
                        .replace(tzinfo=None)
                    )

                if st_start and st_start <= now:
                    active_stage_ids.append(str(s["id"]))
            except Exception:
                pass

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
def get_challenges():
    """
    List all available challenges with their tasks and stages.
    ---
    tags:
      - Challenges
    security:
      - cookieAuth: []
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    user_id = request.user["user_id"]
    user_role = request.user["role"]

    from cache_utils import get_cached, set_cached

    if user_role == "competitor":
        user = db.session.get(User, user_id)
        if not user or not user.challenge_id:
            return jsonify([])
        challenge_id = user.challenge_id

        challenge = db.session.get(Challenge, challenge_id)
        if not challenge or challenge.is_archived:
            return jsonify([])

        cache_key = f"challenge:{challenge_id}:competitor"
        cached_challenge = get_cached(cache_key)
        if cached_challenge is not None:
            return jsonify([cached_challenge])

        challenge_dict = challenge.to_dict()
        filtered = filter_challenge_for_competitor(challenge_dict)
        set_cached(cache_key, filtered, timeout=600)
        return jsonify([filtered])

    if user_role == "jury":
        from models import JuryChallenge
        from sqlalchemy.orm import joinedload

        assigned_challenges = JuryChallenge.query.filter_by(jury_id=user_id).all()
        assigned_ids = [jc.challenge_id for jc in assigned_challenges]
        if not assigned_ids:
            return jsonify([])

        page = request.args.get("page", type=int)
        if page is not None:
            per_page = min(request.args.get("per_page", 10, type=int), 100)
            pagination = (
                Challenge.query.filter(Challenge.id.in_(assigned_ids))
                .options(joinedload(Challenge.tasks), joinedload(Challenge.stages))
                .paginate(page=page, per_page=per_page, error_out=False)
            )
            return jsonify(
                {
                    "items": [c.to_dict() for c in pagination.items],
                    "total": pagination.total,
                    "page": pagination.page,
                    "pages": pagination.pages,
                }
            )

        challenges = (
            Challenge.query.filter(Challenge.id.in_(assigned_ids))
            .options(joinedload(Challenge.tasks), joinedload(Challenge.stages))
            .all()
        )
        return jsonify([c.to_dict() for c in challenges])

    from sqlalchemy.orm import joinedload

    page = request.args.get("page", type=int)
    if page is not None:
        per_page = min(request.args.get("per_page", 10, type=int), 100)
        pagination = Challenge.query.options(
            joinedload(Challenge.tasks), joinedload(Challenge.stages)
        ).paginate(page=page, per_page=per_page, error_out=False)
        return jsonify(
            {
                "items": [c.to_dict() for c in pagination.items],
                "total": pagination.total,
                "page": pagination.page,
                "pages": pagination.pages,
            }
        )

    cache_key = "challenges:all"
    cached_all = get_cached(cache_key)
    if cached_all is not None:
        return jsonify(cached_all)

    challenges = Challenge.query.options(
        joinedload(Challenge.tasks), joinedload(Challenge.stages)
    ).all()
    challenges_list = [c.to_dict() for c in challenges]
    set_cached(cache_key, challenges_list, timeout=600)
    return jsonify(challenges_list)


@challenges_bp.route("/<uuid:challenge_id>", methods=["GET"])
@login_required
@jury_access_required
def get_challenge(challenge_id):
    """
    Get detailed information about a specific challenge.
    ---
    tags:
      - Challenges
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: challenge_id
        required: true
        type: string
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    user_id = request.user["user_id"]
    user_role = request.user["role"]

    if user_role == "competitor":
        user = db.session.get(User, user_id)
        from auth_utils import check_competitor_access

        if not user or not check_competitor_access(user, challenge_id):
            return (
                jsonify(
                    {
                        "error": "Access denied. You are not registered for this competition.",
                        "code": "ERR_NOT_REGISTERED",
                    }
                ),
                403,
            )

        challenge = db.session.get(Challenge, challenge_id)
        if not challenge or challenge.is_archived:
            return (
                jsonify({"error": "Challenge not found.", "code": "ERR_CHALLENGE_NOT_FOUND"}),
                404,
            )

    from cache_utils import get_cached, set_cached

    if user_role == "competitor":
        cache_key = f"challenge:{challenge_id}:competitor"
        cached_challenge = get_cached(cache_key)
        if cached_challenge is not None:
            challenge_dict = cached_challenge
        else:
            challenge = db.session.get(Challenge, challenge_id)
            if not challenge or challenge.is_archived:
                return (
                    jsonify(
                        {
                            "error": "Challenge not found.",
                            "code": "ERR_CHALLENGE_NOT_FOUND",
                        }
                    ),
                    404,
                )
            challenge_dict = challenge.to_dict()
            challenge_dict = filter_challenge_for_competitor(challenge_dict)
            set_cached(cache_key, challenge_dict, timeout=600)
    else:
        cache_key = f"challenge:{challenge_id}"
        cached_challenge = get_cached(cache_key)
        if cached_challenge is not None:
            challenge_dict = cached_challenge
        else:
            challenge = db.get_or_404(Challenge, challenge_id)
            challenge_dict = challenge.to_dict()
            set_cached(cache_key, challenge_dict, timeout=600)

    return jsonify(challenge_dict)


def parse_datetime(val):
    if not val:
        return None
    try:
        if isinstance(val, str):
            if val.endswith("Z"):
                val = val[:-1] + "+00:00"
            # Remove milliseconds/microsecond if present and fromisoformat fails
            try:
                return datetime.fromisoformat(val)
            except ValueError:
                # Try parsing with format without timezone offset first if needed
                # but fromisoformat is usually sufficient. Let's do a basic strip:
                if "T" in val:
                    val = val.split(".")[0]  # strip milliseconds
                return datetime.strptime(val, "%Y-%m-%dT%H:%M:%S")
    except Exception:
        pass
    return None


@challenges_bp.route("", methods=["POST"])
@role_required(["admin", "jury"])
def create_challenge():
    """
    Create a new competition with start/end times, resource limits, and privacy settings.
    ---
    tags:
      - Challenges
    security:
      - cookieAuth: []
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    data = request.json or {}
    title = data.get("title")
    description = data.get("description")
    max_eval_requests = int(data.get("max_eval_requests", 10))
    ram_limit_mb = int(data.get("ram_limit_mb", 8192))
    time_limit_sec = int(data.get("time_limit_sec", 300))
    gpu_required = bool(data.get("gpu_required", True))
    double_blind = data.get("double_blind")
    if double_blind is None:
        double_blind = True
    else:
        double_blind = bool(double_blind)

    start_time = parse_datetime(data.get("start_time"))
    end_time = parse_datetime(data.get("end_time"))
    is_frozen = bool(data.get("is_frozen", False))

    timezone = data.get("timezone", "UTC")

    if not title:
        return (
            jsonify(
                {
                    "error": "Competition title is required.",
                    "code": "ERR_TITLE_REQUIRED",
                }
            ),
            400,
        )

    if not start_time or not end_time:
        return (
            jsonify(
                {
                    "error": "Competition start time and end time are required.",
                    "code": "ERR_DATETIME_REQUIRED",
                }
            ),
            400,
        )

    if max_eval_requests is not None and max_eval_requests < 1:
        return (
            jsonify(
                {
                    "error": "Daily submissions limit must be at least 1.",
                    "code": "ERR_INVALID_LIMITS",
                }
            ),
            400,
        )

    if ram_limit_mb is not None and ram_limit_mb < 128:
        return (
            jsonify(
                {
                    "error": "RAM limit must be at least 128 MB.",
                    "code": "ERR_INVALID_LIMITS",
                }
            ),
            400,
        )

    if time_limit_sec is not None and time_limit_sec < 1:
        return (
            jsonify(
                {
                    "error": "Time limit must be at least 1 second.",
                    "code": "ERR_INVALID_LIMITS",
                }
            ),
            400,
        )

    if end_time <= start_time:
        return (
            jsonify(
                {
                    "error": "End time must be after start time.",
                    "code": "ERR_INVALID_DATES",
                }
            ),
            400,
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
        timezone=timezone,
    )
    db.session.add(challenge)
    db.session.commit()

    from services.audit_service import log_action

    log_action(
        request.user["user_id"],
        "create",
        "challenge",
        target_id=challenge.id,
        details={"title": challenge.title},
    )

    from cache_utils import invalidate_challenge_cache

    invalidate_challenge_cache()

    test_stage_start = parse_datetime(data.get("test_stage_start_time"))
    test_stage_end = parse_datetime(data.get("test_stage_end_time"))
    if test_stage_start and test_stage_end:
        _create_test_stage_for_challenge(challenge, test_stage_start, test_stage_end)
        return jsonify(challenge.to_dict()), 201

    return jsonify(challenge.to_dict()), 201


def _create_test_stage_for_challenge(challenge, start_time, end_time):
    """Create a test stage with warm-up task for the given challenge."""
    from models import Stage, Task

    # Ensure start_time/end_time are offset-naive UTC for comparison with DB values
    if start_time.tzinfo is not None:
        start_time = start_time.astimezone(zoneinfo.ZoneInfo("UTC")).replace(tzinfo=None)
    if end_time.tzinfo is not None:
        end_time = end_time.astimezone(zoneinfo.ZoneInfo("UTC")).replace(tzinfo=None)

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

    import os
    import shutil
    import json as json_mod
    from flask import current_app

    routes_dir = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.dirname(routes_dir)
    templates_dir = os.path.join(backend_dir, "test_stage_templates")
    config_path = os.path.join(templates_dir, "task_config.json")

    with open(config_path, "r", encoding="utf-8") as f:
        task_config = json_mod.load(f)

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
        test_task.files = json_mod.dumps(files_meta)
        db.session.commit()

        # Queue baseline submission
        from routes.tasks import _maybe_queue_baseline

        _maybe_queue_baseline(test_task, challenge, request.user["user_id"])

    from services.audit_service import log_action

    log_action(
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
def update_challenge(challenge_id):
    """
    Update the configuration of an existing challenge.
    ---
    tags:
      - Challenges
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: challenge_id
        required: true
        type: string
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    challenge = db.get_or_404(Challenge, challenge_id)
    data = request.json or {}

    title = data.get("title")
    description = data.get("description")
    max_eval_requests = data.get("max_eval_requests")
    ram_limit_mb = data.get("ram_limit_mb")
    time_limit_sec = data.get("time_limit_sec")
    gpu_required = data.get("gpu_required")

    if title:
        challenge.title = title
    if description is not None:
        challenge.description = description
    if max_eval_requests is not None:
        val = int(max_eval_requests)
        if val < 1:
            return (
                jsonify(
                    {
                        "error": "Daily submissions limit must be at least 1.",
                        "code": "ERR_INVALID_LIMITS",
                    }
                ),
                400,
            )
        challenge.max_eval_requests = val
    if ram_limit_mb is not None:
        val = int(ram_limit_mb)
        if val < 128:
            return (
                jsonify(
                    {
                        "error": "RAM limit must be at least 128 MB.",
                        "code": "ERR_INVALID_LIMITS",
                    }
                ),
                400,
            )
        challenge.ram_limit_mb = val
    if time_limit_sec is not None:
        val = int(time_limit_sec)
        if val < 1:
            return (
                jsonify(
                    {
                        "error": "Time limit must be at least 1 second.",
                        "code": "ERR_INVALID_LIMITS",
                    }
                ),
                400,
            )
        challenge.time_limit_sec = val
    if gpu_required is not None:
        challenge.gpu_required = bool(gpu_required)

    if "start_time" in data:
        st = parse_datetime(data.get("start_time"))
        if not st:
            return (
                jsonify(
                    {
                        "error": "Start time is required.",
                        "code": "ERR_DATETIME_REQUIRED",
                    }
                ),
                400,
            )
        challenge.start_time = st
    if "end_time" in data:
        et = parse_datetime(data.get("end_time"))
        if not et:
            return jsonify({"error": "End time is required.", "code": "ERR_DATETIME_REQUIRED"}), 400
        challenge.end_time = et

    if challenge.end_time <= challenge.start_time:
        return (
            jsonify(
                {
                    "error": "End time must be after start time.",
                    "code": "ERR_INVALID_DATES",
                }
            ),
            400,
        )

    if "is_frozen" in data:
        challenge.is_frozen = bool(data.get("is_frozen"))
    if "double_blind" in data:
        challenge.double_blind = bool(data.get("double_blind"))
    if "timezone" in data:
        challenge.timezone = data.get("timezone")

    if "test_stage_start_time" in data or "test_stage_end_time" in data:
        test_stage_start = parse_datetime(data.get("test_stage_start_time"))
        test_stage_end = parse_datetime(data.get("test_stage_end_time"))
        if test_stage_start and test_stage_end:
            _create_test_stage_for_challenge(challenge, test_stage_start, test_stage_end)
        else:
            from models import Stage

            existing = Stage.query.filter_by(challenge_id=challenge.id, is_test=True).first()
            if existing:
                db.session.delete(existing)
                db.session.commit()

    db.session.commit()

    from services.audit_service import log_action

    log_action(
        request.user["user_id"],
        "update",
        "challenge",
        target_id=challenge.id,
        details={"title": challenge.title},
    )

    from cache_utils import invalidate_challenge_cache, invalidate_leaderboard_cache

    invalidate_challenge_cache(challenge_id)
    invalidate_leaderboard_cache(challenge_id)

    return jsonify(challenge.to_dict())


@challenges_bp.route("/<uuid:challenge_id>", methods=["DELETE"])
@role_required(["admin"])
def delete_challenge(challenge_id):
    """
    Permanently delete a challenge including all its tasks, submissions, and competition backups.
    ---
    tags:
      - Challenges
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: challenge_id
        required: true
        type: string
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    challenge = db.get_or_404(Challenge, challenge_id)

    # Remove competition backups
    import shutil

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

    from services.audit_service import log_action

    log_action(
        request.user["user_id"],
        "delete",
        "challenge",
        target_id=challenge.id,
        details={"title": challenge.title},
    )

    from cache_utils import invalidate_challenge_cache, invalidate_leaderboard_cache

    invalidate_challenge_cache(challenge_id)
    invalidate_leaderboard_cache(challenge_id, delete_only=True)

    return jsonify(
        {
            "message": f"Competition '{challenge.title}' and all its associated tasks and submissions have been deleted successfully."
        }
    )


@challenges_bp.route("/<uuid:challenge_id>/finalize", methods=["POST"])
@role_required(["jury"])
@jury_access_required
def finalize_challenge(challenge_id):
    """
    Finalize the competition scores. Locks rankings and reveals competitor identities.
    ---
    tags:
      - Challenges
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: challenge_id
        required: true
        type: string
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    challenge = db.get_or_404(Challenge, challenge_id)
    if challenge.scores_finalized:
        return (
            jsonify(
                {
                    "error": "Competition is already finalized.",
                    "code": "ERR_ALREADY_FINALIZED",
                }
            ),
            400,
        )

    if not challenge.is_ended:
        return (
            jsonify(
                {
                    "error": "Cannot finalize the competition before its end time.",
                    "code": "ERR_COMPETITION_NOT_ENDED",
                }
            ),
            400,
        )

    # Check if manual points are entered for all competitors for all tasks
    competitors = User.query.filter_by(role="competitor", challenge_id=challenge_id).all()
    if not competitors:
        return (
            jsonify(
                {
                    "error": "Cannot finalize a competition with no competitors.",
                    "code": "ERR_NO_COMPETITORS",
                }
            ),
            400,
        )
    tasks = challenge.tasks

    for comp in competitors:
        manual_points_dict = {}
        if comp.manual_points:
            if isinstance(comp.manual_points, dict):
                manual_points_dict = comp.manual_points
            elif isinstance(comp.manual_points, str):
                try:
                    import json

                    manual_points_dict = json.loads(comp.manual_points)
                except Exception:
                    manual_points_dict = {}

        for task in tasks:
            pts = manual_points_dict.get(str(task.id))
            if pts is None:
                return (
                    jsonify(
                        {
                            "error": f"Cannot finalize. Competitor '{comp.username}' (ID: {comp.id}) is missing manual points for task '{task.title}' (ID: {task.id}).",
                            "code": "ERR_MISSING_MANUAL_POINTS",
                        }
                    ),
                    400,
                )

    challenge.scores_finalized = True
    db.session.commit()

    from services.audit_service import log_action

    log_action(
        request.user["user_id"],
        "finalize",
        "challenge",
        target_id=challenge.id,
        details={"title": challenge.title},
    )

    from cache_utils import invalidate_challenge_cache, invalidate_leaderboard_cache

    invalidate_challenge_cache(challenge_id)
    invalidate_leaderboard_cache(challenge_id)

    return jsonify(
        {
            "message": "Competition finalized! Competitor identities and private scores are now fully revealed to everyone.",
            "challenge": challenge.to_dict(),
        }
    )


@challenges_bp.route("/<uuid:challenge_id>/reveal-results", methods=["PUT"])
@role_required(["admin", "jury"])
@jury_access_required
def toggle_reveal_results(challenge_id):
    """Toggle reveal of private scores and manual points to competitors."""
    challenge = db.get_or_404(Challenge, challenge_id)
    if not challenge.scores_finalized:
        return jsonify({"error": "Must finalize scores before revealing results."}), 400
    data = request.get_json() or {}
    challenge.reveal_results = bool(data.get("reveal_results", True))
    db.session.commit()

    from cache_utils import invalidate_leaderboard_cache

    invalidate_leaderboard_cache(challenge_id)
    return jsonify({"reveal_results": challenge.reveal_results, "challenge": challenge.to_dict()})


@challenges_bp.route("/<uuid:challenge_id>/archive", methods=["POST"])
@role_required(["admin", "jury"])
@jury_access_required
def archive_challenge(challenge_id):
    """
    Toggle archive state. Archived challenges are hidden from competitors.
    ---
    tags:
      - Challenges
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: challenge_id
        required: true
        type: string
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    challenge = db.get_or_404(Challenge, challenge_id)
    challenge.is_archived = not challenge.is_archived
    db.session.commit()

    from services.audit_service import log_action

    log_action(
        request.user["user_id"],
        "archive",
        "challenge" if challenge.is_archived else "restore",
        target_id=challenge.id,
        details={"title": challenge.title},
    )

    from cache_utils import invalidate_challenge_cache

    invalidate_challenge_cache(challenge_id)

    action = "archived" if challenge.is_archived else "restored"
    return jsonify(
        {
            "message": f"Competition has been successfully {action}!",
            "challenge": challenge.to_dict(),
        }
    )


@challenges_bp.route("/<uuid:challenge_id>/stages", methods=["POST"])
@role_required(["admin", "jury"])
@jury_access_required
def create_stage(challenge_id):
    """
    Add a new stage to a challenge with its own deadline and score visibility rules.
    ---
    tags:
      - Challenges
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: challenge_id
        required: true
        type: string
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    challenge = db.get_or_404(Challenge, challenge_id)
    data = request.json or {}

    title = data.get("title")
    stage_number = data.get("stage_number")
    start_time_str = data.get("start_time")
    end_time_str = data.get("end_time")

    if not title or not start_time_str or not end_time_str:
        return (
            jsonify(
                {
                    "error": "Missing title, start_time or end_time.",
                    "code": "ERR_MISSING_STAGE_FIELDS",
                }
            ),
            400,
        )

    start_time = parse_datetime(start_time_str)
    end_time = parse_datetime(end_time_str)

    if not start_time or not end_time:
        return jsonify({"error": "Invalid date format.", "code": "ERR_INVALID_DATE_FORMAT"}), 400

    if start_time.tzinfo is not None:
        start_time = start_time.astimezone(zoneinfo.ZoneInfo("UTC")).replace(tzinfo=None)
    if end_time.tzinfo is not None:
        end_time = end_time.astimezone(zoneinfo.ZoneInfo("UTC")).replace(tzinfo=None)

    if end_time <= start_time:
        return (
            jsonify(
                {
                    "error": "Stage end time must be after start time.",
                    "code": "ERR_INVALID_STAGE_DATES",
                }
            ),
            400,
        )

    if challenge.start_time and start_time < challenge.start_time:
        return (
            jsonify(
                {
                    "error": "Stage start time must be within the competition timeframe.",
                    "code": "ERR_STAGE_OUT_OF_COMPETITION_BOUNDS",
                }
            ),
            400,
        )

    if challenge.end_time and end_time > challenge.end_time:
        return (
            jsonify(
                {
                    "error": "Stage end time must be within the competition timeframe.",
                    "code": "ERR_STAGE_OUT_OF_COMPETITION_BOUNDS",
                }
            ),
            400,
        )

    if not stage_number:
        # Auto-increment stage number
        from models import Stage

        max_num = (
            db.session.query(db.func.max(Stage.stage_number))
            .filter_by(challenge_id=challenge_id)
            .scalar()
            or 0
        )
        stage_number = max_num + 1

    from models import Stage

    stage = Stage(
        challenge_id=challenge_id,
        stage_number=stage_number,
        title=title,
        start_time=start_time,
        end_time=end_time,
    )

    db.session.add(stage)
    db.session.commit()

    from services.audit_service import log_action

    log_action(
        request.user["user_id"],
        "create",
        "stage",
        target_id=stage.id,
        details={"title": stage.title, "challenge_id": challenge_id},
    )

    from cache_utils import invalidate_challenge_cache, invalidate_leaderboard_cache

    invalidate_challenge_cache(challenge_id)
    invalidate_leaderboard_cache(challenge_id)

    return jsonify(stage.to_dict()), 201


@challenges_bp.route("/<uuid:challenge_id>/stages/<uuid:stage_id>", methods=["PUT"])
@role_required(["admin", "jury"])
@jury_access_required
def update_stage(challenge_id, stage_id):
    """
    Update an existing stage configuration.
    ---
    tags:
      - Challenges
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: challenge_id
        required: true
        type: string
      - in: path
        name: stage_id
        required: true
        type: string
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    challenge = db.get_or_404(Challenge, challenge_id)
    from models import Stage

    stage = Stage.query.filter_by(id=stage_id, challenge_id=challenge_id).first_or_404()
    data = request.json or {}

    if "title" in data:
        stage.title = data["title"]
    if "stage_number" in data:
        stage.stage_number = data["stage_number"]
    if "start_time" in data:
        t = parse_datetime(data["start_time"])
        if t:
            if t.tzinfo is not None:
                t = t.astimezone(zoneinfo.ZoneInfo("UTC")).replace(tzinfo=None)
            stage.start_time = t
    if "end_time" in data:
        t = parse_datetime(data["end_time"])
        if t:
            if t.tzinfo is not None:
                t = t.astimezone(zoneinfo.ZoneInfo("UTC")).replace(tzinfo=None)
            stage.end_time = t
    if "reveal_results" in data:
        stage.reveal_results = bool(data["reveal_results"])
    if "is_finalized" in data:
        stage.is_finalized = bool(data["is_finalized"])
    if "finalize_type" in data:
        stage.finalize_type = data["finalize_type"]

    if stage.end_time <= stage.start_time:
        return (
            jsonify(
                {
                    "error": "Stage end time must be after start time.",
                    "code": "ERR_INVALID_STAGE_DATES",
                }
            ),
            400,
        )

    if challenge.start_time and stage.start_time < challenge.start_time:
        return (
            jsonify(
                {
                    "error": "Stage start time must be within the competition timeframe.",
                    "code": "ERR_STAGE_OUT_OF_COMPETITION_BOUNDS",
                }
            ),
            400,
        )

    if challenge.end_time and stage.end_time > challenge.end_time:
        return (
            jsonify(
                {
                    "error": "Stage end time must be within the competition timeframe.",
                    "code": "ERR_STAGE_OUT_OF_COMPETITION_BOUNDS",
                }
            ),
            400,
        )

    db.session.commit()

    from services.audit_service import log_action

    log_action(
        request.user["user_id"],
        "update",
        "stage",
        target_id=stage.id,
        details={"title": stage.title, "challenge_id": challenge_id},
    )

    from cache_utils import invalidate_challenge_cache, invalidate_leaderboard_cache

    invalidate_challenge_cache(challenge_id)
    invalidate_leaderboard_cache(challenge_id)

    return jsonify(stage.to_dict())


@challenges_bp.route("/<uuid:challenge_id>/stages/<uuid:stage_id>", methods=["DELETE"])
@role_required(["admin", "jury"])
@jury_access_required
def delete_stage(challenge_id, stage_id):
    """
    Remove a stage from a challenge.
    ---
    tags:
      - Challenges
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: challenge_id
        required: true
        type: string
      - in: path
        name: stage_id
        required: true
        type: string
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    challenge = db.get_or_404(Challenge, challenge_id)
    from models import Stage

    stage = Stage.query.filter_by(id=stage_id, challenge_id=challenge_id).first_or_404()

    # Nullify stage_id for tasks belonging to this stage
    from models import Task

    tasks = Task.query.filter_by(stage_id=stage_id).all()
    for t in tasks:
        t.stage_id = None

    db.session.delete(stage)
    db.session.commit()

    from services.audit_service import log_action

    log_action(
        request.user["user_id"],
        "delete",
        "stage",
        target_id=stage.id,
        details={"title": stage.title, "challenge_id": challenge_id},
    )

    from cache_utils import invalidate_challenge_cache, invalidate_leaderboard_cache

    invalidate_challenge_cache(challenge_id)
    invalidate_leaderboard_cache(challenge_id)

    return jsonify({"message": f"Stage '{stage.title}' has been deleted."})


@challenges_bp.route("/<uuid:challenge_id>/stages/<uuid:stage_id>/finalize", methods=["POST"])
@role_required(["jury"])
@jury_access_required
def finalize_stage(challenge_id, stage_id):
    """
    Finalize a specific stage. Locks stage scores.
    ---
    tags:
      - Challenges
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: challenge_id
        required: true
        type: string
      - in: path
        name: stage_id
        required: true
        type: string
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    challenge = db.get_or_404(Challenge, challenge_id)
    from models import Stage

    stage = Stage.query.filter_by(id=stage_id, challenge_id=challenge_id).first_or_404()
    if stage.is_finalized:
        return (
            jsonify(
                {
                    "error": "Stage is already finalized.",
                    "code": "ERR_ALREADY_FINALIZED",
                }
            ),
            400,
        )

    now_local = challenge._now_local()
    if now_local < stage.end_time:
        return (
            jsonify(
                {
                    "error": "Cannot finalize the stage before its end time.",
                    "code": "ERR_STAGE_NOT_ENDED",
                }
            ),
            400,
        )
    data = request.json or {}

    finalize_type = data.get("finalize_type", "visible")
    if finalize_type not in ("visible", "internal"):
        return (
            jsonify(
                {
                    "error": "finalize_type must be either 'visible' or 'internal'.",
                    "code": "ERR_INVALID_FINALIZE_TYPE",
                }
            ),
            400,
        )

    # Check if manual points are entered for all competitors for all tasks in this stage
    competitors = User.query.filter_by(role="competitor", challenge_id=challenge_id).all()
    if not competitors:
        return (
            jsonify(
                {
                    "error": "Cannot finalize a stage with no competitors.",
                    "code": "ERR_NO_COMPETITORS",
                }
            ),
            400,
        )
    from models import Task

    stage_tasks = Task.query.filter_by(stage_id=stage_id).all()

    for comp in competitors:
        manual_points_dict = {}
        if comp.manual_points:
            if isinstance(comp.manual_points, dict):
                manual_points_dict = comp.manual_points
            elif isinstance(comp.manual_points, str):
                try:
                    manual_points_dict = json.loads(comp.manual_points)
                except Exception:
                    manual_points_dict = {}

        for task in stage_tasks:
            pts = manual_points_dict.get(str(task.id))
            if pts is None:
                name_str = comp.username
                if comp.name:
                    try:
                        dec_name = decrypt_field(comp.name)
                        dec_surname = decrypt_field(comp.surname)
                        name_str = f"{dec_name} {dec_surname}"
                    except Exception:
                        pass
                return (
                    jsonify(
                        {
                            "error": f"Cannot finalize. Competitor '{name_str}' is missing manual points for task '{task.title}'.",
                            "code": "ERR_MISSING_MANUAL_POINTS",
                        }
                    ),
                    400,
                )

    stage.is_finalized = True
    stage.finalize_type = finalize_type
    num_stages = Stage.query.filter_by(challenge_id=challenge_id).count()
    if num_stages == 1:
        stage.reveal_results = True
    else:
        stage.reveal_results = bool(
            data.get(
                "reveal_results",
                data.get("reveal_private", data.get("reveal_points", False)),
            )
        )

    db.session.commit()

    from services.audit_service import log_action

    log_action(
        request.user["user_id"],
        "finalize",
        "stage",
        target_id=stage.id,
        details={"title": stage.title, "challenge_id": challenge_id},
    )

    from cache_utils import invalidate_challenge_cache, invalidate_leaderboard_cache

    invalidate_challenge_cache(challenge_id)
    invalidate_leaderboard_cache(challenge_id)

    return jsonify(stage.to_dict())


@challenges_bp.route("/<uuid:challenge_id>/test-stage", methods=["POST"])
@login_required
@role_required(["admin", "jury"])
@jury_access_required
def create_test_stage(challenge_id):
    """
    Create a test stage before the competition starts for testing purposes.
    ---
    tags:
      - Challenges
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: challenge_id
        required: true
        type: string
    requestBody:
      required: true
      content:
        application/json:
          schema:
            type: object
            properties:
              title:
                type: string
              start_time:
                type: string
                format: date-time
              end_time:
                type: string
                format: date-time
    responses:
      201:
        description: Test stage created
        content:
          application/json:
            schema:
              type: object
    """
    challenge = db.get_or_404(Challenge, challenge_id)
    data = request.json or {}

    start_time = parse_datetime(data.get("start_time"))
    end_time = parse_datetime(data.get("end_time"))

    if not start_time or not end_time:
        return (
            jsonify(
                {
                    "error": "start_time and end_time are required.",
                    "code": "ERR_MISSING_DATES",
                }
            ),
            400,
        )

    if start_time.tzinfo is not None:
        start_time = start_time.astimezone(zoneinfo.ZoneInfo("UTC")).replace(tzinfo=None)
    if end_time.tzinfo is not None:
        end_time = end_time.astimezone(zoneinfo.ZoneInfo("UTC")).replace(tzinfo=None)

    now = datetime.utcnow()

    if now >= challenge.start_time:
        return (
            jsonify(
                {
                    "error": "Cannot create a test stage after the competition has started.",
                    "code": "ERR_COMPETITION_STARTED",
                }
            ),
            400,
        )

    if end_time > challenge.start_time:
        return (
            jsonify(
                {
                    "error": "Test stage must end before the competition starts.",
                    "code": "ERR_TEST_STAGE_AFTER_COMP_START",
                }
            ),
            400,
        )

    if end_time <= start_time:
        return (
            jsonify(
                {
                    "error": "Test stage end time must be after start time.",
                    "code": "ERR_INVALID_STAGE_DATES",
                }
            ),
            400,
        )

    if any(s.is_test for s in challenge.stages):
        return (
            jsonify(
                {
                    "error": "A test stage already exists for this competition.",
                    "code": "ERR_TEST_STAGE_EXISTS",
                }
            ),
            400,
        )

    try:
        stage = _create_test_stage_for_challenge(challenge, start_time, end_time)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    from cache_utils import invalidate_challenge_cache

    invalidate_challenge_cache(challenge_id)

    return jsonify(stage.to_dict()), 201


@challenges_bp.route("/<uuid:challenge_id>/export-results", methods=["GET"])
@login_required
@role_required(["admin", "jury"])
@jury_access_required
def export_results(challenge_id):
    """
    Export comprehensive competition results as CSV with ranks, scores, and audit log.
    ---
    tags:
      - Challenges
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: challenge_id
        required: true
        type: string
    responses:
      200:
        description: Success

        content:
          application/json:
            schema:
              type: object
    """
    from flask import Response
    from services.challenge_service import generate_exported_results_csv

    challenge = db.get_or_404(Challenge, challenge_id)
    csv_data = generate_exported_results_csv(challenge, view_role=request.user["role"])

    response = Response(
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
def export_challenge(challenge_id):
    """
    Export a challenge configuration as ZIP, including tasks, stages, and uploaded files.
    ---
    tags:
      - Challenges
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: challenge_id
        required: true
        type: string
    responses:
      200:
        description: Challenge export ZIP file
        content:
          application/zip:
            schema:
              type: string
              format: binary
    """
    import io
    import os
    import json
    import zipfile
    from flask import send_file, current_app
    from werkzeug.utils import secure_filename

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

    return send_file(
        zip_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=download_name,
    )


@challenges_bp.route("/import", methods=["POST"])
@role_required(["admin"])
def import_challenge():
    """
    Import a challenge configuration from a ZIP archive.
    Creates challenge, stages, and tasks, and restores files.
    ---
    tags:
      - Challenges
    security:
      - cookieAuth: []
    requestBody:
      required: true
      content:
        multipart/form-data:
          schema:
            type: object
            properties:
              file:
                type: string
                format: binary
    responses:
      201:
        description: Challenge created
        content:
          application/json:
            schema:
              type: object
    """
    import json
    from services.file_validation import validate_extension

    if not request.content_type or "multipart/form-data" not in request.content_type:
        return (
            jsonify({"error": "Only ZIP files uploaded as multipart/form-data are supported."}),
            400,
        )

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    f = request.files["file"]
    valid_ext, ext_err = validate_extension(f.filename, {".zip"})
    if not valid_ext:
        return jsonify({"error": ext_err}), 400

    raw = f.read()
    if not raw:
        return jsonify({"error": "No data provided."}), 400

    import_data = None
    zip_ref = None
    zip_buffer = None

    try:
        if raw.startswith(b"PK\x03\x04"):
            import zipfile
            import io

            zip_buffer = io.BytesIO(raw)
            try:
                zip_ref = zipfile.ZipFile(zip_buffer, "r")
                if "challenge.json" not in zip_ref.namelist():
                    return jsonify({"error": "challenge.json not found in the ZIP archive."}), 400
                challenge_json_content = zip_ref.read("challenge.json").decode("utf-8")
                import_data = json.loads(challenge_json_content)
            except Exception as e:
                return jsonify({"error": f"Invalid or corrupt ZIP archive: {str(e)}"}), 400
        else:
            return jsonify({"error": "Uploaded file is not a valid ZIP archive."}), 400

        if not isinstance(import_data, dict):
            return jsonify({"error": "Import data must be a JSON object."}), 400

        from services.challenge_service import import_challenge_from_dict

        try:
            challenge = import_challenge_from_dict(import_data, zip_ref=zip_ref)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    finally:
        if zip_ref:
            try:
                zip_ref.close()
            except Exception:
                pass

    from services.audit_service import log_action

    log_action(
        request.user["user_id"],
        "import",
        "challenge",
        target_id=challenge.id,
        details={"title": challenge.title},
    )

    return jsonify(challenge.to_dict()), 201


@challenges_bp.route("/<uuid:challenge_id>/audit-logs/download", methods=["GET"])
@role_required(["admin"])
def download_audit_logs(challenge_id):
    """
    Download challenge audit logs dynamically as a JSON stream.
    """
    import io
    import json
    from flask import send_file
    from models import Challenge, AuditLog, User
    from sqlalchemy import or_

    challenge = db.get_or_404(Challenge, challenge_id)

    stage_ids = [s.id for s in challenge.stages]
    task_ids = [t.id for t in challenge.tasks]
    competitor_ids = [
        u.id for u in User.query.filter_by(role="competitor", challenge_id=challenge.id).all()
    ]

    conditions = [(AuditLog.target_type == "challenge") & (AuditLog.target_id == challenge.id)]
    if stage_ids:
        conditions.append((AuditLog.target_type == "stage") & (AuditLog.target_id.in_(stage_ids)))
    if task_ids:
        conditions.append((AuditLog.target_type == "task") & (AuditLog.target_id.in_(task_ids)))
        conditions.append(AuditLog.task_id.in_(task_ids))
    if competitor_ids:
        conditions.append(
            (AuditLog.target_type == "user") & (AuditLog.target_id.in_(competitor_ids))
        )
        conditions.append(AuditLog.target_user_id.in_(competitor_ids))

    audit_logs = AuditLog.query.filter(or_(*conditions)).order_by(AuditLog.timestamp.desc()).all()

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

    logs_data = json.dumps([audit_to_dict(log) for log in audit_logs], indent=2)
    mem_file = io.BytesIO(logs_data.encode("utf-8"))

    return send_file(
        mem_file,
        mimetype="application/json",
        as_attachment=True,
        download_name=f"audit_logs_{challenge_id}.json",
    )
