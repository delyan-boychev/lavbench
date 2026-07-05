"""Challenge / Stage / Submission endpoint response models."""

from uuid import UUID

from pydantic import BaseModel

from schemas.responses._base import RESPONSE_CONFIG
from schemas.responses.common import CellResponse
from schemas.responses.task import TaskResponse

# ── Stage ───────────────────────────────────────────────────────────────


class StageResponse(BaseModel):
    id: UUID
    challenge_id: UUID
    stage_number: int
    title: str
    start_time: str | None = None
    end_time: str | None = None
    is_finalized: bool | None = None
    reveal_results: bool | None = None
    is_test: bool | None = None

    model_config = RESPONSE_CONFIG


# ── Challenge ────────────────────────────────────────────────────────────


class ChallengeResponse(BaseModel):
    id: UUID
    title: str
    description: str | None = None
    max_eval_requests: int | None = None
    ram_limit_mb: int | None = None
    time_limit_sec: int | None = None
    gpu_required: bool | None = None
    is_active: bool | None = None
    is_archived: bool | None = None
    scores_finalized: bool | None = None
    reveal_results: bool | None = None
    start_time: str | None = None
    end_time: str | None = None
    is_frozen: bool | None = None
    double_blind: bool | None = None
    timezone: str = "UTC"
    status: str | None = None
    tasks: list[TaskResponse] = []
    stages: list[StageResponse] = []
    num_tasks: int = 0
    deadline_grace_period_seconds: int = 60

    model_config = RESPONSE_CONFIG


# ── Challenge operations ─────────────────────────────────────────────────


class FinalizeChallengeResponse(BaseModel):
    message: str
    challenge: ChallengeResponse

    model_config = RESPONSE_CONFIG


class RevealResultsResponse(BaseModel):
    reveal_results: bool
    challenge: ChallengeResponse

    model_config = RESPONSE_CONFIG


class ArchiveResponse(BaseModel):
    message: str
    challenge: ChallengeResponse

    model_config = RESPONSE_CONFIG


# ── Stage operations ────────────────────────────────────────────────────


# ── Notebook parse ──────────────────────────────────────────────────────


class ParseNotebookResponse(BaseModel):
    filename: str
    cells: list[CellResponse]

    model_config = RESPONSE_CONFIG


# ── Submit ──────────────────────────────────────────────────────────────


class SubmitResponse(BaseModel):
    message: str
    submission_id: UUID
    status: str = "queued"

    model_config = RESPONSE_CONFIG


# ── Final selection (model lives in submission.py to avoid circular refs) ──
