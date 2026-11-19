"""Route handlers for the auth blueprint."""

from __future__ import annotations

import json
import logging
import time
import uuid

from flask import Blueprint, make_response, request
from flask import Response as FlaskResponse
from spectree import Response
from werkzeug.security import check_password_hash, generate_password_hash

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
from utils import client_ip
from utils.auth_utils import (
    clear_auth_cookie,
    generate_csrf_token,
    login_required,
    set_auth_cookie,
)
from utils.error_utils import err, service_busy, with_retry_after
from utils.spec import api
from utils.threadpool import run_blocking

logger = logging.getLogger(__name__)
auth_bp = Blueprint("auth", __name__)

# Precomputed hash so a login for an unknown username runs the same PBKDF2
# Work as a real one (~100-200ms). Without this, the short-circuit leaks
# Whether a username exists via response timing (username enumeration)
_DUMMY_PASSWORD_HASH = generate_password_hash("lavbench-timing-equalizer")


# Only failed logins count (OWASP, NIST SP 800-63B): a whole school behind one address logs
# In at once, so successes are never limited per address
LOGIN_USER_MAX_FAILURES = 5
LOGIN_USER_FAILURE_WINDOW_SECONDS = 60
LOGIN_IP_MAX_FAILURES = 100
LOGIN_IP_FAILURE_WINDOW_SECONDS = 600


def _verify_password(user: User | None, password: str) -> bool:
    # PBKDF2 releases the GIL, so a native thread hashes while the gevent hub serves others
    stored = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    matches = run_blocking(check_password_hash, stored, password)
    return user is not None and matches


def _user_key(username: str) -> str:
    return f"login_failures:user:{username}"


def _ip_key(ip: str) -> str:
    return f"login_failures:ip:{ip}"


def _login_locked_for(username: str, ip: str) -> int | None:
    """Seconds to wait when the username or the address has too many recent failures.

    Raises when Redis cannot answer, so the caller refuses instead of skipping the limit.
    """
    from utils.cache_utils import get_coordination_client

    r = get_coordination_client()
    if r is None:
        raise ConnectionError("Redis is unavailable")
    now = time.time()
    pipe = r.pipeline(transaction=False)
    pipe.zremrangebyscore(_user_key(username), 0, now - LOGIN_USER_FAILURE_WINDOW_SECONDS)
    pipe.zremrangebyscore(_ip_key(ip), 0, now - LOGIN_IP_FAILURE_WINDOW_SECONDS)
    pipe.zcard(_user_key(username))
    pipe.zcard(_ip_key(ip))
    _, _, user_failures, ip_failures = pipe.execute()
    if ip_failures >= LOGIN_IP_MAX_FAILURES:
        return LOGIN_IP_FAILURE_WINDOW_SECONDS
    if user_failures >= LOGIN_USER_MAX_FAILURES:
        return LOGIN_USER_FAILURE_WINDOW_SECONDS
    return None


def _record_login_failure(username: str, ip: str) -> None:
    """Count a failed login against the username and the address."""
    from utils.cache_utils import get_coordination_client

    r = get_coordination_client()
    if r is None:
        return
    now = time.time()
    member = f"{now}:{uuid.uuid4().hex[:8]}"
    try:
        pipe = r.pipeline(transaction=False)
        pipe.zadd(_user_key(username), {member: now})
        pipe.expire(_user_key(username), LOGIN_USER_FAILURE_WINDOW_SECONDS * 2)
        pipe.zadd(_ip_key(ip), {member: now})
        pipe.expire(_ip_key(ip), LOGIN_IP_FAILURE_WINDOW_SECONDS * 2)
        pipe.execute()
    except Exception as e:
        logger.warning("Failed to record login failure for user %s: %s", username, e)


def _clear_user_failures(username: str) -> None:
    """A successful login clears its username's failures; the address keeps its count."""
    from utils.cache_utils import get_coordination_client

    r = get_coordination_client()
    if r is None:
        return
    try:
        r.delete(_user_key(username))
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
    Only failures count: 5 per username in 60 seconds or 100 per address in 10 minutes
    lock that username or address (429 with Retry-After).
    """
    username = json.username
    password = json.password
    ip = get_client_ip()

    try:
        wait = _login_locked_for(username, ip)
    except Exception as e:
        logger.warning("Login limit check failed: %s", e)
        return service_busy()
    if wait is not None:
        return with_retry_after(err("ERR_RATE_LIMIT_EXCEEDED", 429), wait)

    user = User.query.filter(User.username == username).first()

    if not _verify_password(user, password):
        _record_login_failure(username, ip)
        return err("ERR_INVALID_CREDENTIALS", 401)

    _clear_user_failures(username)

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
    set_auth_cookie(resp, user.id, user.role, user.password_hash)
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
