"""Submission endpoint response models."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from schemas.responses._base import RESPONSE_CONFIG
from schemas.responses.admin import UserMinimalResponse, UserResponse


class SubmissionResponse(BaseModel):
    id: UUID
    challenge_id: UUID
    task_id: UUID | None = None
    task_title: str | None = None
    status: str
    detailed_status: str | None = None
    origin: str | None = Field(
        default=None,
        description=(
            "How the submission arrived: cells, workspace, emergency_upload or baseline; "
            "null on rows created before origins were recorded."
        ),
    )
    evaluation_time_ms: int | None = Field(
        default=None, description="Time the scoring step took; admin and jury only."
    )
    artifact_size: int | None = None
    has_notebook: bool = False
    artifact_sha256: str | None = None
    notebook_sha256: str | None = None
    workspace_meta: dict[str, Any] | None = None
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
    celery_task_id: str | None = None

    model_config = RESPONSE_CONFIG


class SubmissionLightResponse(SubmissionResponse):
    code_cells: str | None = None
    logs: str | None = None

    model_config = RESPONSE_CONFIG


class FinalSelectionState(BaseModel):
    """A competitor's final-selection state on one task, computed by the server."""

    open: bool = Field(..., description="Whether the final submission can still be chosen")
    closes_at: str | None = Field(
        None, description="RFC 3339 UTC close time; null while a run sent in time is still pending"
    )
    counted_submission: SubmissionLightResponse | None = Field(
        None, description="The run that counts now: the selected one, else the best public score"
    )

    model_config = RESPONSE_CONFIG


class TaskSubmissionsResponse(BaseModel):
    items: list[SubmissionLightResponse]
    total: int
    page: int
    pages: int
    final_selection: FinalSelectionState | None = Field(
        None, description="The viewer's own selection state; competitors only"
    )

    model_config = RESPONSE_CONFIG


class SubmissionsListResponse(BaseModel):
    submissions: list[SubmissionLightResponse]
    total: int
    page: int
    pages: int
    per_page: int
    challenge: dict[str, Any] | None = None

    model_config = RESPONSE_CONFIG


class BestSubmissionsResponse(BaseModel):
    items: list[SubmissionLightResponse]

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
