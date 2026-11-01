"""Response models for stage compute, environments and workspace submissions."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel

from schemas.responses._base import RESPONSE_CONFIG


class StageComputeResponse(BaseModel):
    stage_id: UUID
    enabled: bool
    published: bool
    compute_kind: str
    cpu_cores: int
    memory_gib: int
    disk_gib: int
    gpu_type: str | None = None
    image_id: str
    image_digest: str
    asset_version: str
    package_state: str
    package_error: str | None = None
    max_attendance: int
    retention_days: int
    nanocolab_event_id: str | None = None
    sync_state: str
    last_synced_at: str | None = None
    last_sync_error: str | None = None
    declared_paths: list[str] = []
    task_folders: dict[str, str] = {}
    readiness: dict[str, Any] | None = None

    model_config = RESPONSE_CONFIG


class WorkspacePackageResponse(BaseModel):
    name: str
    version: str


class WorkspaceImageResponse(BaseModel):
    image_id: str
    name: str
    description: str
    digest: str
    packages: list[WorkspacePackageResponse]
    default: bool


class WorkspaceImagesResponse(BaseModel):
    images: list[WorkspaceImageResponse]

    model_config = RESPONSE_CONFIG


class EnvironmentStatusResponse(BaseModel):
    status: str
    retry_after_seconds: int | None = None
    message: str | None = None

    model_config = RESPONSE_CONFIG


class EnvironmentLaunchResponse(BaseModel):
    launch_url: str
    launch_token: str
    expires_at: str

    model_config = RESPONSE_CONFIG


class WorkspaceExportResponse(BaseModel):
    id: UUID
    task_id: UUID
    submission_id: UUID | None = None
    source: str
    exported_at: str | None = None
    csv_sha256: str
    csv_size: int
    notebook_sha256: str | None = None
    notebook_size: int | None = None

    model_config = RESPONSE_CONFIG


class WorkspaceSubmitResponse(BaseModel):
    submission_id: UUID
    status: str
    export: WorkspaceExportResponse

    model_config = RESPONSE_CONFIG


class WorkspacePathsResponse(BaseModel):
    task_id: UUID
    workspace_submission_path: str | None = None
    workspace_notebook_path: str | None = None
    sync_ok: bool

    model_config = RESPONSE_CONFIG
