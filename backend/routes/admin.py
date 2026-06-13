import os
import csv
import io
import re
import secrets
import string
import random
import hashlib
import urllib.parse
import subprocess
import json
import zipfile
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file, current_app, Response
from werkzeug.security import generate_password_hash
from models import db, User, Challenge, Submission, Task, generate_pseudonym, decrypt_field, encrypt_field
from auth_utils import role_required

admin_bp = Blueprint('admin', __name__)

# --- HELPERS FOR USER CREATION ---
def generate_unique_username(name, surname):
    norm_name = re.sub(r'[^a-zA-Z0-9]', '', (name or '').lower())
    norm_surname = re.sub(r'[^a-zA-Z0-9]', '', (surname or '').lower())
    
    base = f"comp_{norm_name[:3]}_{norm_surname[:3]}"
    if len(base) < 7:
        base = "comp_user"
        
    while True:
        num = random.randint(1000, 9999)
        username = f"{base}_{num}"
        if not User.query.filter_by(username=username).first():
            return username

def generate_random_password(length=8):
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


# --- ENDPOINTS ---

@admin_bp.route('/register-competitor', methods=['POST'])
@role_required(['admin', 'jury'])
def register_competitor():
    data = request.json or {}
    name = data.get("name")
    surname = data.get("surname")
    grade = data.get("grade")
    school = data.get("school")
    city = data.get("city")
    challenge_id = data.get("challenge_id")
    
    if not challenge_id:
        return jsonify({"error": "challenge_id is required for competitor registration."}), 400
        
    challenge = Challenge.query.get(challenge_id)
    if not challenge:
        return jsonify({"error": "Invalid challenge_id."}), 400
    
    if not name or not surname:
        return jsonify({"error": "Name and Surname are required."}), 400
        
    username = generate_unique_username(name, surname)
    password = generate_random_password(8)
    
    client_hash = hashlib.sha256(password.encode()).hexdigest()
    user = User(
        username=username,
        password_hash=generate_password_hash(client_hash, method='pbkdf2:sha256'),
        role='competitor',
        alias_id=generate_pseudonym(),
        challenge_id=challenge_id
    )
    user.set_demographics(name, surname, grade, school, city)
    db.session.add(user)
    db.session.commit()
    
    return jsonify({
        "message": "Competitor registered successfully.",
        "generated_username": username,
        "generated_password": password,
        "user": user.to_dict(view_role=request.user["role"])
    }), 201


@admin_bp.route('/users', methods=['GET'])
@role_required(['admin', 'jury'])
def get_users():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    role_filter = request.args.get('role')
    challenge_id_filter = request.args.get('challenge_id', type=int)
    search_term = request.args.get('search')
    
    query = User.query
    if role_filter:
        query = query.filter_by(role=role_filter)
    if challenge_id_filter is not None:
        query = query.filter_by(challenge_id=challenge_id_filter)
    if search_term:
        term = f"%{search_term.lower()}%"
        query = query.filter((User.username.ilike(term)) | (User.email.ilike(term)))
        
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        "items": [u.to_dict(view_role=request.user["role"]) for u in pagination.items],
        "total": pagination.total,
        "page": pagination.page,
        "pages": pagination.pages
    })


@admin_bp.route('/users/<int:user_id>', methods=['DELETE'])
@role_required(['admin'])
def delete_user(user_id):
    if request.user["user_id"] == user_id:
        return jsonify({"error": "You cannot delete your own admin account."}), 400
        
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found."}), 404
        
    Submission.query.filter_by(user_id=user_id).delete()
    db.session.delete(user)
    db.session.commit()
    
    return jsonify({"message": f"User {user.username} has been deleted successfully."})


@admin_bp.route('/register-user', methods=['POST'])
@role_required(['admin', 'jury'])
def register_user():
    data = request.json or {}
    username = data.get("username")
    email = data.get("email")
    password = data.get("password")
    name = data.get("name")
    surname = data.get("surname")
    role = data.get("role")
    challenge_id = data.get("challenge_id")
    
    if not role or role not in ['competitor', 'jury', 'admin']:
        return jsonify({"error": "Valid role is required."}), 400
        
    # STRICT CONSTRAINT: Only server-side CLI can register an Administrator (admin)
    if role == "admin":
        return jsonify({"error": "Administrator accounts can only be generated directly on the server command line (CLI)."}), 403
        
    if not name or not surname:
        return jsonify({"error": "Name and Surname are required."}), 400
        
    if role == 'competitor':
        if not challenge_id:
            return jsonify({"error": "challenge_id is required for competitor registration."}), 400
        challenge = Challenge.query.get(challenge_id)
        if not challenge:
            return jsonify({"error": "Invalid challenge_id."}), 400
            
    is_plain = False
    if not password:
        password = generate_random_password(8)
        is_plain = True
        
    if role == 'competitor' and not username:
        username = generate_unique_username(name, surname)
        
    if not username:
        return jsonify({"error": "Username is required."}), 400
        
    if User.query.filter_by(username=username).first():
        return jsonify({"error": "User with this username already exists."}), 400
        
    grade = data.get("grade")
    school = data.get("school")
    city = data.get("city")
    
    client_hash = hashlib.sha256(password.encode()).hexdigest() if is_plain else password
    user = User(
        username=username,
        email=email,
        password_hash=generate_password_hash(client_hash, method='pbkdf2:sha256'),
        role=role,
        alias_id=generate_pseudonym(),
        challenge_id=challenge_id if role == 'competitor' else None
    )
    user.set_demographics(name, surname, grade, school, city)
    db.session.add(user)
    db.session.commit()
    
    return jsonify({
        "message": f"{role.capitalize()} registered successfully.",
        "generated_username": username,
        "generated_password": password,
        "user": user.to_dict(view_role=request.user["role"])
    }), 201


@admin_bp.route('/import-competitors-csv', methods=['POST'])
@role_required(['admin', 'jury'])
def import_competitors_csv():
    challenge_id = request.form.get("challenge_id") or request.args.get("challenge_id")
    if not challenge_id:
        return jsonify({"error": "challenge_id is required for importing competitors."}), 400
        
    challenge = Challenge.query.get(challenge_id)
    if not challenge:
        return jsonify({"error": "Invalid challenge_id."}), 400
        
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded."}), 400
    file = request.files['file']
    if not file.filename.endswith('.csv'):
        return jsonify({"error": "Only CSV (.csv) files are supported."}), 400
        
    try:
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_reader = csv.DictReader(stream)
        
        csv_reader.fieldnames = [f.strip().lower() for f in csv_reader.fieldnames]
        
        required = ["name", "surname"]
        for r in required:
            if r not in csv_reader.fieldnames:
                return jsonify({"error": f"CSV missing required column: '{r}'"}), 400
                
        imported = []
        for row in csv_reader:
            name = row.get("name", "").strip()
            surname = row.get("surname", "").strip()
            grade = row.get("grade", "").strip()
            school = row.get("school", "").strip()
            city = row.get("city", "").strip()
            
            if not name or not surname:
                continue
                
            username = generate_unique_username(name, surname)
            password = generate_random_password(8)
            
            client_hash = hashlib.sha256(password.encode()).hexdigest()
            user = User(
                username=username,
                password_hash=generate_password_hash(client_hash, method='pbkdf2:sha256'),
                role='competitor',
                alias_id=generate_pseudonym(),
                challenge_id=int(challenge_id)
            )
            user.set_demographics(name, surname, grade, school, city)
            db.session.add(user)
            imported.append({
                "name": name,
                "surname": surname,
                "grade": grade,
                "school": school,
                "city": city,
                "generated_username": username,
                "generated_password": password,
                "alias_id": user.alias_id
            })
            
        db.session.commit()
        return jsonify({
            "message": f"Successfully imported {len(imported)} competitors.",
            "competitors": imported
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Failed to parse CSV file: {str(e)}"}), 400


@admin_bp.route('/backup', methods=['GET'])
@role_required(['admin'])
def download_backup():
    db_uri = current_app.config['SQLALCHEMY_DATABASE_URI']
    if not (db_uri.startswith("postgresql://") or db_uri.startswith("postgres://")):
        return jsonify({"error": "Database backup is only supported for PostgreSQL databases."}), 400
        
    parsed = urllib.parse.urlparse(db_uri)
    username = parsed.username
    password = parsed.password
    host = parsed.hostname
    port = parsed.port or 5432
    database = parsed.path.lstrip('/')
    
    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password
        
    cmd = ["pg_dump", "-h", host, "-U", username, "-p", str(port), "-d", database]
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            return jsonify({"error": f"pg_dump failed: {stderr.decode()}"}), 500
        
        from io import BytesIO
        return send_file(
            BytesIO(stdout),
            mimetype="application/octet-stream",
            as_attachment=True,
            download_name=f"backup_nai_db_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.sql"
        )
    except Exception as e:
        return jsonify({"error": f"Failed to execute backup process: {str(e)}"}), 500


@admin_bp.route('/users/<int:user_id>', methods=['PUT'])
@role_required(['admin', 'jury'])
def update_user(user_id):
    user = User.query.get_or_404(user_id)
    current_role = request.user["role"]
    
    # Check if the competition has started for jury edits
    if current_role == 'jury':
        # Jury cannot edit admin or other jury members
        if user.role in ('admin', 'jury'):
            return jsonify({"error": "Jury members cannot edit administrator or other jury accounts."}), 403
            
        # Check current assigned challenge
        if user.challenge_id:
            challenge = Challenge.query.get(user.challenge_id)
            if challenge and challenge.start_time and datetime.utcnow() >= challenge.start_time:
                return jsonify({"error": "Cannot edit user: The assigned competition has already started."}), 403
    
    data = request.json or {}
    name = data.get("name")
    surname = data.get("surname")
    grade = data.get("grade")
    school = data.get("school")
    city = data.get("city")
    email = data.get("email")
    username = data.get("username")
    challenge_id = data.get("challenge_id")
    password = data.get("password")
    
    # Check new challenge start time if jury is assigning
    if challenge_id is not None and challenge_id != "" and challenge_id != user.challenge_id:
        target_challenge_id = int(challenge_id)
        if current_role == 'jury':
            challenge = Challenge.query.get(target_challenge_id)
            if challenge and challenge.start_time and datetime.utcnow() >= challenge.start_time:
                return jsonify({"error": "Cannot assign user to a competition that has already started."}), 403
        user.challenge_id = target_challenge_id
    elif challenge_id == "":
        user.challenge_id = None

    # Update demographics using fallback decryption
    dec_name = decrypt_field(user.name)
    dec_surname = decrypt_field(user.surname)
    dec_grade = decrypt_field(user.grade)
    dec_school = decrypt_field(user.school)
    dec_city = decrypt_field(user.city)

    new_name = name if name is not None else dec_name
    new_surname = surname if surname is not None else dec_surname
    new_grade = grade if grade is not None else dec_grade
    new_school = school if school is not None else dec_school
    new_city = city if city is not None else dec_city

    user.set_demographics(new_name, new_surname, new_grade, new_school, new_city)
    
    if email is not None:
        user.email = email
        
    if username is not None and username != user.username:
        existing = User.query.filter_by(username=username).first()
        if existing:
            return jsonify({"error": "Username is already taken."}), 400
        user.username = username
        
    if password:
        client_hash = hashlib.sha256(password.encode()).hexdigest()
        user.password_hash = generate_password_hash(client_hash, method='pbkdf2:sha256')
        
    db.session.commit()
    return jsonify({
        "message": "User updated successfully.",
        "user": user.to_dict(view_role=request.user["role"])
    })


@admin_bp.route('/challenges/<int:challenge_id>/download-scores-csv', methods=['GET'])
@role_required(['admin', 'jury'])
def download_scores_csv(challenge_id):
    challenge = Challenge.query.get_or_404(challenge_id)
    if not challenge.scores_finalized:
        return jsonify({"error": "Scores must be finalized before downloading."}), 400
        
    tasks = challenge.tasks
    competitors = User.query.filter_by(role='competitor', challenge_id=challenge_id).all()
    
    competitor_data = []
    for comp in competitors:
        task_scores = {}
        total_score = 0.0
        for task in tasks:
            subs = Submission.query.filter_by(task_id=task.id, user_id=comp.id, status='completed').all()
            best_sub = None
            has_late_sub = False
            if challenge.end_time and datetime.utcnow() > challenge.end_time:
                has_late_sub = any(s.executed_at and s.executed_at > challenge.end_time for s in subs)
                
            final_sel = next((s for s in subs if s.is_final_selection), None)
            if final_sel and not has_late_sub:
                best_sub = final_sel
            elif subs:
                is_lower_better = False
                if task.metrics_config:
                    try:
                        m_config = json.loads(task.metrics_config) if isinstance(task.metrics_config, str) else task.metrics_config
                        for m_name, m_info in m_config.items():
                            if m_info.get("higher_is_better") is False:
                                is_lower_better = True
                            break
                    except:
                        pass
                else:
                    metric_name = challenge.metric_name or ''
                    if 'mse' in metric_name.lower() or 'error' in metric_name.lower() or 'loss' in metric_name.lower():
                        is_lower_better = True
                
                if is_lower_better:
                    subs_sorted = sorted(subs, key=lambda x: (x.private_score if x.private_score is not None else x.public_score or 999999))
                else:
                    subs_sorted = sorted(subs, key=lambda x: (x.private_score if x.private_score is not None else x.public_score or -999999), reverse=True)
                
                if subs_sorted:
                    best_sub = subs_sorted[0]
            
            score = 0.0
            if best_sub:
                score = best_sub.private_score if best_sub.private_score is not None else (best_sub.public_score or 0.0)
            
            task_scores[task.id] = score
            total_score += score
            
        competitor_data.append({
            "competitor": comp,
            "task_scores": task_scores,
            "total_score": total_score
        })
        
    # Sort competitors by total score descending
    competitor_data = sorted(competitor_data, key=lambda x: x["total_score"], reverse=True)
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    header = ["Rank", "Alias ID", "Name", "Surname", "Username", "Email", "School", "City", "Grade"]
    for task in tasks:
        header.append(f"Task: {task.title}")
    header.append("Total Score")
    writer.writerow(header)
    
    for rank, item in enumerate(competitor_data, 1):
        comp = item["competitor"]
        row = [
            rank,
            comp.alias_id,
            decrypt_field(comp.name) or "—",
            decrypt_field(comp.surname) or "—",
            comp.username,
            comp.email or "—",
            decrypt_field(comp.school) or "—",
            decrypt_field(comp.city) or "—",
            decrypt_field(comp.grade) or "—",
        ]
        for task in tasks:
            row.append(f"{item['task_scores'][task.id]:.4f}")
        row.append(f"{item['total_score']:.4f}")
        writer.writerow(row)
        
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename=scores_challenge_{challenge_id}.csv"}
    )


@admin_bp.route('/challenges/<int:challenge_id>/download-submissions-zip', methods=['GET'])
@role_required(['admin', 'jury'])
def download_submissions_zip(challenge_id):
    challenge = Challenge.query.get_or_404(challenge_id)
    if not challenge.scores_finalized:
        return jsonify({"error": "Scores must be finalized before downloading submissions."}), 400
        
    competitors = User.query.filter_by(role='competitor', challenge_id=challenge_id).all()
    
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for comp in competitors:
            name_part = decrypt_field(comp.name) or ""
            surname_part = decrypt_field(comp.surname) or ""
            comp_name = f"{name_part}_{surname_part}_{comp.alias_id}"
            comp_name = "".join(c for c in comp_name if c.isalnum() or c in (" ", "_", "-")).strip()
            
            subs = Submission.query.join(Task).filter(
                Submission.user_id == comp.id,
                Submission.is_final_selection == True,
                Task.challenge_id == challenge_id
            ).all()
            
            for sub in subs:
                task_title = "".join(c for c in sub.task.title if c.isalnum() or c in (" ", "_", "-")).strip()
                filename = f"{comp_name}/{task_title}_sub_{sub.id}.ipynb"
                
                try:
                    cells_data = json.loads(sub.code_cells) if isinstance(sub.code_cells, str) else sub.code_cells
                except:
                    cells_data = []
                    
                ipynb_cells = []
                for c in cells_data:
                    source_lines = c.get("source", "")
                    if isinstance(source_lines, str):
                        source_lines = [line + "\n" for line in source_lines.splitlines()]
                    ipynb_cells.append({
                        "cell_type": c.get("type", "code"),
                        "execution_count": None,
                        "metadata": {},
                        "outputs": [],
                        "source": source_lines
                    })
                    
                notebook_json = {
                    "cells": ipynb_cells,
                    "metadata": {
                        "language_info": {
                            "name": "python"
                        }
                    },
                    "nbformat": 4,
                    "nbformat_minor": 2
                }
                
                notebook_str = json.dumps(notebook_json, indent=2)
                zip_file.writestr(filename, notebook_str)
                
    zip_buffer.seek(0)
    return Response(
        zip_buffer.getvalue(),
        mimetype="application/zip",
        headers={"Content-disposition": f"attachment; filename=submissions_challenge_{challenge_id}.zip"}
    )

