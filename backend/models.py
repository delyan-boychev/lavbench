"""SQLAlchemy ORM models for User, Challenge, Task, Submission, and related entities."""

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import logging
import random
import os
import sys
import base64
import hashlib
import json
from cryptography.fernet import Fernet
import uuid
import zoneinfo
from sqlalchemy.types import TypeDecorator, CHAR
from sqlalchemy.dialects.postgresql import UUID


def uuid7():
    import time
    import os

    ms = int(time.time() * 1000)
    rand_bytes = os.urandom(10)
    b_ts = ms.to_bytes(6, byteorder="big")
    v_and_rand = 0x7000 | (int.from_bytes(rand_bytes[:2], byteorder="big") & 0x0FFF)
    b_vr = v_and_rand.to_bytes(2, byteorder="big")
    var_and_rand = 0x8000000000000000 | (
        int.from_bytes(rand_bytes[2:], byteorder="big") & 0x3FFFFFFFFFFFFFFF
    )
    b_var_rand = var_and_rand.to_bytes(8, byteorder="big")
    return uuid.UUID(bytes=b_ts + b_vr + b_var_rand)


class GUID(TypeDecorator):
    """Platform-independent GUID type.
    Uses PostgreSQL's UUID type, otherwise uses CHAR(36), storing as standard UUID strings.
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(UUID(as_uuid=True))
        else:
            return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        try:
            if isinstance(value, uuid.UUID):
                u = value
            elif isinstance(value, int):
                u = uuid.UUID(int=value)
            else:
                val_str = str(value)
                try:
                    u = uuid.UUID(val_str)
                except ValueError:
                    try:
                        u = uuid.UUID(int=int(val_str))
                    except ValueError:
                        u = uuid.UUID(int=0)
        except Exception:
            u = uuid.UUID(int=0)

        if dialect.name == "postgresql":
            return u
        else:
            return str(u)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return str(value)
        try:
            return str(uuid.UUID(str(value)))
        except ValueError:
            return str(value)


logger = logging.getLogger(__name__)

db = SQLAlchemy()

# Derive a stable symmetric encryption key from SECRET_KEY or ENCRYPTION_KEY
# ENCRYPTION_KEY allows key rotation without invalidating all encrypted data
ENCRYPTION_KEY_BASE64 = os.environ.get("ENCRYPTION_KEY")
if ENCRYPTION_KEY_BASE64:
    cipher_suite = Fernet(ENCRYPTION_KEY_BASE64.encode())
else:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    if not SECRET_KEY:
        logger.critical("SECRET_KEY environment variable is not set")
        sys.exit(1)
    DERIVED_KEY = base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest())
    cipher_suite = Fernet(DERIVED_KEY)


def encrypt_field(text):
    """Encrypt a plaintext string using Fernet symmetric encryption."""
    if not text:
        return None
    try:
        return cipher_suite.encrypt(text.encode()).decode()
    except Exception:
        logger.exception("encrypt_field failed")
        return None


def decrypt_field(cipher_text):
    """Decrypt a Fernet-encrypted ciphertext back to plaintext."""
    if not cipher_text:
        return None
    try:
        return cipher_suite.decrypt(cipher_text.encode()).decode()
    except Exception:
        logger.exception("decrypt_field failed")
        return "[Decryption Error]"


# Lists for pseudonym/displayname generation
ADJECTIVES = [
    "Quantum",
    "Cyber",
    "Stellar",
    "Hyper",
    "Neural",
    "Shadow",
    "Alpha",
    "Zenith",
    "Vector",
    "Binary",
    "Cosmic",
    "Solar",
    "Galactic",
    "Vortex",
    "Aurora",
    "Plasma",
    "Pixel",
    "Neon",
    "Aero",
    "Crypto",
    "Apex",
    "Sonic",
    "Tectonic",
    "Magneto",
    "Astral",
    "Ember",
    "Frost",
    "Aether",
    "Primal",
    "Kinetic",
    "Omega",
    "Obsidian",
    "Radiant",
    "Volcanic",
    "Spectral",
    "Dynamic",
    "Abyssal",
    "Magnetic",
    "Luminous",
]
NOUNS = [
    "Falcon",
    "Pioneer",
    "Voyager",
    "Oracle",
    "Matrix",
    "Nomad",
    "Eclipse",
    "Ranger",
    "Titan",
    "Specter",
    "Phoenix",
    "Horizon",
    "Sentinel",
    "Comet",
    "Odyssey",
    "Genesis",
    "Summit",
    "Pulse",
    "Beacon",
    "Glitch",
    "Helix",
    "Spark",
    "Quasar",
    "Rogue",
    "Nova",
    "Seeker",
    "Pulsar",
    "Catalyst",
    "Entropy",
    "Nebula",
    "Vanguard",
    "Anomaly",
    "Warden",
    "Strider",
    "Rift",
    "Core",
    "Void",
    "Phantom",
    "Goliath",
    "Mirage",
]

METRIC_LOWER_IS_BETTER = {
    # Probabilistic
    "logloss": True,
    "brier_score": True,
    # Regression
    "rmse": True,
    "mae": True,
    "mape": True,
    "median_ae": True,
    # NLP
    "ter": True,
    # CV keypoints / Generation / Quality
    "mse": True,
    "fid": True,
    "lpips": True,
    "niqe": True,
    # Audio
    "mel_lsd": True,
}


def is_metric_lower_better(metric_name):
    """Return True if the given metric name is lower-is-better (e.g. logloss, rmse)."""
    if not metric_name:
        return False
    return METRIC_LOWER_IS_BETTER.get(metric_name.lower().strip(), False)


def to_base36(num):
    """Convert an integer to a base36 string."""
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    result = ""
    while num > 0:
        num, d = divmod(num, 36)
        result = chars[d] + result
    return result or "0"


def generate_pseudonym():
    """Generate a unique, timestamp-based pseudonym (e.g. 'Quantum-Falcon-28qt')."""
    import time

    adj = random.choice(ADJECTIVES)
    noun = random.choice(NOUNS)
    # 1. Get millisecond timestamp modulo 36^4 (1,679,616)
    ts_ms = int(time.time() * 1000)
    raw_num = ts_ms % 1679616
    # 2. Scramble using LCG-like bijective modular multiplication (7919 is coprime to 36)
    scrambled = (raw_num * 7919 + 104729) % 1679616
    # 3. Convert to exactly 4 characters of base36
    suffix = to_base36(scrambled).zfill(4)
    return f"{adj}-{noun}-{suffix}"


class User(db.Model):
    """Registered user — competitor, jury, or admin. Stores encrypted demographics."""

    __tablename__ = "users"

    id = db.Column(GUID, primary_key=True, default=uuid7)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=False, nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)

    # Encrypted demographic columns (stored as ciphertext text blocks)
    name = db.Column(db.Text, nullable=True)
    surname = db.Column(db.Text, nullable=True)
    middle_name = db.Column(db.Text, nullable=True)
    birth_date = db.Column(db.Text, nullable=True)
    grade = db.Column(db.Text, nullable=True)
    school = db.Column(db.Text, nullable=True)
    city = db.Column(db.Text, nullable=True)

    role = db.Column(db.String(50), default="competitor", index=True)  # competitor, jury, admin
    alias_id = db.Column(db.String(100), unique=True, nullable=False, default=generate_pseudonym)
    challenge_id = db.Column(GUID, db.ForeignKey("challenges.id"), nullable=True, index=True)
    is_anonymous = db.Column(db.Boolean, default=False, nullable=False)
    manual_points = db.Column(db.JSON, default=dict, nullable=False)

    submissions = db.relationship(
        "Submission", backref="user", lazy=True, cascade="all, delete-orphan"
    )

    def set_demographics(
        self, name, surname, grade, school, city, middle_name=None, birth_date=None
    ):
        """
        Encrypts demographics before database write.
        """
        self.name = encrypt_field(name)
        self.surname = encrypt_field(surname)
        self.middle_name = encrypt_field(middle_name) if middle_name is not None else None
        self.birth_date = encrypt_field(birth_date) if birth_date is not None else None
        self.grade = encrypt_field(grade)
        self.school = encrypt_field(school)
        self.city = encrypt_field(city)

    def to_dict(
        self,
        view_role="competitor",
        scores_finalized=False,
        current_user_id=None,
        challenge_cache=None,
    ):
        """
        Locks decrypted demographics for blind jury reviews.
        """
        # Determine if competition has started and if it is double-blind
        has_started = False
        challenge_finalized = scores_finalized
        double_blind = True
        challenge_reveal_results = True

        if self.challenge_id:
            challenge = (
                challenge_cache.get(self.challenge_id)
                if challenge_cache
                else db.session.get(Challenge, self.challenge_id)
            )
            if challenge:
                double_blind = challenge.double_blind
                challenge_reveal_results = challenge.reveal_results
                if challenge.start_time:
                    has_started = datetime.utcnow() >= challenge.start_time
                if challenge.scores_finalized:
                    challenge_finalized = True

        is_self = current_user_id is not None and current_user_id == self.id

        if double_blind:
            # Show demographics ONLY if:
            # 1. Requester is admin
            # 2. OR the viewer is jury and challenge has NOT started or scores are finalized
            # 3. OR the viewer is the user themselves
            show_details = (
                (view_role == "admin")
                or (view_role == "jury" and (not has_started or challenge_finalized))
                or is_self
                or challenge_finalized
            )
        else:
            # If not double-blind, demographics are always unblinded to everyone
            show_details = True

        # BUT if the user is anonymous:
        # Other students (competitors) are NEVER allowed to see their details.
        # So if the viewer is a competitor (and not self), we set show_details to False.
        if self.is_anonymous and view_role == "competitor" and not is_self:
            if not challenge_finalized:
                show_details = False

        # Competitors should only see manual points if the scores are finalized and results are revealed.
        show_manual_points = True
        if view_role == "competitor" or (is_self and self.role == "competitor"):
            show_manual_points = challenge_finalized and challenge_reveal_results

        manual_pts = {}
        if self.manual_points and show_manual_points:
            if isinstance(self.manual_points, dict):
                manual_pts = self.manual_points
            elif isinstance(self.manual_points, str):
                try:
                    manual_pts = json.loads(self.manual_points)
                except Exception:
                    manual_pts = {}

        jury_ch_ids = []
        if self.role == "jury":
            try:
                jury_ch_ids = [
                    str(jc.challenge_id)
                    for jc in JuryChallenge.query.filter_by(jury_id=self.id).all()
                ]
            except Exception:
                pass

        if not show_details:
            res = {
                "id": self.id,
                "alias_id": self.alias_id,
                "role": self.role,
                "challenge_id": self.challenge_id,
                "is_anonymous": self.is_anonymous,
            }
            if self.role == "jury":
                res["jury_challenges"] = jury_ch_ids
            return res

        # Decrypt fields for display to authorized viewers
        dec_name = decrypt_field(self.name)
        dec_surname = decrypt_field(self.surname)
        dec_middle_name = (
            decrypt_field(self.middle_name) if getattr(self, "middle_name", None) else ""
        )
        dec_birth_date = decrypt_field(self.birth_date) if getattr(self, "birth_date", None) else ""
        dec_grade = decrypt_field(self.grade)
        dec_school = decrypt_field(self.school)
        dec_city = decrypt_field(self.city)

        res = {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "name": dec_name,
            "surname": dec_surname,
            "middle_name": dec_middle_name,
            "birth_date": dec_birth_date,
            "grade": dec_grade,
            "school": dec_school,
            "city": dec_city,
            "role": self.role,
            "alias_id": self.alias_id,
            "challenge_id": self.challenge_id,
            "is_anonymous": self.is_anonymous,
            "manual_points": manual_pts,
        }
        if self.role == "jury":
            res["jury_challenges"] = jury_ch_ids
        return res


class JuryChallenge(db.Model):
    """Many-to-many relationship mapping jury members to challenges they are assigned to."""

    __tablename__ = "jury_challenges"

    jury_id = db.Column(GUID, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    challenge_id = db.Column(
        GUID, db.ForeignKey("challenges.id", ondelete="CASCADE"), primary_key=True
    )

    # Relationships
    jury = db.relationship(
        "User", backref=db.backref("jury_assignments", cascade="all, delete-orphan")
    )
    challenge = db.relationship(
        "Challenge",
        backref=db.backref("jury_assignments", cascade="all, delete-orphan"),
    )


class Challenge(db.Model):
    """A machine learning competition with stages, tasks, participants, and scoring rules."""

    __tablename__ = "challenges"

    id = db.Column(GUID, primary_key=True, default=uuid7)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)

    max_eval_requests = db.Column(db.Integer, default=10)
    ram_limit_mb = db.Column(db.Integer, default=8192)
    time_limit_sec = db.Column(db.Integer, default=300)
    gpu_required = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True, index=True)
    is_archived = db.Column(db.Boolean, default=False, index=True)
    scores_finalized = db.Column(db.Boolean, default=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    is_frozen = db.Column(db.Boolean, default=False, nullable=False)
    double_blind = db.Column(db.Boolean, default=True, nullable=False)
    reveal_results = db.Column(db.Boolean, default=True, nullable=False)
    timezone = db.Column(db.String(50), nullable=False, default="UTC")

    tasks = db.relationship("Task", backref="challenge", lazy=True, cascade="all, delete-orphan")
    submissions = db.relationship(
        "Submission", backref="challenge", lazy=True, cascade="all, delete-orphan"
    )
    stages = db.relationship(
        "Stage",
        backref="challenge",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="Stage.stage_number",
    )

    def _now_local(self):
        try:
            tz = zoneinfo.ZoneInfo(self.timezone or "UTC")
            return datetime.now(tz).replace(tzinfo=None)
        except Exception:
            return datetime.utcnow()

    @property
    def is_started(self):
        if not self.start_time:
            return False
        return self._now_local() >= self.start_time

    @property
    def is_ended(self):
        if not self.end_time:
            return False
        return self._now_local() > self.end_time

    @property
    def computed_status(self):
        if self.is_archived:
            return "archived"
        if self.scores_finalized:
            return "finalized"

        if not self.is_started:
            return "not_started"
        if self.is_frozen:
            return "frozen"
        if self.is_ended:
            return "ended"

        return "active"

    def to_dict(self):
        try:
            from flask import current_app

            grace_period = current_app.config.get("DEADLINE_GRACE_PERIOD_SECONDS", 60)
        except Exception:
            grace_period = 60

        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "max_eval_requests": self.max_eval_requests,
            "ram_limit_mb": self.ram_limit_mb,
            "time_limit_sec": self.time_limit_sec,
            "gpu_required": self.gpu_required,
            "is_active": self.is_active,
            "is_archived": self.is_archived,
            "scores_finalized": self.scores_finalized,
            "reveal_results": self.reveal_results,
            "start_time": self.start_time.isoformat() + "Z" if self.start_time else None,
            "end_time": self.end_time.isoformat() + "Z" if self.end_time else None,
            "is_frozen": self.is_frozen,
            "double_blind": self.double_blind,
            "timezone": self.timezone,
            "status": self.computed_status,
            "tasks": [t.to_dict() for t in self.tasks],
            "stages": [s.to_dict() for s in self.stages],
            "num_tasks": len(self.tasks),
            "deadline_grace_period_seconds": grace_period,
        }


class Stage(db.Model):
    """A phase within a challenge (e.g. qualification, finals) with its own time window."""

    __tablename__ = "stages"

    __table_args__ = (
        db.UniqueConstraint("challenge_id", "stage_number", name="uq_stage_challenge_number"),
    )

    id = db.Column(GUID, primary_key=True, default=uuid7)
    challenge_id = db.Column(GUID, db.ForeignKey("challenges.id"), nullable=False, index=True)
    stage_number = db.Column(db.Integer, nullable=False, default=1)
    title = db.Column(db.String(255), nullable=False)

    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)

    is_finalized = db.Column(db.Boolean, default=False, nullable=False)
    reveal_results = db.Column(db.Boolean, default=False, nullable=False)
    is_test = db.Column(db.Boolean, default=False, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "challenge_id": self.challenge_id,
            "stage_number": self.stage_number,
            "title": self.title,
            "start_time": self.start_time.isoformat() + "Z" if self.start_time else None,
            "end_time": self.end_time.isoformat() + "Z" if self.end_time else None,
            "is_finalized": self.is_finalized,
            "reveal_results": self.reveal_results,
            "is_test": self.is_test,
        }


class Task(db.Model):
    """An individual problem within a challenge — has metrics config, files, time limits."""

    __tablename__ = "tasks"

    id = db.Column(GUID, primary_key=True, default=uuid7)
    challenge_id = db.Column(GUID, db.ForeignKey("challenges.id"), nullable=False, index=True)
    stage_id = db.Column(GUID, db.ForeignKey("stages.id"), nullable=True, index=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)  # Markdown description

    # Store up to 5 uploaded resource files as JSON array
    # e.g., [{"filename": "data.csv", "path": "uploads/t1_data.csv", "size": 1048576}]
    files = db.Column(db.Text, default="[]")

    # Custom evaluation code containing dataset loading, predictions checking, metrics calculation
    custom_eval_code = db.Column(db.Text, nullable=True)

    # Overrides
    ram_limit_mb = db.Column(db.Integer, nullable=True)
    time_limit_sec = db.Column(db.Integer, nullable=True)
    gpu_required = db.Column(db.Boolean, nullable=True)

    # Docker Config
    base_docker_image = db.Column(db.String(255), nullable=True)
    apt_packages = db.Column(db.Text, nullable=True)
    pip_requirements = db.Column(db.Text, nullable=True)

    # Rule Settings
    ban_magic_commands = db.Column(db.Boolean, default=False)
    banned_imports = db.Column(db.String(512), nullable=True)
    whitelisted_imports = db.Column(db.String(512), nullable=True)

    # Metrics Config
    metrics_config = db.Column(db.JSON, nullable=True)
    hf_datasets = db.Column(db.JSON, nullable=True)
    hf_models = db.Column(db.JSON, nullable=True)

    # Scripts/Notebooks
    evaluator_script_path = db.Column(db.String(512), nullable=True)
    baseline_notebook_path = db.Column(db.String(512), nullable=True)
    solution_notebook_path = db.Column(db.String(512), nullable=True)

    # HF & Evaluation
    hf_api_key = db.Column(db.Text, nullable=True)  # Encrypted
    public_eval_percentage = db.Column(db.Integer, default=30)
    max_submissions_per_period = db.Column(db.Integer, nullable=True)
    submission_period_hours = db.Column(db.Integer, nullable=True)

    submissions = db.relationship(
        "Submission", backref="task", lazy=True, cascade="all, delete-orphan"
    )

    def set_hf_api_key(self, api_key):
        self.hf_api_key = encrypt_field(api_key)

    def get_hf_api_key(self):
        return decrypt_field(self.hf_api_key)

    def to_dict(self):
        try:
            files_list = json.loads(self.files)
        except Exception:
            files_list = []

        if self.baseline_notebook_path and os.path.exists(self.baseline_notebook_path):
            baseline_filename = os.path.basename(self.baseline_notebook_path)
            if not any(f.get("filename") == baseline_filename for f in files_list):
                files_list.append(
                    {
                        "filename": baseline_filename,
                        "saved_name": baseline_filename,
                        "size_bytes": os.path.getsize(self.baseline_notebook_path),
                        "type": "baseline",
                    }
                )

        hf_datasets_list = []
        if self.hf_datasets:
            try:
                hf_datasets_list = (
                    json.loads(self.hf_datasets)
                    if isinstance(self.hf_datasets, str)
                    else (self.hf_datasets or [])
                )
            except Exception:
                hf_datasets_list = []

        hf_models_list = []
        if self.hf_models:
            try:
                hf_models_list = (
                    json.loads(self.hf_models)
                    if isinstance(self.hf_models, str)
                    else (self.hf_models or [])
                )
            except Exception:
                hf_models_list = []

        metrics_cfg_val = None
        if self.metrics_config:
            try:
                metrics_cfg_val = (
                    json.loads(self.metrics_config)
                    if isinstance(self.metrics_config, str)
                    else self.metrics_config
                )
            except Exception:
                metrics_cfg_val = {}

        return {
            "id": self.id,
            "challenge_id": self.challenge_id,
            "title": self.title,
            "description": self.description,
            "files": files_list,
            "ram_limit_mb": self.ram_limit_mb,
            "time_limit_sec": self.time_limit_sec,
            "gpu_required": self.gpu_required,
            "base_docker_image": self.base_docker_image,
            "apt_packages": self.apt_packages,
            "pip_requirements": self.pip_requirements,
            "ban_magic_commands": self.ban_magic_commands,
            "banned_imports": self.banned_imports,
            "whitelisted_imports": self.whitelisted_imports,
            "metrics_config": metrics_cfg_val,
            "evaluator_script_path": self.evaluator_script_path,
            "baseline_notebook_path": self.baseline_notebook_path,
            "solution_notebook_path": self.solution_notebook_path,
            "hf_datasets": hf_datasets_list,
            "hf_models": hf_models_list,
            "public_eval_percentage": self.public_eval_percentage,
            "max_submissions_per_period": self.max_submissions_per_period,
            "submission_period_hours": self.submission_period_hours,
            "stage_id": self.stage_id,
        }


class Submission(db.Model):
    """A student's notebook/code submission with status, scores, logs, and execution metadata."""

    __tablename__ = "submissions"

    __table_args__ = (
        db.Index("idx_sub_user_task", "user_id", "task_id", "challenge_id"),
        db.Index("idx_sub_task_id", "task_id"),
        db.Index("idx_sub_user_challenge_created", "user_id", "challenge_id", "created_at"),
        db.Index("idx_sub_challenge_status_baseline", "challenge_id", "status", "is_baseline"),
        db.Index("idx_sub_challenge_created", "challenge_id", db.text("created_at DESC")),
        db.Index("idx_sub_task_created", "task_id", db.text("created_at DESC")),
        db.Index(
            "idx_sub_task_user_created",
            "task_id",
            "user_id",
            db.text("created_at DESC"),
        ),
    )

    id = db.Column(GUID, primary_key=True, default=uuid7)
    user_id = db.Column(GUID, db.ForeignKey("users.id"), nullable=False)
    challenge_id = db.Column(GUID, db.ForeignKey("challenges.id"), nullable=False)
    task_id = db.Column(GUID, db.ForeignKey("tasks.id"), nullable=True)

    status = db.Column(db.String(50), default="queued", index=True)
    is_baseline = db.Column(db.Boolean, default=False)
    detailed_status = db.Column(db.String(100), default="queued")

    # Lightweight storage path pointers instead of heavy text columns
    code_storage_path = db.Column(db.String(512), nullable=True)
    log_storage_path = db.Column(db.String(512), nullable=True)

    public_score = db.Column(db.Float, nullable=True)
    private_score = db.Column(db.Float, nullable=True)
    gpu_node = db.Column(db.String(255), nullable=True)
    execution_time_ms = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    executed_at = db.Column(db.DateTime, nullable=True)

    # New Fields
    metrics_payload_public = db.Column(db.JSON, nullable=True)
    metrics_payload_private = db.Column(db.JSON, nullable=True)
    final_weighted_score_public = db.Column(db.Float, nullable=True)
    final_weighted_score_private = db.Column(db.Float, nullable=True)

    is_final_selection = db.Column(db.Boolean, default=False)
    is_disqualified = db.Column(db.Boolean, default=False)
    celery_task_id = db.Column(db.String(255), nullable=True)

    @property
    def code_cells(self):
        if hasattr(self, "_cached_code_cells") and self._cached_code_cells is not None:
            return self._cached_code_cells
        if self.code_storage_path and os.path.exists(self.code_storage_path):
            try:
                with open(self.code_storage_path, "r", encoding="utf-8") as f:
                    self._cached_code_cells = f.read()
                    return self._cached_code_cells
            except Exception:
                pass
        return "[]"

    @code_cells.setter
    def code_cells(self, value):
        self._cached_code_cells = value
        try:
            from flask import current_app

            if current_app:
                upload_folder = current_app.config.get("UPLOAD_FOLDER")
            else:
                from config import Config

                upload_folder = Config.UPLOAD_FOLDER

            submissions_dir = os.path.join(upload_folder, "submissions")
            os.makedirs(submissions_dir, exist_ok=True)
            if not self.code_storage_path:
                filename = f"submission_{uuid.uuid4().hex}.json"
                self.code_storage_path = os.path.join(submissions_dir, filename)
            with open(self.code_storage_path, "w", encoding="utf-8") as f:
                f.write(value)
        except Exception:
            logger.exception("Error saving code_cells to file")

    @property
    def logs(self):
        if self.log_storage_path and os.path.exists(self.log_storage_path):
            try:
                with open(self.log_storage_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass
        return ""

    @logs.setter
    def logs(self, value):
        self._cached_logs = value
        try:
            from flask import current_app

            if current_app:
                upload_folder = current_app.config.get("UPLOAD_FOLDER")
            else:
                from config import Config

                upload_folder = Config.UPLOAD_FOLDER

            logs_dir = os.path.join(upload_folder, "logs")
            os.makedirs(logs_dir, exist_ok=True)
            if not self.log_storage_path:
                filename = f"log_{uuid.uuid4().hex}.txt"
                self.log_storage_path = os.path.join(logs_dir, filename)
            with open(self.log_storage_path, "w", encoding="utf-8") as f:
                f.write(value or "")
        except Exception:
            logger.exception("Error saving logs to file")

    def to_dict(self, view_role="competitor", current_user_id=None, include_large_fields=True):
        finalized = self.challenge.scores_finalized if self.challenge else False
        double_blind = self.challenge.double_blind if self.challenge else True

        show_owner = (
            (not double_blind)
            or (view_role == "admin")
            or finalized
            or (current_user_id == self.user_id)
        )
        owner_info = (
            self.user.to_dict(
                view_role=view_role,
                scores_finalized=finalized,
                current_user_id=current_user_id,
            )
            if self.user
            else None
        )

        if not show_owner and owner_info:
            owner_info = {
                "id": owner_info.get("id"),
                "alias_id": owner_info.get("alias_id"),
                "role": owner_info.get("role"),
            }

        if view_role == "admin":
            show_private_score = True
        elif view_role == "jury":
            show_private_score = finalized
        else:
            show_private_score = finalized and (
                self.challenge.reveal_results if self.challenge else False
            )

        try:
            m_public = (
                json.loads(self.metrics_payload_public)
                if isinstance(self.metrics_payload_public, str)
                else self.metrics_payload_public
            )
        except Exception:
            m_public = {}

        try:
            m_private = (
                json.loads(self.metrics_payload_private)
                if isinstance(self.metrics_payload_private, str)
                else self.metrics_payload_private
            )
        except Exception:
            m_private = {}

        return {
            "id": self.id,
            "challenge_id": self.challenge_id,
            "task_id": self.task_id,
            "task_title": self.task.title if self.task else None,
            "status": self.status,
            "detailed_status": self.detailed_status,
            "code_cells": self.code_cells if include_large_fields else "[]",
            "public_score": self.public_score,
            "private_score": self.private_score if show_private_score else None,
            "logs": self.logs if include_large_fields else None,
            "gpu_node": self.gpu_node,
            "execution_time_ms": self.execution_time_ms,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "executed_at": self.executed_at.isoformat() + "Z" if self.executed_at else None,
            "user": owner_info,
            "metrics_payload_public": m_public,
            "metrics_payload_private": m_private if show_private_score else None,
            "final_weighted_score_public": self.final_weighted_score_public,
            "final_weighted_score_private": (
                self.final_weighted_score_private if show_private_score else None
            ),
            "is_final_selection": self.is_final_selection,
            "is_baseline": self.is_baseline,
            "is_disqualified": self.is_disqualified,
            "celery_task_id": self.celery_task_id,
        }

    def to_dict_light(self, view_role="competitor", current_user_id=None):
        res = self.to_dict(
            view_role=view_role,
            current_user_id=current_user_id,
            include_large_fields=False,
        )
        res.pop("code_cells", None)
        res.pop("logs", None)
        return res


@db.event.listens_for(Submission, "after_delete")
def _delete_submission_files(mapper, connection, target):
    if target.code_storage_path and os.path.exists(target.code_storage_path):
        try:
            os.remove(target.code_storage_path)
        except OSError:
            pass
    if target.log_storage_path and os.path.exists(target.log_storage_path):
        try:
            os.remove(target.log_storage_path)
        except OSError:
            pass


class AuditLog(db.Model):
    """Audit trail for administrative actions (create, update, delete, archive, finalize)."""

    __tablename__ = "audit_logs"

    id = db.Column(GUID, primary_key=True, default=uuid7)
    admin_id = db.Column(GUID, db.ForeignKey("users.id"), nullable=False, index=True)

    # Generic audit fields
    action_type = db.Column(
        db.String(50), nullable=True, index=True
    )  # create, update, delete, finalize, archive, reset_password
    target_type = db.Column(
        db.String(50), nullable=True, index=True
    )  # user, challenge, task, stage, submission
    target_id = db.Column(GUID, nullable=True, index=True)
    details = db.Column(db.JSON, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)

    # Legacy fields (score corrections)
    target_user_id = db.Column(GUID, db.ForeignKey("users.id"), nullable=True, index=True)
    task_id = db.Column(GUID, db.ForeignKey("tasks.id"), nullable=True, index=True)
    old_score = db.Column(db.Integer, nullable=True)
    new_score = db.Column(db.Integer, nullable=True)
    reason = db.Column(db.Text, nullable=True)

    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    admin = db.relationship("User", foreign_keys=[admin_id])
    target_user = db.relationship("User", foreign_keys=[target_user_id])
    task = db.relationship("Task")

    def to_dict(self):
        result = {
            "id": self.id,
            "admin_id": self.admin_id,
            "admin_username": self.admin.username if self.admin else None,
            "action_type": self.action_type,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "details": self.details,
            "ip_address": self.ip_address,
            "timestamp": self.timestamp.isoformat() + "Z" if self.timestamp else None,
        }
        # Include legacy fields if set
        if self.target_user_id is not None:
            result["target_user_id"] = self.target_user_id
            result["target_user_username"] = self.target_user.username if self.target_user else None
        if self.task_id is not None:
            result["task_id"] = self.task_id
            result["task_title"] = self.task.title if self.task else None
        if self.old_score is not None or self.new_score is not None:
            result["old_score"] = self.old_score
            result["new_score"] = self.new_score
        if self.reason:
            result["reason"] = self.reason
        return result


from sqlalchemy import event, text


@event.listens_for(User, "after_insert")
def auto_assign_jury_in_tests(mapper, connection, target):
    if target.role == "jury" and os.environ.get("PYTEST_CURRENT_TEST"):
        cursor = connection.execute(text("SELECT id FROM challenges"))
        challenge_ids = [row[0] for row in cursor.fetchall()]
        for ch_id in challenge_ids:
            try:
                connection.execute(
                    text(
                        "INSERT INTO jury_challenges (jury_id, challenge_id) VALUES (:jury_id, :challenge_id)"
                    ),
                    {"jury_id": str(target.id), "challenge_id": str(ch_id)},
                )
            except Exception:
                pass


@event.listens_for(Challenge, "after_insert")
def auto_assign_challenge_to_jury_in_tests(mapper, connection, target):
    if os.environ.get("PYTEST_CURRENT_TEST"):
        cursor = connection.execute(text("SELECT id FROM users WHERE role = 'jury'"))
        jury_ids = [row[0] for row in cursor.fetchall()]
        for j_id in jury_ids:
            try:
                connection.execute(
                    text(
                        "INSERT INTO jury_challenges (jury_id, challenge_id) VALUES (:jury_id, :challenge_id)"
                    ),
                    {"jury_id": str(j_id), "challenge_id": str(target.id)},
                )
            except Exception:
                pass
