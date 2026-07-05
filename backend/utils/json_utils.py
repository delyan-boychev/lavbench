from __future__ import annotations

import contextlib
import json
from typing import Any


def safe_json_loads(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return list(value)
    with contextlib.suppress(json.JSONDecodeError, TypeError, ValueError):
        return json.loads(value)
    return default


def ensure_json_list(value: Any, default: Any = None) -> list[Any]:
    result = safe_json_loads(value, default)
    if not isinstance(result, list):
        return default or []
    return result
