"""Pydantic schemas for the leaderboard blueprint."""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field, field_validator

from schemas.exceptions import SchemaError


class ManualPointsSchema(BaseModel):
    user_id: str = Field(..., min_length=1)
    points: dict[str, Any] = Field(..., min_length=1)
    reason: str | None = Field(default=None)

    @field_validator("points")
    @classmethod
    def validate_point_values(cls, v: dict[str, Any]) -> dict[str, int | float]:
        normalized: dict[str, int | float] = {}
        for task_id, val in v.items():
            # bool is an int subclass, so reject it explicitly
            if isinstance(val, bool) or not isinstance(val, int | float) or not math.isfinite(val):
                raise SchemaError(
                    "ERR_POINTS_INVALID", f"Points for task '{task_id}' must be a number."
                )
            if val < 0 or val > 100:
                raise SchemaError(
                    "ERR_POINTS_OUT_OF_BOUNDS",
                    f"Points for task '{task_id}' must be between 0 and 100.",
                )
            # Tolerance absorbs binary float noise such as 12.34 * 100 = 1233.9999999999998
            if abs(val * 100 - round(val * 100)) > 1e-6:
                raise SchemaError(
                    "ERR_POINTS_INVALID",
                    f"Points for task '{task_id}' can have at most 2 decimal places.",
                )
            rounded = round(float(val), 2)
            normalized[task_id] = int(rounded) if rounded.is_integer() else rounded
        return normalized
