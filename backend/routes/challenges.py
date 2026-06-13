from flask import Blueprint, request, jsonify
from models import db, Challenge, User
from auth_utils import login_required, role_required

challenges_bp = Blueprint('challenges', __name__)

@challenges_bp.route('', methods=['GET'])
@login_required
def get_challenges():
    user_id = request.user["user_id"]
    user_role = request.user["role"]
    
    from cache_utils import get_cached, set_cached
    
    if user_role == 'competitor':
        user = User.query.get(user_id)
        if not user or not user.challenge_id:
            return jsonify([])
        challenge_id = user.challenge_id
        cache_key = f"challenge:{challenge_id}"
        cached_challenge = get_cached(cache_key)
        if cached_challenge is not None:
            return jsonify([cached_challenge])
            
        challenge = Challenge.query.get(challenge_id)
        if not challenge:
            return jsonify([])
        challenge_dict = challenge.to_dict()
        set_cached(cache_key, challenge_dict, timeout=600)
        return jsonify([challenge_dict])
        
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
        
    cache_key = "challenges:all"
    cached_all = get_cached(cache_key)
    if cached_all is not None:
        return jsonify(cached_all)
        
    challenges = Challenge.query.all()
    challenges_list = [c.to_dict() for c in challenges]
    set_cached(cache_key, challenges_list, timeout=600)
    return jsonify(challenges_list)


@challenges_bp.route('/<int:challenge_id>', methods=['GET'])
@login_required
def get_challenge(challenge_id):
    user_id = request.user["user_id"]
    user_role = request.user["role"]
    
    if user_role == 'competitor':
        user = User.query.get(user_id)
        if not user or user.challenge_id != challenge_id:
            return jsonify({"error": "Access denied. You are not registered for this competition."}), 403
            
    from cache_utils import get_cached, set_cached
    cache_key = f"challenge:{challenge_id}"
    cached_challenge = get_cached(cache_key)
    if cached_challenge is not None:
        return jsonify(cached_challenge)
        
    challenge = Challenge.query.get_or_404(challenge_id)
    challenge_dict = challenge.to_dict()
    set_cached(cache_key, challenge_dict, timeout=600)
    return jsonify(challenge_dict)


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
    double_blind = data.get("double_blind")
    if double_blind is None:
        double_blind = True
    else:
        double_blind = bool(double_blind)
    
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
        freeze_time=freeze_time,
        double_blind=double_blind
    )
    db.session.add(challenge)
    db.session.commit()
    
    from cache_utils import invalidate_challenge_cache
    invalidate_challenge_cache()
    
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
    if "double_blind" in data:
        challenge.double_blind = bool(data.get("double_blind"))
        
    db.session.commit()
    
    from cache_utils import invalidate_challenge_cache, invalidate_leaderboard_cache
    invalidate_challenge_cache(challenge_id)
    invalidate_leaderboard_cache(challenge_id)
    
    return jsonify(challenge.to_dict())


@challenges_bp.route('/<int:challenge_id>', methods=['DELETE'])
@role_required(['admin', 'jury'])
def delete_challenge(challenge_id):
    challenge = Challenge.query.get_or_404(challenge_id)
    
    users = User.query.filter_by(challenge_id=challenge_id).all()
    for u in users:
        u.challenge_id = None
        
    db.session.delete(challenge)
    db.session.commit()
    
    from cache_utils import invalidate_challenge_cache, invalidate_leaderboard_cache
    invalidate_challenge_cache(challenge_id)
    invalidate_leaderboard_cache(challenge_id)
    
    return jsonify({"message": f"Competition '{challenge.title}' and all its associated tasks and submissions have been deleted successfully."})


@challenges_bp.route('/<int:challenge_id>/finalize', methods=['POST'])
@role_required(['jury'])
def finalize_challenge(challenge_id):
    challenge = Challenge.query.get_or_404(challenge_id)
    
    # Check if manual points are entered for all competitors for all tasks
    competitors = User.query.filter_by(role='competitor', challenge_id=challenge_id).all()
    tasks = challenge.tasks
    
    for comp in competitors:
        manual_points_dict = {}
        if comp.manual_points:
            if isinstance(comp.manual_points, dict):
                manual_points_dict = comp.manual_points
            elif isinstance(comp.manual_points, str):
                try:
                    import json
                    manual_points_dict = json.loads(comp.manual_points)
                except Exception:
                    manual_points_dict = {}
        
        for task in tasks:
            pts = manual_points_dict.get(str(task.id))
            if pts is None:
                return jsonify({
                    "error": f"Cannot finalize. Competitor '{comp.username}' (ID: {comp.id}) is missing manual points for task '{task.title}' (ID: {task.id})."
                }), 400
                
    # Read reveal options
    data = request.get_json() or {}
    challenge.reveal_public_scores = bool(data.get("reveal_public_scores", True))
    challenge.reveal_private_scores = bool(data.get("reveal_private_scores", True))
    challenge.reveal_points = bool(data.get("reveal_points", True))
    
    challenge.scores_finalized = True
    db.session.commit()
    
    from cache_utils import invalidate_challenge_cache, invalidate_leaderboard_cache
    invalidate_challenge_cache(challenge_id)
    invalidate_leaderboard_cache(challenge_id)
    
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
    
    from cache_utils import invalidate_challenge_cache
    invalidate_challenge_cache(challenge_id)
    
    action = "archived" if challenge.is_archived else "restored"
    return jsonify({
        "message": f"Competition has been successfully {action}!",
        "challenge": challenge.to_dict()
    })
