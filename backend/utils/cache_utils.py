"""Redis connection pool, distributed cache locking, and dead-letter logging."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Generator, Iterable
from contextlib import contextmanager, suppress
from typing import Any

import redis as redis_lib

from config import Config
from utils.dates import utcnow

logger = logging.getLogger(__name__)

_pools: dict[str, redis_lib.BlockingConnectionPool] = {}
_pools_pid: int | None = None

_sse_pools: dict[str, redis_lib.BlockingConnectionPool] = {}
_sse_pools_pid: int | None = None

DIRTY_CHALLENGES_SET = "leaderboard:dirty_challenges"
DIRTY_LEADERBOARD_VERSIONS = "leaderboard:dirty_versions"

# Kombu's Redis transport keeps one list per priority step: step 0 is the bare queue
# Name, the others are "{queue}\x06\x16{step}"; the Celery app sets these steps (tests pin both)
KOMBU_PRIORITY_SEP = "\x06\x16"
EVALUATION_PRIORITY_STEPS = (0, 1, 2, 3, 4)

_MIGRATE_DIRTY_SET_SCRIPT = """
local members = redis.call('smembers', KEYS[1])
for _, challenge_id in ipairs(members) do
    redis.call('hincrby', KEYS[2], challenge_id, 1)
end
if #members > 0 then
    redis.call('del', KEYS[1])
end
return #members
"""

_DELETE_IF_VALUE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""

_EXPIRE_IF_VALUE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""

_CLEAR_DIRTY_VERSION_SCRIPT = """
local current = redis.call('hget', KEYS[1], ARGV[1])
if current == ARGV[2] then
    return redis.call('hdel', KEYS[1], ARGV[1])
end
return 0
"""


def worker_spec_key(hostname: str) -> str:
    return f"worker_spec:{hostname}"


def submission_fallback_key(submission_id: Any) -> str:
    return f"submission:{submission_id}:fallback"


def submission_logs_key(submission_id: Any) -> str:
    return f"submission:{submission_id}:logs"


def submission_status_key(submission_id: Any) -> str:
    return f"submission:{submission_id}:status"


def leaderboard_cache_key(challenge_id: Any) -> str:
    return f"leaderboard:raw:{challenge_id}"


def attempt_ended_key(attempt_id: Any) -> str:
    return f"attempt:ended:{attempt_id}"


def sandbox_live_key(attempt_id: Any) -> str:
    return f"sandbox:live:{attempt_id}"


# Longer than any delivery can run, so a worker sees the end before the key expires
ATTEMPT_ENDED_TTL_SECONDS = 4 * 3600


def mark_attempt_ended(attempt_id: Any) -> None:
    """Tell workers an attempt is over (killed, cleared, timed out): its sandbox is removed."""
    if not attempt_id:
        return
    r = get_coordination_client()
    if r is None:
        return
    try:
        pipe = r.pipeline(transaction=False)
        pipe.set(attempt_ended_key(attempt_id), "1", ex=ATTEMPT_ENDED_TTL_SECONDS)
        pipe.srem(EVAL_PENDING_SET, str(attempt_id))
        pipe.execute()
    except Exception as e:
        logger.warning("Could not mark attempt %s as ended: %s", attempt_id, e)


# Attempts sent to the broker and not yet claimed by a worker
EVAL_PENDING_SET = "eval:pending"
# Kept a day: a run claimed this long ago is over whatever its limits
ATTEMPT_CLAIMED_TTL_SECONDS = 86400


def attempt_claimed_key(attempt_id: Any) -> str:
    return f"attempt:claimed:{attempt_id}"


def mark_attempt_pending(attempt_id: Any) -> None:
    r = get_coordination_client()
    if r is not None and attempt_id:
        with suppress(Exception):
            r.sadd(EVAL_PENDING_SET, str(attempt_id))


def clear_attempt_pending(attempt_id: Any) -> None:
    r = get_coordination_client()
    if r is not None and attempt_id:
        with suppress(Exception):
            r.srem(EVAL_PENDING_SET, str(attempt_id))


def record_attempt_claimed(attempt_id: Any) -> None:
    """A worker took the attempt: it leaves the pending set and its claim time is kept."""
    r = get_coordination_client()
    if r is None or not attempt_id:
        return
    with suppress(Exception):
        pipe = r.pipeline(transaction=False)
        pipe.srem(EVAL_PENDING_SET, str(attempt_id))
        pipe.set(
            attempt_claimed_key(attempt_id),
            str(redis_time(r)),
            ex=ATTEMPT_CLAIMED_TTL_SECONDS,
            nx=True,
        )
        pipe.execute()


def broker_message_ids(queue_names: Iterable[str]) -> set[str]:
    """Task ids of every message waiting on the queues or held unacknowledged by a worker."""
    r = get_coordination_client()
    ids: set[str] = set()
    if r is None:
        raise LockUnavailableError("broker")
    for name in queue_names:
        for key in _priority_list_keys(name):
            for raw in r.lrange(key, 0, -1):
                with suppress(Exception):
                    ids.add(str(json.loads(raw)["headers"]["id"]))
    for raw in r.hvals("unacked"):
        with suppress(Exception):
            ids.add(str(json.loads(raw)[0]["headers"]["id"]))
    return ids


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


class LockUnavailableError(RuntimeError):
    """Raised by a strict lock when Redis cannot answer, as opposed to the lock being held."""


def _blocking_pool(url: str, max_connections: int) -> redis_lib.BlockingConnectionPool:
    """A pool that waits for a free connection instead of raising at once when all are busy."""
    return redis_lib.BlockingConnectionPool.from_url(
        url,
        max_connections=max_connections,
        timeout=Config.REDIS_POOL_TIMEOUT_SECONDS,
        socket_connect_timeout=Config.REDIS_SOCKET_CONNECT_TIMEOUT,
        socket_timeout=Config.REDIS_SOCKET_TIMEOUT,
        retry_on_timeout=True,
        **_build_ssl_kwargs(url),
    )


def _get_pool(url: str) -> redis_lib.BlockingConnectionPool | None:
    global _pools_pid
    current_pid = os.getpid()
    if _pools_pid != current_pid:
        _pools.clear()
        _pools_pid = current_pid
    pool = _pools.get(url)
    if pool is None:
        try:
            pool = _blocking_pool(url, Config.REDIS_POOL_MAX_CONNECTIONS)
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


def redis_time(r: Any) -> float:
    """Return the Redis server clock in epoch seconds; the local clock if Redis fails.

    Worker heartbeats and the status check both read the broker's clock, so a
    machine whose own clock drifts never makes a live worker look stale.
    """
    try:
        seconds, microseconds = r.time()
        return int(seconds) + int(microseconds) / 1_000_000
    except Exception:
        return time.time()


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


def _get_sse_pool(url: str) -> redis_lib.BlockingConnectionPool | None:
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
            pool = _blocking_pool(url, max(Config.SSE_MAX_GLOBAL, 100))
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


def delete_if_value(r: redis_lib.Redis[Any], key: str, value: str) -> bool:
    """Atomically delete ``key`` only while it still holds ``value`` (its owner token)."""
    return bool(r.eval(_DELETE_IF_VALUE_SCRIPT, 1, key, value))  # type: ignore[no-untyped-call]


def _acquire(lock_key: str, ttl: int, strict: bool) -> tuple[Any, str, bool]:
    """SET NX the lock; with ``strict`` a Redis failure raises instead of reading as held."""
    r = get_coordination_client()
    owner = uuid.uuid4().hex
    if r is None:
        if strict:
            raise LockUnavailableError(lock_key)
        return None, owner, False
    try:
        return r, owner, bool(r.set(lock_key, owner, nx=True, ex=ttl))
    except Exception as exc:
        logger.warning("Lock acquire failed for %s: %s", lock_key, exc)
        if strict:
            raise LockUnavailableError(lock_key) from exc
        return r, owner, False


@contextmanager
def cache_lock(
    lock_key: str, ttl: int = 120, *, strict: bool = False
) -> Generator[bool, None, None]:
    """Context manager: acquires a Redis lock (SET NX), releases on exit.
    Uses a UUID value so only the owner can release (prevents TTL cross-deletion).

    Callers must use ``as got`` and act on it: the lock is not held when it is
    False. With ``strict`` a Redis failure raises ``LockUnavailableError`` instead.
    Locks live on the broker instance, which never evicts, so an evicted key can
    never let two holders in.
    """
    r, owner, got = _acquire(lock_key, ttl, strict)
    try:
        yield bool(got)
    finally:
        if got and r:
            try:
                delete_if_value(r, lock_key, owner)
            except Exception as e:
                logger.warning("Failed to release Redis lock %s: %s", lock_key, e)


@contextmanager
def renewing_lock(
    lock_key: str, ttl: int = 60, *, strict: bool = False
) -> Generator[bool, None, None]:
    """Like ``cache_lock``, but renewed every ``ttl / 3`` seconds while the holder works.

    A holder that dies stops renewing, so the lock frees itself within ``ttl``.
    """
    r, owner, got = _acquire(lock_key, ttl, strict)
    stop = threading.Event()

    def renew() -> None:
        while not stop.wait(ttl / 3):
            try:
                if not r or not r.eval(_EXPIRE_IF_VALUE_SCRIPT, 1, lock_key, owner, ttl):
                    return
            except Exception as e:
                logger.warning("Failed to renew Redis lock %s: %s", lock_key, e)

    renewer = threading.Thread(target=renew, daemon=True) if got else None
    if renewer is not None:
        renewer.start()
    try:
        yield bool(got)
    finally:
        stop.set()
        if renewer is not None:
            renewer.join(timeout=1)
        if got and r:
            try:
                delete_if_value(r, lock_key, owner)
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


def _priority_list_keys(queue_name: str) -> list[str]:
    """Return the broker lists holding one queue's messages, one per priority step."""
    return [
        queue_name if step == 0 else f"{queue_name}{KOMBU_PRIORITY_SEP}{step}"
        for step in EVALUATION_PRIORITY_STEPS
    ]


def get_queue_depths(queue_names: Iterable[str]) -> dict[str, int]:
    """Return the number of messages pending on each Celery queue, in one round trip.

    The priority lists have fixed names, so one pipelined LLEN per list replaces a
    keyspace SCAN. Fails open (every queue reads 0) when Redis is unavailable, so
    submissions are never rejected because of a monitoring hiccup.
    """
    names = list(dict.fromkeys(queue_names))
    depths = dict.fromkeys(names, 0)
    r = get_coordination_client()
    if not r or not names:
        return depths
    try:
        pipe = r.pipeline(transaction=False)
        for name in names:
            for key in _priority_list_keys(name):
                pipe.llen(key)
        lengths = iter(pipe.execute())
        for name in names:
            depths[name] = sum(int(next(lengths) or 0) for _ in EVALUATION_PRIORITY_STEPS)
    except Exception:
        logger.exception("Failed to read queue depths for %s", ", ".join(names))
        return dict.fromkeys(names, 0)
    return depths


def get_queue_depth(queue_name: str) -> int:
    """Return the number of messages pending on one Celery queue (see ``get_queue_depths``)."""
    return get_queue_depths([queue_name])[queue_name]


def get_dirty_leaderboard_versions(r: redis_lib.Redis[Any]) -> dict[str, int]:
    """Return dirty challenge versions after atomically consuming the legacy set."""
    r.eval(  # type: ignore[no-untyped-call]
        _MIGRATE_DIRTY_SET_SCRIPT,
        2,
        DIRTY_CHALLENGES_SET,
        DIRTY_LEADERBOARD_VERSIONS,
    )
    versions: dict[str, int] = {}
    for raw_challenge_id, raw_version in r.hgetall(DIRTY_LEADERBOARD_VERSIONS).items():
        challenge_id = (
            raw_challenge_id.decode("utf-8")
            if isinstance(raw_challenge_id, bytes)
            else str(raw_challenge_id)
        )
        version = raw_version.decode("utf-8") if isinstance(raw_version, bytes) else raw_version
        versions[challenge_id] = int(version)
    return versions


def clear_dirty_leaderboard_version(
    r: redis_lib.Redis[Any], challenge_id: Any, rebuilt_version: int
) -> bool:
    """Clear a dirty marker only when no newer invalidation was recorded."""
    return bool(
        r.eval(  # type: ignore[no-untyped-call]
            _CLEAR_DIRTY_VERSION_SCRIPT,
            1,
            DIRTY_LEADERBOARD_VERSIONS,
            str(challenge_id),
            str(rebuilt_version),
        )
    )


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


def invalidate_leaderboard_cache(challenge_id: Any, delete_only: bool = False) -> None:
    """Mark the challenge leaderboard cache as dirty for periodic Celery Beat rebuilding."""
    if not challenge_id:
        return
    challenge_id = str(challenge_id)

    if delete_only:
        delete_cached(leaderboard_cache_key(challenge_id))
        delete_cached(f"leaderboard:pending:{challenge_id}")
        r = get_coordination_client()
        if r:
            with suppress(Exception):
                pipeline = r.pipeline(transaction=True)
                pipeline.srem(DIRTY_CHALLENGES_SET, challenge_id)
                pipeline.hdel(DIRTY_LEADERBOARD_VERSIONS, challenge_id)
                pipeline.execute()
        return

    r = get_coordination_client()
    if r:
        try:
            r.hincrby(DIRTY_LEADERBOARD_VERSIONS, challenge_id, 1)
            return
        except Exception as e:
            logger.warning("Failed to mark challenge %s as dirty in Redis: %s", challenge_id, e)

    # Fallback if Redis is down/unavailable: delete cache to avoid serving stale indefinitely
    delete_cached(leaderboard_cache_key(challenge_id))
