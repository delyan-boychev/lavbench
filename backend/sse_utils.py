import os
import json
import redis
from flask import current_app

def publish_leaderboard_update(task_id):
    if not task_id:
        return
    try:
        broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
        r = redis.Redis.from_url(broker_url)
        r.publish(f"task_{task_id}_leaderboard", json.dumps({"event": "update"}))
    except Exception as e:
        print(f"Redis publish leaderboard update error: {e}")

def publish_submissions_update(task_id, user_id):
    if not task_id or not user_id:
        return
    try:
        broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
        r = redis.Redis.from_url(broker_url)
        r.publish(f"task_{task_id}_user_{user_id}_submissions", json.dumps({"event": "update"}))
    except Exception as e:
        print(f"Redis publish submissions update error: {e}")
