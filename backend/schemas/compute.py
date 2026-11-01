"""Pydantic schemas for stage compute and workspace paths."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.exceptions import SchemaError

IMAGE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{0,62}$")


class StageComputeSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    published: bool = False
    compute_kind: Literal["CPU", "GPU"] = "CPU"
    cpu_cores: int = Field(default=2, ge=1, le=128)
    memory_gib: int = Field(default=8, ge=1, le=1024)
    disk_gib: int = Field(default=10, ge=10, le=65536)
    gpu_type: str | None = Field(default=None, max_length=100)
    image_id: str = Field(default="", max_length=500)
    max_attendance: int = Field(default=1, ge=1, le=10000)
    retention_days: int = Field(default=30, ge=1, le=365)

    @model_validator(mode="after")
    def check_enabled_fields(self) -> Self:
        if self.image_id and not IMAGE_ID_PATTERN.fullmatch(self.image_id):
            raise SchemaError("ERR_INVALID_WORKSPACE_IMAGE", "Choose an environment from the list.")
        if self.enabled and not self.image_id:
            raise SchemaError("ERR_INVALID_WORKSPACE_IMAGE", "Choose an environment from the list.")
        if self.compute_kind == "GPU" and not self.gpu_type:
            raise SchemaError("ERR_VALIDATION", "GPU compute requires a GPU type.")
        return self


def _safe_path(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > 512 or value.startswith("/") or "\\" in value:
        raise SchemaError("ERR_INVALID_WORKSPACE_PATH", "Path must be relative to the workspace.")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts) or PurePosixPath(value).as_posix() != value:
        raise SchemaError("ERR_INVALID_WORKSPACE_PATH", "Path must be relative to the workspace.")
    return value


class WorkspacePathsSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_path: str | None = None
    notebook_path: str | None = None

    @field_validator("submission_path", "notebook_path", mode="before")
    @classmethod
    def _validate_path(cls, v: Any) -> str | None:
        return _safe_path(v)
