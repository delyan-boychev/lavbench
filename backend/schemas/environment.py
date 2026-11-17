"""Pydantic schemas for nanoColab environments."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.common import _parse_datetime_strict
from schemas.exceptions import SchemaError

IMAGE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{0,62}$")


class SaveEnvironmentSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    auto_publish: bool = False
    compute_kind: Literal["CPU", "GPU"] = "CPU"
    cpu_cores: int = Field(default=2, ge=1, le=128)
    memory_gib: int = Field(default=8, ge=1, le=1024)
    disk_gib: int = Field(default=10, ge=10, le=65536)
    gpu_type: str | None = Field(default=None, min_length=1, max_length=100)
    image_id: str = Field(default="", max_length=63)
    archive_until: datetime | None = None

    @field_validator("archive_until", mode="before")
    @classmethod
    def _parse_archive_until(cls, v: Any) -> datetime | None:
        return _parse_datetime_strict(v)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.image_id and not IMAGE_ID_PATTERN.fullmatch(self.image_id):
            raise SchemaError("ERR_INVALID_WORKSPACE_IMAGE", "Choose an image from the list.")
        if self.compute_kind == "GPU" and not self.gpu_type:
            raise SchemaError("ERR_VALIDATION", "A GPU environment needs a GPU type.")
        return self


class ExtendEnvironmentSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    end_time: datetime
    reason: str = ""

    @field_validator("end_time", mode="before")
    @classmethod
    def _parse_end(cls, v: Any) -> datetime | None:
        return _parse_datetime_strict(v)

    @field_validator("reason", mode="after")
    @classmethod
    def _check_reason(cls, v: str) -> str:
        v = v.strip()
        # The reason goes to nanoColab, which needs 8 to 2000 characters
        if not 8 <= len(v) <= 2000:
            raise SchemaError("ERR_REASON_REQUIRED", "Give a reason of 8 to 2000 characters.")
        return v
