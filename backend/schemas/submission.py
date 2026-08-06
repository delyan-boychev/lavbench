"""Pydantic schemas for the submissions blueprint."""

from __future__ import annotations

import json as jsonlib
from typing import Any

from pydantic import BaseModel, Field, field_validator

from config import Config
from schemas.exceptions import SchemaError


class SelectedCellsSchema(BaseModel):
    selected_cells: list[dict[str, Any]] = Field(
        ...,
        min_length=1,
        max_length=Config.MAX_SELECTED_CELLS,
    )

    @field_validator("selected_cells", mode="before")
    @classmethod
    def _validate_cells(cls, v: Any) -> Any:
        if isinstance(v, str) or not isinstance(v, (list, tuple)):
            raise SchemaError("ERR_INVALID_SELECTED_CELLS", "Each selected cell must be a dict.")
        if len(v) > Config.MAX_SELECTED_CELLS:
            raise SchemaError(
                "ERR_PAYLOAD_TOO_LARGE",
                f"A submission may contain at most {Config.MAX_SELECTED_CELLS} cells.",
            )
        total_bytes = 0
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
            source = cell.get("source", "")
            if isinstance(source, str) and len(source) > Config.MAX_CODE_CELL_CHARS:
                raise SchemaError(
                    "ERR_PAYLOAD_TOO_LARGE",
                    f"A single cell may contain at most {Config.MAX_CODE_CELL_CHARS} characters.",
                )
            cell_bytes = len(
                jsonlib.dumps(cell, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
            if cell_bytes > Config.MAX_CODE_CELL_CHARS:
                raise SchemaError(
                    "ERR_PAYLOAD_TOO_LARGE",
                    f"A single cell may contain at most {Config.MAX_CODE_CELL_CHARS} bytes.",
                )
            total_bytes += cell_bytes
            if total_bytes > Config.MAX_CODE_CELLS_CHARS:
                raise SchemaError(
                    "ERR_PAYLOAD_TOO_LARGE",
                    f"Submission code may contain at most {Config.MAX_CODE_CELLS_CHARS} bytes.",
                )
        return v


class SubmitCodeSchema(SelectedCellsSchema):
    task_id: str = Field(..., min_length=1)
