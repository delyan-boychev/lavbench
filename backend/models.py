from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import random
import string
import os
import base64
import hashlib
import json
from cryptography.fernet import Fernet

db = SQLAlchemy()

# Derive a stable symmetric encryption key from SECRET_KEY
# This ensures field encryption persists across server restarts
SECRET_KEY = os.environ.get("SECRET_KEY", "nai-super-secret-key-1337")
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
        # Determine if competition has started
        has_started = False
        challenge_finalized = scores_finalized
        if self.challenge_id:
            challenge = Challenge.query.get(self.challenge_id)
            if challenge:
                if challenge.start_time:
                    has_started = (datetime.utcnow() >= challenge.start_time)
                if challenge.scores_finalized:
                    challenge_finalized = True

        # Decrypt / show demographics logic:
        # Show demographics ONLY if:
        # 1. Requester is admin
        # 2. OR the competition has NOT started yet (needed for registration editing before start)
        # 3. OR the scores are finalized (reveals identities)
        # 4. OR the viewer is the user themselves (current_user_id == self.id)
        is_self = (current_user_id is not None and current_user_id == self.id)
        show_details = (view_role == 'admin') or (not has_started) or challenge_finalized or is_self
        
        if not show_details:
            return {
                "id": self.id,
                "alias_id": self.alias_id,
                "role": self.role,
                "challenge_id": self.challenge_id
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
            "challenge_id": self.challenge_id
        }

class Challenge(db.Model):
    __tablename__ = 'challenges'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    
    # Legacy fields kept for migration compatibility but can be empty/unused
    hf_dataset_path = db.Column(db.String(255), nullable=True)
    hf_dataset_config = db.Column(db.String(255), nullable=True)
    hf_dataset_split = db.Column(db.String(50), nullable=True, default='test')
    metric_name = db.Column(db.String(100), nullable=True, default='accuracy')
    
    max_eval_requests = db.Column(db.Integer, default=10)
    ram_limit_mb = db.Column(db.Integer, default=8192)
    time_limit_sec = db.Column(db.Integer, default=300)
    gpu_required = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)
    is_archived = db.Column(db.Boolean, default=False)
    scores_finalized = db.Column(db.Boolean, default=False)
    start_time = db.Column(db.DateTime, nullable=True)
    end_time = db.Column(db.DateTime, nullable=True)
    freeze_time = db.Column(db.DateTime, nullable=True)
    
    tasks = db.relationship('Task', backref='challenge', lazy=True, cascade="all, delete-orphan")
    submissions = db.relationship('Submission', backref='challenge', lazy=True, cascade="all, delete-orphan")
    
    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "hf_dataset_path": self.hf_dataset_path,
            "hf_dataset_config": self.hf_dataset_config,
            "hf_dataset_split": self.hf_dataset_split,
            "metric_name": self.metric_name,
            "max_eval_requests": self.max_eval_requests,
            "ram_limit_mb": self.ram_limit_mb,
            "time_limit_sec": self.time_limit_sec,
            "gpu_required": self.gpu_required,
            "is_active": self.is_active,
            "is_archived": self.is_archived,
            "scores_finalized": self.scores_finalized,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "freeze_time": self.freeze_time.isoformat() if self.freeze_time else None,
            "tasks": [t.to_dict() for t in self.tasks]
        }

class Task(db.Model):
    __tablename__ = 'tasks'
    
    id = db.Column(db.Integer, primary_key=True)
    challenge_id = db.Column(db.Integer, db.ForeignKey('challenges.id'), nullable=False)
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
    require_submit_tag = db.Column(db.Boolean, default=False)
    ban_magic_commands = db.Column(db.Boolean, default=False)
    banned_imports = db.Column(db.String(512), nullable=True)
    
    # Metrics Config
    metrics_config = db.Column(db.JSON, nullable=True)
    
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
            "metrics_config": metrics_cfg_val,
            "evaluator_script_path": self.evaluator_script_path,
            "baseline_notebook_path": self.baseline_notebook_path,
            "solution_notebook_path": self.solution_notebook_path,
            "hf_train_repo": self.hf_train_repo,
            "hf_eval_repo": self.hf_eval_repo,
            "public_eval_percentage": self.public_eval_percentage,
            "max_submissions_per_period": self.max_submissions_per_period,
            "submission_period_hours": self.submission_period_hours
        }

class Submission(db.Model):
    __tablename__ = 'submissions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    challenge_id = db.Column(db.Integer, db.ForeignKey('challenges.id'), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=True)
    
    status = db.Column(db.String(50), default='queued')
    detailed_status = db.Column(db.String(100), default='queued')
    code_cells = db.Column(db.Text, nullable=False)
    
    public_score = db.Column(db.Float, nullable=True)
    private_score = db.Column(db.Float, nullable=True)
    logs = db.Column(db.Text, nullable=True)
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
    plagiarism_score = db.Column(db.Float, nullable=True)
    llm_probability = db.Column(db.Float, nullable=True)
    
    def to_dict(self, view_role='competitor', current_user_id=None):
        finalized = self.challenge.scores_finalized if self.challenge else False
        
        show_owner = (view_role == 'admin') or finalized or (current_user_id == self.user_id)
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
            "celery_task_id": self.celery_task_id,
            "plagiarism_score": self.plagiarism_score,
            "llm_probability": self.llm_probability
        }
