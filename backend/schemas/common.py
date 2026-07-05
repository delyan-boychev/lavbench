from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from schemas.exceptions import SchemaError


def _parse_datetime_strict(v: Any) -> datetime | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, datetime):
        return v
    try:
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            if "T" in v:
                v = v.split(".")[0]
            return datetime.strptime(v, "%Y-%m-%dT%H:%M:%S")
    except Exception:
        raise SchemaError(
            "ERR_INVALID_DATE_FORMAT",
            "Invalid date format. Use ISO-8601 (e.g., '2025-01-01T00:00:00Z').",
        ) from None


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=10, ge=1, le=100)
