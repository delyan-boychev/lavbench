from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import random
import string
import os
import base64
import hashlib
import json
from cryptography.fernet import Fernet
import uuid

db = SQLAlchemy()

# Derive a stable symmetric encryption key from SECRET_KEY
# This ensures field encryption persists across server restarts
SECRET_KEY = os.environ.get("SECRET_KEY", "nai-super-secret-key-1337-secure-random-length-for-jwt")
DERIVED_KEY = base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest())
cipher_suite = Fernet(DERIVED_KEY)

def encrypt_field(text):
    if not text:
        return None
    try:
        return cipher_suite.encrypt(text.encode()).decode()
    except Exception:
        return None

def decrypt_field(cipher_text):
    if not cipher_text:
        return None
    try:
        return cipher_suite.decrypt(cipher_text.encode()).decode()
    except Exception:
        return "[Decryption Error]"


# Lists for pseudonym/displayname generation
ADJECTIVES = ["Quantum", "Cyber", "Stellar", "Hyper", "Neural", "Shadow", "Alpha", "Zenith", "Vector", "Binary"]
NOUNS = ["Falcon", "Pioneer", "Voyager", "Oracle", "Matrix", "Nomad", "Eclipse", "Ranger", "Titan", "Specter"]

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
    "mel_lsd": True
}

def is_metric_lower_better(metric_name):
    if not metric_name:
        return False
    return METRIC_LOWER_IS_BETTER.get(metric_name.lower().strip(), False)

def generate_pseudonym():
    adj = random.choice(ADJECTIVES)
    noun = random.choice(NOUNS)
    num = random.randint(100, 999)
    return f"{adj}-{noun}-{num}"

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    
    # Encrypted demographic columns (stored as ciphertext text blocks)
    name = db.Column(db.Text, nullable=True)
    surname = db.Column(db.Text, nullable=True)
    grade = db.Column(db.Text, nullable=True)
    school = db.Column(db.Text, nullable=True)
    city = db.Column(db.Text, nullable=True)
    
    role = db.Column(db.String(50), default='competitor')  # competitor, jury, admin
    alias_id = db.Column(db.String(100), unique=True, nullable=False, default=generate_pseudonym)
    challenge_id = db.Column(db.Integer, db.ForeignKey('challenges.id'), nullable=True)
    is_anonymous = db.Column(db.Boolean, default=False, nullable=False)
    manual_points = db.Column(db.JSON, default=dict, nullable=False)
    
    submissions = db.relationship('Submission', backref='user', lazy=True)
    
    def set_demographics(self, name, surname, grade, school, city):
        """
        Encrypts demographics before database write.
        """
        self.name = encrypt_field(name)
        self.surname = encrypt_field(surname)
        self.grade = encrypt_field(grade)
        self.school = encrypt_field(school)
        self.city = encrypt_field(city)
        
    def to_dict(self, view_role='competitor', scores_finalized=False, current_user_id=None):
        """
        Locks decrypted demographics for blind jury reviews.
        """
        # Determine if competition has started and if it is double-blind
        has_started = False
        challenge_finalized = scores_finalized
        double_blind = True
        
        if self.challenge_id:
            challenge = db.session.get(Challenge, self.challenge_id)
            if challenge:
                double_blind = challenge.double_blind
                if challenge.start_time:
                    has_started = (datetime.utcnow() >= challenge.start_time)
                if challenge.scores_finalized:
                    challenge_finalized = True

        is_self = (current_user_id is not None and current_user_id == self.id)
        
        if double_blind:
            # Show demographics ONLY if:
            # 1. Requester is admin
            # 2. OR the viewer is jury and challenge has NOT started or scores are finalized
            # 3. OR the viewer is the user themselves
            show_details = (view_role == 'admin') or (view_role == 'jury' and (not has_started or challenge_finalized)) or is_self
        else:
            # If not double-blind, demographics are always unblinded to everyone
            show_details = True
            
        # BUT if the user is anonymous:
        # Other students (competitors) are NEVER allowed to see their details.
        # So if the viewer is a competitor (and not self), we set show_details to False.
        if self.is_anonymous and view_role == 'competitor' and not is_self:
            show_details = False
            
        manual_pts = {}
        if self.manual_points:
            if isinstance(self.manual_points, dict):
                manual_pts = self.manual_points
            elif isinstance(self.manual_points, str):
                try:
                    manual_pts = json.loads(self.manual_points)
                except Exception:
                    manual_pts = {}

        if not show_details:
            return {
                "id": self.id,
                "alias_id": self.alias_id,
                "role": self.role,
                "challenge_id": self.challenge_id,
                "is_anonymous": self.is_anonymous,
                "manual_points": manual_pts
            }
            
        # Decrypt fields for display to authorized viewers
        dec_name = decrypt_field(self.name)
        dec_surname = decrypt_field(self.surname)
        dec_grade = decrypt_field(self.grade)
        dec_school = decrypt_field(self.school)
        dec_city = decrypt_field(self.city)
        
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "name": dec_name,
            "surname": dec_surname,
            "grade": dec_grade,
            "school": dec_school,
            "city": dec_city,
            "role": self.role,
            "alias_id": self.alias_id,
            "challenge_id": self.challenge_id,
            "is_anonymous": self.is_anonymous,
            "manual_points": manual_pts
        }

class Challenge(db.Model):
    __tablename__ = 'challenges'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    
    max_eval_requests = db.Column(db.Integer, default=10)
    ram_limit_mb = db.Column(db.Integer, default=8192)
    time_limit_sec = db.Column(db.Integer, default=300)
    gpu_required = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)
    is_archived = db.Column(db.Boolean, default=False)
    scores_finalized = db.Column(db.Boolean, default=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    is_frozen = db.Column(db.Boolean, default=False, nullable=False)
    double_blind = db.Column(db.Boolean, default=True, nullable=False)
    reveal_public_scores = db.Column(db.Boolean, default=True, nullable=False)
    reveal_private_scores = db.Column(db.Boolean, default=True, nullable=False)
    reveal_points = db.Column(db.Boolean, default=True, nullable=False)
    timezone = db.Column(db.String(50), nullable=False, default='UTC')
    
    tasks = db.relationship('Task', backref='challenge', lazy=True, cascade="all, delete-orphan")
    submissions = db.relationship('Submission', backref='challenge', lazy=True, cascade="all, delete-orphan")
    stages = db.relationship('Stage', backref='challenge', lazy=True, cascade="all, delete-orphan", order_by="Stage.stage_number")
    
    @property
    def computed_status(self):
        if self.is_archived:
            return "archived"
        if self.scores_finalized:
            return "finalized"
        
        now = datetime.utcnow()
        if self.start_time and now < self.start_time:
            return "not_started"
        if self.is_frozen:
            return "frozen"
        if self.end_time and now > self.end_time:
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
            "reveal_public_scores": self.reveal_public_scores,
            "reveal_private_scores": self.reveal_private_scores,
            "reveal_points": self.reveal_points,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "is_frozen": self.is_frozen,
            "double_blind": self.double_blind,
            "timezone": self.timezone,
            "status": self.computed_status,
            "tasks": [t.to_dict() for t in self.tasks],
            "stages": [s.to_dict() for s in self.stages],
            "num_tasks": len(self.tasks),
            "deadline_grace_period_seconds": grace_period
        }

class Stage(db.Model):
    __tablename__ = 'stages'
    
    id = db.Column(db.Integer, primary_key=True)
    challenge_id = db.Column(db.Integer, db.ForeignKey('challenges.id'), nullable=False)
    stage_number = db.Column(db.Integer, nullable=False, default=1)
    title = db.Column(db.String(255), nullable=False)
    
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    
    is_finalized = db.Column(db.Boolean, default=False, nullable=False)
    finalize_type = db.Column(db.String(50), nullable=True) # "internal" or "visible"
    reveal_public = db.Column(db.Boolean, default=True, nullable=False)
    reveal_private = db.Column(db.Boolean, default=False, nullable=False)
    reveal_points = db.Column(db.Boolean, default=False, nullable=False)
    
    def to_dict(self):
        return {
            "id": self.id,
            "challenge_id": self.challenge_id,
            "stage_number": self.stage_number,
            "title": self.title,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "is_finalized": self.is_finalized,
            "finalize_type": self.finalize_type,
            "reveal_public": self.reveal_public,
            "reveal_private": self.reveal_private,
            "reveal_points": self.reveal_points
        }

class Task(db.Model):
    __tablename__ = 'tasks'
    
    id = db.Column(db.Integer, primary_key=True)
    challenge_id = db.Column(db.Integer, db.ForeignKey('challenges.id'), nullable=False)
    stage_id = db.Column(db.Integer, db.ForeignKey('stages.id'), nullable=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)  # Markdown description
    task_type = db.Column(db.String(100), nullable=True)
    
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
    require_submit_tag = db.Column(db.Boolean, default=False)
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
    hf_train_repo = db.Column(db.String(255), nullable=True)
    hf_eval_repo = db.Column(db.String(255), nullable=True)
    hf_api_key = db.Column(db.Text, nullable=True) # Encrypted
    public_eval_percentage = db.Column(db.Integer, default=30)
    max_submissions_per_period = db.Column(db.Integer, nullable=True)
    submission_period_hours = db.Column(db.Integer, nullable=True)
    
    submissions = db.relationship('Submission', backref='task', lazy=True, cascade="all, delete-orphan")
    
    def set_hf_api_key(self, api_key):
        self.hf_api_key = encrypt_field(api_key)
        
    def get_hf_api_key(self):
        return decrypt_field(self.hf_api_key)
        
    def to_dict(self):
        try:
            files_list = json.loads(self.files)
        except Exception:
            files_list = []
            
        metrics_cfg_val = None
        if self.metrics_config:
            try:
                metrics_cfg_val = json.loads(self.metrics_config) if isinstance(self.metrics_config, str) else self.metrics_config
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
            "require_submit_tag": self.require_submit_tag,
            "ban_magic_commands": self.ban_magic_commands,
            "banned_imports": self.banned_imports,
            "whitelisted_imports": self.whitelisted_imports,
            "metrics_config": metrics_cfg_val,
            "evaluator_script_path": self.evaluator_script_path,
            "baseline_notebook_path": self.baseline_notebook_path,
            "solution_notebook_path": self.solution_notebook_path,
            "hf_train_repo": self.hf_train_repo,
            "hf_eval_repo": self.hf_eval_repo,
            "hf_datasets": json.loads(self.hf_datasets) if isinstance(self.hf_datasets, str) else (self.hf_datasets or []),
            "hf_models": json.loads(self.hf_models) if isinstance(self.hf_models, str) else (self.hf_models or []),
            "public_eval_percentage": self.public_eval_percentage,
            "max_submissions_per_period": self.max_submissions_per_period,
            "submission_period_hours": self.submission_period_hours,
            "stage_id": self.stage_id,
            "task_type": self.task_type
        }

class Submission(db.Model):
    __tablename__ = 'submissions'
    
    __table_args__ = (
        db.Index('idx_sub_user_task', 'user_id', 'task_id', 'challenge_id'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    challenge_id = db.Column(db.Integer, db.ForeignKey('challenges.id'), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=True)
    
    status = db.Column(db.String(50), default='queued')
    detailed_status = db.Column(db.String(100), default='queued')
    
    # Lightweight storage path pointers instead of heavy text columns
    code_storage_path = db.Column(db.String(512), nullable=True)
    log_storage_path = db.Column(db.String(512), nullable=True)
    
    public_score = db.Column(db.Float, nullable=True)
    private_score = db.Column(db.Float, nullable=True)
    gpu_node = db.Column(db.String(255), nullable=True)
    execution_time_ms = db.Column(db.Integer, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
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
        if hasattr(self, '_cached_code_cells') and self._cached_code_cells is not None:
            return self._cached_code_cells
        if self.code_storage_path and os.path.exists(self.code_storage_path):
            try:
                with open(self.code_storage_path, 'r', encoding='utf-8') as f:
                    self._cached_code_cells = f.read()
                    return self._cached_code_cells
            except Exception:
                pass
        return "[]"

    @code_cells.setter
    def code_cells(self, value):
        self._cached_code_cells = value
        try:
            from config import Config
            submissions_dir = os.path.join(Config.UPLOAD_FOLDER, "submissions")
            os.makedirs(submissions_dir, exist_ok=True)
            if not self.code_storage_path:
                filename = f"submission_{uuid.uuid4().hex}.json"
                self.code_storage_path = os.path.join(submissions_dir, filename)
            with open(self.code_storage_path, 'w', encoding='utf-8') as f:
                f.write(value)
        except Exception as e:
            print(f"Error saving code_cells to file: {e}")

    @property
    def logs(self):
        if hasattr(self, '_cached_logs') and self._cached_logs is not None:
            return self._cached_logs
        if self.log_storage_path and os.path.exists(self.log_storage_path):
            try:
                with open(self.log_storage_path, 'r', encoding='utf-8') as f:
                    self._cached_logs = f.read()
                    return self._cached_logs
            except Exception:
                pass
        return ""

    @logs.setter
    def logs(self, value):
        self._cached_logs = value
        try:
            from config import Config
            logs_dir = os.path.join(Config.UPLOAD_FOLDER, "logs")
            os.makedirs(logs_dir, exist_ok=True)
            if not self.log_storage_path:
                filename = f"log_{uuid.uuid4().hex}.txt"
                self.log_storage_path = os.path.join(logs_dir, filename)
            with open(self.log_storage_path, 'w', encoding='utf-8') as f:
                f.write(value or "")
        except Exception as e:
            print(f"Error saving logs to file: {e}")

    def to_dict(self, view_role='competitor', current_user_id=None):
        finalized = self.challenge.scores_finalized if self.challenge else False
        double_blind = self.challenge.double_blind if self.challenge else True
        
        show_owner = (not double_blind) or (view_role == 'admin') or finalized or (current_user_id == self.user_id)
        owner_info = self.user.to_dict(view_role=view_role, scores_finalized=finalized, current_user_id=current_user_id) if self.user else None
        
        if not show_owner and owner_info:
            owner_info = {
                "id": owner_info.get("id"),
                "alias_id": owner_info.get("alias_id"),
                "role": owner_info.get("role")
            }
            
        show_private_score = (view_role == 'admin') or finalized
        
        try:
            m_public = json.loads(self.metrics_payload_public) if isinstance(self.metrics_payload_public, str) else self.metrics_payload_public
        except:
            m_public = {}
            
        try:
            m_private = json.loads(self.metrics_payload_private) if isinstance(self.metrics_payload_private, str) else self.metrics_payload_private
        except:
            m_private = {}
            
        return {
            "id": self.id,
            "challenge_id": self.challenge_id,
            "task_id": self.task_id,
            "task_title": self.task.title if self.task else None,
            "status": self.status,
            "detailed_status": self.detailed_status,
            "code_cells": self.code_cells,
            "public_score": self.public_score,
            "private_score": self.private_score if show_private_score else None,
            "logs": self.logs,
            "gpu_node": self.gpu_node,
            "execution_time_ms": self.execution_time_ms,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "user": owner_info,
            "metrics_payload_public": m_public,
            "metrics_payload_private": m_private if show_private_score else None,
            "final_weighted_score_public": self.final_weighted_score_public,
            "final_weighted_score_private": self.final_weighted_score_private if show_private_score else None,
            "is_final_selection": self.is_final_selection,
            "is_disqualified": self.is_disqualified,
            "celery_task_id": self.celery_task_id
        }

    def to_dict_light(self, view_role='competitor', current_user_id=None):
        res = self.to_dict(view_role=view_role, current_user_id=current_user_id)
        res.pop("code_cells", None)
        res.pop("logs", None)
        return res

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    target_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False)
    old_score = db.Column(db.Integer, nullable=True)
    new_score = db.Column(db.Integer, nullable=True)
    reason = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    admin = db.relationship('User', foreign_keys=[admin_id])
    target_user = db.relationship('User', foreign_keys=[target_user_id])
    task = db.relationship('Task')
    
    def to_dict(self):
        return {
            "id": self.id,
            "admin_id": self.admin_id,
            "admin_username": self.admin.username if self.admin else None,
            "target_user_id": self.target_user_id,
            "target_user_username": self.target_user.username if self.target_user else None,
            "task_id": self.task_id,
            "task_title": self.task.title if self.task else None,
            "old_score": self.old_score,
            "new_score": self.new_score,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None
        }
