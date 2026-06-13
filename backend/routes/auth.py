from flask import Blueprint, request, jsonify
from werkzeug.security import check_password_hash
from models import db, User
from auth_utils import generate_token, login_required

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.json or {}
    identifier = data.get("email") or data.get("username")
    password = data.get("password")
    
    if not identifier or not password:
        return jsonify({"error": "Missing username/email or password."}), 400
        
    user = User.query.filter((User.email == identifier) | (User.username == identifier)).first()
    
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "Invalid credentials."}), 401
        
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
