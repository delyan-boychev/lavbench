import os
import json
import logging
import redis

logger = logging.getLogger(__name__)

def publish_leaderboard_update(task_id):
    if not task_id:
        return
    try:
        broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
        r = redis.Redis.from_url(broker_url)
        r.publish(f"task_{task_id}_leaderboard", json.dumps({"event": "update"}))
    except Exception:
        logger.exception("Redis publish leaderboard update error for task %s", task_id)

def publish_submissions_update(task_id, user_id):
    if not task_id or not user_id:
        return
    try:
        broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
        r = redis.Redis.from_url(broker_url)
        r.publish(f"task_{task_id}_user_{user_id}_submissions", json.dumps({"event": "update"}))
    except Exception:
        logger.exception("Redis publish submissions update error for task %s user %s", task_id, user_id)

def publish_submission_log(submission_id, log_line):
    if not submission_id:
        return
    try:
        broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
        r = redis.Redis.from_url(broker_url)
        log_key = f"submission:{submission_id}:logs"
        r.rpush(log_key, log_line)
        r.ltrim(log_key, -10000, -1)
        r.expire(log_key, 3600)  # Expire logs in 1 hour
        r.publish(f"submission_{submission_id}_logs", json.dumps({"log": log_line}))
    except Exception:
        logger.exception("Redis publish submission log error for submission %s", submission_id)

def clear_submission_logs(submission_id):
    if not submission_id:
        return
    try:
        broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
        r = redis.Redis.from_url(broker_url)
        r.delete(f"submission:{submission_id}:logs")
    except Exception:
        logger.exception("Redis clear submission logs error for submission %s", submission_id)
