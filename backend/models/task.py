"""Task model."""

import json
import logging
import os
from typing import Any

from models.base import GUID, db, decrypt_field, encrypt_field, uuid7

logger = logging.getLogger(__name__)

_ADMIN_JURY_ROLES = frozenset({"admin", "jury"})


class Task(db.Model):  # type: ignore[misc, name-defined]
    __tablename__ = "tasks"

    id = db.Column(GUID, primary_key=True, default=uuid7)
    challenge_id = db.Column(
        GUID, db.ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage_id = db.Column(
        GUID, db.ForeignKey("stages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)

    files = db.Column(db.Text, default="[]")
    custom_eval_code = db.Column(db.Text, nullable=True)
    evaluator_metric_name = db.Column(db.String(128), nullable=True)
    evaluator_options_schema = db.Column(db.Text, nullable=True)

    ram_limit_mb = db.Column(db.Integer, nullable=True)
    time_limit_sec = db.Column(db.Integer, nullable=True)
    gpu_required = db.Column(db.Boolean, nullable=True)

    base_docker_image = db.Column(db.String(255), nullable=True)
    apt_packages = db.Column(db.Text, nullable=True)
    pip_requirements = db.Column(db.Text, nullable=True)

    ban_magic_commands = db.Column(db.Boolean, default=False)
    banned_imports = db.Column(db.String(512), nullable=True)
    whitelisted_imports = db.Column(db.String(512), nullable=True)

    metrics_config = db.Column(db.JSON, nullable=True)
    hf_datasets = db.Column(db.JSON, nullable=True)
    hf_models = db.Column(db.JSON, nullable=True)

    evaluator_script_path = db.Column(db.String(512), nullable=True)
    baseline_notebook_path = db.Column(db.String(512), nullable=True)
    solution_notebook_path = db.Column(db.String(512), nullable=True)

    hf_api_key = db.Column(db.Text, nullable=True)
    public_eval_percentage = db.Column(db.Integer, default=30)
    max_submissions_per_period = db.Column(db.Integer, nullable=True)
    submission_period_hours = db.Column(db.Integer, nullable=True)

    submissions = db.relationship(
        "Submission", backref="task", lazy=True, cascade="all, delete-orphan"
    )

    def set_hf_api_key(self, api_key: str) -> None:
        self.hf_api_key = encrypt_field(api_key)

    def get_hf_api_key(self) -> str | None:
        return decrypt_field(self.hf_api_key)

    def to_dict(self, view_role: str = "competitor") -> dict[str, Any]:
        try:
            files_list = json.loads(self.files)
        except Exception as e:
            logger.warning("Failed to parse files for task %s: %s", self.id, e)
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

        hf_datasets_list: list[Any] = []
        if self.hf_datasets:
            try:
                hf_datasets_list = (
                    json.loads(self.hf_datasets)
                    if isinstance(self.hf_datasets, str)
                    else (self.hf_datasets or [])
                )
            except Exception as e:
                logger.warning("Failed to parse hf_datasets for task %s: %s", self.id, e)
                hf_datasets_list = []

        hf_models_list: list[Any] = []
        if self.hf_models:
            try:
                hf_models_list = (
                    json.loads(self.hf_models)
                    if isinstance(self.hf_models, str)
                    else (self.hf_models or [])
                )
            except Exception as e:
                logger.warning("Failed to parse hf_models for task %s: %s", self.id, e)
                hf_models_list = []

        metrics_cfg_val = None
        if self.metrics_config:
            try:
                metrics_cfg_val = (
                    json.loads(self.metrics_config)
                    if isinstance(self.metrics_config, str)
                    else self.metrics_config
                )
            except Exception as e:
                logger.warning("Failed to parse metrics_config for task %s: %s", self.id, e)
                metrics_cfg_val = {}

        show_internal = view_role in _ADMIN_JURY_ROLES
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
            "evaluator_script_path": self.evaluator_script_path if show_internal else None,
            "evaluator_metric_name": self.evaluator_metric_name,
            "evaluator_options_schema": self.evaluator_options_schema,
            "baseline_notebook_path": self.baseline_notebook_path if show_internal else None,
            "solution_notebook_path": self.solution_notebook_path if show_internal else None,
            "hf_datasets": hf_datasets_list,
            "hf_models": hf_models_list,
            "public_eval_percentage": self.public_eval_percentage,
            "max_submissions_per_period": self.max_submissions_per_period,
            "submission_period_hours": self.submission_period_hours,
            "stage_id": self.stage_id,
        }
