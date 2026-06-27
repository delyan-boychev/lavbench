from cache_utils import get_cached, set_cached
from flask import current_app


def cached_or_compute(cache_key, compute_fn, timeout=300):
    result = get_cached(cache_key)
    if result is not None:
        return result
    result = compute_fn()
    set_cached(cache_key, result, timeout=timeout)
    return result


def cached_or_compute_unless_testing(cache_key, compute_fn, timeout=300):
    if current_app.config.get("TESTING", False):
        return compute_fn()
    return cached_or_compute(cache_key, compute_fn, timeout=timeout)
