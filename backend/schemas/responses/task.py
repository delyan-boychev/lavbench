"""Task endpoint response models."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from schemas.responses._base import RESPONSE_CONFIG
from schemas.responses.common import FileInfo


class TaskResponse(BaseModel):
    """Fields visible to competitors."""

    id: UUID
    challenge_id: UUID
    title: str
    folder_name: str | None = None
    evaluation_mode: str = "notebook"
    emergency_upload_enabled: bool = False
    mode_locked: bool = False
    files_locked: bool = False
    description: str | None = None
    files: list[FileInfo] = []
    ram_limit_mb: int | None = None
    time_limit_sec: int | None = None
    gpu_required: bool | None = None
    base_docker_image: str | None = None
    apt_packages: str | None = None
    pip_requirements: str | None = None
    ban_magic_commands: bool | None = None
    banned_imports: str | None = None
    whitelisted_imports: str | None = None
    metrics_config: dict[str, Any] | None = None
    hf_folders: list[str] = []
    # Whether HF data reaches this task's code: notebook runs, or workspaces for file tasks
    hf_applies: bool = True
    hf_unpacked_bytes: int | None = None
    hf_file_count: int | None = None
    public_eval_percentage: int | None = None
    max_submissions_per_period: int | None = None
    submission_period_hours: int | None = None
    stage_id: UUID | None = None
    evaluator_script_path: str | None = None
    evaluator_metric_name: str | None = None
    evaluator_options_schema: str | None = None
    baseline_notebook_path: str | None = None
    solution_notebook_path: str | None = None

    model_config = RESPONSE_CONFIG


class TaskAdminResponse(TaskResponse):
    """All fields — visible to admin/jury only."""

    problem_codes: list[str] | None = None
    problem_fields: dict[str, dict[str, Any]] | None = Field(
        default=None, description="Message fields stored with some problem codes, by code"
    )
    hf_zip_sha256: str | None = None
    hf_zip_size: int | None = None
    hf_skipped_count: int | None = None
    hf_zip_not_imported: bool = False

    model_config = RESPONSE_CONFIG
