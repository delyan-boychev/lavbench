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

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.json or {}
    identifier = data.get("email") or data.get("username")
    password = data.get("password")
    
    if not identifier or not password:
        return jsonify({"error": "Missing username/email or password."}), 400
        
    if check_rate_limit(identifier):
        return jsonify({"error": "Too many failed login attempts. Please try again in a minute."}), 429
        
    user = User.query.filter((User.email == identifier) | (User.username == identifier)).first()
    
    if not user or not check_password_hash(user.password_hash, password):
        record_failure(identifier)
        return jsonify({"error": "Invalid credentials."}), 401
        
    clear_failures(identifier)
        
    if user.role == 'competitor' and user.challenge_id:
        from models import Challenge
        challenge = Challenge.query.get(user.challenge_id)
        if challenge and challenge.is_archived:
            return jsonify({"error": "This competition has been archived. Registered students are not allowed to log in."}), 403
            
    token = generate_token(user.id, user.role)
    return jsonify({
        "message": "Logged in successfully.",
        "token": token,
        "user": user.to_dict(current_user_id=user.id)
    })

@auth_bp.route('/me', methods=['GET'])
@login_required
def me():
    user = User.query.get(request.user["user_id"])
    if not user:
        return jsonify({"error": "User not found."}), 404
    return jsonify({"user": user.to_dict(current_user_id=user.id)})
