"""SchemaError: validation error carrying an API error code."""

from __future__ import annotations

from typing import Any

from utils.error_utils import DEFAULT_ERROR_MESSAGES


class SchemaError(ValueError):
    def __init__(
        self, code: str, message: str = "", field: str | None = None, **extra: Any
    ) -> None:
        self.code = code
        # Without a message the code's default sentence is used, as in err()
        message = message or DEFAULT_ERROR_MESSAGES.get(code, "")
        self.message = message
        self.field = field
        self.extra = extra
        super().__init__(message)
