"""Worker endpoint response models."""

from typing import Any

from pydantic import BaseModel

from schemas.responses._base import RESPONSE_CONFIG


class WorkerActiveTasksResponse(BaseModel):
    tasks: list[dict[str, Any]]

    model_config = RESPONSE_CONFIG


class WorkerActiveDatasetsResponse(BaseModel):
    datasets: list[str]
    hf_api_key: str | None = None
    model_config = RESPONSE_CONFIG


class WorkerHfKeyResponse(BaseModel):
    hf_key: str | None = None

    model_config = RESPONSE_CONFIG


class WorkerStatusResponse(BaseModel):
    model_config = RESPONSE_CONFIG


class WorkerReportResponse(BaseModel):
    message: str

    model_config = RESPONSE_CONFIG


class WorkerLogsResponse(BaseModel):
    status: str

    model_config = RESPONSE_CONFIG
