from pydantic import BaseModel, Field, field_validator

from schemas.exceptions import SchemaError


class ManualPointsSchema(BaseModel):
    user_id: str = Field(..., min_length=1)
    points: dict = Field(..., min_length=1)
    reason: str | None = Field(default=None)

    @field_validator("points")
    @classmethod
    def validate_point_values(cls, v):
        for task_id, val in v.items():
            if not isinstance(val, int):
                raise SchemaError(
                    "ERR_POINTS_MUST_BE_INT", f"Points for task '{task_id}' must be an integer."
                )
            if val < 0 or val > 100:
                raise SchemaError(
                    "ERR_POINTS_OUT_OF_BOUNDS",
                    f"Points for task '{task_id}' must be between 0 and 100.",
                )
        return v
