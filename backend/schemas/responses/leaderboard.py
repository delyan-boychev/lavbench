"""Leaderboard endpoint response models."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel

from schemas.responses._base import RESPONSE_CONFIG
from schemas.responses.task import TaskResponse


class LeaderboardResponse(BaseModel):
    challenge_id: UUID | None = None
    challenge_title: str | None = None
    metric_name: str = "Score"
    is_normalized: bool = False
    is_finalized: bool = False
    reveal_results: bool = True
    tasks: list[TaskResponse]
    leaderboard: list[dict[str, Any]]

    model_config = RESPONSE_CONFIG


class TaskLeaderboardResponse(BaseModel):
    challenge_title: str | None = None
    task_title: str | None = None
    metric_name: str = "Score"
    is_normalized: bool = False
    is_finalized: bool = False
    leaderboard: list[dict[str, Any]]

    model_config = RESPONSE_CONFIG


class ManualPointsResponse(BaseModel):
    message: str
    user_id: UUID
    manual_points: dict[str, Any]

    model_config = RESPONSE_CONFIG
