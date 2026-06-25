import os
import csv
import io
import re
import secrets
import string
import json
import zipfile
import logging
from datetime import datetime
from flask import (
    Blueprint,
    request,
    jsonify,
    send_file,
    current_app,
    Response,
    stream_with_context,
)
from werkzeug.security import generate_password_hash
from models import (
    db,
    User,
    Challenge,
    Submission,
    generate_pseudonym,
    decrypt_field,
    to_base36,
)
from auth_utils import role_required, jury_access_required
from evaluation_engine import AVAILABLE_METRICS

logger = logging.getLogger(__name__)
admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/metrics", methods=["GET"])
@role_required(["admin", "jury"])
def get_available_metrics():
    """
    List all built-in evaluation metrics available for task configuration.
    ---
    tags:
      - Admin
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
    return jsonify(AVAILABLE_METRICS), 200


def transliterate_bulgarian(text):
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


def generate_unique_username(name, surname, role="competitor"):
    import time

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


def generate_random_password(length=12):
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(chars) for _ in range(length))


# --- ENDPOINTS ---


@admin_bp.route("/register-competitor", methods=["POST"])
@role_required(["admin", "jury"])
@jury_access_required
def register_competitor():
    """
    Register a new competitor with auto-generated credentials.
    ---
    tags:
      - Admin
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
    name = data.get("name")
    surname = data.get("surname")
    middle_name = data.get("middle_name")
    birth_date = data.get("birth_date")
    grade = data.get("grade")
    school = data.get("school")
    city = data.get("city")
    challenge_id = data.get("challenge_id")

    if not challenge_id:
        return jsonify({"error": "challenge_id is required for competitor registration."}), 400

    challenge = db.session.get(Challenge, challenge_id)
    if not challenge:
        return jsonify({"error": "Invalid challenge_id."}), 400

    # Check if the competition has started
    if challenge.is_started:
        if request.user["role"] != "admin":
            return (
                jsonify(
                    {
                        "error": "Jury members cannot register competitors once the competition has started."
                    }
                ),
                403,
            )

    if (
        not name
        or not surname
        or not middle_name
        or not birth_date
        or not grade
        or not school
        or not city
    ):
        return (
            jsonify(
                {
                    "error": "Name, Surname, Middle Name, Birth Date, Grade, School and City are required."
                }
            ),
            400,
        )

    # Check if a competitor with the same demographics is already registered for this competition
    competitors = User.query.filter_by(role="competitor", challenge_id=challenge_id).all()
    norm = lambda s: s.strip().lower() if s else ""
    target_name = norm(name)
    target_middle = norm(middle_name)
    target_surname = norm(surname)
    target_birth = norm(birth_date)
    target_grade = norm(grade)
    target_school = norm(school)
    target_city = norm(city)

    for c in competitors:
        if (
            norm(decrypt_field(c.name)) == target_name
            and norm(decrypt_field(c.middle_name)) == target_middle
            and norm(decrypt_field(c.surname)) == target_surname
            and norm(decrypt_field(c.birth_date)) == target_birth
            and norm(decrypt_field(c.grade)) == target_grade
            and norm(decrypt_field(c.school)) == target_school
            and norm(decrypt_field(c.city)) == target_city
        ):
            return (
                jsonify(
                    {
                        "error": "A competitor with these demographic details is already registered for this competition.",
                        "code": "ERR_COMPETITOR_ALREADY_REGISTERED",
                    }
                ),
                400,
            )

    username = generate_unique_username(name, surname)
    password = generate_random_password(12)

    user = User(
        username=username,
        password_hash=generate_password_hash(password, method="pbkdf2:sha256"),
        role="competitor",
        alias_id=generate_pseudonym(),
        challenge_id=challenge_id,
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

    from services.audit_service import log_action

    log_action(
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

    from cache_utils import invalidate_leaderboard_cache

    invalidate_leaderboard_cache(challenge_id)

    return (
        jsonify(
            {
                "message": "Competitor registered successfully.",
                "generated_username": username,
                "generated_password": password,
                "user": user.to_dict(view_role=request.user["role"]),
            }
        ),
        201,
    )


@admin_bp.route("/users", methods=["GET"])
@role_required(["admin", "jury"])
def get_users():
    """
    List and search users with pagination. Supports filtering by role and challenge.
    ---
    tags:
      - Admin
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
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 10, type=int), 100)
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
            query = query.filter(User.id == None)
        else:
            query = query.filter(User.role == "competitor", User.challenge_id.in_(assigned_ids))
            if challenge_id_filter is not None:
                if challenge_id_filter not in assigned_ids:
                    query = query.filter(User.id == None)
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
        return jsonify(
            {
                "items": [u.to_dict(view_role=request.user["role"]) for u in pagination.items],
                "total": pagination.total,
                "page": pagination.page,
                "pages": pagination.pages,
            }
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
    candidates = filtered_query.all()
    # If no matches in searchable fields, fall back to full scan for encrypted field matches
    if not candidates:
        candidates = query.all()

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

    return jsonify(
        {
            "items": [u.to_dict(view_role=request.user["role"]) for u in paginated_items],
            "total": total,
            "page": page,
            "pages": (total + per_page - 1) // per_page if total > 0 else 1,
        }
    )


@admin_bp.route("/users/<uuid:user_id>", methods=["DELETE"])
@role_required(["admin"])
def delete_user(user_id):
    """
    Permanently delete a user and all their submissions.
    ---
    tags:
      - Admin
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: user_id
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
    if str(request.user["user_id"]) == str(user_id):
        return jsonify({"error": "You cannot delete your own admin account."}), 400

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found."}), 404

    from services.audit_service import log_action

    log_action(
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

    return jsonify({"message": f"User {user.username} has been deleted successfully."})


@admin_bp.route("/register-user", methods=["POST"])
@role_required(["admin", "jury"])
@jury_access_required
def register_user():
    """
    Register a new user account with specified role and demographics.
    ---
    tags:
      - Admin
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
    username = data.get("username")
    email = data.get("email")
    password = data.get("password")
    name = data.get("name")
    surname = data.get("surname")
    middle_name = data.get("middle_name")
    birth_date = data.get("birth_date")
    grade = data.get("grade")
    school = data.get("school")
    city = data.get("city")
    role = data.get("role")
    challenge_id = data.get("challenge_id")

    if not role or role not in ["competitor", "jury", "admin"]:
        return jsonify({"error": "Valid role is required."}), 400

    if request.user["role"] == "jury" and role != "competitor":
        return jsonify({"error": "Jury members can only register competitor accounts."}), 403

    # STRICT CONSTRAINT: Only server-side CLI can register an Administrator (admin)
    if role == "admin":
        return (
            jsonify(
                {
                    "error": "Administrator accounts can only be generated directly on the server command line (CLI)."
                }
            ),
            403,
        )

    if not name or not surname:
        return jsonify({"error": "Name and Surname are required."}), 400

    if role == "competitor":
        if not middle_name or not birth_date or not grade or not school or not city:
            return (
                jsonify(
                    {
                        "error": "Middle Name, Birth Date, Grade, School and City are required for competitor accounts."
                    }
                ),
                400,
            )
        if not challenge_id:
            return jsonify({"error": "challenge_id is required for competitor registration."}), 400
        challenge = db.session.get(Challenge, challenge_id)
        if not challenge:
            return jsonify({"error": "Invalid challenge_id."}), 400

        # Check if a competitor with the same demographics is already registered for this competition
        competitors = User.query.filter_by(role="competitor", challenge_id=challenge_id).all()
        norm = lambda s: s.strip().lower() if s else ""
        target_name = norm(name)
        target_middle = norm(middle_name)
        target_surname = norm(surname)
        target_birth = norm(birth_date)
        target_grade = norm(grade)
        target_school = norm(school)
        target_city = norm(city)

        for c in competitors:
            if (
                norm(decrypt_field(c.name)) == target_name
                and norm(decrypt_field(c.middle_name)) == target_middle
                and norm(decrypt_field(c.surname)) == target_surname
                and norm(decrypt_field(c.birth_date)) == target_birth
                and norm(decrypt_field(c.grade)) == target_grade
                and norm(decrypt_field(c.school)) == target_school
                and norm(decrypt_field(c.city)) == target_city
            ):
                return (
                    jsonify(
                        {
                            "error": "A competitor with these demographic details is already registered for this competition.",
                            "code": "ERR_COMPETITOR_ALREADY_REGISTERED",
                        }
                    ),
                    400,
                )
        # Check if the competition has started
        if challenge.is_started:
            if request.user["role"] != "admin":
                return (
                    jsonify(
                        {
                            "error": "Jury members cannot register competitors once the competition has started."
                        }
                    ),
                    403,
                )

    if not password:
        password = generate_random_password(12)

    # Pregenerate username for competitors and judges (jury) if not provided
    if role in ["competitor", "jury"] and not username:
        username = generate_unique_username(name, surname, role=role)

    if not username:
        return jsonify({"error": "Username is required."}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({"error": "User with this username already exists."}), 400

    is_anon = bool(data.get("is_anonymous", False))

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

    jury_challenges = data.get("jury_challenges")
    if role == "jury" and jury_challenges:
        from models import JuryChallenge

        for ch_id in jury_challenges:
            if ch_id:
                assignment = JuryChallenge(jury_id=user.id, challenge_id=ch_id)
                db.session.add(assignment)
        db.session.commit()

    from services.audit_service import log_action

    log_action(
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

    return (
        jsonify(
            {
                "message": f"{role.capitalize()} registered successfully.",
                "generated_username": username,
                "generated_password": password,
                "user": user.to_dict(view_role=request.user["role"]),
            }
        ),
        201,
    )


@admin_bp.route("/import-competitors-csv", methods=["POST"])
@role_required(["admin", "jury"])
def import_competitors_csv():
    """
    Bulk import competitors from a CSV file.
    ---
    tags:
      - Admin
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
    challenge_id = request.form.get("challenge_id") or request.args.get("challenge_id")
    if not challenge_id:
        return jsonify({"error": "challenge_id is required for importing competitors."}), 400

    challenge = db.session.get(Challenge, challenge_id)
    if not challenge:
        return jsonify({"error": "Invalid challenge_id."}), 400

    # Check if the competition has started
    if challenge.is_started:
        if request.user["role"] != "admin":
            return (
                jsonify(
                    {
                        "error": "Jury members cannot import competitors once the competition has started."
                    }
                ),
                403,
            )

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400
    file = request.files["file"]

    from services.file_validation import validate_extension, validate_csv_content

    valid_ext, ext_err = validate_extension(file.filename, {".csv"})
    if not valid_ext:
        return jsonify({"error": ext_err}), 400

    try:
        raw = file.read()
    except Exception:
        return jsonify({"error": "Failed to read uploaded file."}), 400
    valid_content, content_err, _ = validate_csv_content(raw)
    if not valid_content:
        return jsonify({"error": content_err}), 400

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
                return jsonify({"error": f"CSV missing required column: '{readable_name}'"}), 400

        # Fetch existing competitors in this challenge to prevent duplicate rows
        existing_competitors = User.query.filter_by(
            role="competitor", challenge_id=challenge_id
        ).all()
        norm = lambda s: s.strip().lower() if s else ""
        seen_demographics = set()
        for c in existing_competitors:
            seen_demographics.add(
                (
                    norm(decrypt_field(c.name)),
                    norm(decrypt_field(c.middle_name)),
                    norm(decrypt_field(c.surname)),
                    norm(decrypt_field(c.birth_date)),
                    norm(decrypt_field(c.grade)),
                    norm(decrypt_field(c.school)),
                    norm(decrypt_field(c.city)),
                )
            )

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
            demo_tuple = (
                norm(name),
                norm(middle_name),
                norm(surname),
                norm(birth_date),
                norm(grade),
                norm(school),
                norm(city),
            )
            if demo_tuple in seen_demographics:
                continue
            seen_demographics.add(demo_tuple)

            username = generate_unique_username(name, surname)
            password = generate_random_password(12)

            # Anonymity preference: accepts column names 'anonymous' or 'is_anonymous'. Can be 1 or 0, default is 0.
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
                    "is_anonymous": is_anon,
                    "generated_username": username,
                    "generated_password": password,
                    "alias_id": user.alias_id,
                }
            )

        db.session.commit()

        from services.audit_service import log_action

        log_action(
            request.user["user_id"],
            "import_competitors",
            "user",
            details={"challenge_id": challenge_id, "count": len(imported)},
        )

        from cache_utils import invalidate_leaderboard_cache

        invalidate_leaderboard_cache(challenge_id)
        return (
            jsonify(
                {
                    "message": f"Successfully imported {len(imported)} competitors.",
                    "competitors": imported,
                }
            ),
            201,
        )

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Failed to parse CSV file: {str(e)}"}), 400


BACKUPS_DIR = os.environ.get("BACKUPS_DIR", "/backups")


def _list_backup_files(directory):
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
def list_backups():
    """
    List all system backups with filenames, sizes, and timestamps.
    ---
    tags:
      - Admin
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
    return jsonify({"backups": _list_backup_files(BACKUPS_DIR)})


@admin_bp.route("/backups/force", methods=["POST"])
@role_required(["admin"])
def force_backup():
    """
    Trigger an immediate manual backup of the database and uploaded files.
    ---
    tags:
      - Admin
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
    from services.audit_service import log_action

    log_action(request.user["user_id"], "create", "backup", details={"auto": False})
    from tasks import run_backup

    task = run_backup.delay(auto=False)
    return jsonify({"task_id": task.id, "status": "started"}), 202


@admin_bp.route("/backups/live", methods=["GET"])
@role_required(["admin"])
def stream_backup_status():
    """
    Stream backup events in real-time via Server-Sent Events.
    ---
    tags:
      - SSE Streaming
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

    def event_generator():
        with current_app.app_context():
            yield f"data: {json.dumps({'backups': _list_backup_files(BACKUPS_DIR)})}\n\n"

        from cache_utils import get_redis_client

        r = get_redis_client()
        pubsub = r.pubsub()
        pubsub.subscribe("backup_status")
        try:
            while True:
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=10.0)
                if message:
                    with current_app.app_context():
                        yield f"data: {json.dumps({'backups': _list_backup_files(BACKUPS_DIR), 'event': json.loads(message['data'])})}\n\n"
                else:
                    yield ": keep-alive\n\n"
        except GeneratorExit:
            pass
        finally:
            try:
                pubsub.unsubscribe()
                pubsub.close()
            except Exception:
                pass

    return Response(
        stream_with_context(event_generator()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@admin_bp.route("/backups/<path:filename>/download", methods=["GET"])
@role_required(["admin"])
def download_backup_file(filename):
    """
    Download a specific backup archive file.
    ---
    tags:
      - Admin
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: filename
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
    safe_path = os.path.abspath(os.path.join(BACKUPS_DIR, filename))
    if not safe_path.startswith(os.path.abspath(BACKUPS_DIR)):
        return jsonify({"error": "Invalid path"}), 403
    if not os.path.isfile(safe_path):
        return jsonify({"error": "Not found"}), 404
    return send_file(safe_path, as_attachment=True, download_name=filename)


@admin_bp.route("/backups/<path:filename>", methods=["DELETE"])
@role_required(["admin"])
def delete_backup_file(filename):
    """
    Delete a manual backup file. Auto-backups cannot be deleted.
    ---
    tags:
      - Admin
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: filename
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
    if filename.startswith("auto_"):
        return jsonify({"error": "Auto-backups cannot be deleted manually."}), 403
    safe_path = os.path.abspath(os.path.join(BACKUPS_DIR, filename))
    if not safe_path.startswith(os.path.abspath(BACKUPS_DIR)):
        return jsonify({"error": "Invalid path"}), 403
    if not os.path.isfile(safe_path):
        return jsonify({"error": "Not found"}), 404
    os.remove(safe_path)
    from services.audit_service import log_action

    log_action(request.user["user_id"], "delete", "backup", details={"filename": filename})
    return jsonify({"message": "Deleted."})


@admin_bp.route("/audit-logs", methods=["GET"])
@role_required(["admin"])
def get_audit_logs():
    """
    Get paginated audit logs, optionally filtered by challenge_id and action_type.
    Only available to admins.
    ---
    tags:
      - Admin
    security:
      - cookieAuth: []
    parameters:
      - name: page
        in: query
        schema:
          type: integer
      - name: per_page
        in: query
        schema:
          type: integer
      - name: challenge_id
        in: query
        schema:
          type: string
      - name: action_type
        in: query
        schema:
          type: string
    responses:
      200:
        description: Success
    """
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 15, type=int), 100)
    challenge_id = request.args.get("challenge_id")
    action_type = request.args.get("action_type")

    from models import AuditLog, Challenge, User
    from sqlalchemy import or_

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

    return (
        jsonify(
            {
                "logs": [log.to_dict() for log in paginated.items],
                "total": paginated.total,
                "pages": paginated.pages,
                "page": paginated.page,
                "per_page": paginated.per_page,
            }
        ),
        200,
    )


@admin_bp.route("/users/<uuid:user_id>", methods=["PUT"])
@role_required(["admin", "jury"])
@jury_access_required
def update_user(user_id):
    """
    Update user profile fields. Jury members have restricted edit access.
    ---
    tags:
      - Admin
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: user_id
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
    user = db.get_or_404(User, user_id)
    current_role = request.user["role"]
    old_challenge_id = user.challenge_id

    # Check if the competition has started for jury edits
    if current_role == "jury":
        # Jury cannot edit admin or other jury members
        if user.role in ("admin", "jury"):
            return (
                jsonify(
                    {"error": "Jury members cannot edit administrator or other jury accounts."}
                ),
                403,
            )

        # Check current assigned challenge
        if user.challenge_id:
            challenge = db.session.get(Challenge, user.challenge_id)
            if challenge and challenge.is_started:
                return (
                    jsonify(
                        {"error": "Cannot edit user: The assigned competition has already started."}
                    ),
                    403,
                )

    data = request.json or {}
    name = data.get("name")
    surname = data.get("surname")
    middle_name = data.get("middle_name")
    birth_date = data.get("birth_date")
    grade = data.get("grade")
    school = data.get("school")
    city = data.get("city")
    email = data.get("email")
    username = data.get("username")
    challenge_id = data.get("challenge_id")
    password = data.get("password")
    is_anonymous = data.get("is_anonymous")
    role = data.get("role")
    jury_challenges = data.get("jury_challenges")

    if is_anonymous is not None:
        user.is_anonymous = bool(is_anonymous)

    if role is not None:
        if role in ["competitor", "jury", "admin"]:
            if role == "admin" and user.role != "admin":
                return jsonify({"error": "Cannot change user role to Administrator."}), 403
            user.role = role

    if jury_challenges is not None:
        from models import JuryChallenge

        JuryChallenge.query.filter_by(jury_id=user.id).delete()
        for ch_id in jury_challenges:
            if ch_id:
                assignment = JuryChallenge(jury_id=user.id, challenge_id=ch_id)
                db.session.add(assignment)

    # Check new challenge start time if jury is assigning
    if challenge_id is not None and challenge_id != "" and challenge_id != user.challenge_id:
        target_challenge_id = str(challenge_id)
        if current_role == "jury":
            from models import JuryChallenge

            assigned = JuryChallenge.query.filter_by(
                jury_id=request.user["user_id"], challenge_id=target_challenge_id
            ).first()
            if not assigned:
                return (
                    jsonify(
                        {
                            "error": "Access denied. You are not assigned to this competition.",
                            "code": "ERR_ACCESS_DENIED",
                        }
                    ),
                    403,
                )
            challenge = db.session.get(Challenge, target_challenge_id)
            if challenge and challenge.is_started:
                return (
                    jsonify(
                        {"error": "Cannot assign user to a competition that has already started."}
                    ),
                    403,
                )
        user.challenge_id = target_challenge_id
    elif challenge_id == "":
        user.challenge_id = None

    # Update demographics using fallback decryption
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

    # Validate that middle name, birth date, grade, school and city are present for competitors if they are being updated
    if user.role == "competitor" and (
        "name" in data
        or "surname" in data
        or "middle_name" in data
        or "birth_date" in data
        or "grade" in data
        or "school" in data
        or "city" in data
        or role == "competitor"
    ):
        if (
            not new_name
            or not new_surname
            or not new_middle_name
            or not new_birth_date
            or not new_grade
            or not new_school
            or not new_city
        ):
            return (
                jsonify(
                    {
                        "error": "Name, Surname, Middle Name, Birth Date, Grade, School and City are required for competitor accounts."
                    }
                ),
                400,
            )

        # Check if a competitor with the same demographics is already registered for this competition (excluding this user themselves)
        competitors = User.query.filter_by(role="competitor", challenge_id=user.challenge_id).all()
        norm = lambda s: s.strip().lower() if s else ""
        target_name = norm(new_name)
        target_middle = norm(new_middle_name)
        target_surname = norm(new_surname)
        target_birth = norm(new_birth_date)
        target_grade = norm(new_grade)
        target_school = norm(new_school)
        target_city = norm(new_city)

        for c in competitors:
            if c.id == user.id:
                continue
            if (
                norm(decrypt_field(c.name)) == target_name
                and norm(decrypt_field(c.middle_name)) == target_middle
                and norm(decrypt_field(c.surname)) == target_surname
                and norm(decrypt_field(c.birth_date)) == target_birth
                and norm(decrypt_field(c.grade)) == target_grade
                and norm(decrypt_field(c.school)) == target_school
                and norm(decrypt_field(c.city)) == target_city
            ):
                return (
                    jsonify(
                        {
                            "error": "A competitor with these demographic details is already registered for this competition.",
                            "code": "ERR_COMPETITOR_ALREADY_REGISTERED",
                        }
                    ),
                    400,
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
            return jsonify({"error": "Username is already taken."}), 400
        user.username = username

    if password:
        user.password_hash = generate_password_hash(password, method="pbkdf2:sha256")

    db.session.commit()

    from cache_utils import invalidate_leaderboard_cache

    if old_challenge_id:
        invalidate_leaderboard_cache(old_challenge_id)
    if user.challenge_id and user.challenge_id != old_challenge_id:
        invalidate_leaderboard_cache(user.challenge_id)

    from services.audit_service import log_action

    log_action(
        request.user["user_id"],
        "update",
        "user",
        target_id=user.id,
        details={"username": user.username},
    )
    return jsonify(
        {
            "message": "User updated successfully.",
            "user": user.to_dict(view_role=request.user["role"]),
        }
    )


@admin_bp.route("/users/<uuid:user_id>/reset-password", methods=["POST"])
@role_required(["admin", "jury"])
@jury_access_required
def reset_user_password(user_id):
    """
    Generate a new random password for a specific user.
    ---
    tags:
      - Admin
    security:
      - cookieAuth: []
    parameters:
      - in: path
        name: user_id
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
    user = db.get_or_404(User, user_id)
    # Check if competition has started and requester is jury
    if request.user["role"] == "jury":
        if user.challenge_id:
            challenge = db.session.get(Challenge, user.challenge_id)
            if challenge and challenge.is_started:
                return (
                    jsonify(
                        {
                            "error": "Cannot reset password: The assigned competition has already started."
                        }
                    ),
                    403,
                )

    new_password = generate_random_password(12)
    user.password_hash = generate_password_hash(new_password, method="pbkdf2:sha256")
    db.session.commit()

    from services.audit_service import log_action

    log_action(
        request.user["user_id"],
        "reset_password",
        "user",
        target_id=user.id,
        details={"username": user.username},
    )

    return jsonify(
        {
            "message": f"Password reset successfully for {user.username}.",
            "username": user.username,
            "password": new_password,
        }
    )


@admin_bp.route("/challenges/<uuid:challenge_id>/reset-all-passwords", methods=["POST"])
@role_required(["admin", "jury"])
@jury_access_required
def reset_all_challenge_passwords(challenge_id):
    """
    Generate new passwords for all competitors in a challenge.
    ---
    tags:
      - Admin
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
    # Check if competition has started and requester is jury
    if request.user["role"] == "jury":
        if challenge.is_started:
            return (
                jsonify({"error": "Cannot reset passwords: The competition has already started."}),
                403,
            )

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
    from services.audit_service import log_action

    log_action(
        request.user["user_id"],
        "reset_passwords",
        "user",
        details={"challenge_id": challenge_id, "count": len(competitors)},
    )
    return jsonify(
        {
            "message": f"Reset passwords for {len(competitors)} competitors.",
            "reset_accounts": results,
        }
    )


@admin_bp.route("/challenges/<uuid:challenge_id>/download-scores-csv", methods=["GET"])
@role_required(["admin", "jury"])
@jury_access_required
def download_scores_csv(challenge_id):
    """
    Generate and download a CSV of all competitor scores for a challenge.
    ---
    tags:
      - Admin
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
    from services.challenge_service import generate_scores_csv

    challenge = db.get_or_404(Challenge, challenge_id)
    if not challenge.scores_finalized:
        return jsonify({"error": "Scores must be finalized before downloading."}), 400

    csv_data = generate_scores_csv(challenge)

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-disposition": f"attachment; filename=scores_challenge_{challenge_id}.csv"
        },
    )


@admin_bp.route("/challenges/<uuid:challenge_id>/download-submissions-zip", methods=["GET"])
@role_required(["admin", "jury"])
@jury_access_required
def download_submissions_zip(challenge_id):
    """
    Download completed student submissions as a ZIP archive.
    Allows anonymized downloads when a stage or the competition has ended,
    and non-anonymized downloads once finalized.
    """
    challenge = db.get_or_404(Challenge, challenge_id)
    stage_id = request.args.get("stage_id")

    now = datetime.utcnow()

    # 1. Determine target stage and tasks
    stage = None
    if stage_id:
        from models import Stage

        stage = db.get_or_404(Stage, stage_id)
        if str(stage.challenge_id) != str(challenge.id):
            return jsonify({"error": "Stage does not belong to this challenge."}), 400
        tasks = [t for t in challenge.tasks if t.stage_id == stage.id]
    else:
        tasks = challenge.tasks

    # 2. Check if download is allowed
    # Allowed if finalized OR (if stage_id provided, stage has ended) OR (if no stage_id, challenge has ended)
    is_allowed = False
    if challenge.scores_finalized:
        is_allowed = True
    elif stage and (stage.is_finalized or stage.end_time < now):
        is_allowed = True
    elif not stage and (challenge.end_time and challenge.end_time < now):
        is_allowed = True

    if not is_allowed:
        if stage:
            return (
                jsonify(
                    {"error": "Submissions cannot be downloaded until this stage has finished."}
                ),
                400,
            )
        else:
            return (
                jsonify(
                    {
                        "error": "Submissions cannot be downloaded until the competition has finished."
                    }
                ),
                400,
            )

    # 3. Determine if anonymized
    # Anonymized unless challenge/competition is finalized (scores_finalized = True)
    is_anonymized = not challenge.scores_finalized

    competitors = User.query.filter_by(role="competitor", challenge_id=challenge_id).all()

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for comp in competitors:
            # 4. Folder name according to anonymization state
            if is_anonymized:
                comp_name = comp.alias_id
            else:
                name_part = decrypt_field(comp.name) or ""
                surname_part = decrypt_field(comp.surname) or ""
                comp_name = f"{name_part}_{surname_part}_{comp.alias_id}"

            comp_name = "".join(c for c in comp_name if c.isalnum() or c in (" ", "_", "-")).strip()

            for task in tasks:
                subs = Submission.query.filter_by(
                    task_id=task.id, user_id=comp.id, status="completed"
                ).all()
                if not subs:
                    continue

                from services.submission_service import get_best_submission

                best_sub = get_best_submission(task, subs, challenge)

                if best_sub:
                    task_title = "".join(
                        c for c in task.title if c.isalnum() or c in (" ", "_", "-")
                    ).strip()

                    # 5. Group by stage name if there are multiple stages in the challenge
                    if not stage_id and task.stage_id:
                        from models import Stage

                        task_stage = db.session.get(Stage, task.stage_id)
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

                    try:
                        cells_data = (
                            json.loads(best_sub.code_cells)
                            if isinstance(best_sub.code_cells, str)
                            else best_sub.code_cells
                        )
                    except:
                        cells_data = []

                    ipynb_cells = []
                    for c in cells_data:
                        if isinstance(c, dict):
                            source_lines = c.get("source", "")
                            cell_type = c.get("type", "code") or c.get("cell_type", "code")
                        else:
                            source_lines = str(c)
                            cell_type = "code"

                        if isinstance(source_lines, str):
                            source_lines = [line + "\n" for line in source_lines.splitlines()]
                        ipynb_cells.append(
                            {
                                "cell_type": cell_type,
                                "execution_count": None,
                                "metadata": {},
                                "outputs": [],
                                "source": source_lines,
                            }
                        )

                    notebook_json = {
                        "cells": ipynb_cells,
                        "metadata": {"language_info": {"name": "python"}},
                        "nbformat": 4,
                        "nbformat_minor": 2,
                    }

                    notebook_str = json.dumps(notebook_json, indent=2)
                    zip_file.writestr(filename, notebook_str)

        # Check if the zip file has no entries, write a readme to prevent empty/corrupted archives
        if not zip_file.namelist():
            target_desc = f"stage: {stage.title}" if stage else f"challenge: {challenge.title}"
            zip_file.writestr(
                "README.txt",
                f"No completed student submissions found for {target_desc}",
            )

    zip_buffer.seek(0)
    zip_filename = f"submissions_challenge_{challenge_id}"
    if stage_id:
        zip_filename += f"_stage_{stage_id}"
    if is_anonymized:
        zip_filename += "_anonymized"
    zip_filename += ".zip"

    return Response(
        zip_buffer.getvalue(),
        mimetype="application/zip",
        headers={"Content-disposition": f"attachment; filename={zip_filename}"},
    )


@admin_bp.route("/workers/stats", methods=["GET"])
@role_required(["admin", "jury"])
def get_detailed_worker_stats():
    """
    Get detailed worker cluster statistics including CPU, RAM, GPU specs.
    ---
    tags:
      - Admin
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
    return jsonify(_get_worker_stats_response())


@admin_bp.route("/workers/stats/live", methods=["GET"])
@role_required(["admin", "jury"])
def stream_worker_stats():
    """
    Stream real-time worker cluster statistics via Server-Sent Events.
    ---
    tags:
      - SSE Streaming
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

    def event_generator():
        with current_app.app_context():
            # Send initial data immediately
            res_data = _get_worker_stats_response()
            yield f"data: {json.dumps(res_data)}\n\n"

        from cache_utils import get_redis_client

        r = get_redis_client()
        pubsub = r.pubsub()
        pubsub.subscribe("worker_stats_update")

        try:
            while True:
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=2.0)
                if message:
                    with current_app.app_context():
                        res_data = _get_worker_stats_response()
                        yield f"data: {json.dumps(res_data)}\n\n"
                else:
                    # Push periodic updates every 5s even if no pubsub event
                    with current_app.app_context():
                        res_data = _get_worker_stats_response()
                        yield f"data: {json.dumps(res_data)}\n\n"
        except GeneratorExit:
            try:
                pubsub.unsubscribe()
                pubsub.close()
            except:
                pass
        except Exception as e:
            logger.error("Worker stats SSE error: %s", e)
            try:
                pubsub.unsubscribe()
                pubsub.close()
            except:
                pass

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return Response(
        stream_with_context(event_generator()),
        mimetype="text/event-stream",
        headers=headers,
    )


def _get_worker_stats_response():
    from flask import current_app
    from cache_utils import get_cached, set_cached

    is_testing = current_app.config.get("TESTING", False)
    cache_key = "worker:status:detailed"
    if not is_testing:
        cached_val = get_cached(cache_key)
        if cached_val is not None:
            return cached_val

    try:
        import os
        import shutil
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
        except Exception:
            pass

        # Disk usage
        try:
            total, used, free = shutil.disk_usage("/")
            system_resources["disk"] = {
                "total_gb": round(total / (1024**3), 2),
                "used_gb": round(used / (1024**3), 2),
                "free_gb": round(free / (1024**3), 2),
                "percent_used": round((used / total) * 100, 1) if total > 0 else 0,
            }
        except Exception:
            pass

        # Memory usage
        try:
            if platform.system() == "Linux":
                if os.path.exists("/proc/meminfo"):
                    with open("/proc/meminfo", "r") as f:
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
                total_bytes = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip())
                total_gb = total_bytes / (1024**3)

                vm_stat = subprocess.check_output(["vm_stat"]).decode("utf-8")
                pages_free = 0
                pages_active = 0
                pages_inactive = 0
                pages_speculative = 0
                pages_wire = 0
                page_size = 4096

                for line in vm_stat.split("\n"):
                    if "page size of" in line:
                        try:
                            page_size = int(line.split("page size of")[1].split("bytes")[0].strip())
                        except Exception:
                            pass
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
        except Exception:
            pass

        # 2. Collect Celery Worker Statistics
        from tasks import celery

        inspect = celery.control.inspect(timeout=1.0)

        pings = inspect.ping() or {}
        stats = inspect.stats() or {}
        active = inspect.active() or {}
        reserved = inspect.reserved() or {}
        registered = inspect.registered() or {}

        workers_list = []
        for worker_name in pings.keys():
            w_stats = stats.get(worker_name, {})
            w_active = active.get(worker_name, [])
            w_reserved = reserved.get(worker_name, [])
            w_registered = registered.get(worker_name, [])

            # Extract basic stats
            pool = w_stats.get("pool", {})
            broker = w_stats.get("broker", {})
            total_tasks = w_stats.get("total", {})
            w_rusage = w_stats.get("rusage", {})

            # Format worker resource usage if available
            rusage_formatted = {}
            if w_rusage:
                maxrss = w_rusage.get("maxrss", 0)
                # Normalize macOS vs Linux maxrss
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

            workers_list.append(
                {
                    "name": worker_name,
                    "status": "online",
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

        res_data = {
            "connected_workers_count": len(workers_list),
            "workers": workers_list,
            "system": system_resources,
        }
        if not is_testing:
            set_cached(cache_key, res_data, timeout=10)
        return res_data
    except Exception as e:
        return {"error": str(e)}


@admin_bp.route("/dead-letters", methods=["GET"])
@role_required(["admin"])
def get_dead_letters():
    """
    Inspect the dead letter queue of permanently failed submission evaluations.
    ---
    tags:
      - Admin
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
    from cache_utils import get_redis_client

    r = get_redis_client()
    if not r:
        return jsonify({"items": []}), 200
    try:
        entries = r.lrange("dead_letter_queue", 0, -1)
        items = [json.loads(e) for e in entries]
        return jsonify({"items": items}), 200
    except Exception:
        return jsonify({"items": []}), 200
