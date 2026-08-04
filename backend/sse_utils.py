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

from cache_utils import get_coordination_client, get_redis_client, submission_logs_key
from config import Config
from models.base import uuid7

logger = logging.getLogger(__name__)

SSE_MAX_PER_USER = Config.SSE_MAX_PER_USER
SSE_MAX_GLOBAL = Config.SSE_MAX_GLOBAL
SSE_IDLE_TIMEOUT = Config.SSE_IDLE_TIMEOUT

_CONNECTIONS_KEY = "sse:connections"
_STALE_TTL = 120

CHANNEL_TASK_REBUILD = "task_rebuild"
CHANNEL_BACKUPS = "backup_status"
CHANNEL_WORKER_STATS = "worker_stats_update"
CHANNEL_QUEUE = "queue_updates"
CHANNEL_WORKER_STATUS = "worker_status_live"


def leaderboard_channel(challenge_id: Any) -> str:
    return f"leaderboard_{challenge_id}"


def submissions_channel(task_id: Any, challenge_id: Any) -> str:
    return f"task_{task_id}_challenge_{challenge_id}_submissions"


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
    """Publish a leaderboard-changed event to the challenge-level Redis channel for SSE."""
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


def publish_submissions_update(task_id: Any, challenge_id: Any) -> None:
    """Publish a submission-list-changed event to the challenge-level Redis channel."""
    if not task_id or not challenge_id:
        return
    try:
        r = _redis()
        if r:
            r.publish(
                submissions_channel(task_id, challenge_id),
                json.dumps({"event": "update"}),
            )
    except Exception:
        logger.exception(
            "Redis publish submissions update error for task %s challenge %s",
            task_id,
            challenge_id,
        )


def publish_submission_log(submission_id: Any, log_line: str) -> None:
    """Append a log line to the submission's Redis list and publish to its SSE channel.

    Log storage lives on the redis-cache instance (H-P2) so the broker's
    small noeviction quota is never consumed by user-triggerable log volume;
    the SSE publish itself goes over the coordination (broker) channel.
    """
    if not submission_id:
        return
    try:
        cache_r = get_redis_client()
        if cache_r:
            log_key = submission_logs_key(submission_id)
            cache_r.rpush(log_key, log_line)
            cache_r.ltrim(log_key, -Config.SSE_LOG_MAX_LINES, -1)
            cache_r.expire(log_key, Config.SSE_LOG_TTL)
        r = get_coordination_client()
        if r:
            r.publish(submission_logs_channel(submission_id), json.dumps({"log": log_line}))
    except Exception:
        logger.exception("Redis publish submission log error for submission %s", submission_id)


def publish_submission_log_batch(submission_id: Any, log_lines: list[str]) -> None:
    """Append a batch of log lines and publish them in a single Redis round trip.

    Storage ops are pipelined on the redis-cache instance and the SSE publish
    carries the whole batch as ``{"logs": [...]}`` (M-P3: ~1 op per 50 lines
    instead of 4 ops per line). Subscribers split the batch into per-line
    events, so the frontend contract is unchanged.
    """
    if not submission_id or not log_lines:
        return
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
    """Publish the final status of a submission to its SSE channel."""
    if not submission_id or not status:
        return
    try:
        r = _redis()
        if r:
            r.publish(submission_logs_channel(submission_id), json.dumps({"status": status}))
    except Exception:
        logger.exception("Redis publish submission status error for submission %s", submission_id)


def publish_queue_update() -> None:
    """Notify queue listeners that the submission queue may have changed."""
    try:
        r = _redis()
        if r:
            r.publish(CHANNEL_QUEUE, json.dumps({"event": "update"}))
    except Exception:
        logger.exception("Redis publish queue update error")
