from flask import Blueprint, request, jsonify, make_response
from werkzeug.security import check_password_hash
from models import db, User
from auth_utils import generate_token, login_required, set_auth_cookie, clear_auth_cookie

auth_bp = Blueprint('auth', __name__)

def check_rate_limit(identifier):
    try:
        from cache_utils import get_redis_client
        r = get_redis_client()
        if not r:
            return False
        key = f"login_failures:{identifier}"
        failures = r.get(key)
        if failures and int(failures) >= 5:
            return True
        return False
    except Exception:
        return False

def record_failure(identifier):
    try:
        from cache_utils import get_redis_client
        r = get_redis_client()
        if not r:
            return
        key = f"login_failures:{identifier}"
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, 60)
        pipe.execute()
    except Exception:
        pass

def clear_failures(identifier):
    try:
        from cache_utils import get_redis_client
        r = get_redis_client()
        if not r:
            return
        key = f"login_failures:{identifier}"
        r.delete(key)
    except Exception:
        pass

def get_client_ip():
    if request.headers.getlist("X-Forwarded-For"):
        return request.headers.getlist("X-Forwarded-For")[0].split(',')[0].strip()
    return request.remote_addr or "127.0.0.1"

@auth_bp.route('/login', methods=['POST'])
def login():
    """
    Authenticate a user and receive a session cookie.
    Password must be SHA-256 hashed client-side before sending.
    Sets httpOnly cookie `auth_token` on success.
    Rate limited: 5 failed attempts per username+IP per 60 seconds.
    ---
    tags:
      - Auth
    parameters:
      - in: body
        name: body
        required: true
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
              description: SHA-256 hash of the plaintext password
              example: "a1b2c3..."
    responses:
      200:
        description: Login successful. httpOnly cookie set.
        headers:
          Set-Cookie:
            type: string
            description: auth_token=httpOnly; SameSite=Strict
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
        schema:
          $ref: '#/components/schemas/Error'
      401:
        description: Invalid credentials
        schema:
          $ref: '#/components/schemas/Error'
      403:
        description: Competition archived (competitor login only)
        schema:
          $ref: '#/components/schemas/Error'
      429:
        description: Rate limited (5 failures per 60s per username+IP)
        schema:
          $ref: '#/components/schemas/Error'
    """
    data = request.json or {}
    username = data.get("username")
    password = data.get("password")
    
    if not username or not password:
        return jsonify({
            "error": "Missing username or password.",
            "code": "ERR_MISSING_CREDENTIALS"
        }), 400
        
    ip = get_client_ip()
    rate_limit_key = f"{username}:{ip}"
        
    if check_rate_limit(rate_limit_key):
        return jsonify({
            "error": "Too many failed login attempts. Please try again in a minute.",
            "code": "ERR_RATE_LIMIT_EXCEEDED"
        }), 429
        
    user = User.query.filter(User.username == username).first()
    
    if not user or not check_password_hash(user.password_hash, password):
        record_failure(rate_limit_key)
        return jsonify({
            "error": "Invalid credentials.",
            "code": "ERR_INVALID_CREDENTIALS"
        }), 401
        
    clear_failures(rate_limit_key)
        
    if user.role == 'competitor' and user.challenge_id:
        from models import Challenge
        challenge = db.session.get(Challenge, user.challenge_id)
        if challenge and challenge.is_archived:
            return jsonify({
                "error": "This competition has been archived. Registered students are not allowed to log in.",
                "code": "ERR_COMPETITION_ARCHIVED"
            }), 403
            
    user_data = user.to_dict(current_user_id=user.id)
    resp = make_response(jsonify({
        "message": "Logged in successfully.",
        "user": user_data
    }))
    set_auth_cookie(resp, user.id, user.role)
    return resp


@auth_bp.route('/logout', methods=['POST'])
def logout():
    """
    Log out the current user. Clears the httpOnly cookie and revokes the JWT token.
    ---
    tags:
      - Auth
    responses:
      200:
        description: Logged out successfully. Cookie cleared, token revoked.
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


@auth_bp.route('/me', methods=['GET'])
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
        schema:
          type: object
          properties:
            user:
              $ref: '#/components/schemas/User'
      401:
        description: Unauthorized — missing, expired, or revoked token
        schema:
          $ref: '#/components/schemas/Error'
      404:
        description: User not found (deleted after token was issued)
        schema:
          $ref: '#/components/schemas/Error'
    """
    user = db.session.get(User, request.user["user_id"])
    if not user:
        return jsonify({
            "error": "User not found.",
            "code": "ERR_USER_NOT_FOUND"
        }), 404
    return jsonify({"user": user.to_dict(current_user_id=user.id)})
