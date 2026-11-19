"""Server-Sent Events (SSE) publish/subscribe helpers for real-time updates.

Connection limiting uses Redis Sorted Sets — new connections are always
accepted, but if a limit is exceeded the **oldest** connection is dropped.
This ensures the UI never gets blocked from connecting.
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from config import Config
from models.base import uuid7
from services.submission_status import TERMINAL_STATUSES
from utils.cache_utils import (
    get_coordination_client,
    get_redis_client,
    submission_logs_key,
    submission_status_key,
)

logger = logging.getLogger(__name__)

SSE_MAX_PER_USER = Config.SSE_MAX_PER_USER
SSE_MAX_GLOBAL = Config.SSE_MAX_GLOBAL

_CONNECTIONS_KEY = "sse:connections"
_STALE_TTL = 120

CHANNEL_BACKUPS = "backup_status"
CHANNEL_QUEUE = "queue_updates"


def leaderboard_channel(challenge_id: Any) -> str:
    return f"leaderboard_{challenge_id}"


def submission_logs_channel(submission_id: Any) -> str:
    return f"submission_{submission_id}_logs"


def _redis() -> Any:
    return get_coordination_client()


def _member_for(user_id: Any = None) -> tuple[str, str | None]:
    member = str(uuid7())
    user_key = f"sse:user:{user_id}" if user_id else None
    return member, user_key


def _cleanup_stale(r: Any, *keys: str) -> None:
    cutoff = time.time() - _STALE_TTL
    for key in keys:
        with contextlib.suppress(Exception):
            r.zremrangebyscore(key, 0, cutoff)


def _trim_oldest(r: Any, key: str, limit: int) -> None:
    count = r.zcard(key)
    if count > limit:
        r.zpopmin(key, count - limit)


@contextmanager
def sse_connection_limit(
    user_id: Any = None,
    remote_addr: Any = None,
    max_global: int | None = None,
    max_per_user: int | None = None,
) -> Generator[tuple[bool, str], None, None]:
    """Context manager that caps concurrent SSE connections via Redis Sorted Sets.

    New connections are **always** allowed. If the per-user or global limit
    is exceeded, the **oldest** connection in that set is dropped instead.
    Stale connections (no heartbeat for 120s) are pruned on every check.

    Yields ``(allowed, member)`` — ``allowed`` is always True. The caller
    should check ``zscore(member)`` inside polling loops to detect eviction.
    """
    r = _redis()
    if not r:
        yield True, ""
        return

    member, user_key = _member_for(user_id)
    now = time.time()

    effective_max_global = max_global if max_global is not None else SSE_MAX_GLOBAL
    effective_max_per_user = max_per_user if max_per_user is not None else SSE_MAX_PER_USER

    try:
        r.zadd(_CONNECTIONS_KEY, {member: now})
        _cleanup_stale(r, _CONNECTIONS_KEY)
        _trim_oldest(r, _CONNECTIONS_KEY, effective_max_global)

        if user_key:
            r.zadd(user_key, {member: now})
            _cleanup_stale(r, user_key)
            _trim_oldest(r, user_key, effective_max_per_user)

        yield True, member
    except Exception:
        logger.warning("SSE connection limit check failed (allowing):", exc_info=True)
        yield True, ""
    finally:
        try:
            r.zrem(_CONNECTIONS_KEY, member)
            if user_key:
                r.zrem(user_key, member)
        except Exception:
            logger.warning("SSE connection cleanup failed:", exc_info=True)


def sse_heartbeat(member: str, user_id: Any = None) -> bool:
    """Refresh a live SSE member's timestamp in the connection zsets.

    Returns False when the member has been evicted/trimmed and the
    stream should terminate, True otherwise (including Redis failures).
    """
    if not member:
        return True
    try:
        r = _redis()
        if not r:
            return True
        now = time.time()
        if r.zscore(_CONNECTIONS_KEY, member) is None:
            return False
        r.zadd(_CONNECTIONS_KEY, {member: now})
        if user_id is not None:
            r.zadd(f"sse:user:{user_id}", {member: now})
        return True
    except Exception:
        return True


def publish_leaderboard_update(challenge_id: Any) -> None:
    """Signal leaderboard SSE clients; only the leaderboard rebuild beat task calls this."""
    if not challenge_id:
        return
    try:
        r = _redis()
        if r:
            r.publish(
                leaderboard_channel(challenge_id),
                json.dumps({"event": "update"}),
            )
    except Exception:
        logger.exception("Redis publish leaderboard update error for challenge %s", challenge_id)


_TRUNCATION_MARKER = " [line truncated]"


def cap_log_line(line: str) -> str:
    """Cut a log line to SSE_LOG_MAX_LINE_BYTES of UTF-8, ending with a truncation marker."""
    limit = Config.SSE_LOG_MAX_LINE_BYTES
    encoded = line.encode("utf-8")
    if len(encoded) <= limit:
        return line
    marker = _TRUNCATION_MARKER.encode("utf-8")
    kept = encoded[: max(0, limit - len(marker))].decode("utf-8", errors="ignore")
    return kept + _TRUNCATION_MARKER


def publish_submission_log_batch(submission_id: Any, log_lines: list[str]) -> None:
    """Append a batch of log lines and publish them in a single Redis round trip.

    Storage ops are pipelined on the redis-cache instance and the SSE publish
    carries the whole batch as ``{"logs": [...]}`` (~1 op per 50 lines
    instead of 4 ops per line). Subscribers split the batch into per-line
    events, so the frontend contract is unchanged. Each line is capped at
    SSE_LOG_MAX_LINE_BYTES.
    """
    if not submission_id or not log_lines:
        return
    log_lines = [cap_log_line(line) for line in log_lines]
    try:
        cache_r = get_redis_client()
        if cache_r:
            log_key = submission_logs_key(submission_id)
            pipe = cache_r.pipeline(transaction=False)
            for line in log_lines:
                pipe.rpush(log_key, line)
            pipe.ltrim(log_key, -Config.SSE_LOG_MAX_LINES, -1)
            pipe.expire(log_key, Config.SSE_LOG_TTL)
            pipe.execute()
        r = get_coordination_client()
        if r:
            r.publish(submission_logs_channel(submission_id), json.dumps({"logs": log_lines}))
    except Exception:
        logger.exception(
            "Redis publish submission log batch error for submission %s", submission_id
        )


def clear_submission_logs(submission_id: Any) -> None:
    """Delete the Redis log list for a submission (stored on the cache instance)."""
    if not submission_id:
        return
    try:
        r = get_redis_client()
        if r:
            r.delete(submission_logs_key(submission_id))
    except Exception:
        logger.exception("Redis clear submission logs error for submission %s", submission_id)


def publish_submission_status(submission_id: Any, status: str) -> None:
    """Publish the final status of a submission to its SSE channel.

    A terminal status is also stored on the broker instance, so a log stream that
    missed the publish (or subscribed just after it) can still end without a DB
    query. The broker never evicts; the cache instance (volatile-lru) could drop it.
    """
    if not submission_id or not status:
        return
    r = _redis()
    if not r:
        return
    if status in TERMINAL_STATUSES:
        try:
            r.set(submission_status_key(submission_id), status, ex=Config.SSE_LOG_TTL)
        except Exception:
            logger.warning("Redis store of final status failed for submission %s", submission_id)
    try:
        r.publish(submission_logs_channel(submission_id), json.dumps({"status": status}))
    except Exception:
        logger.exception("Redis publish submission status error for submission %s", submission_id)


def get_submission_final_status(submission_id: Any) -> str | None:
    """Return the terminal status stored on the broker instance, or None when unknown."""
    try:
        r = _redis()
        if not r:
            return None
        value = r.get(submission_status_key(submission_id))
    except Exception:
        logger.warning("Redis read of submission status failed for %s", submission_id)
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return value if value in TERMINAL_STATUSES else None


def publish_queue_update() -> None:
    """Notify queue listeners that the submission queue may have changed."""
    try:
        r = _redis()
        if r:
            r.publish(CHANNEL_QUEUE, json.dumps({"event": "update"}))
    except Exception:
        logger.exception("Redis publish queue update error")


def environment_channel(challenge_id: Any) -> str:
    return f"environment_{challenge_id}"


def publish_environment_update(challenge_id: Any) -> None:
    """Signal open pages that an environment of the competition changed."""
    try:
        r = _redis()
        if r:
            r.publish(environment_channel(challenge_id), json.dumps({"event": "update"}))
    except Exception:
        logger.exception("Redis publish environment update error for %s", challenge_id)
