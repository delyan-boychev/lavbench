from flask import Blueprint, request, jsonify
from models import db, Challenge, User
from auth_utils import login_required, role_required

challenges_bp = Blueprint('challenges', __name__)

@challenges_bp.route('', methods=['GET'])
@login_required
def get_challenges():
    user_id = request.user["user_id"]
    user_role = request.user["role"]
    
    if user_role == 'competitor':
        user = User.query.get(user_id)
        if not user or not user.challenge_id:
            return jsonify([])
        challenge = Challenge.query.get(user.challenge_id)
        return jsonify([challenge.to_dict()] if challenge else [])
        
    page = request.args.get('page', type=int)
    if page is not None:
        per_page = request.args.get('per_page', 10, type=int)
        pagination = Challenge.query.paginate(page=page, per_page=per_page, error_out=False)
        return jsonify({
            "items": [c.to_dict() for c in pagination.items],
            "total": pagination.total,
            "page": pagination.page,
            "pages": pagination.pages
        })
        
    challenges = Challenge.query.all()
    return jsonify([c.to_dict() for c in challenges])


@challenges_bp.route('/<int:challenge_id>', methods=['GET'])
@login_required
def get_challenge(challenge_id):
    user_id = request.user["user_id"]
    user_role = request.user["role"]
    
    if user_role == 'competitor':
        user = User.query.get(user_id)
        if not user or user.challenge_id != challenge_id:
            return jsonify({"error": "Access denied. You are not registered for this competition."}), 403
            
    challenge = Challenge.query.get_or_404(challenge_id)
    return jsonify(challenge.to_dict())


from datetime import datetime

def parse_datetime(val):
    if not val:
        return None
    try:
        if isinstance(val, str):
            if val.endswith('Z'):
                val = val[:-1] + '+00:00'
            # Remove milliseconds/microsecond if present and fromisoformat fails
            try:
                return datetime.fromisoformat(val)
            except ValueError:
                # Try parsing with format without timezone offset first if needed
                # but fromisoformat is usually sufficient. Let's do a basic strip:
                if 'T' in val:
                    val = val.split('.')[0] # strip milliseconds
                return datetime.strptime(val, "%Y-%m-%dT%H:%M:%S")
    except Exception:
        pass
    return None

@challenges_bp.route('', methods=['POST'])
@role_required(['admin', 'jury'])
def create_challenge():
    data = request.json or {}
    title = data.get("title")
    description = data.get("description")
    max_eval_requests = int(data.get("max_eval_requests", 10))
    ram_limit_mb = int(data.get("ram_limit_mb", 8192))
    time_limit_sec = int(data.get("time_limit_sec", 300))
    gpu_required = bool(data.get("gpu_required", True))
    
    start_time = parse_datetime(data.get("start_time"))
    end_time = parse_datetime(data.get("end_time"))
    freeze_time = parse_datetime(data.get("freeze_time"))
    
    if not title:
        return jsonify({"error": "Competition title is required."}), 400
        
    challenge = Challenge(
        title=title,
        description=description,
        max_eval_requests=max_eval_requests,
        ram_limit_mb=ram_limit_mb,
        time_limit_sec=time_limit_sec,
        gpu_required=gpu_required,
        start_time=start_time,
        end_time=end_time,
        freeze_time=freeze_time
    )
    db.session.add(challenge)
    db.session.commit()
    
    return jsonify(challenge.to_dict()), 201


@challenges_bp.route('/<int:challenge_id>', methods=['PUT'])
@role_required(['admin', 'jury'])
def update_challenge(challenge_id):
    challenge = Challenge.query.get_or_404(challenge_id)
    data = request.json or {}
    
    title = data.get("title")
    description = data.get("description")
    max_eval_requests = data.get("max_eval_requests")
    ram_limit_mb = data.get("ram_limit_mb")
    time_limit_sec = data.get("time_limit_sec")
    gpu_required = data.get("gpu_required")
    
    if title:
        challenge.title = title
    if description is not None:
        challenge.description = description
    if max_eval_requests is not None:
        challenge.max_eval_requests = int(max_eval_requests)
    if ram_limit_mb is not None:
        challenge.ram_limit_mb = int(ram_limit_mb)
    if time_limit_sec is not None:
        challenge.time_limit_sec = int(time_limit_sec)
    if gpu_required is not None:
        challenge.gpu_required = bool(gpu_required)
        
    if "start_time" in data:
        challenge.start_time = parse_datetime(data.get("start_time"))
    if "end_time" in data:
        challenge.end_time = parse_datetime(data.get("end_time"))
    if "freeze_time" in data:
        challenge.freeze_time = parse_datetime(data.get("freeze_time"))
        
    db.session.commit()
    return jsonify(challenge.to_dict())


@challenges_bp.route('/<int:challenge_id>', methods=['DELETE'])
@role_required(['admin', 'jury'])
def delete_challenge(challenge_id):
    challenge = Challenge.query.get_or_404(challenge_id)
    
    # Dissociate users from this competition before deleting to prevent FK violations
    users = User.query.filter_by(challenge_id=challenge_id).all()
    for u in users:
        u.challenge_id = None
        
    db.session.delete(challenge)
    db.session.commit()
    return jsonify({"message": f"Competition '{challenge.title}' and all its associated tasks and submissions have been deleted successfully."})


@challenges_bp.route('/<int:challenge_id>/finalize', methods=['POST'])
@role_required(['admin', 'jury'])
def finalize_challenge(challenge_id):
    challenge = Challenge.query.get_or_404(challenge_id)
    challenge.scores_finalized = True
    db.session.commit()
    return jsonify({
        "message": "Competition finalized! Competitor identities and private scores are now fully revealed to everyone.",
        "challenge": challenge.to_dict()
    })


@challenges_bp.route('/<int:challenge_id>/archive', methods=['POST'])
@role_required(['admin', 'jury'])
def archive_challenge(challenge_id):
    challenge = Challenge.query.get_or_404(challenge_id)
    challenge.is_archived = not challenge.is_archived
    db.session.commit()
    action = "archived" if challenge.is_archived else "restored"
    return jsonify({
        "message": f"Competition has been successfully {action}!",
        "challenge": challenge.to_dict()
    })
