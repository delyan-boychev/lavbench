from __future__ import annotations

from collections.abc import Callable
from typing import Any

from flask import current_app

from cache_utils import get_cached, set_cached
from config import Config


def cached_or_compute(
    cache_key: str, compute_fn: Callable[[], Any], timeout: int | None = None
) -> Any:
    timeout = timeout or Config.CACHE_TIMEOUT
    result = get_cached(cache_key)
    if result is not None:
        return result
    result = compute_fn()
    set_cached(cache_key, result, timeout=timeout)
    return result


def cached_or_compute_unless_testing(
    cache_key: str, compute_fn: Callable[[], Any], timeout: int | None = None
) -> Any:
    timeout = timeout or Config.CACHE_TIMEOUT
    if current_app.config.get("TESTING", False):
        return compute_fn()
    return cached_or_compute(cache_key, compute_fn, timeout=timeout)
