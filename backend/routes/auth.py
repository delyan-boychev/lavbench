from __future__ import annotations

import json
import logging
import time

from flask import Blueprint, make_response, request
from flask import Response as FlaskResponse
from spectree import Response
from werkzeug.security import check_password_hash, generate_password_hash

from auth_utils import clear_auth_cookie, generate_csrf_token, login_required, set_auth_cookie
from error_utils import err
from models import User, db
from schemas.auth import LoginSchema
from schemas.responses import (
    CsrfTokenResponse,
    CurrentUserResponse,
    ErrorResponse,
    LoginResponse,
    LogoutResponse,
    UserResponse,
)
from spec import api
from utils import client_ip

logger = logging.getLogger(__name__)
auth_bp = Blueprint("auth", __name__)

# Precomputed hash so a login for an unknown username runs the same PBKDF2
# work as a real one (~100-200ms). Without this, the short-circuit leaks
# whether a username exists via response timing (username enumeration).
_DUMMY_PASSWORD_HASH = generate_password_hash("lavbench-timing-equalizer")


def _verify_password(user: User | None, password: str) -> bool:
    if user is None:
        check_password_hash(_DUMMY_PASSWORD_HASH, password)
        return False
    return check_password_hash(user.password_hash, password)


def _login_rate_limit_exceeded(username: str, ip: str) -> bool:
    """
    Two-tier sliding window rate limiting:
    - Per-username: max 5 failures per 60s
    - Per-IP: max 30 failures per 60s (accommodates school NAT)

    Falls back to an in-process sliding window when Redis is unavailable so a
    monitoring/backend hiccup does not silently disable throttling entirely.
    """
    try:
        from cache_utils import get_redis_client

        r = get_redis_client()
        if not r:
            return _local_failure_exceeded(username, ip)

        now = time.time()
        window = 60

        user_key = f"login_failures:user:{username}"
        ip_key = f"login_failures:ip:{ip}"

        r.zremrangebyscore(user_key, 0, now - window)
        r.zremrangebyscore(ip_key, 0, now - window)

        user_failures = r.zcard(user_key)
        ip_failures = r.zcard(ip_key)

        return user_failures >= 5 or ip_failures >= 30
    except Exception:
        return _local_failure_exceeded(username, ip)


_LOCAL_LOGIN_WINDOW = 60.0
_LOCAL_LOGIN_USER_MAX = 5
_LOCAL_LOGIN_IP_MAX = 30
_LOCAL_LOGIN_FAILURES: dict[str, list[float]] = {}


def _local_failure_exceeded(username: str, ip: str) -> bool:
    """In-process fallback: prune + count records from this process."""
    now = time.time()
    for key in (f"user:{username}", f"ip:{ip}"):
        kept = [t for t in _LOCAL_LOGIN_FAILURES.get(key, []) if t > now - _LOCAL_LOGIN_WINDOW]
        if kept:
            _LOCAL_LOGIN_FAILURES[key] = kept
        else:
            _LOCAL_LOGIN_FAILURES.pop(key, None)
    return (
        len(_LOCAL_LOGIN_FAILURES.get(f"user:{username}", [])) >= _LOCAL_LOGIN_USER_MAX
        or len(_LOCAL_LOGIN_FAILURES.get(f"ip:{ip}", [])) >= _LOCAL_LOGIN_IP_MAX
    )


def _record_login_failure(username: str, ip: str) -> None:
    """Record a failed login attempt in sliding window (Redis + local fallback)."""
    now = time.time()
    for key in (f"user:{username}", f"ip:{ip}"):
        kept = [t for t in _LOCAL_LOGIN_FAILURES.get(key, []) if t > now - _LOCAL_LOGIN_WINDOW]
        kept.append(now)
        _LOCAL_LOGIN_FAILURES[key] = kept
    try:
        from cache_utils import get_redis_client

        r = get_redis_client()
        if not r:
            return
        r.zadd(f"login_failures:user:{username}", {str(now): now})
        r.zadd(f"login_failures:ip:{ip}", {str(now): now})
        r.expire(f"login_failures:user:{username}", 120)
        r.expire(f"login_failures:ip:{ip}", 120)
    except Exception as e:
        logger.warning("Failed to record login failure for user %s: %s", username, e)


def _clear_login_failures(username: str, ip: str) -> None:
    """Clear failure records on successful login (Redis + local fallback)."""
    _LOCAL_LOGIN_FAILURES.pop(f"user:{username}", None)
    _LOCAL_LOGIN_FAILURES.pop(f"ip:{ip}", None)
    try:
        from cache_utils import get_redis_client

        r = get_redis_client()
        if not r:
            return
        r.delete(f"login_failures:user:{username}")
        r.delete(f"login_failures:ip:{ip}")
    except Exception as e:
        logger.warning("Failed to clear login failures for user %s: %s", username, e)


def get_client_ip() -> str:
    return client_ip.get_client_ip()


@auth_bp.route("/login", methods=["POST"])
@api.validate(
    json=LoginSchema,
    resp=Response(HTTP_200=LoginResponse, HTTP_401=ErrorResponse),
    tags=["Auth"],
)
def login(json: LoginSchema) -> FlaskResponse | tuple[FlaskResponse, int]:
    """
    Authenticate a user and receive a session cookie.
    Password must be sent as plaintext; the server hashes it.
    Sets httpOnly cookie `auth_token` on success.
    Rate limited: 5 failed attempts per username+IP per 60 seconds.
    """
    username = json.username
    password = json.password
    ip = get_client_ip()

    if _login_rate_limit_exceeded(username, ip):
        return err("ERR_RATE_LIMIT_EXCEEDED", 429)

    user = User.query.filter(User.username == username).first()

    if not _verify_password(user, password):
        _record_login_failure(username, ip)
        return err("ERR_INVALID_CREDENTIALS", 401)

    _clear_login_failures(username, ip)

    if user.role == "competitor" and user.challenge_id:
        from models import Challenge

        challenge = db.session.get(Challenge, user.challenge_id)
        if challenge and challenge.is_archived:
            return err(
                "ERR_COMPETITION_ARCHIVED",
                403,
                message="This competition has been archived. "
                "Registered competitors are not allowed to log in.",
            )

    user_data = UserResponse.model_validate(user.to_dict(current_user_id=user.id))
    resp = make_response(
        LoginResponse(message="Logged in successfully.", user=user_data).model_dump_json()
    )
    resp.headers["Content-Type"] = "application/json"
    set_auth_cookie(resp, user.id, user.role)
    return resp


@auth_bp.route("/csrf-token", methods=["GET"])
@api.validate(
    resp=Response(HTTP_200=CsrfTokenResponse),
    tags=["Auth"],
)
def get_csrf_token() -> FlaskResponse | tuple[FlaskResponse, int]:
    """Get a CSRF token for state-changing requests."""
    return generate_csrf_token()


@auth_bp.route("/logout", methods=["POST"])
@api.validate(
    resp=Response(HTTP_200=LogoutResponse),
    tags=["Auth"],
)
def logout() -> FlaskResponse:
    """Log out the current user. Clears the httpOnly cookie and revokes the JWT token."""
    resp = make_response(json.dumps({"message": "Logged out successfully."}))
    resp.headers["Content-Type"] = "application/json"
    clear_auth_cookie(resp)
    return resp


@auth_bp.route("/me", methods=["GET"])
@login_required
@api.validate(
    resp=Response(HTTP_200=CurrentUserResponse, HTTP_404=ErrorResponse),
    tags=["Auth"],
    security=[{"cookieAuth": []}],
)
def me() -> CurrentUserResponse | tuple[FlaskResponse, int]:
    """Get the current authenticated user's profile."""
    user = db.session.get(User, request.user["user_id"])
    if not user:
        return err("ERR_USER_NOT_FOUND", 404)
    user_data = UserResponse.model_validate(user.to_dict(current_user_id=user.id))
    return CurrentUserResponse(user=user_data)
