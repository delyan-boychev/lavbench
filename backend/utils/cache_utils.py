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

_pools: dict[str, redis_lib.ConnectionPool] = {}
_pools_pid: int | None = None

_sse_pools: dict[str, redis_lib.ConnectionPool] = {}
_sse_pools_pid: int | None = None

DIRTY_CHALLENGES_SET = "leaderboard:dirty_challenges"


def worker_spec_key(hostname: str) -> str:
    return f"worker_spec:{hostname}"


def submission_fallback_key(submission_id: Any) -> str:
    return f"submission:{submission_id}:fallback"


def submission_logs_key(submission_id: Any) -> str:
    return f"submission:{submission_id}:logs"


def _build_ssl_kwargs(url: str) -> dict[str, Any]:
    ssl_kwargs: dict[str, Any] = {}
    if url.startswith("rediss://"):
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
    return ssl_kwargs


def _get_pool(url: str) -> redis_lib.ConnectionPool | None:
    global _pools_pid
    current_pid = os.getpid()
    if _pools_pid != current_pid:
        _pools.clear()
        _pools_pid = current_pid
    pool = _pools.get(url)
    if pool is None:
        try:
            pool = redis_lib.ConnectionPool.from_url(
                url,
                max_connections=100,
                socket_connect_timeout=Config.REDIS_SOCKET_CONNECT_TIMEOUT,
                socket_timeout=Config.REDIS_SOCKET_TIMEOUT,
                retry_on_timeout=True,
                **_build_ssl_kwargs(url),
            )
            _pools[url] = pool
        except Exception:
            logger.exception("Failed to create Redis connection pool for %s", url)
            return None
    return pool


def _client_for(url: str) -> redis_lib.Redis[Any] | None:
    pool = _get_pool(url)
    if pool is None:
        return None
    return redis_lib.Redis(connection_pool=pool)


def get_redis_client() -> redis_lib.Redis[Any] | None:
    """Returns a Redis client from a shared ConnectionPool (auto-reconnect, greenlet-safe)."""
    return _client_for(Config.CACHE_REDIS_URL or Config.CELERY_BROKER_URL)


def get_coordination_client() -> redis_lib.Redis[Any] | None:
    """Returns a Redis client bound to the Celery broker (shared across machines)."""
    return _client_for(Config.CELERY_BROKER_URL or "redis://localhost:6379/0")


def redis_dependency_is_healthy(client: redis_lib.Redis[Any] | None, *, require_aof: bool) -> bool:
    """Check Redis connectivity, loading/persistence state, and memory headroom."""
    if client is None or not client.ping():
        return False

    persistence = client.info("persistence")
    if int(persistence.get("loading", 0)) != 0:
        return False
    if require_aof and (
        int(persistence.get("aof_enabled", 0)) != 1
        or persistence.get("aof_last_write_status") != "ok"
    ):
        return False

    memory = client.info("memory")
    used_memory = int(memory.get("used_memory", 0))
    maxmemory = int(memory.get("maxmemory", 0))
    if maxmemory > 0:
        maximum_used_percent = 100 - Config.REDIS_HEALTH_MIN_FREE_PERCENT
        if used_memory * 100 > maxmemory * maximum_used_percent:
            return False
    return True


def _get_sse_pool(url: str) -> redis_lib.ConnectionPool | None:
    """Connection pool for blocking pubsub subscriptions, sized to SSE_MAX_GLOBAL.

    Kept separate from the general pool so that long-lived pubsub connections
    held by SSE streams can never exhaust the connections used by cache and
    coordination operations.
    """
    global _sse_pools_pid
    current_pid = os.getpid()
    if _sse_pools_pid != current_pid:
        _sse_pools.clear()
        _sse_pools_pid = current_pid
    pool = _sse_pools.get(url)
    if pool is None:
        try:
            pool = redis_lib.ConnectionPool.from_url(
                url,
                max_connections=max(Config.SSE_MAX_GLOBAL, 100),
                socket_connect_timeout=Config.REDIS_SOCKET_CONNECT_TIMEOUT,
                socket_timeout=Config.REDIS_SOCKET_TIMEOUT,
                retry_on_timeout=True,
                **_build_ssl_kwargs(url),
            )
            _sse_pools[url] = pool
        except Exception:
            logger.exception("Failed to create SSE Redis connection pool for %s", url)
            return None
    return pool


def get_sse_client() -> redis_lib.Redis[Any] | None:
    """Returns a Redis client for blocking pubsub SSE subscriptions.

    Uses a dedicated pool (sized >= SSE_MAX_GLOBAL) so up to SSE_MAX_GLOBAL
    concurrent streams never starve the shared pools.
    """
    pool = _get_sse_pool(Config.CELERY_BROKER_URL or "redis://localhost:6379/0")
    if pool is None:
        return None
    return redis_lib.Redis(connection_pool=pool)


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


def log_dead_letter(
    submission_id: Any, task_id: Any = None, challenge_id: Any = None, error: Any = None
) -> None:
    """Logs a permanently failed Celery task to Redis for inspection."""
    r = get_coordination_client()
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


def get_queue_depth(queue_name: str) -> int:
    """Return the number of messages currently pending on a Celery queue.

    Includes priority sub-queues (Celery stores messages with ``priority=N``
    under ``{queue}@{N}`` keys, e.g. ``cpu_queue@0`` / ``cpu_queue@8``, so the
    bare key alone would undercount). Fails open (returns 0) when Redis is
    unavailable so submissions are never rejected because of a monitoring
    hiccup.
    """
    r = get_coordination_client()
    if not r:
        return 0
    try:
        total = int(r.llen(queue_name) or 0)
        cursor = 0
        while True:
            cursor, keys = r.scan(cursor=cursor, match=f"{queue_name}@*", count=500)
            for k in keys:
                total += int(r.llen(k) or 0)
            if cursor == 0:
                break
        return total
    except Exception:
        logger.exception("Failed to read queue depth for %s", queue_name)
        return 0


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
        r = get_coordination_client()
        if r:
            with suppress(Exception):
                r.srem(DIRTY_CHALLENGES_SET, challenge_id)
        return

    r = get_coordination_client()
    if r:
        try:
            r.sadd(DIRTY_CHALLENGES_SET, challenge_id)
            return
        except Exception as e:
            logger.warning("Failed to mark challenge %s as dirty in Redis: %s", challenge_id, e)

    # Fallback if Redis is down/unavailable: delete cache to avoid serving stale indefinitely
    delete_cached(f"leaderboard:raw:{challenge_id}:frozen")
    delete_cached(f"leaderboard:raw:{challenge_id}:unfrozen")
