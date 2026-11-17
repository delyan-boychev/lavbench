"""Shared Pydantic schema helpers (spectree validation error formatting)."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from schemas.exceptions import SchemaError
from utils.error_utils import err


def _format_validation_error_for_response(resp: Any, e: ValidationError) -> None:
    """Modify a Flask Response in-place to reformat validation errors.

    Used by the spectree ``before`` handler to replace the default pydantic
    error list with the project convention: ``{"error": "<msg>", "code": "ERR_*"}``.
    """
    details = []
    specific: SchemaError | None = None
    specific_field = ""
    for err_item in e.errors():
        field = " → ".join(str(loc) for loc in err_item["loc"])
        ctx = err_item.get("ctx", {})
        error_obj = ctx.get("error")
        if isinstance(error_obj, SchemaError):
            if specific is None:
                specific = error_obj
                path = [str(loc) for loc in err_item["loc"]]
                specific_field = ".".join([*path, error_obj.field] if error_obj.field else path)
            details.append(f"{field}: {error_obj.message}")
        else:
            details.append(f"{field}: {err_item['msg']}")
    if specific is not None:
        message: str | None = "; ".join(details)
        # The field lets a form show the message under the input it is about
        extra = {**specific.extra, "field": specific_field} if specific_field else specific.extra
        new_resp, _ = err(specific.code, 422, message=message, **extra)
    else:
        message = "; ".join(details) if details else None
        new_resp, _ = err("ERR_VALIDATION", 422, message=message)
    resp.data = new_resp.data
    resp.content_type = new_resp.content_type
    resp.status_code = 422
    resp.headers.clear()
    for key, value in new_resp.headers:
        resp.headers[key] = value
