"""Submission endpoint response models."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel

from schemas.responses._base import RESPONSE_CONFIG
from schemas.responses.admin import UserMinimalResponse, UserResponse


class SubmissionResponse(BaseModel):
    id: UUID
    challenge_id: UUID
    task_id: UUID | None = None
    task_title: str | None = None
    status: str
    detailed_status: str | None = None
    code_cells: str | None = None
    public_score: float | None = None
    private_score: float | None = None
    logs: str | None = None
    gpu_node: str | None = None
    execution_time_ms: int | None = None
    created_at: str | None = None
    executed_at: str | None = None
    user: UserMinimalResponse | UserResponse | None = None
    metrics_payload_public: dict[str, Any] | None = None
    metrics_payload_private: dict[str, Any] | None = None
    final_weighted_score_public: float | None = None
    final_weighted_score_private: float | None = None
    is_final_selection: bool = False
    is_baseline: bool = False
    is_disqualified: bool = False
    celery_task_id: str | None = None

    model_config = RESPONSE_CONFIG


class SubmissionLightResponse(SubmissionResponse):
    code_cells: str | None = None
    logs: str | None = None

    model_config = RESPONSE_CONFIG


class SubmissionsListResponse(BaseModel):
    submissions: list[SubmissionLightResponse]
    total: int
    page: int
    pages: int
    per_page: int
    challenge: dict[str, Any] | None = None

    model_config = RESPONSE_CONFIG


class QueueItemResponse(BaseModel):
    id: UUID
    status: str
    detailed_status: str | None = None
    user_id: UUID
    user_alias: str | None = None
    task_id: UUID | None = None
    task_title: str | None = None
    challenge_id: UUID
    created_at: str | None = None
    celery_task_id: str | None = None

    model_config = RESPONSE_CONFIG


class SelectFinalResponse(BaseModel):
    message: str
    submission: SubmissionResponse

    model_config = RESPONSE_CONFIG
