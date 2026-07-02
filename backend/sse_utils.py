"""Server-Sent Events (SSE) publish/subscribe helpers for real-time updates."""

import json
import logging
from contextlib import contextmanager

from cache_utils import get_redis_client
from config import Config

SSE_MAX_PER_USER = Config.SSE_MAX_PER_USER
SSE_MAX_GLOBAL = Config.SSE_MAX_GLOBAL
SSE_IDLE_TIMEOUT = Config.SSE_IDLE_TIMEOUT

logger = logging.getLogger(__name__)


def _redis():
    return get_redis_client()


@contextmanager
def sse_connection_limit(user_id=None, remote_addr=None):
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
        if r and allowed:
            try:
                pipe = r.pipeline()
                if user_key:
                    pipe.decr(user_key)
                pipe.decr(global_key)
                pipe.execute()
            except Exception as e:
                logger.warning("SSE connection counter cleanup failed: %s", e)


def publish_leaderboard_update(task_id, challenge_id=None):
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


def publish_submissions_update(task_id, user_id):
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


def publish_submission_log(submission_id, log_line):
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


def clear_submission_logs(submission_id):
    """Delete the Redis log list for a submission."""
    if not submission_id:
        return
    try:
        r = _redis()
        if r:
            r.delete(f"submission:{submission_id}:logs")
    except Exception:
        logger.exception("Redis clear submission logs error for submission %s", submission_id)


def publish_submission_status(submission_id, status):
    """Publish the final status of a submission to its SSE channel."""
    if not submission_id or not status:
        return
    try:
        r = _redis()
        if r:
            r.publish(f"submission_{submission_id}_logs", json.dumps({"status": status}))
    except Exception:
        logger.exception("Redis publish submission status error for submission %s", submission_id)
