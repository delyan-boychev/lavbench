"""SchemaError: validation error carrying an API error code."""

from __future__ import annotations

from typing import Any


class SchemaError(ValueError):
    def __init__(
        self, code: str, message: str = "", field: str | None = None, **extra: Any
    ) -> None:
        self.code = code
        self.message = message
        self.field = field
        self.extra = extra
        super().__init__(message)
