from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from schemas.exceptions import SchemaError


class SelectedCellsSchema(BaseModel):
    selected_cells: list[dict[str, Any]] = Field(..., min_length=1)

    @field_validator("selected_cells", mode="after")
    @classmethod
    def _validate_cells(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for cell in v:
            if not isinstance(cell, dict):
                raise SchemaError(
                    "ERR_INVALID_SELECTED_CELLS", "Each selected cell must be a dict."
                )
            if not {"id", "type", "source"}.intersection(cell):
                raise SchemaError(
                    "ERR_INVALID_SELECTED_CELLS",
                    "Each selected cell must have at least an id, type, and source.",
                )
        return v


class SubmitCodeSchema(SelectedCellsSchema):
    task_id: str = Field(..., min_length=1)
