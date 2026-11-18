"""Response models for nanoColab environments, workspaces and launches."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from schemas.responses._base import RESPONSE_CONFIG


class EnvironmentStatusResponse(BaseModel):
    state: str
    published: bool
    progress: int | None = None
    since: str | None = None
    alert: bool = False
    code: str | None = None
    message: str | None = None
    limit: str | None = None
    fetched_at: str | None = None


class WorkspaceSettingResponse(BaseModel):
    enabled: bool
    auto_publish: bool
    image_id: str
    profile_id: str
    cpu_cores: int
    memory_gib: int
    workspace_gib: int
    archive_until: str | None = None


class EnvironmentResponse(BaseModel):
    id: UUID | None = None
    challenge_id: UUID
    stage_id: UUID | None = None
    stage_title: str | None = None
    enabled: bool
    auto_publish: bool
    published_at: str | None = None
    compute_kind: str
    cpu_cores: int
    memory_gib: int
    workspace_gib: int
    data_gib: int
    disk_gib: int
    gpu_type: str | None = None
    image_id: str
    image_digest: str | None = None
    archive_until: str
    max_attendance: int
    starts_at: str
    ends_at: str
    asset_version: str | None = None
    folders: list[str | None]
    status: EnvironmentStatusResponse

    model_config = RESPONSE_CONFIG


class EnvironmentListResponse(BaseModel):
    environments: list[EnvironmentResponse]

    model_config = RESPONSE_CONFIG


class WorkspacePackageResponse(BaseModel):
    name: str
    version: str


class WorkspaceImageResponse(BaseModel):
    image_id: str
    name: str
    description: str = ""
    packages: list[WorkspacePackageResponse] = []
    default: bool = False


class WorkspaceProfileResponse(BaseModel):
    id: str
    name: str
    cpu_cores: int
    memory_gib: int


class WorkspaceSizeResponse(BaseModel):
    min: int
    max: int
    default: int


class WorkspaceImagesResponse(BaseModel):
    available: bool
    images: list[WorkspaceImageResponse]
    profiles: list[WorkspaceProfileResponse]
    workspace_gib: WorkspaceSizeResponse

    model_config = RESPONSE_CONFIG


class WorkspaceRowResponse(BaseModel):
    user_id: UUID
    alias: str
    username: str | None = None
    opened: bool
    created_at: str | None = None
    last_launched_at: str | None = None
    last_submission_at: str | None = None
    last_submission_status: str | None = None


class WorkspaceListResponse(BaseModel):
    workspaces: list[WorkspaceRowResponse]

    model_config = RESPONSE_CONFIG


class TaskEnvironmentResponse(BaseModel):
    status: str
    folder_name: str | None = None
    open_path: str
    starts_at: str
    ends_at: str

    model_config = RESPONSE_CONFIG


class EnvironmentLaunchResponse(BaseModel):
    launch_url: str
    launch_token: str
    expires_at: str
    open_path: str

    model_config = RESPONSE_CONFIG
