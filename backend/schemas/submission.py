from pydantic import BaseModel, Field, field_validator

from schemas.exceptions import SchemaError


class SelectedCellsSchema(BaseModel):
    selected_cells: list[dict] = Field(..., min_length=1)

    @field_validator("selected_cells", mode="after")
    @classmethod
    def _validate_cells(cls, v):
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
