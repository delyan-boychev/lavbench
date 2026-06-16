import os
import sys
import logging
import jwt
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify

logger = logging.getLogger(__name__)

def _require_env(key):
    val = os.environ.get(key)
    if not val:
        print(f"FATAL: Required environment variable '{key}' is not set.", file=sys.stderr)
        sys.exit(1)
    return val

AUTH_COOKIE_NAME = "auth_token"
AUTH_COOKIE_MAX_AGE = 86400  # 24 hours

def _extract_token():
    # 1. httpOnly cookie (primary method — browser auto-attaches, immune to XSS)
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if token:
        return token
    # 2. Authorization header (fallback for API clients / workers)
    token = request.headers.get("Authorization")
    if token:
        return token
    # 3. URL query param (legacy, for EventSource SSE — cookie covers this now)
    token = request.args.get("token")
    if token:
        logger.warning("Token received via URL query parameter")
    return token

def set_auth_cookie(response, user_id, role):
    token = generate_token(user_id, role)
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        max_age=AUTH_COOKIE_MAX_AGE,
        httponly=True,
        samesite="Strict",
        secure=False,  # Set True when behind HTTPS
        path="/"
    )
    return token

def clear_auth_cookie(response):
    response.set_cookie(
        AUTH_COOKIE_NAME,
        "",
        max_age=0,
        httponly=True,
        samesite="Strict",
        secure=False,
        path="/"
    )

# JWT Settings
SECRET_KEY = os.environ.get("SECRET_KEY") or _require_env("SECRET_KEY")

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
        token = _extract_token()
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
            token = _extract_token()
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
    # Worker bootstrapping (active-datasets preloading) uses raw WORKER_SECRET_KEY
    if submission_id is None and task_id is None:
        worker_key = os.environ.get("WORKER_SECRET_KEY")
        if worker_key and token == worker_key:
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


