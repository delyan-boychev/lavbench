"""Redis connection pool, distributed cache locking, and dead-letter logging."""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections.abc import Generator
from contextlib import contextmanager, suppress
from typing import Any

import redis as redis_lib

from config import Config
from utils.dates import utcnow

logger = logging.getLogger(__name__)

_pool: redis_lib.ConnectionPool | None = None
_pool_pid: int | None = None


def get_redis_client() -> redis_lib.Redis[Any] | None:
    """Returns a Redis client from a shared ConnectionPool (auto-reconnect, greenlet-safe)."""
    global _pool, _pool_pid
    current_pid = os.getpid()
    if _pool is None or _pool_pid != current_pid:
        broker_url = Config.CELERY_BROKER_URL
        ssl_kwargs: dict[str, Any] = {}
        if broker_url.startswith("rediss://"):
            import ssl

            ssl_ca_certs = Config.REDIS_SSL_CA_CERTS or None
            ssl_certfile = Config.REDIS_SSL_CERTFILE or None
            ssl_keyfile = Config.REDIS_SSL_KEYFILE or None
            ssl_cert_reqs_str = Config.REDIS_SSL_CERT_REQS

            ssl_cert_reqs = ssl.CERT_REQUIRED
            if ssl_cert_reqs_str == "none":
                ssl_cert_reqs = ssl.CERT_NONE
            elif ssl_cert_reqs_str == "optional":
                ssl_cert_reqs = ssl.CERT_OPTIONAL

            ssl_kwargs["ssl_cert_reqs"] = ssl_cert_reqs
            if ssl_ca_certs:
                ssl_kwargs["ssl_ca_certs"] = ssl_ca_certs
            if ssl_certfile:
                ssl_kwargs["ssl_certfile"] = ssl_certfile
            if ssl_keyfile:
                ssl_kwargs["ssl_keyfile"] = ssl_keyfile

        try:
            _pool = redis_lib.ConnectionPool.from_url(
                broker_url,
                max_connections=100,
                socket_connect_timeout=Config.REDIS_SOCKET_CONNECT_TIMEOUT,
                socket_timeout=Config.REDIS_SOCKET_TIMEOUT,
                retry_on_timeout=True,
                **ssl_kwargs,
            )
            _pool_pid = current_pid
        except Exception:
            logger.exception("Failed to create Redis connection pool")
            return None
    return redis_lib.Redis(connection_pool=_pool)


@contextmanager
def cache_lock(lock_key: str, ttl: int = 120) -> Generator[bool, None, None]:
    """Context manager: acquires a Redis lock (SET NX), releases on exit.
    Uses a UUID value so only the owner can release (prevents TTL cross-deletion)."""
    r = get_redis_client()
    owner = uuid.uuid4().hex
    got = False
    if r:
        try:
            got = bool(r.set(lock_key, owner, nx=True, ex=ttl))
        except Exception:
            logger.exception("cache_lock acquire failed for %s", lock_key)
    try:
        yield bool(got)
    finally:
        if got and r:
            try:
                lua_script = """
                if redis.call('get', KEYS[1]) == ARGV[1] then
                    return redis.call('del', KEYS[1])
                end
                return 0
                """
                r.eval(lua_script, 1, lock_key, owner)  # type: ignore[no-untyped-call]
            except Exception as e:
                logger.warning("Failed to release Redis lock %s: %s", lock_key, e)


def acquire_cache_lock(lock_key: str, ttl: int = 30) -> bool:
    """Legacy compat — use `with cache_lock(key, ttl)` instead."""
    r = get_redis_client()
    if not r:
        return False
    try:
        return bool(r.set(lock_key, "1", nx=True, ex=ttl))
    except Exception:
        logger.exception("acquire_cache_lock failed for %s", lock_key)
        return False


def release_cache_lock(lock_key: str) -> None:
    """Legacy compat — automatically handled by cache_lock context manager."""
    r = get_redis_client()
    if not r:
        return
    with suppress(Exception):
        r.delete(lock_key)


def log_dead_letter(
    submission_id: Any, task_id: Any = None, challenge_id: Any = None, error: Any = None
) -> None:
    """Logs a permanently failed Celery task to Redis for inspection."""
    r = get_redis_client()
    if not r:
        return
    try:
        entry = {
            "submission_id": submission_id,
            "task_id": task_id,
            "challenge_id": challenge_id,
            "failed_at": utcnow().isoformat(),
            "error": str(error)[:1000] if error else None,
        }
        r.lpush("dead_letter_queue", json.dumps(entry))
        r.ltrim("dead_letter_queue", 0, 999)
    except Exception:
        logger.exception("log_dead_letter failed")


def get_cached(key: str) -> Any:
    """Get a JSON-deserialized value from Redis by key. Returns None on miss/error."""
    r = get_redis_client()
    if not r:
        return None
    try:
        data = r.get(key)
        if data:
            return json.loads(data)
    except Exception:
        logger.exception("Cache get error for %s", key)
    return None


def set_cached(key: str, value: Any, timeout: int = 300) -> bool:
    """JSON-serialize and store a value in Redis with an expiry TTL."""
    r = get_redis_client()
    if not r:
        return False
    try:
        r.set(key, json.dumps(value), ex=timeout)
        return True
    except Exception:
        logger.exception("Cache set error for %s", key)
        return False


def delete_cached(key: str) -> bool:
    """Delete a key from Redis. Returns True if deleted, False on error."""
    r = get_redis_client()
    if not r:
        return False
    try:
        r.delete(key)
        return True
    except Exception:
        logger.exception("Cache delete error for %s", key)
        return False


def invalidate_challenge_cache(challenge_id: Any = None) -> None:
    """Clear cached challenge listings and (optionally) a specific challenge entry."""
    delete_cached("challenges:all")
    if challenge_id:
        challenge_id = str(challenge_id)
        delete_cached(f"challenge:{challenge_id}")
        delete_cached(f"challenge:{challenge_id}:competitor")


def invalidate_leaderboard_cache(challenge_id: Any, delete_only: bool = False) -> None:
    """Mark the challenge leaderboard cache as dirty for periodic Celery Beat rebuilding."""
    if not challenge_id:
        return
    challenge_id = str(challenge_id)

    if delete_only:
        delete_cached(f"leaderboard:raw:{challenge_id}:frozen")
        delete_cached(f"leaderboard:raw:{challenge_id}:unfrozen")
        delete_cached(f"leaderboard:pending:{challenge_id}")
        r = get_redis_client()
        if r:
            with suppress(Exception):
                r.srem("leaderboard:dirty_challenges", challenge_id)
        return

    r = get_redis_client()
    if r:
        try:
            r.sadd("leaderboard:dirty_challenges", challenge_id)
            return
        except Exception as e:
            logger.warning("Failed to mark challenge %s as dirty in Redis: %s", challenge_id, e)

    # Fallback if Redis is down/unavailable: delete cache to avoid serving stale indefinitely
    delete_cached(f"leaderboard:raw:{challenge_id}:frozen")
    delete_cached(f"leaderboard:raw:{challenge_id}:unfrozen")
