from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from error_utils import err
from schemas.exceptions import SchemaError


def _format_validation_error_for_response(resp: Any, e: ValidationError) -> None:
    """Modify a Flask Response in-place to reformat validation errors.

    Used by the spectree ``before`` handler to replace the default pydantic
    error list with the project convention: ``{"error": "<msg>", "code": "ERR_*"}``.
    """
    details = []
    specific_code = None
    for err_item in e.errors():
        field = " → ".join(str(loc) for loc in err_item["loc"])
        ctx = err_item.get("ctx", {})
        error_obj = ctx.get("error")
        if isinstance(error_obj, SchemaError):
            if specific_code is None:
                specific_code = error_obj.code
            details.append(f"{field}: {error_obj.message}")
        else:
            details.append(f"{field}: {err_item['msg']}")
    if specific_code:
        code = specific_code
        message: str | None = "; ".join(details)
        new_resp, _ = err(code, 422, message=message)
    else:
        message = "; ".join(details) if details else None
        new_resp, _ = err("ERR_VALIDATION", 422, message=message)
    resp.data = new_resp.data
    resp.content_type = new_resp.content_type
    resp.status_code = 422
    resp.headers.clear()
    for key, value in new_resp.headers:
        resp.headers[key] = value
