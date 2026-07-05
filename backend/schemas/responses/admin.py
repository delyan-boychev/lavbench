"""Admin / User response models."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, RootModel

from schemas.responses._base import RESPONSE_CONFIG

# ── User ─────────────────────────────────────────────────────────────────


class UserMinimalResponse(BaseModel):
    id: UUID
    alias_id: str | None = None
    role: str
    challenge_id: UUID | None = None
    is_anonymous: bool | None = None
    jury_challenges: list[str] | None = None

    model_config = RESPONSE_CONFIG


class UserResponse(BaseModel):
    id: UUID
    username: str | None = None
    email: str | None = None
    name: str | None = None
    surname: str | None = None
    middle_name: str | None = None
    birth_date: str | None = None
    grade: str | None = None
    school: str | None = None
    city: str | None = None
    role: str
    alias_id: str | None = None
    challenge_id: UUID | None = None
    is_anonymous: bool | None = None
    manual_points: dict[str, Any] | None = None
    jury_challenges: list[str] | None = None

    model_config = RESPONSE_CONFIG


# ── User management ────────────────────────────────────────────────────


class RegisterUserResponse(BaseModel):
    message: str
    generated_username: str
    generated_password: str
    user: UserResponse

    model_config = RESPONSE_CONFIG


class UpdateUserResponse(BaseModel):
    message: str
    user: UserResponse

    model_config = RESPONSE_CONFIG


class ImportedCompetitorResponse(BaseModel):
    id: UUID
    name: str
    surname: str
    middle_name: str = ""
    birth_date: str
    email: str | None = None
    grade: str
    school: str
    city: str
    role: str
    is_anonymous: bool = False
    generated_username: str
    generated_password: str
    alias_id: str | None = None

    model_config = RESPONSE_CONFIG


class ImportCompetitorsResponse(BaseModel):
    message: str
    competitors: list[ImportedCompetitorResponse]

    model_config = RESPONSE_CONFIG


class ResetPasswordResponse(BaseModel):
    message: str
    username: str
    password: str

    model_config = RESPONSE_CONFIG


class BulkResetPasswordResponse(BaseModel):
    message: str
    reset_accounts: list[dict[str, Any]]

    model_config = RESPONSE_CONFIG


# ── Audit log ──────────────────────────────────────────────────────────


class AuditLogResponse(BaseModel):
    id: UUID
    admin_id: UUID
    admin_username: str | None = None
    action_type: str
    target_type: str
    target_id: str | None = None
    details: str | None = None
    ip_address: str | None = None
    timestamp: str | None = None
    target_user_id: UUID | None = None
    target_user_username: str | None = None
    task_id: UUID | None = None
    task_title: str | None = None
    old_score: float | None = None
    new_score: float | None = None
    reason: str | None = None

    model_config = RESPONSE_CONFIG


class AuditLinkListResponse(BaseModel):
    logs: list[AuditLogResponse]
    total: int
    pages: int
    page: int
    per_page: int

    model_config = RESPONSE_CONFIG


# ── Backups ────────────────────────────────────────────────────────────


class BackupInfo(BaseModel):
    filename: str
    size_bytes: int | None = None
    created_at: str | None = None

    model_config = RESPONSE_CONFIG


class BackupListResponse(BaseModel):
    backups: list[BackupInfo]

    model_config = RESPONSE_CONFIG


class BackupStartResponse(BaseModel):
    task_id: str
    status: str = "started"

    model_config = RESPONSE_CONFIG


# ── Metrics ────────────────────────────────────────────────────────────


class AvailableMetricsResponse(RootModel[dict[str, dict[str, list[str] | str]]]):
    """Available metrics with their configurable parameters."""

    root: dict[str, dict[str, list[str] | str]]

    model_config = RESPONSE_CONFIG


# ── Worker stats ───────────────────────────────────────────────────────


class WorkerStatsResponse(BaseModel):
    """Free-form worker stats dict."""

    model_config = RESPONSE_CONFIG


# ── Dead letters ──────────────────────────────────────────────────────


class DeadLetterItem(BaseModel):
    id: UUID | None = None
    message: str | None = None
    timestamp: str | None = None
    details: dict[str, Any] | None = None

    model_config = RESPONSE_CONFIG


class DeadLetterListResponse(BaseModel):
    items: list[DeadLetterItem]

    model_config = RESPONSE_CONFIG
