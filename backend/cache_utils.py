import os
import json
import redis

def get_redis_client():
    try:
        broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
        return redis.Redis.from_url(broker_url)
    except Exception:
        return None

def get_cached(key):
    r = get_redis_client()
    if not r:
        return None
    try:
        data = r.get(key)
        if data:
            return json.loads(data)
    except Exception as e:
        print(f"Cache get error for {key}: {e}")
    return None

def set_cached(key, value, timeout=300):
    r = get_redis_client()
    if not r:
        return False
    try:
        r.set(key, json.dumps(value), ex=timeout)
        return True
    except Exception as e:
        print(f"Cache set error for {key}: {e}")
        return False

def delete_cached(key):
    r = get_redis_client()
    if not r:
        return False
    try:
        r.delete(key)
        return True
    except Exception as e:
        print(f"Cache delete error for {key}: {e}")
        return False

def invalidate_challenge_cache(challenge_id=None):
    delete_cached("challenges:all")
    if challenge_id:
        delete_cached(f"challenge:{challenge_id}")
        delete_cached(f"challenge:{challenge_id}:competitor")

def invalidate_leaderboard_cache(challenge_id):
    if challenge_id:
        delete_cached(f"leaderboard:raw:{challenge_id}:frozen")
        delete_cached(f"leaderboard:raw:{challenge_id}:unfrozen")
