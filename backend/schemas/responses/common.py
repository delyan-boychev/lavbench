"""Shared response models — error, pagination, small reusable shapes."""

from __future__ import annotations

from pydantic import BaseModel, Field

from schemas.responses._base import RESPONSE_CONFIG


class ErrorResponse(BaseModel):
    code: str = Field(..., description="Machine-readable error code, e.g. ERR_INVALID_CREDENTIALS")
    error: str = Field(..., description="Human-readable error message")

    model_config = RESPONSE_CONFIG


class MessageResponse(BaseModel):
    message: str

    model_config = RESPONSE_CONFIG


class PaginatedResponse[T](BaseModel):
    items: list[T]
    total: int
    page: int
    pages: int

    model_config = RESPONSE_CONFIG


class HealthResponse(BaseModel):
    status: str
    version: str

    model_config = RESPONSE_CONFIG


class CellResponse(BaseModel):
    id: int
    type: str = Field(..., pattern=r"^(code|markdown)$")
    source: str

    model_config = RESPONSE_CONFIG


class FileInfo(BaseModel):
    filename: str
    saved_name: str | None = None
    size_bytes: int | None = None
    type: str | None = None

    model_config = RESPONSE_CONFIG


class DeleteResponse(BaseModel):
    message: str

    model_config = RESPONSE_CONFIG


class TokenResponse(BaseModel):
    csrf_token: str

    model_config = RESPONSE_CONFIG
