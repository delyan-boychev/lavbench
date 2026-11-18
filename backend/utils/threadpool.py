"""Run CPU-bound work off the gevent hub so one request does not stall the others."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def run_blocking[T](func: Callable[..., T], *args: Any) -> T:
    """Call *func* in gevent's native threadpool when gevent patched the process, else inline."""
    try:
        from gevent import get_hub, monkey  # type: ignore[import-untyped]
    except ImportError:
        return func(*args)
    if not monkey.is_module_patched("threading"):
        return func(*args)
    result: T = get_hub().threadpool.apply(func, args)
    return result
