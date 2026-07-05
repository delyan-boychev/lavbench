from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, cast


def parse_json_body[T: Callable[..., Any]](f: T) -> T:
    @wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        from flask import request

        data = request.json or {}
        return f(data, *args, **kwargs)

    return cast(T, wrapper)
