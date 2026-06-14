import os
import jwt
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify

# JWT Settings
SECRET_KEY = os.environ.get("SECRET_KEY", "nai-super-secret-key-1337-secure-random-length-for-jwt")

def generate_token(user_id, role):
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": datetime.utcnow() + timedelta(days=1), # Token valid for 24 hours
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def verify_token(token):
    if not token:
        return None
    try:
        if token.startswith("Bearer "):
            token = token[7:]
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return {"user_id": int(payload["sub"]), "role": payload["role"]}
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("Authorization") or request.args.get("token")
        user_data = verify_token(token)
        if not user_data:
            return jsonify({"error": "Unauthorized access. Token is missing, expired, or invalid."}), 401
        request.user = user_data
        return f(*args, **kwargs)
    return decorated

def role_required(allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            token = request.headers.get("Authorization") or request.args.get("token")
            user_data = verify_token(token)
            if not user_data or user_data["role"] not in allowed_roles:
                return jsonify({"error": f"Unauthorized. Requires role: {allowed_roles}"}), 403
            request.user = user_data
            return f(*args, **kwargs)
        return decorated
    return decorator


def generate_worker_token(submission_id, task_id, expires_in_sec):
    payload = {
        "sub": str(submission_id),
        "task_id": task_id,
        "role": "worker_submission",
        "exp": datetime.utcnow() + timedelta(seconds=expires_in_sec),
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def verify_worker_token(token, submission_id=None, task_id=None):
    if not token:
        return False
    # Only allow global WORKER_SECRET_KEY for non-submission-specific endpoints (like preloading active datasets)
    if submission_id is None and task_id is None:
        global_key = os.environ.get("WORKER_SECRET_KEY")
        if global_key and token == global_key:
            return True
    try:
        if token.startswith("Bearer "):
            token = token[7:]
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        if payload.get("role") != "worker_submission":
            return False
        if submission_id is not None and payload.get("sub") != str(submission_id):
            return False
        if task_id is not None and payload.get("task_id") != task_id:
            return False
        return True
    except Exception:
        return False


