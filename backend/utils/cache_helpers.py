"""Memoization helpers layered on top of the Redis cache."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from config import Config
from utils.cache_utils import get_cached, set_cached


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
