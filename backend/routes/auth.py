import logging
import time

from auth_utils import clear_auth_cookie, generate_csrf_token, login_required, set_auth_cookie
from error_utils import err
from flask import Blueprint, jsonify, make_response, request
from models import User, db
from werkzeug.security import check_password_hash

logger = logging.getLogger(__name__)
auth_bp = Blueprint("auth", __name__)


def _login_rate_limit_exceeded(username, ip):
    """
    Two-tier sliding window rate limiting:
    - Per-username: max 5 failures per 60s
    - Per-IP: max 30 failures per 60s (accommodates school NAT)
    """
    try:
        from cache_utils import get_redis_client

        r = get_redis_client()
        if not r:
            return False

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
        return False


def _record_login_failure(username, ip):
    """Record a failed login attempt in sliding window."""
    try:
        from cache_utils import get_redis_client

        r = get_redis_client()
        if not r:
            return
        now = time.time()
        r.zadd(f"login_failures:user:{username}", {str(now): now})
        r.zadd(f"login_failures:ip:{ip}", {str(now): now})
        r.expire(f"login_failures:user:{username}", 120)
        r.expire(f"login_failures:ip:{ip}", 120)
    except Exception as e:
        logger.warning("Failed to record login failure for user %s: %s", username, e)


def _clear_login_failures(username, ip):
    """Clear failure records on successful login."""
    try:
        from cache_utils import get_redis_client

        r = get_redis_client()
        if not r:
            return
        r.delete(f"login_failures:user:{username}")
        r.delete(f"login_failures:ip:{ip}")
    except Exception as e:
        logger.warning("Failed to clear login failures for user %s: %s", username, e)


def get_client_ip():
    if request.headers.getlist("X-Forwarded-For"):
        return request.headers.getlist("X-Forwarded-For")[0].split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"


@auth_bp.route("/login", methods=["POST"])
def login():
    """
    Authenticate a user and receive a session cookie.
    Password must be sent as plaintext; the server hashes it.
    Sets httpOnly cookie `auth_token` on success.
    Rate limited: 5 failed attempts per username+IP per 60 seconds.
    ---
    tags:
      - Auth
    parameters:
      - in: body
        name: body
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [username, password]
              properties:
                username:
                  type: string
                  description: Username or email
                  example: "admin_1c15d4d7"
                password:
                  type: string
                  description: Plaintext password
                  example: "mysecurepassword123"
    responses:
      200:
        description: Login successful. httpOnly cookie set.
        headers:
          Set-Cookie:
            type: string
            description: auth_token=httpOnly; SameSite=Strict
        content:
          application/json:
            schema:
              type: object
              properties:
                message:
                  type: string
                  example: "Logged in successfully."
                user:
                  $ref: '#/components/schemas/User'
      400:
        description: Missing username or password
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/Error'
      401:
        description: Invalid credentials
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/Error'
      403:
        description: Competition archived (competitor login only)
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/Error'
      429:
        description: Rate limited (5 failures per 60s per username+IP)
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/Error'
    """
    data = request.json or {}
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return err("ERR_MISSING_CREDENTIALS", 400)

    ip = get_client_ip()

    if _login_rate_limit_exceeded(username, ip):
        return err("ERR_RATE_LIMIT_EXCEEDED", 429)

    user = User.query.filter(User.username == username).first()

    if not user or not check_password_hash(user.password_hash, password):
        # Check legacy format (SHA-256 wrapped). Migrate on successful match.
        import hashlib

        legacy_hash = hashlib.sha256(password.encode()).hexdigest()
        if not user or not check_password_hash(user.password_hash, legacy_hash):
            _record_login_failure(username, ip)
            return err("ERR_INVALID_CREDENTIALS", 401)
        db.session.commit()

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

    user_data = user.to_dict(current_user_id=user.id)
    resp = make_response(jsonify({"message": "Logged in successfully.", "user": user_data}))
    set_auth_cookie(resp, user.id, user.role)
    return resp


@auth_bp.route("/csrf-token", methods=["GET"])
def get_csrf_token():
    """
    Get a CSRF token for state-changing requests.
    Returns the token in the response body and sets it as a non-httpOnly cookie.
    The frontend should read the cookie and include it as X-CSRF-Token header.
    ---
    tags:
      - Auth
    responses:
      200:
        description: CSRF token generated
        content:
          application/json:
            schema:
              type: object
              properties:
                csrf_token:
                  type: string
    """

    return generate_csrf_token()


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """
    Log out the current user. Clears the httpOnly cookie and revokes the JWT token.
    ---
    tags:
      - Auth
    responses:
      200:
        description: Logged out successfully. Cookie cleared, token revoked.
        content:
          application/json:
            schema:
              type: object
              properties:
                message:
                  type: string
                  example: "Logged out successfully."
    """
    resp = make_response(jsonify({"message": "Logged out successfully."}))
    clear_auth_cookie(resp)
    return resp


@auth_bp.route("/me", methods=["GET"])
@login_required
def me():
    """
    Get the current authenticated user's profile.
    Requires valid httpOnly cookie or Authorization header.
    ---
    tags:
      - Auth
    security:
      - cookieAuth: []
    responses:
      200:
        description: Current user profile
        content:
          application/json:
            schema:
              type: object
              properties:
                user:
                  $ref: '#/components/schemas/User'
      401:
        description: Unauthorized — missing, expired, or revoked token
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/Error'
      404:
        description: User not found (deleted after token was issued)
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/Error'
    """
    user = db.session.get(User, request.user["user_id"])
    if not user:
        return err("ERR_USER_NOT_FOUND", 404)
    return jsonify({"user": user.to_dict(current_user_id=user.id)})
