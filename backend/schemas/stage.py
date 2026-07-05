from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from schemas.common import _parse_datetime_strict
from schemas.exceptions import SchemaError


class CreateStageSchema(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    stage_number: int | None = Field(default=None, ge=1)
    start_time: datetime = Field(...)
    end_time: datetime = Field(...)

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def _parse_dt(cls, v):
        return _parse_datetime_strict(v)

    @model_validator(mode="after")
    def check_dates(self):
        if self.end_time and self.start_time and self.end_time <= self.start_time:
            raise SchemaError("ERR_INVALID_DATE_RANGE", "Stage end_time must be after start_time.")
        return self


class UpdateStageSchema(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    stage_number: int | None = Field(default=None, ge=1)
    start_time: datetime | None = Field(default=None)
    end_time: datetime | None = Field(default=None)
    reveal_results: bool | None = Field(default=None)
    is_finalized: bool | None = Field(default=None)

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def _parse_dt(cls, v):
        return _parse_datetime_strict(v)

    @model_validator(mode="after")
    def check_dates(self):
        if self.end_time and self.start_time and self.end_time <= self.start_time:
            raise SchemaError("ERR_INVALID_DATE_RANGE", "Stage end_time must be after start_time.")
        return self


class CreateTestStageSchema(BaseModel):
    start_time: datetime = Field(...)
    end_time: datetime = Field(...)

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def _parse_dt(cls, v):
        return _parse_datetime_strict(v)

    @model_validator(mode="after")
    def check_dates(self):
        if self.end_time and self.start_time and self.end_time <= self.start_time:
            raise SchemaError(
                "ERR_INVALID_DATE_RANGE", "Test stage end_time must be after start_time."
            )
        return self


class RevealResultsSchema(BaseModel):
    reveal_results: bool | None = Field(default=None)
