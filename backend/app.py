import os
import json
from datetime import datetime, timedelta

# Load .env before any module that reads environment variables
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

from flask import Flask, jsonify
from flask_cors import CORS
from flasgger import Swagger
from werkzeug.middleware.proxy_fix import ProxyFix
from config import Config
from models import db, User, Challenge, Submission, Task

def create_app():
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config.from_object(Config)
    
    # Enable CORS - restrict origins in production
    cors_origins = os.environ.get("CORS_ORIGINS", "http://localhost:80").split(",")
    CORS(app, resources={r"/api/*": {"origins": cors_origins}})
    
    db.init_app(app)
    
    # Register Service Blueprints
    from routes.auth import auth_bp
    from routes.admin import admin_bp
    from routes.challenges import challenges_bp
    from routes.submissions import submissions_bp
    from routes.leaderboard import leaderboard_bp
    from routes.tasks import tasks_bp
    from routes.docs import docs_bp
    
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(admin_bp, url_prefix='/api/admin')
    app.register_blueprint(challenges_bp, url_prefix='/api/challenges')
    app.register_blueprint(submissions_bp, url_prefix='/api')
    app.register_blueprint(leaderboard_bp, url_prefix='/api')
    app.register_blueprint(tasks_bp, url_prefix='/api')
    app.register_blueprint(docs_bp, url_prefix='/api/docs')
    
    app.config['SWAGGER'] = {
        'openapi': '3.0.0',
        'uiversion': 3
    }
    
    Swagger(app, template={
        "info": {
            "title": "LavBench API",
            "description": "Machine Learning Competition Platform — REST + SSE Endpoints",
            "version": "1.0"
        },
        "tags": [
            {"name": "Auth", "description": "Login, logout, session management"},
            {"name": "Challenges", "description": "Competition CRUD, stages, finalize, archive, export"},
            {"name": "Submissions", "description": "Notebook parsing, submit, select final, logs"},
            {"name": "Tasks", "description": "Task CRUD, file uploads, evaluation configuration"},
            {"name": "Leaderboard", "description": "Rankings, manual points, score corrections"},
            {"name": "Admin", "description": "User management, backups, workers, dead letters"},
            {"name": "SSE Streaming", "description": "Real-time Server-Sent Event streams"},
            {"name": "Docs", "description": "In-app guide endpoints"}
        ],
        "components": {
            "securitySchemes": {
                "cookieAuth": {
                    "type": "apiKey",
                    "name": "auth_token",
                    "in": "cookie",
                    "description": "Session cookie required for most endpoints."
                }
            },
            "schemas": {
            "Error": {
                "type": "object",
                "required": ["error", "code"],
                "properties": {
                    "error": {"type": "string", "description": "Human-readable error message"},
                    "code": {"type": "string", "description": "Machine-readable error code", "example": "ERR_INVALID_CREDENTIALS"}
                }
            },
            "User": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "username": {"type": "string"},
                    "email": {"type": "string"},
                    "role": {"type": "string", "enum": ["competitor", "jury", "admin"]},
                    "alias_id": {"type": "string", "description": "Pseudonym for leaderboard display"},
                    "name": {"type": "string"},
                    "surname": {"type": "string"},
                    "grade": {"type": "string"},
                    "school": {"type": "string"},
                    "city": {"type": "string"},
                    "challenge_id": {"type": "integer"},
                    "is_anonymous": {"type": "boolean"},
                    "manual_points": {"type": "object"}
                }
            },
            "Challenge": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "max_eval_requests": {"type": "integer"},
                    "ram_limit_mb": {"type": "integer"},
                    "time_limit_sec": {"type": "integer"},
                    "gpu_required": {"type": "boolean"},
                    "is_active": {"type": "boolean"},
                    "is_archived": {"type": "boolean"},
                    "scores_finalized": {"type": "boolean"},
                    "is_frozen": {"type": "boolean"},
                    "double_blind": {"type": "boolean"},
                    "start_time": {"type": "string", "format": "date-time"},
                    "end_time": {"type": "string", "format": "date-time"},
                    "timezone": {"type": "string"},
                    "status": {"type": "string"}
                }
            },
            "Task": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "challenge_id": {"type": "integer"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "files": {"type": "array", "items": {"type": "object"}},
                    "ram_limit_mb": {"type": "integer"},
                    "time_limit_sec": {"type": "integer"},
                    "gpu_required": {"type": "boolean"},
                    "base_docker_image": {"type": "string"},
                    "apt_packages": {"type": "string"},
                    "pip_requirements": {"type": "string"},
                    "require_submit_tag": {"type": "boolean"},
                    "ban_magic_commands": {"type": "boolean"},
                    "banned_imports": {"type": "string"},
                    "whitelisted_imports": {"type": "string"},
                    "metrics_config": {"type": "object"},
                    "stage_id": {"type": "integer"},
                    "max_submissions_per_period": {"type": "integer"},
                    "submission_period_hours": {"type": "integer"}
                }
            },
            "Submission": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "challenge_id": {"type": "integer"},
                    "task_id": {"type": "integer"},
                    "task_title": {"type": "string"},
                    "status": {"type": "string"},
                    "detailed_status": {"type": "string"},
                    "public_score": {"type": "number"},
                    "private_score": {"type": "number"},
                    "execution_time_ms": {"type": "integer"},
                    "created_at": {"type": "string", "format": "date-time"},
                    "executed_at": {"type": "string", "format": "date-time"},
                    "is_final_selection": {"type": "boolean"},
                    "is_baseline": {"type": "boolean"},
                    "user": {"$ref": "#/components/schemas/User"}
                }
            },
            "Cell": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "type": {"type": "string", "enum": ["code", "markdown"]},
                    "source": {"type": "string"}
                }
            }
            }
        }
    })
    
    @app.route('/api/health', methods=['GET'])
    def health_check():
        """
        Health check for Docker and load balancer monitoring.
        Verifies database connectivity.
        ---
        tags:
          - Admin
        responses:
          200:
            description: Service healthy
            schema:
              type: object
              properties:
                status: {type: string, example: "ok"}
                database: {type: string, example: "connected"}
          503:
            description: Database unreachable
            schema:
              type: object
              properties:
                status: {type: string, example: "error"}
                detail: {type: string}
        """
        try:
            db.session.execute(db.text("SELECT 1"))
            return jsonify({"status": "ok", "database": "connected"}), 200
        except Exception as e:
            return jsonify({"status": "error", "detail": str(e)}), 503
    
    return app

app = create_app()


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host='0.0.0.0', port=5001, debug=debug_mode)
