from flask import Blueprint, request, jsonify
from werkzeug.security import check_password_hash
from models import db, User
from auth_utils import generate_token, login_required

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
            
    token = generate_token(user.id, user.role)
    return jsonify({
        "message": "Logged in successfully.",
        "token": token,
        "user": user.to_dict(current_user_id=user.id)
    })


@auth_bp.route('/me', methods=['GET'])
@login_required
def me():
    user = db.session.get(User, request.user["user_id"])
    if not user:
        return jsonify({
            "error": "User not found.",
            "code": "ERR_USER_NOT_FOUND"
        }), 404
    return jsonify({"user": user.to_dict(current_user_id=user.id)})
