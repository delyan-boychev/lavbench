"""Redis connection pool, distributed cache locking, and dead-letter logging."""

import os
import json
import uuid
from datetime import datetime
from contextlib import contextmanager
import logging
import redis as redis_lib

logger = logging.getLogger(__name__)

_pool = None
_pool_pid = None


def get_redis_client():
    """Returns a Redis client from a shared ConnectionPool (auto-reconnect, greenlet-safe)."""
    global _pool, _pool_pid
    current_pid = os.getpid()
    if _pool is None or _pool_pid != current_pid:
        broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
        ssl_kwargs = {}
        if broker_url.startswith("rediss://"):
            import ssl

            ssl_ca_certs = os.environ.get("REDIS_SSL_CA_CERTS")
            ssl_certfile = os.environ.get("REDIS_SSL_CERTFILE")
            ssl_keyfile = os.environ.get("REDIS_SSL_KEYFILE")
            ssl_cert_reqs_str = os.environ.get("REDIS_SSL_CERT_REQS", "required")

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

        _pool = redis_lib.ConnectionPool.from_url(broker_url, max_connections=100, **ssl_kwargs)
        _pool_pid = current_pid
    return redis_lib.Redis(connection_pool=_pool)


@contextmanager
def cache_lock(lock_key, ttl=120):
    """Context manager: acquires a Redis lock (SET NX), releases on exit.
    Uses a UUID value so only the owner can release (prevents TTL cross-deletion)."""
    r = get_redis_client()
    owner = uuid.uuid4().hex
    got = False
    if r:
        try:
            got = r.set(lock_key, owner, nx=True, ex=ttl)
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
                r.eval(lua_script, 1, lock_key, owner)
            except Exception:
                pass


def acquire_cache_lock(lock_key, ttl=30):
    """Legacy compat — use `with cache_lock(key, ttl)` instead."""
    r = get_redis_client()
    if not r:
        return False
    try:
        return r.set(lock_key, "1", nx=True, ex=ttl)
    except Exception:
        logger.exception("acquire_cache_lock failed for %s", lock_key)
        return False


def release_cache_lock(lock_key):
    """Legacy compat — automatically handled by cache_lock context manager."""
    r = get_redis_client()
    if not r:
        return
    try:
        r.delete(lock_key)
    except Exception:
        pass


def log_dead_letter(submission_id, task_id=None, challenge_id=None, error=None):
    """Logs a permanently failed Celery task to Redis for inspection."""
    r = get_redis_client()
    if not r:
        return
    try:
        entry = {
            "submission_id": submission_id,
            "task_id": task_id,
            "challenge_id": challenge_id,
            "failed_at": datetime.utcnow().isoformat(),
            "error": str(error)[:1000] if error else None,
        }
        r.lpush("dead_letter_queue", json.dumps(entry))
        r.ltrim("dead_letter_queue", 0, 999)
    except Exception:
        logger.exception("log_dead_letter failed")


def get_cached(key):
    """Get a JSON-deserialized value from Redis by key. Returns None on miss/error."""
    r = get_redis_client()
    if not r:
        return None
    try:
        data = r.get(key)
        if data:
            return json.loads(data)
    except Exception as e:
        logger.exception("Cache get error for %s", key)
    return None


def set_cached(key, value, timeout=300):
    """JSON-serialize and store a value in Redis with an expiry TTL."""
    r = get_redis_client()
    if not r:
        return False
    try:
        r.set(key, json.dumps(value), ex=timeout)
        return True
    except Exception as e:
        logger.exception("Cache set error for %s", key)
        return False


def delete_cached(key):
    """Delete a key from Redis. Returns True if deleted, False on error."""
    r = get_redis_client()
    if not r:
        return False
    try:
        r.delete(key)
        return True
    except Exception as e:
        logger.exception("Cache delete error for %s", key)
        return False


def invalidate_challenge_cache(challenge_id=None):
    """Clear cached challenge listings and (optionally) a specific challenge entry."""
    delete_cached("challenges:all")
    if challenge_id:
        challenge_id = str(challenge_id)
        delete_cached(f"challenge:{challenge_id}")
        delete_cached(f"challenge:{challenge_id}:competitor")


def invalidate_leaderboard_cache(challenge_id, delete_only=False):
    """Clear or warm background leaderboard cache for a given challenge."""
    if not challenge_id:
        return
    challenge_id = str(challenge_id)

    if delete_only:
        delete_cached(f"leaderboard:raw:{challenge_id}:frozen")
        delete_cached(f"leaderboard:raw:{challenge_id}:unfrozen")
        delete_cached(f"leaderboard:pending:{challenge_id}")
        return

    r = get_redis_client()
    if r:
        pending_key = f"leaderboard:pending:{challenge_id}"
        try:
            is_new = r.set(pending_key, "1", nx=True, ex=5)
            if not is_new:
                return
        except Exception:
            pass

    try:
        from tasks import recalculate_leaderboard

        recalculate_leaderboard.delay(challenge_id)
    except Exception:
        delete_cached(f"leaderboard:raw:{challenge_id}:frozen")
        delete_cached(f"leaderboard:raw:{challenge_id}:unfrozen")
