"""JWT authentication, token verification, rate limiting, and authorization utilities."""

import os
import sys
import logging
import uuid
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


def _redis_client():
    try:
        from cache_utils import get_redis_client

        return get_redis_client()
    except Exception:
        return None


def _redis_exists(key):
    try:
        r = _redis_client()
        if r is not None:
            val = r.exists(key)
            return bool(val)
    except Exception:
        pass
    return False


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
        path="/",
    )
    return token


def clear_auth_cookie(response):
    token = _extract_token()
    if token:
        revoke_token(token)
    response.set_cookie(
        AUTH_COOKIE_NAME, "", max_age=0, httponly=True, samesite="Strict", secure=False, path="/"
    )


# JWT Settings
SECRET_KEY = os.environ.get("SECRET_KEY") or _require_env("SECRET_KEY")


def generate_token(user_id, role):
    """Create a signed JWT with user id, role, and unique jti for revocation."""
    payload = {
        "sub": str(user_id),
        "role": role,
        "jti": uuid.uuid4().hex,
        "exp": datetime.utcnow() + timedelta(days=1),  # Token valid for 24 hours
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def revoke_token(token):
    """Add the token's jti to the Redis revocation blacklist for its remaining lifetime."""
    try:
        if token.startswith("Bearer "):
            token = token[7:]
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"], options={"verify_exp": False})
        jti = payload.get("jti")
        exp = payload.get("exp")
        if jti and exp:
            r = _redis_client()
            if r:
                ttl = max(1, int(exp - datetime.utcnow().timestamp()))
                try:
                    r.setex(f"revoked:{jti}", ttl, "1")
                except Exception:
                    pass
    except Exception:
        pass


def _fetch_current_role(user_id):
    try:
        from models import db, User

        if db and db.session:
            user = db.session.get(User, user_id)
            if user:
                return user.role
    except Exception:
        pass
    return None


def verify_token(token):
    """Decode and verify a JWT. Checks revocation blacklist and DB role (live role sync)."""
    if not token:
        return None
    try:
        if token.startswith("Bearer "):
            token = token[7:]
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        user_id = int(payload["sub"])
        # Check blacklist
        jti = payload.get("jti")
        if jti and _redis_exists(f"revoked:{jti}"):
            return None
        # Fetch current role from DB (handles mid-session promotions/demotions)
        # Falls back to JWT role if DB is unavailable (e.g. test environments)
        role = _fetch_current_role(user_id) or payload.get("role")
        return {"user_id": user_id, "role": role}
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def login_required(f):
    """Decorator: requires a valid JWT (cookie/header). Injects request.user."""

    @wraps(f)
    def decorated(*args, **kwargs):
        token = _extract_token()
        user_data = verify_token(token)
        if not user_data:
            return (
                jsonify({"error": "Unauthorized access. Token is missing, expired, or invalid."}),
                401,
            )
        request.user = user_data
        if not verify_csrf_token():
            return (
                jsonify({"error": "CSRF token missing or invalid.", "code": "ERR_CSRF_FAILED"}),
                403,
            )
        return f(*args, **kwargs)

    return decorated


def role_required(allowed_roles):
    """Decorator: requires JWT + role membership in allowed_roles (list of strings)."""

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            token = _extract_token()
            user_data = verify_token(token)
            if not user_data or user_data["role"] not in allowed_roles:
                return jsonify({"error": f"Unauthorized. Requires role: {allowed_roles}"}), 403
            request.user = user_data
            if not verify_csrf_token():
                return (
                    jsonify({"error": "CSRF token missing or invalid.", "code": "ERR_CSRF_FAILED"}),
                    403,
                )
            return f(*args, **kwargs)

        return decorated

    return decorator


# --- Rate limiting ---


def rate_limit(max_requests=60, window_seconds=60, per_user=True):
    """Decorator: per-user (or per-IP) rate limiting via Lua atomic counters."""

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            r = _redis_client()
            if not r:
                return f(*args, **kwargs)
            # Build key: rate:user_id:endpoint or rate:ip:endpoint
            if per_user and hasattr(request, "user") and request.user:
                identity = str(request.user["user_id"])
            else:
                identity = request.remote_addr or "127.0.0.1"
            key = f"rate:{identity}:{request.endpoint}"
            try:
                lua_script = """
                local current = redis.call('incr', KEYS[1])
                if current == 1 then
                    redis.call('expire', KEYS[1], ARGV[1])
                end
                return current
                """
                current = r.eval(lua_script, 1, key, window_seconds)
                if current > max_requests:
                    return (
                        jsonify(
                            {
                                "error": "Too many requests. Please slow down.",
                                "code": "ERR_RATE_LIMITED",
                            }
                        ),
                        429,
                    )
            except Exception:
                pass  # Redis down — allow request through
            return f(*args, **kwargs)

        return decorated

    return decorator


CSRF_COOKIE_NAME = "csrf_token"


def generate_csrf_token():
    """Generate a CSRF token and set it as a non-httpOnly cookie."""
    token = uuid.uuid4().hex
    response = jsonify({"csrf_token": token})
    response.set_cookie(
        CSRF_COOKIE_NAME,
        token,
        max_age=3600,
        httponly=False,
        samesite="Strict",
        secure=False,
        path="/",
    )
    return response


def verify_csrf_token():
    """Verify the X-CSRF-Token header matches the csrf_token cookie."""
    if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
        return True
    # Worker endpoints use token auth, skip CSRF
    if request.headers.get("X-Worker-Token") or request.headers.get("Authorization", "").startswith(
        "Bearer "
    ):
        return True
    header_token = request.headers.get("X-CSRF-Token")
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    if not header_token or not cookie_token or header_token != cookie_token:
        return False
    return True


def csrf_required(f):
    """Decorator: requires valid CSRF token for non-GET requests."""

    @wraps(f)
    def decorated(*args, **kwargs):
        if not verify_csrf_token():
            return (
                jsonify({"error": "CSRF token missing or invalid.", "code": "ERR_CSRF_FAILED"}),
                403,
            )
        return f(*args, **kwargs)

    return decorated


def generate_worker_token(submission_id, task_id, expires_in_sec):
    """Create a short-lived JWT so workers can authenticate back to the server."""
    payload = {
        "sub": str(submission_id),
        "task_id": task_id,
        "role": "worker_submission",
        "exp": datetime.utcnow() + timedelta(seconds=expires_in_sec),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def generate_worker_bootstrap_token(worker_id="worker", expires_in_sec=3600):
    """Create a short-lived JWT for worker bootstrap (active-datasets, hf-key)."""
    payload = {
        "sub": worker_id,
        "role": "worker_bootstrap",
        "jti": uuid.uuid4().hex,
        "exp": datetime.utcnow() + timedelta(seconds=expires_in_sec),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def verify_worker_token(token, submission_id=None, task_id=None):
    """Verify a worker JWT. Optionally scoped to submission_id/task_id."""
    if not token:
        return False
    try:
        if token.startswith("Bearer "):
            token = token[7:]
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        role = payload.get("role")
        if role not in ("worker_submission", "worker_bootstrap"):
            return False
        if role == "worker_submission":
            if submission_id is not None and payload.get("sub") != str(submission_id):
                return False
            if task_id is not None and payload.get("task_id") != task_id:
                return False
        return True
    except Exception:
        return False
