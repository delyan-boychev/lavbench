"""Task endpoint response models."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel

from schemas.responses._base import RESPONSE_CONFIG
from schemas.responses.common import FileInfo


class TaskResponse(BaseModel):
    """Fields visible to competitors."""

    id: UUID
    challenge_id: UUID
    title: str
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
    hf_datasets: list[str] = []
    hf_models: list[str] = []
    public_eval_percentage: int | None = None
    max_submissions_per_period: int | None = None
    submission_period_hours: int | None = None
    stage_id: UUID | None = None

    model_config = RESPONSE_CONFIG


class TaskAdminResponse(TaskResponse):
    """All fields — visible to admin/jury only."""

    evaluator_script_path: str | None = None
    baseline_notebook_path: str | None = None
    solution_notebook_path: str | None = None

    model_config = RESPONSE_CONFIG
