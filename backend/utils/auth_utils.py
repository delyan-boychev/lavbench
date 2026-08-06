"""Authentication, token verification, rate limiting, and authorization utilities."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import sys
import time
import uuid
from collections.abc import Callable
from datetime import timedelta
from functools import wraps
from typing import Any

import jwt
from flask import Response, jsonify, request

from config import Config
from utils.dates import utcnow
from utils.error_utils import err

logger = logging.getLogger(__name__)


def _require_env(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        msg = f"FATAL: Required environment variable '{key}' is not set."
        sys.stderr.write(msg + "\n")
        sys.exit(1)
    return val


def _redis_client() -> Any:
    try:
        from utils.cache_utils import get_redis_client

        return get_redis_client()
    except Exception:
        return None


def _redis_exists(key: str) -> bool:
    try:
        r = _redis_client()
        if r is not None:
            val = r.exists(key)
            return bool(val)
    except Exception as e:
        logger.warning("Redis exists check failed for key %s: %s", key, e)
    return False


# In-memory fallback for jti revocation when Redis is down. Redis is the system
# Of record; during an outage we still want logout/admin revocations to be
# Honored on the process that performed them (they always are, because we write
# Here synchronously). Bounded + lazily pruned.
_LOCAL_REVOKED_TOKENS: dict[str, float] = {}
_LOCAL_REVOKED_MAX = 10_000


def _record_revoked_locally(jti: str, expires_at: float) -> None:
    _LOCAL_REVOKED_TOKENS[jti] = expires_at
    if len(_LOCAL_REVOKED_TOKENS) > _LOCAL_REVOKED_MAX:
        now = time.time()
        expired = [k for k, v in _LOCAL_REVOKED_TOKENS.items() if v <= now]
        for k in expired:
            _LOCAL_REVOKED_TOKENS.pop(k, None)


def _is_token_revoked(jti: str) -> bool:
    """Fail-closed revocation check with an in-process fallback.

    Redis is the source of truth. If Redis is unavailable we still honor
    revocations recorded in this process (logout + admin revoke always record
    locally first). Tokens revoked only from another process during an outage
    are not detected here — an accepted trade-off that keeps the site up while
    preserving the strongest guarantee (this host's own revocations).
    """
    now = time.time()
    expiry = _LOCAL_REVOKED_TOKENS.get(jti)
    if expiry is not None:
        if expiry > now:
            return True
        _LOCAL_REVOKED_TOKENS.pop(jti, None)
    return _redis_exists(f"revoked:{jti}")


AUTH_COOKIE_NAME = "auth_token"
AUTH_COOKIE_MAX_AGE = 86400  # 24 hours


def _extract_token() -> str | None:
    # 1. httpOnly cookie (primary method — browser auto-attaches, immune to XSS)
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if token:
        return token
    # 2. Authorization header (fallback for API clients / workers)
    token = request.headers.get("Authorization")
    if token:
        return token
    return token


def set_auth_cookie(response: Response, user_id: str, role: str, password_hash: str) -> str:
    token = generate_token(user_id, role, password_hash=password_hash)
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        max_age=AUTH_COOKIE_MAX_AGE,
        httponly=True,
        samesite="Strict",
        secure=Config.SECURE_COOKIES,
        path="/",
    )
    return token


def clear_auth_cookie(response: Response) -> None:
    token = _extract_token()
    if token:
        revoke_token(token)
    response.set_cookie(
        AUTH_COOKIE_NAME,
        "",
        max_age=0,
        httponly=True,
        samesite="Strict",
        secure=Config.SECURE_COOKIES,
        path="/",
    )


# JWT Settings
SECRET_KEY = Config.SECRET_KEY


class AuthenticationUnavailableError(RuntimeError):
    """Raised when current-user authentication cannot reach its source of truth."""


def _authentication_fingerprint(password_hash: str) -> str:
    """Bind a session to the user's current password without exposing its hash."""
    return hmac.new(
        SECRET_KEY.encode("utf-8"), password_hash.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def generate_token(user_id: str, role: str, password_hash: str | None = None) -> str:
    """Create a signed JWT bound to the user's current password hash."""
    if password_hash is None:
        user = _fetch_current_user(str(user_id))
        if user is not None:
            password_hash = user.password_hash
    payload = {
        "sub": str(user_id),
        "role": role,
        "jti": uuid.uuid4().hex,
        "exp": utcnow() + timedelta(days=1),  # Token valid for 24 hours
        "iat": utcnow(),
    }
    if password_hash is not None:
        payload["auth_fp"] = _authentication_fingerprint(password_hash)
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def revoke_token(token: str) -> None:
    """Add the token's jti to the Redis revocation blacklist for its remaining lifetime."""
    try:
        if token.startswith("Bearer "):
            token = token[7:]
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"], options={"verify_exp": False})
        jti = payload.get("jti")
        exp = payload.get("exp")
        if jti and exp:
            expires_at = float(exp)
            # Always record locally first so revocation holds even if Redis is
            # Unavailable for the write
            _record_revoked_locally(jti, expires_at)
            r = _redis_client()
            if r:
                ttl = max(1, int(exp - utcnow().timestamp()))
                try:
                    r.set(f"revoked:{jti}", "1", ex=ttl)
                except Exception:
                    logger.warning(
                        "Failed to write revocation for jti=%s to Redis (local fallback active)",
                        jti,
                        exc_info=True,
                    )
    except Exception as e:
        logger.warning("Revocation token parsing failed: %s", e)


def _fetch_current_user(user_id: str) -> Any | None:
    try:
        from models import User, db

        return db.session.get(User, user_id)
    except Exception as exc:
        logger.error("Failed to fetch current user for user_id=%s", user_id, exc_info=True)
        raise AuthenticationUnavailableError from exc


def verify_token(token: str | None) -> dict[str, Any] | None:
    """Decode a JWT and verify it against the current database user."""
    if not token:
        return None
    try:
        if token.startswith("Bearer "):
            token = token[7:]
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        user_id = str(payload["sub"])
        # Check blacklist
        jti = payload.get("jti")
        if jti and _is_token_revoked(jti):
            return None
        user = _fetch_current_user(user_id)
        if user is None or not user.password_hash:
            return None
        token_fingerprint = payload.get("auth_fp")
        current_fingerprint = _authentication_fingerprint(user.password_hash)
        if not isinstance(token_fingerprint, str) or not hmac.compare_digest(
            token_fingerprint, current_fingerprint
        ):
            return None
        return {"user_id": user_id, "role": user.role}
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def login_required(f: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator: requires a valid JWT (cookie/header). Injects request.user."""

    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        token = _extract_token()
        try:
            user_data = verify_token(token)
        except AuthenticationUnavailableError:
            return err("ERR_AUTH_UNAVAILABLE", 503)
        if not user_data:
            return err("ERR_TOKEN_INVALID", 401)
        request.user = user_data  # type: ignore[attr-defined]
        if not verify_csrf_token():
            return err("ERR_CSRF_FAILED", 403)
        return f(*args, **kwargs)

    return decorated


def role_required(allowed_roles: list[str]) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: requires JWT + role membership in allowed_roles (list of strings)."""

    def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(f)
        def decorated(*args: Any, **kwargs: Any) -> Any:
            token = _extract_token()
            try:
                user_data = verify_token(token)
            except AuthenticationUnavailableError:
                return err("ERR_AUTH_UNAVAILABLE", 503)
            if not user_data:
                return err("ERR_TOKEN_INVALID", 401)
            if user_data["role"] not in allowed_roles:
                return err(
                    "ERR_ROLE_REQUIRED",
                    403,
                    message=f"Unauthorized. Requires role: {allowed_roles}",
                )
            request.user = user_data  # type: ignore[attr-defined]
            if not verify_csrf_token():
                return err("ERR_CSRF_FAILED", 403)
            return f(*args, **kwargs)

        return decorated

    return decorator


# ── Rate limiting ──
def rate_limit(
    max_requests: int = 60,
    window_seconds: int = 60,
    per_user: bool = True,
    identity: Callable[[], str] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: per-user (or per-IP) rate limiting via Lua atomic counters.

    When identity is provided, it is invoked at request time and takes
    precedence over per_user / per-IP key construction.
    """

    def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(f)
        def decorated(*args: Any, **kwargs: Any) -> Any:
            r = _redis_client()
            if not r:
                return f(*args, **kwargs)
            # Build key: rate:user_id:endpoint or rate:ip:endpoint
            if identity is not None:
                key_identity = identity()
            elif per_user and hasattr(request, "user") and request.user:
                key_identity = str(request.user["user_id"])
            else:
                key_identity = request.remote_addr or "127.0.0.1"
            key = f"rate:{key_identity}:{request.endpoint}"
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
                    return err("ERR_RATE_LIMITED", 429)
            except Exception as e:
                logger.warning("Rate limit Redis error (allowing request): %s", e)
                # Redis down — allow request through
            return f(*args, **kwargs)

        return decorated

    return decorator


CSRF_COOKIE_NAME = "csrf_token"


def generate_csrf_token() -> Response:
    """Generate a CSRF token and set it as a non-httpOnly cookie."""
    token = uuid.uuid4().hex
    response = jsonify({"csrf_token": token})
    response.set_cookie(
        CSRF_COOKIE_NAME,
        token,
        max_age=3600,
        httponly=False,
        samesite="Strict",
        secure=Config.SECURE_COOKIES,
        path="/",
    )
    return response


def verify_csrf_token() -> bool:
    """Verify the X-CSRF-Token header matches the csrf_token cookie."""
    if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
        return True
    # Worker endpoints use token auth (Ed25519 signed), skip CSRF
    # Bearer token auth is not vulnerable to CSRF (browsers don't auto-attach Authorization)
    if request.headers.get("X-Worker-Token") or request.headers.get("Authorization", "").startswith(
        "Bearer "
    ):
        return True
    header_token = request.headers.get("X-CSRF-Token")
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    return not (not header_token or not cookie_token or header_token != cookie_token)


def csrf_required(f: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator: requires valid CSRF token for non-GET requests."""

    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        if not verify_csrf_token():
            return err("ERR_CSRF_FAILED", 403)
        return f(*args, **kwargs)

    return decorated


def jury_access_required(f: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator: restricts jury members to only
    access endpoints of challenges they are assigned to.

    Admins are always allowed access. Other roles are not checked here.
    """

    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        if not hasattr(request, "user") or not request.user:
            token = _extract_token()
            try:
                user_data = verify_token(token)
            except AuthenticationUnavailableError:
                return err("ERR_AUTH_UNAVAILABLE", 503)
            if not user_data:
                return err("ERR_TOKEN_INVALID", 401)
            request.user = user_data  # type: ignore[attr-defined]

        user_role = request.user["role"]  # type: ignore[attr-defined]
        user_id = request.user["user_id"]  # type: ignore[attr-defined]

        if user_role == "jury":
            challenge_id = kwargs.get("challenge_id")

            from models import Stage, Submission, Task, User, db

            if not challenge_id:
                if "task_id" in kwargs:
                    task = db.session.get(Task, kwargs["task_id"])
                    if task:
                        challenge_id = task.challenge_id
                elif "stage_id" in kwargs:
                    stage = db.session.get(Stage, kwargs["stage_id"])
                    if stage:
                        challenge_id = stage.challenge_id
                elif "submission_id" in kwargs:
                    sub = db.session.get(Submission, kwargs["submission_id"])
                    if sub:
                        challenge_id = sub.challenge_id
                elif "user_id" in kwargs:
                    usr = db.session.get(User, kwargs["user_id"])
                    if usr and usr.challenge_id:
                        challenge_id = usr.challenge_id

            if not challenge_id:
                challenge_id = request.args.get("challenge_id") or (
                    request.json.get("challenge_id") if request.is_json else None
                )

            if not challenge_id:
                return err("ERR_ACCESS_DENIED", 403)

            if not jury_has_challenge_access(user_id, challenge_id):
                return err("ERR_ACCESS_DENIED", 403)

        return f(*args, **kwargs)

    return decorated


def jury_has_challenge_access(user_id: Any, challenge_id: Any) -> bool:
    """Return whether a jury member is assigned to a challenge."""
    if user_id is None or challenge_id is None:
        return False

    from models import JuryChallenge

    assignment = JuryChallenge.query.filter_by(jury_id=user_id, challenge_id=challenge_id).first()
    return assignment is not None


def jury_challenge_ids(user_id: Any) -> set[Any]:
    """Return all challenge IDs assigned to a jury member."""
    from models import JuryChallenge

    assignments = JuryChallenge.query.filter_by(jury_id=user_id).all()
    return {assignment.challenge_id for assignment in assignments}


def check_competitor_access(user: Any, challenge_id: Any) -> bool:
    """Check if a competitor user is assigned to the given challenge."""
    if not user or user.challenge_id is None or challenge_id is None:
        return False
    return str(user.challenge_id) == str(challenge_id)
