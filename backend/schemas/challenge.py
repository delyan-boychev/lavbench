from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Self
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator, model_validator

from schemas.common import _parse_datetime_strict
from schemas.exceptions import SchemaError


class _ChallengeLimits(BaseModel):
    max_eval_requests: int | None = Field(default=None, ge=1)
    ram_limit_mb: int | None = Field(default=None, ge=128)
    time_limit_sec: int | None = Field(default=None, ge=1)


class CreateChallengeSchema(_ChallengeLimits):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None)
    gpu_required: bool = True
    double_blind: bool = True
    start_time: datetime = Field(...)
    end_time: datetime = Field(...)
    timezone: str = "UTC"
    is_frozen: bool = False
    test_stage_start_time: datetime | None = Field(default=None)
    test_stage_end_time: datetime | None = Field(default=None)

    @field_validator(
        "start_time", "end_time", "test_stage_start_time", "test_stage_end_time", mode="before"
    )
    @classmethod
    def _parse_dt(cls, v: Any) -> datetime | None:
        return _parse_datetime_strict(v)

    @model_validator(mode="after")
    def check_dates(self) -> Self:
        start = self.start_time
        end = self.end_time
        if start and end:
            tz = ZoneInfo(self.timezone) if self.timezone != "UTC" else UTC
            if start.tzinfo is None:
                start = start.replace(tzinfo=tz)
            if end.tzinfo is None:
                end = end.replace(tzinfo=tz)
            if end <= start:
                raise SchemaError("ERR_INVALID_DATE_RANGE", "end_time must be after start_time")
        return self


class UpdateChallengeSchema(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None)
    max_eval_requests: int | None = Field(default=None, ge=1)
    ram_limit_mb: int | None = Field(default=None, ge=128)
    time_limit_sec: int | None = Field(default=None, ge=1)
    gpu_required: bool | None = Field(default=None)
    double_blind: bool | None = Field(default=None)
    start_time: datetime | None = Field(default=None)
    end_time: datetime | None = Field(default=None)
    timezone: str | None = Field(default=None)
    is_frozen: bool | None = Field(default=None)
    test_stage_start_time: datetime | None = Field(default=None)
    test_stage_end_time: datetime | None = Field(default=None)

    @field_validator(
        "start_time", "end_time", "test_stage_start_time", "test_stage_end_time", mode="before"
    )
    @classmethod
    def _parse_dt(cls, v: Any) -> datetime | None:
        return _parse_datetime_strict(v)

    @model_validator(mode="after")
    def check_dates(self) -> Self:
        start = self.start_time
        end = self.end_time
        if start and end:
            tz_str = self.timezone or "UTC"
            tz = ZoneInfo(tz_str) if tz_str != "UTC" else UTC
            if start.tzinfo is None:
                start = start.replace(tzinfo=tz)
            if end.tzinfo is None:
                end = end.replace(tzinfo=tz)
            if end <= start:
                raise SchemaError("ERR_INVALID_DATE_RANGE", "end_time must be after start_time")
        return self
