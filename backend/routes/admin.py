from __future__ import annotations

import contextlib
import csv
import io
import json
import logging
import os
import re
import secrets
import shutil
import string
import tempfile
import time
import zipfile
from datetime import datetime
from typing import Any

from flask import Blueprint, current_app, request
from flask import Response as FlaskResponse
from spectree import Response
from sqlalchemy import or_
from werkzeug.security import generate_password_hash

from auth_utils import jury_access_required, rate_limit, role_required
from cache_utils import get_redis_client, invalidate_leaderboard_cache
from config import Config
from error_utils import err
from evaluation_engine import AVAILABLE_METRICS
from models import (
    AuditLog,
    Challenge,
    Submission,
    User,
    db,
    decrypt_field,
    generate_pseudonym,
    to_base36,
)
from schemas.admin import CreateUserSchema, RegisterCompetitorSchema, UpdateUserSchema
from schemas.responses import (
    AuditLinkListResponse,
    AvailableMetricsResponse,
    BackupListResponse,
    BackupStartResponse,
    BulkResetPasswordResponse,
    DeadLetterListResponse,
    ErrorResponse,
    ImportCompetitorsResponse,
    MessageResponse,
    PaginatedResponse,
    RegisterUserResponse,
    ResetPasswordResponse,
    UpdateUserResponse,
    UserResponse,
    WorkerStatsResponse,
)
from services.challenge_service import generate_scores_csv
from services.file_validation import validate_csv_content, validate_extension
from spec import api
from sse_utils import SSE_IDLE_TIMEOUT, sse_connection_limit
from utils.audit import log_audit
from utils.cache_helpers import cached_or_compute_unless_testing
from utils.competitor import check_duplicate_demographics, demographics_tuple
from utils.dates import utcnow
from utils.ipynb import cells_to_ipynb_json, wrap_raw_code_cells
from utils.pagination import extract_pagination, paginated_response
from utils.sse import sse_response

logger = logging.getLogger(__name__)
admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/metrics", methods=["GET"])
@role_required(["admin", "jury"])
@api.validate(
    tags=["Admin"], security=[{"cookieAuth": []}], resp=Response(HTTP_200=AvailableMetricsResponse)
)
def get_available_metrics() -> AvailableMetricsResponse:
    return AvailableMetricsResponse(root=AVAILABLE_METRICS)


def transliterate_bulgarian(text: str) -> str:
    if not text:
        return ""
    mapping = {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sht",
        "ъ": "a",
        "ь": "y",
        "ю": "yu",
        "я": "ya",
    }
    return "".join(mapping.get(c, c) for c in text.lower())


def generate_unique_username(name: str, surname: str, role: str = "competitor") -> str:
    trans_name = transliterate_bulgarian(name)
    trans_surname = transliterate_bulgarian(surname)
    norm_name = re.sub(r"[^a-zA-Z0-9]", "", trans_name)
    norm_surname = re.sub(r"[^a-zA-Z0-9]", "", trans_surname)

    prefix = "jury" if role == "jury" else "comp"
    base = f"{prefix}_{norm_name[:3]}_{norm_surname[:3]}"
    if len(base) < len(prefix) + 4:
        base = f"{prefix}_user"

    # 1. Get millisecond timestamp modulo 36^4 (1,679,616)
    ts_ms = int(time.time() * 1000)
    raw_num = ts_ms % 1679616

    # 2. Scramble using LCG-like bijective modular multiplication (7919 is coprime to 36)
    scrambled = (raw_num * 7919 + 104729) % 1679616

    # 3. Convert to exactly 4 characters of base36
    suffix = to_base36(scrambled).zfill(4)
    return f"{base}_{suffix}"


def generate_random_password(length: int = 12) -> str:
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(chars) for _ in range(length))


# --- ENDPOINTS ---


@admin_bp.route("/register-competitor", methods=["POST"])
@role_required(["admin", "jury"])
@jury_access_required
@rate_limit(max_requests=20, window_seconds=60)
@api.validate(
    json=RegisterCompetitorSchema,
    tags=["Admin"],
    security=[{"cookieAuth": []}],
    resp=Response(HTTP_201=RegisterUserResponse, HTTP_422=ErrorResponse),
)
def register_competitor(
    json: RegisterCompetitorSchema,
) -> tuple[RegisterUserResponse, int] | tuple[FlaskResponse, int]:
    name, surname, middle_name = json.name, json.surname, json.middle_name
    birth_date, grade, school, city = json.birth_date, json.grade, json.school, json.city
    challenge_id = json.challenge_id

    challenge = db.session.get(Challenge, challenge_id)
    if not challenge:
        return err("ERR_INVALID_CHALLENGE_ID", 400)

    if challenge.is_started and request.user["role"] != "admin":
        return err("ERR_JURY_REGISTRATION_STARTED", 403)

    existing = User.query.filter_by(role="competitor", challenge_id=challenge_id).all()

    if check_duplicate_demographics(
        existing, name, middle_name, surname, birth_date, grade, school, city, decrypt_field
    ):
        return err(
            "ERR_COMPETITOR_ALREADY_REGISTERED",
            400,
            message="A competitor with these demographic "
            "details is already registered for this competition.",
        )

    username = generate_unique_username(name, surname)
    password = generate_random_password(12)

    user = User(
        username=username,
        password_hash=generate_password_hash(password, method="pbkdf2:sha256"),
        role="competitor",
        alias_id=generate_pseudonym(),
        challenge_id=challenge_id,
        email=json.email,
    )
    user.set_demographics(
        name,
        surname,
        grade,
        school,
        city,
        middle_name=middle_name,
        birth_date=birth_date,
    )
    db.session.add(user)
    db.session.commit()

    log_audit(
        request.user["user_id"],
        "create",
        "user",
        target_id=user.id,
        details={
            "username": username,
            "role": "competitor",
            "challenge_id": challenge_id,
        },
    )

    invalidate_leaderboard_cache(challenge_id)

    return RegisterUserResponse(
        message="Competitor registered successfully.",
        generated_username=username,
        generated_password=password,
        user=user.to_dict(view_role=request.user["role"]),
    ), 201


@admin_bp.route("/users", methods=["GET"])
@role_required(["admin", "jury"])
@api.validate(
    resp=Response(HTTP_200=PaginatedResponse[UserResponse], HTTP_422=ErrorResponse),
    tags=["Admin"],
    security=[{"cookieAuth": []}],
)
def get_users() -> dict[str, Any] | tuple[FlaskResponse, int]:
    page, per_page = extract_pagination(request, default_per_page=10, max_per_page=100)
    role_filter = request.args.get("role")
    challenge_id_filter = request.args.get("challenge_id")
    search_term = request.args.get("search")

    query = User.query
    requester_role = request.user["role"]
    requester_id = request.user["user_id"]

    if requester_role == "jury":
        from models import JuryChallenge

        assigned_challenges = JuryChallenge.query.filter_by(jury_id=requester_id).all()
        assigned_ids = [jc.challenge_id for jc in assigned_challenges]
        if not assigned_ids:
            query = query.filter(User.id.is_(None))
        else:
            query = query.filter(User.role == "competitor", User.challenge_id.in_(assigned_ids))
            if challenge_id_filter is not None and challenge_id_filter not in assigned_ids:
                query = query.filter(User.id.is_(None))
    else:
        if role_filter:
            query = query.filter_by(role=role_filter)
        if challenge_id_filter is not None:
            query = query.filter_by(challenge_id=challenge_id_filter)

    # Fetch all challenges to cache started status
    challenges = Challenge.query.all()
    started_challenge_ids = {c.id for c in challenges if c.is_started}

    if not search_term:
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        return paginated_response(
            [u.to_dict(view_role=request.user["role"]) for u in pagination.items],
            pagination.total,
            pagination.page,
            pagination.pages,
        )

    # Reduce result set via DB query before decrypting
    term = search_term.lower()
    user_role = request.user["role"]
    # Filter by searchable non-encrypted fields first
    filtered_query = query.filter(
        (User.username.ilike(f"%{search_term}%"))
        | (User.alias_id.ilike(f"%{search_term}%"))
        | (User.email.ilike(f"%{search_term}%"))
    )
    candidates = filtered_query.limit(Config.USER_SEARCH_LIMIT).all()
    # If no matches in searchable fields, fall back to full scan for encrypted field matches
    if not candidates:
        candidates = query.limit(Config.USER_SEARCH_LIMIT).all()

    filtered_items = []
    for u in candidates:
        comp_started = u.challenge_id in started_challenge_ids if u.challenge_id else False
        alias_match = term in (u.alias_id or "").lower()

        if user_role == "jury" and comp_started:
            match = alias_match
        else:
            dec_name = decrypt_field(u.name) or ""
            dec_surname = decrypt_field(u.surname) or ""
            full_name = f"{dec_name} {dec_surname}".lower()
            dec_school = decrypt_field(u.school) or ""
            dec_city = decrypt_field(u.city) or ""

            match = (
                alias_match
                or term in (u.username or "").lower()
                or term in (u.email or "").lower()
                or term in dec_name.lower()
                or term in dec_surname.lower()
                or term in full_name
                or term in dec_school.lower()
                or term in dec_city.lower()
            )

        if match:
            filtered_items.append(u)

    total = len(filtered_items)
    start = (page - 1) * per_page
    end = start + per_page
    paginated_items = filtered_items[start:end]

    return paginated_response(
        [u.to_dict(view_role=request.user["role"]) for u in paginated_items],
        total,
        page,
        (total + per_page - 1) // per_page if total > 0 else 1,
    )


@admin_bp.route("/users/<uuid:user_id>", methods=["DELETE"])
@role_required(["admin"])
@api.validate(
    tags=["Admin"],
    security=[{"cookieAuth": []}],
    resp=Response(HTTP_200=MessageResponse, HTTP_422=ErrorResponse),
)
def delete_user(user_id: Any) -> MessageResponse | tuple[FlaskResponse, int]:
    if str(request.user["user_id"]) == str(user_id):
        return err("ERR_CANNOT_DELETE_SELF", 400)

    user = db.session.get(User, user_id)
    if not user:
        return err("ERR_USER_NOT_FOUND", 404)

    log_audit(
        request.user["user_id"],
        "delete",
        "user",
        target_id=user.id,
        details={"username": user.username, "role": user.role},
    )

    # ORM delete per submission — triggers after_delete event for file cleanup
    subs = Submission.query.filter_by(user_id=user_id).all()
    for s in subs:
        db.session.delete(s)
    db.session.delete(user)
    db.session.commit()

    if user.challenge_id:
        from cache_utils import invalidate_leaderboard_cache

        invalidate_leaderboard_cache(user.challenge_id)

    return MessageResponse(message=f"User {user.username} has been deleted successfully.")


@admin_bp.route("/register-user", methods=["POST"])
@role_required(["admin", "jury"])
@jury_access_required
@rate_limit(max_requests=20, window_seconds=60)
@api.validate(
    json=CreateUserSchema,
    tags=["Admin"],
    security=[{"cookieAuth": []}],
    resp=Response(HTTP_201=RegisterUserResponse, HTTP_422=ErrorResponse),
)
def register_user(
    json: CreateUserSchema,
) -> tuple[RegisterUserResponse, int] | tuple[FlaskResponse, int]:
    username, email, password = json.username, json.email, json.password
    name, surname, middle_name = json.name, json.surname, json.middle_name
    birth_date, grade, school, city = json.birth_date, json.grade, json.school, json.city
    role, challenge_id = json.role, json.challenge_id

    if request.user["role"] == "jury" and role != "competitor":
        return err("ERR_JURY_ONLY_COMPETITOR", 403)

    if role == "admin":
        return err("ERR_ADMIN_CLI_ONLY", 403)

    if role == "competitor":
        if not middle_name or not birth_date or not grade or not school or not city:
            return err(
                "ERR_MISSING_DEMOGRAPHICS",
                400,
                message="Middle Name, Birth Date, Grade, School and City are "
                "required for competitor accounts.",
            )
        if not challenge_id:
            return err("ERR_CHALLENGE_ID_REQUIRED", 400)
        challenge = db.session.get(Challenge, challenge_id)
        if not challenge:
            return err("ERR_INVALID_CHALLENGE_ID", 400)

        existing = User.query.filter_by(role="competitor", challenge_id=challenge_id).all()

        if check_duplicate_demographics(
            existing, name, middle_name, surname, birth_date, grade, school, city, decrypt_field
        ):
            return err(
                "ERR_COMPETITOR_ALREADY_REGISTERED",
                400,
                message="A competitor with these demographic "
                "details is already registered for this competition.",
            )
        if challenge.is_started and request.user["role"] != "admin":
            return err("ERR_JURY_REGISTRATION_STARTED", 403)

    if not password:
        password = generate_random_password(12)

    if role in ["competitor", "jury"] and not username:
        username = generate_unique_username(name, surname, role=role)

    if not username:
        return err("ERR_USERNAME_REQUIRED", 400)

    if User.query.filter_by(username=username).first():
        return err("ERR_USERNAME_TAKEN", 400)

    is_anon = json.is_anonymous

    user = User(
        username=username,
        email=email,
        password_hash=generate_password_hash(password, method="pbkdf2:sha256"),
        role=role,
        alias_id=generate_pseudonym(),
        challenge_id=challenge_id if role == "competitor" else None,
        is_anonymous=is_anon,
    )
    user.set_demographics(
        name,
        surname,
        grade,
        school,
        city,
        middle_name=middle_name,
        birth_date=birth_date,
    )
    db.session.add(user)
    db.session.commit()

    jury_challenges = json.jury_challenges
    if role == "jury" and jury_challenges:
        from models import JuryChallenge

        for ch_id in jury_challenges:
            if ch_id:
                assignment = JuryChallenge(jury_id=user.id, challenge_id=ch_id)
                db.session.add(assignment)
        db.session.commit()

    log_audit(
        request.user["user_id"],
        "create",
        "user",
        target_id=user.id,
        details={
            "username": username,
            "role": role,
            "challenge_id": challenge_id if role == "competitor" else None,
        },
    )

    return RegisterUserResponse(
        message=f"{role.capitalize()} registered successfully.",
        generated_username=username,
        generated_password=password,
        user=user.to_dict(view_role=request.user["role"]),
    ), 201


@admin_bp.route("/import-competitors-csv", methods=["POST"])
@role_required(["admin", "jury"])
@rate_limit(max_requests=10, window_seconds=60)
@api.validate(
    tags=["Admin"],
    security=[{"cookieAuth": []}],
    resp=Response(HTTP_201=ImportCompetitorsResponse, HTTP_422=ErrorResponse),
)
def import_competitors_csv() -> tuple[ImportCompetitorsResponse, int] | tuple[FlaskResponse, int]:
    challenge_id = request.form.get("challenge_id") or request.args.get("challenge_id")
    if not challenge_id:
        return err(
            "ERR_CHALLENGE_ID_REQUIRED",
            400,
            message="challenge_id is required for importing competitors.",
        )

    challenge = db.session.get(Challenge, challenge_id)
    if not challenge:
        return err("ERR_INVALID_CHALLENGE_ID", 400)

    # Check if the competition has started
    if challenge.is_started and request.user["role"] != "admin":
        return err(
            "ERR_JURY_REGISTRATION_STARTED",
            403,
            message="Jury members cannot import competitors once the competition has started.",
        )

    if "file" not in request.files:
        return err("ERR_FILE_REQUIRED", 400)
    file = request.files["file"]

    valid_ext, ext_err = validate_extension(file.filename, {".csv"})
    if not valid_ext:
        return err("ERR_FILE_INVALID", 400, message=ext_err)

    if file.content_length and file.content_length > 50 * 1024 * 1024:
        return err("ERR_FILE_TOO_LARGE", 400, message="CSV file exceeds 50MB limit")

    raw = file.read()
    if len(raw) > 50 * 1024 * 1024:
        return err("ERR_FILE_TOO_LARGE", 400, message="CSV file exceeds 50MB limit")
    valid_content, content_err, _ = validate_csv_content(raw)
    if not valid_content:
        return err("ERR_CSV_PARSE_FAILED", 400, message=content_err)

    try:
        stream = io.StringIO(raw.decode("UTF8"), newline=None)
        csv_reader = csv.DictReader(stream)

        # Standardize headers to handle synonyms and casing
        normalized_headers = []
        header_mapping = {}
        for f in csv_reader.fieldnames:
            normalized = f.strip().lower().replace(" ", "_")
            if normalized in ("middle_name", "middle name", "patronymic"):
                normalized = "middle_name"
            elif normalized in (
                "birth_date",
                "birth date",
                "date_of_birth",
                "date of birth",
                "birthday",
                "birth_day",
            ):
                normalized = "birth_date"
            header_mapping[f] = normalized
            normalized_headers.append(normalized)

        required = [
            "name",
            "surname",
            "middle_name",
            "birth_date",
            "grade",
            "school",
            "city",
        ]
        for r in required:
            if r not in normalized_headers:
                readable_name = r.replace("_", " ")
                return err(
                    "ERR_CSV_MISSING_COLUMN",
                    400,
                    message=f"CSV missing required column: '{readable_name}'",
                )

        # Fetch existing competitors in this challenge to prevent duplicate rows
        existing_competitors = User.query.filter_by(
            role="competitor", challenge_id=challenge_id
        ).all()

        seen_demographics = set()
        for c in existing_competitors:
            seen_demographics.add(demographics_tuple(c, decrypt_field=decrypt_field))

        imported = []
        for row in csv_reader:
            # Map row keys to normalized keys
            mapped_row = {header_mapping[k]: v for k, v in row.items() if k in header_mapping}
            name = mapped_row.get("name", "").strip()
            surname = mapped_row.get("surname", "").strip()
            middle_name = mapped_row.get("middle_name", "").strip()
            birth_date = mapped_row.get("birth_date", "").strip()
            email = mapped_row.get("email", "").strip() or None
            grade = mapped_row.get("grade", "").strip()
            school = mapped_row.get("school", "").strip()
            city = mapped_row.get("city", "").strip()

            if (
                not name
                or not surname
                or not middle_name
                or not birth_date
                or not grade
                or not school
                or not city
            ):
                continue

            # Check duplicate demographics
            demo_tuple = demographics_tuple(
                {
                    "name": name,
                    "middle_name": middle_name,
                    "surname": surname,
                    "birth_date": birth_date,
                    "grade": grade,
                    "school": school,
                    "city": city,
                }
            )
            if demo_tuple in seen_demographics:
                continue
            seen_demographics.add(demo_tuple)

            username = generate_unique_username(name, surname)
            password = generate_random_password(12)

            # Anonymity preference: accepts column names
            # 'anonymous' or 'is_anonymous'. Can be 1 or 0, default is 0.

            is_anon_val = mapped_row.get("anonymous")
            if is_anon_val is None:
                is_anon_val = mapped_row.get("is_anonymous")

            is_anon = False
            if is_anon_val is not None:
                is_anon_clean = is_anon_val.strip().lower()
                if is_anon_clean in ("1", "true", "yes"):
                    is_anon = True

            user = User(
                username=username,
                password_hash=generate_password_hash(password, method="pbkdf2:sha256"),
                role="competitor",
                alias_id=generate_pseudonym(),
                challenge_id=challenge_id,
                is_anonymous=is_anon,
                email=email,
            )
            user.set_demographics(
                name,
                surname,
                grade,
                school,
                city,
                middle_name=middle_name,
                birth_date=birth_date,
            )
            db.session.add(user)
            db.session.flush()
            imported.append(
                {
                    "id": str(user.id),
                    "name": name,
                    "middle_name": middle_name,
                    "surname": surname,
                    "birth_date": birth_date,
                    "email": email,
                    "grade": grade,
                    "school": school,
                    "city": city,
                    "role": "competitor",
                    "is_anonymous": is_anon,
                    "generated_username": username,
                    "generated_password": password,
                    "alias_id": user.alias_id,
                }
            )

        db.session.commit()

        log_audit(
            request.user["user_id"],
            "import_competitors",
            "user",
            details={"challenge_id": challenge_id, "count": len(imported)},
        )

        invalidate_leaderboard_cache(challenge_id)
        return ImportCompetitorsResponse(
            message=f"Successfully imported {len(imported)} competitors.",
            competitors=imported,
        ), 201

    except Exception as e:
        db.session.rollback()
        return err("ERR_CSV_PARSE_FAILED", 400, message=f"Failed to parse CSV file: {e!s}")


BACKUPS_DIR = Config.BACKUPS_DIR


def _list_backup_files(directory: str) -> list[dict[str, Any]]:
    if not os.path.isdir(directory):
        return []
    files = []
    for f in sorted(os.listdir(directory), reverse=True):
        if not f.endswith(".tar.gz"):
            continue
        path = os.path.join(directory, f)
        ftype = "manual"
        if f.startswith("auto_"):
            ftype = "auto"
        elif (
            f.startswith("submission_ended")
            or f.startswith("grace_ended")
            or f.startswith("finalized")
        ):
            ftype = "competition"
        files.append(
            {
                "filename": f,
                "size_mb": (
                    round(os.path.getsize(path) / (1024 * 1024), 2) if os.path.isfile(path) else 0
                ),
                "created_at": datetime.utcfromtimestamp(os.path.getctime(path)).isoformat(),
                "type": ftype,
            }
        )
    return files


@admin_bp.route("/backups", methods=["GET"])
@role_required(["admin"])
@api.validate(
    tags=["Admin"], security=[{"cookieAuth": []}], resp=Response(HTTP_200=BackupListResponse)
)
def list_backups() -> BackupListResponse:
    return BackupListResponse(backups=_list_backup_files(BACKUPS_DIR))


@admin_bp.route("/backups/force", methods=["POST"])
@role_required(["admin"])
@rate_limit(max_requests=5, window_seconds=60)
@api.validate(
    tags=["Admin"], security=[{"cookieAuth": []}], resp=Response(HTTP_202=BackupStartResponse)
)
def force_backup() -> BackupStartResponse | tuple[BackupStartResponse, int]:
    log_audit(request.user["user_id"], "create", "backup", details={"auto": False})
    from tasks import run_backup

    task = run_backup.delay(auto=False)
    return BackupStartResponse(task_id=task.id, status="started"), 202


@admin_bp.route("/backups/live", methods=["GET"])
@role_required(["admin"])
@api.validate(resp=Response(HTTP_200=None), tags=["SSE Streaming"], security=[{"cookieAuth": []}])
def stream_backup_status() -> tuple[FlaskResponse, int, dict[str, str]]:

    def event_generator():
        user_id = request.user["user_id"]
        with sse_connection_limit(user_id=user_id) as allowed:
            if not allowed:
                yield f"data: {json.dumps({'error': 'too many connections'})}\n\n"
                return

            with current_app.app_context():
                yield f"data: {json.dumps({'backups': _list_backup_files(BACKUPS_DIR)})}\n\n"

            r = get_redis_client()
            pubsub = r.pubsub() if r else None
            if pubsub:
                pubsub.subscribe("backup_status")
            start_time = time.time()
            try:
                while True:
                    if time.time() - start_time > SSE_IDLE_TIMEOUT:
                        yield f"data: {json.dumps({'event': 'timeout'})}\n\n"
                        break
                    if pubsub:
                        message = pubsub.get_message(ignore_subscribe_messages=True, timeout=10.0)
                        if message:
                            with current_app.app_context():
                                data = {
                                    "backups": _list_backup_files(BACKUPS_DIR),
                                    "event": json.loads(message["data"]),
                                }
                                yield f"data: {json.dumps(data)}\n\n"
                                continue
                    else:
                        time.sleep(10.0)
                    yield ": keep-alive\n\n"
            except GeneratorExit:
                pass
            finally:
                if pubsub:
                    with contextlib.suppress(Exception):
                        pubsub.unsubscribe()
                        pubsub.close()

    return sse_response(event_generator)


@admin_bp.route("/backups/<path:filename>/download", methods=["GET"])
@role_required(["admin"])
@rate_limit(max_requests=10, window_seconds=60)
@api.validate(
    resp=Response(HTTP_200=None, HTTP_403=ErrorResponse, HTTP_404=ErrorResponse),
    tags=["Admin"],
    security=[{"cookieAuth": []}],
)
def download_backup_file(
    filename: str,
) -> tuple[bytes, int, dict[str, str]] | tuple[FlaskResponse, int]:
    safe_path = os.path.abspath(os.path.join(BACKUPS_DIR, filename))
    if not safe_path.startswith(os.path.abspath(BACKUPS_DIR)):
        return err("ERR_INVALID_PATH", 403)
    if not os.path.isfile(safe_path):
        return err("ERR_NOT_FOUND", 404, message="Not found")
    with open(safe_path, "rb") as fh:
        file_data = fh.read()
    return (
        file_data,
        200,
        {
            "Content-Type": "application/octet-stream",
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@admin_bp.route("/backups/<path:filename>", methods=["DELETE"])
@role_required(["admin"])
@api.validate(
    tags=["Admin"],
    security=[{"cookieAuth": []}],
    resp=Response(HTTP_200=MessageResponse, HTTP_422=ErrorResponse),
)
def delete_backup_file(filename: str) -> MessageResponse | tuple[FlaskResponse, int]:
    if filename.startswith("auto_"):
        return err("ERR_NO_AUTO_BACKUP_DELETE", 403)
    safe_path = os.path.abspath(os.path.join(BACKUPS_DIR, filename))
    if not safe_path.startswith(os.path.abspath(BACKUPS_DIR)):
        return err("ERR_INVALID_PATH", 403)
    if not os.path.isfile(safe_path):
        return err("ERR_NOT_FOUND", 404, message="Not found")
    os.remove(safe_path)
    log_audit(request.user["user_id"], "delete", "backup", details={"filename": filename})
    return MessageResponse(message="Deleted.")


@admin_bp.route("/audit-logs", methods=["GET"])
@role_required(["admin"])
@api.validate(
    tags=["Admin"],
    security=[{"cookieAuth": []}],
    resp=Response(HTTP_200=AuditLinkListResponse, HTTP_422=ErrorResponse),
)
def get_audit_logs() -> AuditLinkListResponse | tuple[FlaskResponse, int]:
    page, per_page = extract_pagination(request, default_per_page=15, max_per_page=100)
    challenge_id = request.args.get("challenge_id")
    action_type = request.args.get("action_type")
    query = AuditLog.query

    if challenge_id:
        challenge = db.get_or_404(Challenge, challenge_id)
        stage_ids = [s.id for s in challenge.stages]
        task_ids = [t.id for t in challenge.tasks]
        competitor_ids = [
            u.id for u in User.query.filter_by(role="competitor", challenge_id=challenge.id).all()
        ]

        conditions = [(AuditLog.target_type == "challenge") & (AuditLog.target_id == challenge.id)]
        if stage_ids:
            conditions.append(
                (AuditLog.target_type == "stage") & (AuditLog.target_id.in_(stage_ids))
            )
        if task_ids:
            conditions.append((AuditLog.target_type == "task") & (AuditLog.target_id.in_(task_ids)))
            conditions.append(AuditLog.task_id.in_(task_ids))
        if competitor_ids:
            conditions.append(
                (AuditLog.target_type == "user") & (AuditLog.target_id.in_(competitor_ids))
            )
            conditions.append(AuditLog.target_user_id.in_(competitor_ids))

        query = query.filter(or_(*conditions))

    if action_type:
        query = query.filter(AuditLog.action_type == action_type)

    paginated = query.order_by(AuditLog.timestamp.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return AuditLinkListResponse(
        logs=[log.to_dict() for log in paginated.items],
        total=paginated.total,
        pages=paginated.pages,
        page=paginated.page,
        per_page=paginated.per_page,
    )


@admin_bp.route("/users/<uuid:user_id>", methods=["PUT"])
@role_required(["admin", "jury"])
@jury_access_required
@api.validate(
    json=UpdateUserSchema,
    tags=["Admin"],
    security=[{"cookieAuth": []}],
    resp=Response(HTTP_200=UpdateUserResponse, HTTP_422=ErrorResponse),
)
def update_user(
    user_id: Any, json: UpdateUserSchema
) -> UpdateUserResponse | tuple[FlaskResponse, int]:
    user = db.get_or_404(User, user_id)
    current_role = request.user["role"]
    old_challenge_id = user.challenge_id

    if current_role == "jury":
        if user.role in ("admin", "jury"):
            return err("ERR_JURY_CANNOT_EDIT_ADMIN", 403)

        if user.challenge_id:
            challenge = db.session.get(Challenge, user.challenge_id)
            if challenge and challenge.is_started:
                return err("ERR_CANNOT_EDIT_STARTED", 403)

    name = json.name
    surname = json.surname
    middle_name = json.middle_name
    birth_date = json.birth_date
    grade = json.grade
    school = json.school
    city = json.city
    email = json.email
    username = json.username
    challenge_id = json.challenge_id
    password = json.password
    is_anonymous = json.is_anonymous
    role = json.role
    jury_challenges = json.jury_challenges

    if is_anonymous is not None:
        user.is_anonymous = is_anonymous

    if role is not None:
        if role == "admin" and user.role != "admin":
            return err("ERR_CANNOT_CHANGE_ROLE_ADMIN", 403)
        user.role = role

    if jury_challenges is not None:
        from models import JuryChallenge

        JuryChallenge.query.filter_by(jury_id=user.id).delete()
        for ch_id in jury_challenges:
            if ch_id:
                assignment = JuryChallenge(jury_id=user.id, challenge_id=ch_id)
                db.session.add(assignment)

    if challenge_id is not None and challenge_id != "" and challenge_id != user.challenge_id:
        target_challenge_id = str(challenge_id)
        if current_role == "jury":
            from models import JuryChallenge

            assigned = JuryChallenge.query.filter_by(
                jury_id=request.user["user_id"], challenge_id=target_challenge_id
            ).first()
            if not assigned:
                return err(
                    "ERR_ACCESS_DENIED",
                    403,
                    message="Access denied. You are not assigned to this competition.",
                )
            challenge = db.session.get(Challenge, target_challenge_id)
            if challenge and challenge.is_started:
                return err("ERR_CANNOT_ASSIGN_STARTED", 403)
        user.challenge_id = target_challenge_id
    elif challenge_id == "":
        user.challenge_id = None

    dec_name = decrypt_field(user.name)
    dec_surname = decrypt_field(user.surname)
    dec_middle_name = decrypt_field(user.middle_name) if getattr(user, "middle_name", None) else ""
    dec_birth_date = decrypt_field(user.birth_date) if getattr(user, "birth_date", None) else ""
    dec_grade = decrypt_field(user.grade)
    dec_school = decrypt_field(user.school)
    dec_city = decrypt_field(user.city)

    new_name = name if name is not None else dec_name
    new_surname = surname if surname is not None else dec_surname
    new_middle_name = middle_name if middle_name is not None else dec_middle_name
    new_birth_date = birth_date if birth_date is not None else dec_birth_date
    new_grade = grade if grade is not None else dec_grade
    new_school = school if school is not None else dec_school
    new_city = city if city is not None else dec_city

    demo_fields = {"name", "surname", "middle_name", "birth_date", "grade", "school", "city"}
    changed_demographics = json.model_fields_set & demo_fields
    if user.role == "competitor" and (changed_demographics or role == "competitor"):
        if (
            not new_name
            or not new_surname
            or not new_middle_name
            or not new_birth_date
            or not new_grade
            or not new_school
            or not new_city
        ):
            return err(
                "ERR_MISSING_DEMOGRAPHICS",
                400,
                message="Name, Surname, Middle Name, Birth Date, Grade, School "
                "and City are required for competitor accounts.",
            )

        existing = User.query.filter_by(role="competitor", challenge_id=user.challenge_id).all()

        if check_duplicate_demographics(
            existing,
            new_name,
            new_middle_name,
            new_surname,
            new_birth_date,
            new_grade,
            new_school,
            new_city,
            decrypt_field,
            exclude_id=user.id,
        ):
            return err(
                "ERR_COMPETITOR_ALREADY_REGISTERED",
                400,
                message="A competitor with these demographic "
                "details is already registered for this competition.",
            )

    user.set_demographics(
        new_name,
        new_surname,
        new_grade,
        new_school,
        new_city,
        middle_name=new_middle_name,
        birth_date=new_birth_date,
    )

    if email is not None:
        user.email = email

    if username is not None and username != user.username:
        existing = User.query.filter_by(username=username).first()
        if existing:
            return err("ERR_USERNAME_TAKEN", 400, message="Username is already taken.")
        user.username = username

    if password:
        user.password_hash = generate_password_hash(password, method="pbkdf2:sha256")

    db.session.commit()

    if old_challenge_id:
        invalidate_leaderboard_cache(old_challenge_id)
    if user.challenge_id and user.challenge_id != old_challenge_id:
        invalidate_leaderboard_cache(user.challenge_id)

    log_audit(
        request.user["user_id"],
        "update",
        "user",
        target_id=user.id,
        details={"username": user.username},
    )
    return UpdateUserResponse(
        message="User updated successfully.",
        user=user.to_dict(view_role=request.user["role"]),
    )


@admin_bp.route("/users/<uuid:user_id>/reset-password", methods=["POST"])
@role_required(["admin", "jury"])
@jury_access_required
@rate_limit(max_requests=10, window_seconds=60)
@api.validate(
    tags=["Admin"],
    security=[{"cookieAuth": []}],
    resp=Response(HTTP_200=ResetPasswordResponse, HTTP_422=ErrorResponse),
)
def reset_user_password(user_id: Any) -> ResetPasswordResponse | tuple[FlaskResponse, int]:
    user = db.get_or_404(User, user_id)
    # Check if competition has started and requester is jury
    if request.user["role"] == "jury" and user.challenge_id:
        challenge = db.session.get(Challenge, user.challenge_id)
        if challenge and challenge.is_started:
            return err("ERR_CANNOT_RESET_STARTED", 403)

    new_password = generate_random_password(12)
    user.password_hash = generate_password_hash(new_password, method="pbkdf2:sha256")
    db.session.commit()

    log_audit(
        request.user["user_id"],
        "reset_password",
        "user",
        target_id=user.id,
        details={"username": user.username},
    )

    return ResetPasswordResponse(
        message=f"Password reset successfully for {user.username}.",
        username=user.username,
        password=new_password,
    )


@admin_bp.route("/challenges/<uuid:challenge_id>/reset-all-passwords", methods=["POST"])
@role_required(["admin", "jury"])
@jury_access_required
@rate_limit(max_requests=3, window_seconds=300)
@api.validate(
    tags=["Admin"],
    security=[{"cookieAuth": []}],
    resp=Response(HTTP_200=BulkResetPasswordResponse, HTTP_422=ErrorResponse),
)
def reset_all_challenge_passwords(
    challenge_id: Any,
) -> BulkResetPasswordResponse | tuple[FlaskResponse, int]:
    challenge = db.get_or_404(Challenge, challenge_id)
    # Check if competition has started and requester is jury
    if request.user["role"] == "jury" and challenge.is_started:
        return err("ERR_CANNOT_RESET_BULK_STARTED", 403)

    competitors = User.query.filter_by(role="competitor", challenge_id=challenge_id).all()

    results = []
    for user in competitors:
        new_password = generate_random_password(12)
        user.password_hash = generate_password_hash(new_password, method="pbkdf2:sha256")

        # Decrypt demographics for output
        dec_name = decrypt_field(user.name)
        dec_surname = decrypt_field(user.surname)
        dec_middle_name = (
            decrypt_field(user.middle_name) if getattr(user, "middle_name", None) else ""
        )
        dec_birth_date = decrypt_field(user.birth_date) if getattr(user, "birth_date", None) else ""

        results.append(
            {
                "id": str(user.id),
                "username": user.username,
                "name": dec_name or "",
                "middle_name": dec_middle_name or "",
                "surname": dec_surname or "",
                "birth_date": dec_birth_date or "",
                "password": new_password,
                "alias_id": user.alias_id,
                "email": user.email,
            }
        )

    db.session.commit()
    log_audit(
        request.user["user_id"],
        "reset_passwords",
        "user",
        details={"challenge_id": challenge_id, "count": len(competitors)},
    )
    return BulkResetPasswordResponse(
        message=f"Reset passwords for {len(competitors)} competitors.",
        reset_accounts=results,
    )


@admin_bp.route("/challenges/<uuid:challenge_id>/download-scores-csv", methods=["GET"])
@role_required(["admin", "jury"])
@jury_access_required
@rate_limit(max_requests=10, window_seconds=60)
@api.validate(
    resp=Response(HTTP_200=None, HTTP_400=ErrorResponse),
    tags=["Admin"],
    security=[{"cookieAuth": []}],
)
def download_scores_csv(challenge_id: Any) -> FlaskResponse | tuple[FlaskResponse, int]:
    challenge = db.get_or_404(Challenge, challenge_id)
    if not challenge.scores_finalized:
        return err("ERR_SCORES_NOT_FINALIZED", 400)

    csv_data = generate_scores_csv(challenge)

    return FlaskResponse(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-disposition": f"attachment; filename=scores_challenge_{challenge_id}.csv"
        },
    )


@admin_bp.route("/challenges/<uuid:challenge_id>/download-submissions-zip", methods=["GET"])
@role_required(["admin", "jury"])
@jury_access_required
@rate_limit(max_requests=5, window_seconds=120)
@api.validate(
    resp=Response(HTTP_200=None, HTTP_400=ErrorResponse),
    tags=["Admin"],
    security=[{"cookieAuth": []}],
)
def download_submissions_zip(
    challenge_id: Any,
) -> tuple[bytes, int, dict[str, str]] | tuple[FlaskResponse, int]:
    """
    Download completed competitor submissions as a ZIP archive.
    Allows anonymized downloads when a stage or the competition has ended,
    and non-anonymized downloads once finalized.
    """
    challenge = db.get_or_404(Challenge, challenge_id)
    stage_id = request.args.get("stage_id")

    now = utcnow()

    # 1. Determine target stage and tasks
    stage = None
    if stage_id:
        from models import Stage

        stage = db.get_or_404(Stage, stage_id)
        if str(stage.challenge_id) != str(challenge.id):
            return err("ERR_STAGE_MISMATCH", 400)
        tasks = [t for t in challenge.tasks if t.stage_id == stage.id]
    else:
        tasks = list(challenge.tasks)

    # 2. Check if download is allowed
    # Allowed if finalized OR (if stage_id provided,
    # stage has ended) OR (if no stage_id, challenge has ended)

    is_allowed = False
    if (
        challenge.scores_finalized
        or (stage and (stage.is_finalized or stage.end_time < now))
        or (not stage and (challenge.end_time and challenge.end_time < now))
    ):
        is_allowed = True

    if not is_allowed:
        if stage:
            return err("ERR_STAGE_NOT_FINISHED", 400)
        else:
            return err("ERR_COMPETITION_NOT_FINISHED", 400)

    # 3. Determine if anonymized
    is_anonymized = not challenge.scores_finalized

    competitors = User.query.filter_by(role="competitor", challenge_id=challenge_id).all()

    # Batch-load all completed submissions for the challenge to avoid N+1 queries
    comp_ids = [c.id for c in competitors]
    task_ids = [t.id for t in tasks]
    all_subs = Submission.query.filter(
        Submission.task_id.in_(task_ids),
        Submission.user_id.in_(comp_ids),
        Submission.status == "completed",
    ).all()
    subs_by_key: dict[tuple[int, int], list[Submission]] = {}
    for s in all_subs:
        subs_by_key.setdefault((s.user_id, s.task_id), []).append(s)

    # Preload stages for stage name lookup
    stage_ids = {t.stage_id for t in tasks if t.stage_id}
    stages = (
        {s.id: s for s in Stage.query.filter(Stage.id.in_(stage_ids)).all()} if stage_ids else {}
    )

    with (
        tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as zip_tmp,
        zipfile.ZipFile(zip_tmp, "w", zipfile.ZIP_DEFLATED) as zip_file,
    ):
        for comp in competitors:
            if is_anonymized:
                comp_name = comp.alias_id
            else:
                name_part = decrypt_field(comp.name) or ""
                surname_part = decrypt_field(comp.surname) or ""
                comp_name = f"{name_part}_{surname_part}_{comp.alias_id}"

            comp_name = "".join(c for c in comp_name if c.isalnum() or c in (" ", "_", "-")).strip()

            for task in tasks:
                subs = subs_by_key.get((comp.id, task.id), [])
                if not subs:
                    continue

                from services.submission_service import get_best_submission

                best_sub = get_best_submission(task, subs, challenge)

                if best_sub:
                    task_title = "".join(
                        c for c in task.title if c.isalnum() or c in (" ", "_", "-")
                    ).strip()

                    if not stage_id and task.stage_id:
                        task_stage = stages.get(task.stage_id)
                        stage_title = (
                            "".join(
                                c for c in task_stage.title if c.isalnum() or c in (" ", "_", "-")
                            ).strip()
                            if task_stage
                            else "Stage"
                        )
                        filename = f"{comp_name}/{stage_title}/{task_title}_sub_{best_sub.id}.ipynb"
                    else:
                        filename = f"{comp_name}/{task_title}_sub_{best_sub.id}.ipynb"

                    notebook_bytes = wrap_raw_code_cells(best_sub.code_storage_path)
                    if notebook_bytes is None:
                        notebook_bytes = cells_to_ipynb_json([]).encode("utf-8")
                    zip_file.writestr(filename, notebook_bytes)

        if not zip_file.namelist():
            target_desc = f"stage: {stage.title}" if stage else f"challenge: {challenge.title}"
            zip_file.writestr(
                "README.txt",
                f"No completed competitor submissions found for {target_desc}",
            )
    zip_filename = f"submissions_challenge_{challenge_id}"
    if stage_id:
        zip_filename += f"_stage_{stage_id}"
    if is_anonymized:
        zip_filename += "_anonymized"
    zip_filename += ".zip"

    from flask import after_this_request

    @after_this_request
    def cleanup(response):
        with contextlib.suppress(OSError):
            os.unlink(zip_tmp.name)
        return response

    with open(zip_tmp.name, "rb") as fh:
        zip_bytes = fh.read()
    return (
        zip_bytes,
        200,
        {
            "Content-Type": "application/zip",
            "Content-Disposition": f'attachment; filename="{zip_filename}"',
        },
    )


@admin_bp.route("/workers/stats", methods=["GET"])
@role_required(["admin", "jury"])
@api.validate(
    resp=Response(HTTP_200=WorkerStatsResponse), tags=["Admin"], security=[{"cookieAuth": []}]
)
def get_detailed_worker_stats() -> dict[str, Any]:
    return _get_worker_stats_response()


@admin_bp.route("/workers/stats/live", methods=["GET"])
@role_required(["admin", "jury"])
@api.validate(resp=Response(HTTP_200=None), tags=["SSE Streaming"], security=[{"cookieAuth": []}])
def stream_worker_stats() -> tuple[FlaskResponse, int, dict[str, str]]:

    def event_generator():
        user_id = request.user["user_id"]
        with sse_connection_limit(user_id=user_id) as allowed:
            if not allowed:
                yield f"data: {json.dumps({'error': 'too many connections'})}\n\n"
                return

            with current_app.app_context():
                res_data = _get_worker_stats_response()
                yield f"data: {json.dumps(res_data)}\n\n"

            r = get_redis_client()
            pubsub = r.pubsub() if r else None
            if pubsub:
                pubsub.subscribe("worker_stats_update")
            start_time = time.time()

            try:
                while True:
                    if time.time() - start_time > SSE_IDLE_TIMEOUT:
                        yield f"data: {json.dumps({'event': 'timeout'})}\n\n"
                        break
                    if pubsub:
                        message = pubsub.get_message(ignore_subscribe_messages=True, timeout=2.0)
                        if message:
                            with current_app.app_context():
                                res_data = _get_worker_stats_response()
                                yield f"data: {json.dumps(res_data)}\n\n"
                                continue
                    else:
                        time.sleep(2.0)
                    with current_app.app_context():
                        res_data = _get_worker_stats_response()
                        yield f"data: {json.dumps(res_data)}\n\n"
            except GeneratorExit:
                pass
            except Exception as e:
                logger.error("Worker stats SSE error: %s", e)
            finally:
                if pubsub:
                    with contextlib.suppress(Exception):
                        pubsub.unsubscribe()
                        pubsub.close()

    return sse_response(event_generator)


def _get_worker_stats_response() -> dict[str, Any]:

    def _compute():
        import platform
        import subprocess

        # 1. Collect Host System Resources
        system_resources = {
            "cpu_count": os.cpu_count(),
            "load_avg": [0.0, 0.0, 0.0],
            "memory": {
                "total_gb": 0.0,
                "used_gb": 0.0,
                "free_gb": 0.0,
                "percent_used": 0.0,
            },
            "disk": {
                "total_gb": 0.0,
                "used_gb": 0.0,
                "free_gb": 0.0,
                "percent_used": 0.0,
            },
            "os": platform.system(),
            "platform_release": platform.release(),
            "python_version": platform.python_version(),
        }

        # Load average
        try:
            if hasattr(os, "getloadavg"):
                system_resources["load_avg"] = list(os.getloadavg())
        except Exception as e:
            logger.warning("Failed to get load average: %s", e)

        # Disk usage
        try:
            total, used, free = shutil.disk_usage("/")
            system_resources["disk"] = {
                "total_gb": round(total / (1024**3), 2),
                "used_gb": round(used / (1024**3), 2),
                "free_gb": round(free / (1024**3), 2),
                "percent_used": round((used / total) * 100, 1) if total > 0 else 0,
            }
        except Exception as e:
            logger.warning("Failed to get disk usage: %s", e)

        # Memory usage
        try:
            if platform.system() == "Linux":
                if os.path.exists("/proc/meminfo"):
                    with open("/proc/meminfo") as f:
                        lines = f.readlines()
                    mem_info = {}
                    for line in lines:
                        parts = line.split(":")
                        if len(parts) == 2:
                            name = parts[0].strip()
                            val_parts = parts[1].strip().split()
                            if val_parts:
                                mem_info[name] = int(val_parts[0])

                    total_kb = mem_info.get("MemTotal", 0)
                    free_kb = mem_info.get("MemFree", 0)
                    available_kb = mem_info.get("MemAvailable", total_kb - free_kb)
                    used_kb = total_kb - available_kb

                    system_resources["memory"] = {
                        "total_gb": round(total_kb / (1024**2), 2),
                        "used_gb": round(used_kb / (1024**2), 2),
                        "free_gb": round(available_kb / (1024**2), 2),
                        "percent_used": round((used_kb / total_kb) * 100, 1) if total_kb > 0 else 0,
                    }
            elif platform.system() == "Darwin":
                total_bytes = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip())  # noqa: S607
                total_gb = total_bytes / (1024**3)

                vm_stat = subprocess.check_output(["vm_stat"]).decode("utf-8")  # noqa: S607
                pages_free = 0
                pages_active = 0
                pages_inactive = 0
                pages_speculative = 0
                pages_wire = 0
                page_size = 4096

                for line in vm_stat.split("\n"):
                    if "page size of" in line:
                        with contextlib.suppress(Exception):
                            page_size = int(line.split("page size of")[1].split("bytes")[0].strip())
                    elif "Pages free:" in line:
                        pages_free = int(line.split(":")[1].strip().replace(".", ""))
                    elif "Pages active:" in line:
                        pages_active = int(line.split(":")[1].strip().replace(".", ""))
                    elif "Pages inactive:" in line:
                        pages_inactive = int(line.split(":")[1].strip().replace(".", ""))
                    elif "Pages speculative:" in line:
                        pages_speculative = int(line.split(":")[1].strip().replace(".", ""))
                    elif "Pages wired down:" in line:
                        pages_wire = int(line.split(":")[1].strip().replace(".", ""))

                used_bytes = (pages_active + pages_wire) * page_size
                free_bytes = (pages_free + pages_speculative + pages_inactive) * page_size

                system_resources["memory"] = {
                    "total_gb": round(total_gb, 2),
                    "used_gb": round(used_bytes / (1024**3), 2),
                    "free_gb": round(free_bytes / (1024**3), 2),
                    "percent_used": (
                        round((used_bytes / total_bytes) * 100, 1) if total_bytes > 0 else 0
                    ),
                }
        except Exception as e:
            logger.warning("Failed to get memory usage: %s", e)

        # 2. Collect Celery Worker Statistics
        from tasks import celery

        inspect = celery.control.inspect(timeout=1.0)

        pings = inspect.ping() or {}
        stats = inspect.stats() or {}
        active = inspect.active() or {}
        reserved = inspect.reserved() or {}
        registered = inspect.registered() or {}

        r = None
        try:
            from cache_utils import get_redis_client

            r = get_redis_client()
        except Exception:
            r = None

        workers_list = []
        for worker_name in pings:
            w_stats = stats.get(worker_name, {})
            w_active = active.get(worker_name, [])
            w_reserved = reserved.get(worker_name, [])
            w_registered = registered.get(worker_name, [])

            pool = w_stats.get("pool", {})
            broker = w_stats.get("broker", {})
            total_tasks = w_stats.get("total", {})
            w_rusage = w_stats.get("rusage", {})

            rusage_formatted = {}
            if w_rusage:
                maxrss = w_rusage.get("maxrss", 0)
                maxrss_mb = (
                    round(maxrss / (1024 * 1024), 2)
                    if platform.system() == "Darwin"
                    else round(maxrss / 1024, 2)
                )
                rusage_formatted = {
                    "utime_sec": w_rusage.get("utime"),
                    "stime_sec": w_rusage.get("stime"),
                    "maxrss_mb": maxrss_mb,
                }

            spec = None
            if r:
                try:
                    spec_data = r.get(f"worker_spec:{worker_name}")
                    if spec_data:
                        spec = json.loads(spec_data)
                except Exception as e:
                    logger.warning("Failed to retrieve worker spec for %s: %s", worker_name, e)

            has_gpu = "gpu" in worker_name.lower()
            if spec:
                gpu_type = spec.get("gpu_type", "NVIDIA GPU" if has_gpu else "N/A")
                vram_gb = spec.get("vram_gb", 8.0 if has_gpu else "N/A")
                ram_gb = spec.get("ram_gb", 16.0 if has_gpu else 8.0)
                worker_type = spec.get("type", "GPU" if has_gpu else "CPU")
            else:
                gpu_type = "NVIDIA GPU" if has_gpu else "N/A"
                vram_gb = 8.0 if has_gpu else "N/A"
                ram_gb = 16.0 if has_gpu else 8.0
                worker_type = "GPU" if has_gpu else "CPU"

            workers_list.append(
                {
                    "name": worker_name,
                    "status": "online",
                    "type": worker_type,
                    "gpu_type": gpu_type,
                    "vram_gb": vram_gb,
                    "ram_gb": ram_gb,
                    "pid": w_stats.get("pid"),
                    "uptime": w_stats.get("uptime"),
                    "pool_size": pool.get("max-concurrency", 0),
                    "total_tasks_processed": sum(total_tasks.values()) if total_tasks else 0,
                    "active_tasks_count": len(w_active),
                    "reserved_tasks_count": len(w_reserved),
                    "active_tasks": w_active,
                    "reserved_tasks": w_reserved,
                    "registered_tasks": w_registered,
                    "rusage": rusage_formatted,
                    "broker": {
                        "transport": broker.get("transport"),
                        "hostname": broker.get("hostname"),
                        "port": broker.get("port"),
                    },
                }
            )

        return {
            "connected_workers_count": len(workers_list),
            "workers": workers_list,
            "system": system_resources,
        }

    try:
        return cached_or_compute_unless_testing("worker:status:detailed", _compute, timeout=10)
    except Exception as e:
        return {
            "connected_workers_count": 0,
            "workers": [],
            "system": {
                "cpu_count": os.cpu_count(),
                "load_avg": [0.0, 0.0, 0.0],
                "memory": {"total_gb": 0.0, "used_gb": 0.0, "free_gb": 0.0, "percent_used": 0.0},
                "disk": {"total_gb": 0.0, "used_gb": 0.0, "free_gb": 0.0, "percent_used": 0.0},
            },
            "error": str(e),
        }


@admin_bp.route("/dead-letters", methods=["GET"])
@role_required(["admin"])
@api.validate(
    tags=["Admin"], security=[{"cookieAuth": []}], resp=Response(HTTP_200=DeadLetterListResponse)
)
def get_dead_letters() -> tuple[DeadLetterListResponse, int]:
    r = get_redis_client()
    if not r:
        return DeadLetterListResponse(items=[]), 200
    try:
        entries = r.lrange("dead_letter_queue", 0, -1)
        items = [json.loads(e) for e in entries]
        return DeadLetterListResponse(items=items), 200
    except Exception:
        return DeadLetterListResponse(items=[]), 200
