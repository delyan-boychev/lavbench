"""Server-Sent Events (SSE) publish/subscribe helpers for real-time updates."""

from __future__ import annotations

import json
import logging
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from cache_utils import get_redis_client
from config import Config

SSE_MAX_PER_USER = Config.SSE_MAX_PER_USER
SSE_MAX_GLOBAL = Config.SSE_MAX_GLOBAL
SSE_IDLE_TIMEOUT = Config.SSE_IDLE_TIMEOUT

logger = logging.getLogger(__name__)


def _redis() -> Any:
    return get_redis_client()


@contextmanager
def sse_connection_limit(
    user_id: Any = None, remote_addr: Any = None
) -> Generator[bool, None, None]:
    """Context manager that tracks and caps concurrent SSE connections via Redis.
    Enforces per-user and global connection limits with auto-cleanup on exit."""
    r = get_redis_client()
    user_key = f"sse:user:{user_id}" if user_id else None
    global_key = "sse:global"
    allowed = True

    if r:
        try:
            pipe = r.pipeline()
            if user_key:
                pipe.incr(user_key)
                pipe.expire(user_key, 120)
            pipe.incr(global_key)
            pipe.expire(global_key, 120)
            results = pipe.execute()
            if user_key:
                user_count = results[0]
                global_count = results[1]
            else:
                user_count = 0
                global_count = results[0] if not user_key else results[1]

            if user_count > SSE_MAX_PER_USER:
                allowed = False
                logger.warning("SSE limit: user %s has %s active connections", user_id, user_count)
            elif global_count > SSE_MAX_GLOBAL:
                allowed = False
                logger.warning("SSE limit: global connections at %s", global_count)
        except Exception as e:
            logger.warning("SSE connection limit check failed (allowing): %s", e)

    try:
        yield allowed
    finally:
        # Safely decrement counters — only if the key still exists and is > 0.
        # This prevents DECR from creating a key with value -1 if the TTL
        # expired between the INCR (entry) and DECR (cleanup).
        if r and allowed:
            try:
                for key in ([user_key] if user_key else []) + [global_key]:
                    val = r.get(key)
                    if val is not None and int(val) > 0:
                        r.decr(key)
                    elif val is not None:
                        r.delete(key)
            except Exception as e:
                logger.warning("SSE connection counter cleanup failed: %s", e)


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
