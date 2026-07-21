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

from cache_utils import get_redis_client
from config import Config
from models.base import uuid7

logger = logging.getLogger(__name__)

SSE_MAX_PER_USER = Config.SSE_MAX_PER_USER
SSE_MAX_GLOBAL = Config.SSE_MAX_GLOBAL
SSE_IDLE_TIMEOUT = Config.SSE_IDLE_TIMEOUT

_CONNECTIONS_KEY = "sse:connections"
_STALE_TTL = 120


def _redis() -> Any:
    return get_redis_client()


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
) -> Generator[bool, None, None]:
    """Context manager that caps concurrent SSE connections via Redis Sorted Sets.

    New connections are **always** allowed. If the per-user or global limit
    is exceeded, the **oldest** connection in that set is dropped instead.
    Stale connections (no heartbeat for 120s) are pruned on every check.

    Yields ``True`` always — the caller does not need to handle rejection.
    """
    r = get_redis_client()
    if not r:
        yield True
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

        yield True
    except Exception:
        logger.warning("SSE connection limit check failed (allowing):", exc_info=True)
        yield True
    finally:
        try:
            r.zrem(_CONNECTIONS_KEY, member)
            if user_key:
                r.zrem(user_key, member)
        except Exception:
            logger.warning("SSE connection cleanup failed:", exc_info=True)


def publish_leaderboard_update(task_id: Any, challenge_id: Any = None) -> None:
    """Publish a leaderboard-changed event to Redis channels for SSE consumers."""
    if not task_id:
        return
    try:
        r = _redis()
        if r:
            r.publish(f"task_{task_id}_leaderboard", json.dumps({"event": "update"}))
            if challenge_id:
                r.publish(
                    f"challenge_{challenge_id}_leaderboard",
                    json.dumps({"event": "update"}),
                )
    except Exception:
        logger.exception("Redis publish leaderboard update error for task %s", task_id)


def publish_submissions_update(task_id: Any, user_id: Any) -> None:
    """Publish a submission-list-changed event for a specific task+user."""
    if not task_id or not user_id:
        return
    try:
        r = _redis()
        if r:
            r.publish(
                f"task_{task_id}_user_{user_id}_submissions",
                json.dumps({"event": "update"}),
            )
    except Exception:
        logger.exception(
            "Redis publish submissions update error for task %s user %s",
            task_id,
            user_id,
        )


def publish_submission_log(submission_id: Any, log_line: str) -> None:
    """Append a log line to the submission's Redis list and publish to its SSE channel."""
    if not submission_id:
        return
    try:
        r = _redis()
        if r:
            log_key = f"submission:{submission_id}:logs"
            r.rpush(log_key, log_line)
            r.ltrim(log_key, -Config.SSE_LOG_MAX_LINES, -1)
            r.expire(log_key, Config.SSE_LOG_TTL)
            r.publish(f"submission_{submission_id}_logs", json.dumps({"log": log_line}))
    except Exception:
        logger.exception("Redis publish submission log error for submission %s", submission_id)


def clear_submission_logs(submission_id: Any) -> None:
    """Delete the Redis log list for a submission."""
    if not submission_id:
        return
    try:
        r = _redis()
        if r:
            r.delete(f"submission:{submission_id}:logs")
    except Exception:
        logger.exception("Redis clear submission logs error for submission %s", submission_id)


def publish_submission_status(submission_id: Any, status: str) -> None:
    """Publish the final status of a submission to its SSE channel."""
    if not submission_id or not status:
        return
    try:
        r = _redis()
        if r:
            r.publish(f"submission_{submission_id}_logs", json.dumps({"status": status}))
    except Exception:
        logger.exception("Redis publish submission status error for submission %s", submission_id)


def publish_queue_update() -> None:
    """Notify queue listeners that the submission queue may have changed."""
    try:
        r = _redis()
        if r:
            r.publish("queue_updates", json.dumps({"event": "update"}))
    except Exception:
        logger.exception("Redis publish queue update error")
