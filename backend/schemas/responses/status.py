"""Status response models for GET /api/status and GET /api/admin/system-status."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from schemas.responses._base import RESPONSE_CONFIG

# Statuspage component status words, ordered from best to worst
StatusWord = Literal[
    "operational",
    "degraded_performance",
    "partial_outage",
    "major_outage",
    "under_maintenance",
]


class StatusComponents(BaseModel):
    api: StatusWord = Field(..., description="Database and broker reachable")
    scoring: StatusWord = Field(
        ..., description="Live consumers on the evaluation queues and queue age"
    )

    model_config = RESPONSE_CONFIG


class PublicStatusResponse(BaseModel):
    status: StatusWord = Field(..., description="Worst status across components")
    components: StatusComponents
    updated_at: str = Field(..., description="RFC 3339 UTC time the status was computed")

    model_config = RESPONSE_CONFIG


class QueueStatus(BaseModel):
    name: str
    consumers: int = Field(..., description="Workers with a fresh heartbeat consuming this queue")
    queued: int = Field(..., description="Messages pending on the broker queue")

    model_config = RESPONSE_CONFIG


class WorkerHeartbeat(BaseModel):
    name: str
    type: str = Field(..., description="'cpu' or 'gpu'")
    queues: list[str]
    online: bool = Field(..., description="Heartbeat younger than WORKER_HEARTBEAT_STALE_SECONDS")
    last_seen: str | None = Field(None, description="RFC 3339 UTC time of the last heartbeat")
    concurrency: int | None = None
    cpu_cores: int | None = None
    ram_gb: float | None = None
    gpu_type: str | None = None
    vram_gb: float | None = None

    model_config = RESPONSE_CONFIG


class SubmissionCounts(BaseModel):
    queued: int
    running: int
    oldest_queued_seconds: int | None = Field(
        None, description="Age of the oldest queued submission, or null when none is queued"
    )
    completed_last_15m: int
    failed_last_15m: int

    model_config = RESPONSE_CONFIG


class SystemStatusResponse(BaseModel):
    status: StatusWord
    components: StatusComponents
    queues: list[QueueStatus]
    workers: list[WorkerHeartbeat]
    submissions: SubmissionCounts
    updated_at: str

    model_config = RESPONSE_CONFIG
