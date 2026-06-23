"""Flask application factory and Swagger/OpenAPI configuration."""

import os
import json
from datetime import datetime, timedelta

# Load .env before any module that reads environment variables
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

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

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(admin_bp, url_prefix="/api/admin")
    app.register_blueprint(challenges_bp, url_prefix="/api/challenges")
    app.register_blueprint(submissions_bp, url_prefix="/api")
    app.register_blueprint(leaderboard_bp, url_prefix="/api")
    app.register_blueprint(tasks_bp, url_prefix="/api")
    app.register_blueprint(docs_bp, url_prefix="/api/docs")

    app.config["SWAGGER"] = {"openapi": "3.0.0", "uiversion": 3}

    Swagger(
        app,
        template={
            "info": {
                "title": "LavBench API",
                "description": "Machine Learning Competition Platform — REST + SSE Endpoints",
                "version": "1.0",
            },
            "tags": [
                {"name": "Auth", "description": "Login, logout, session management"},
                {
                    "name": "Challenges",
                    "description": "Competition CRUD, stages, finalize, archive, export",
                },
                {
                    "name": "Submissions",
                    "description": "Notebook parsing, submit, select final, logs",
                },
                {
                    "name": "Tasks",
                    "description": "Task CRUD, file uploads, evaluation configuration",
                },
                {
                    "name": "Leaderboard",
                    "description": "Rankings, manual points, score corrections",
                },
                {"name": "Admin", "description": "User management, backups, workers, dead letters"},
                {"name": "SSE Streaming", "description": "Real-time Server-Sent Event streams"},
                {"name": "Docs", "description": "In-app guide endpoints"},
            ],
            "components": {
                "securitySchemes": {
                    "cookieAuth": {
                        "type": "apiKey",
                        "name": "auth_token",
                        "in": "cookie",
                        "description": "Session cookie required for most endpoints.",
                    }
                },
                "schemas": {
                    "Error": {
                        "type": "object",
                        "required": ["error", "code"],
                        "properties": {
                            "error": {
                                "type": "string",
                                "description": "Human-readable error message",
                            },
                            "code": {
                                "type": "string",
                                "description": "Machine-readable error code",
                                "example": "ERR_INVALID_CREDENTIALS",
                            },
                        },
                    },
                    "User": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "format": "uuid"},
                            "username": {"type": "string"},
                            "email": {"type": "string"},
                            "role": {"type": "string", "enum": ["competitor", "jury", "admin"]},
                            "alias_id": {
                                "type": "string",
                                "description": "Pseudonym for leaderboard display",
                            },
                            "name": {"type": "string"},
                            "surname": {"type": "string"},
                            "grade": {"type": "string"},
                            "school": {"type": "string"},
                            "city": {"type": "string"},
                            "challenge_id": {"type": "string", "format": "uuid"},
                            "is_anonymous": {"type": "boolean"},
                            "manual_points": {"type": "object"},
                        },
                    },
                    "Challenge": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "format": "uuid"},
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
                            "status": {"type": "string"},
                        },
                    },
                    "Task": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "format": "uuid"},
                            "challenge_id": {"type": "string", "format": "uuid"},
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "files": {"type": "array", "items": {"type": "object"}},
                            "ram_limit_mb": {"type": "integer"},
                            "time_limit_sec": {"type": "integer"},
                            "gpu_required": {"type": "boolean"},
                            "base_docker_image": {"type": "string"},
                            "apt_packages": {"type": "string"},
                            "pip_requirements": {"type": "string"},
                            "ban_magic_commands": {"type": "boolean"},
                            "banned_imports": {"type": "string"},
                            "whitelisted_imports": {"type": "string"},
                            "metrics_config": {"type": "object"},
                            "stage_id": {"type": "string", "format": "uuid"},
                            "max_submissions_per_period": {"type": "integer"},
                            "submission_period_hours": {"type": "integer"},
                        },
                    },
                    "Submission": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "format": "uuid"},
                            "challenge_id": {"type": "string", "format": "uuid"},
                            "task_id": {"type": "string", "format": "uuid"},
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
                            "user": {"$ref": "#/components/schemas/User"},
                        },
                    },
                    "Cell": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "type": {"type": "string", "enum": ["code", "markdown"]},
                            "source": {"type": "string"},
                        },
                    },
                },
            },
        },
    )

    @app.route("/api/health", methods=["GET"])
    def health_check():
        """
        Health check for Docker and load balancer monitoring.
        Verifies database, Redis, Celery, and disk availability.
        ---
        tags:
          - Admin
        responses:
          200:
            description: Service healthy
            content:
              application/json:
                schema:
                  type: object
          503:
            description: Service degraded
            content:
              application/json:
                schema:
                  type: object
        """
        import platform

        checks = {}
        all_ok = True

        # Database check
        try:
            db.session.execute(db.text("SELECT 1"))
            checks["database"] = "connected"
        except Exception as e:
            checks["database"] = f"error: {e}"
            all_ok = False

        # Redis check
        try:
            from cache_utils import get_redis_client

            r = get_redis_client()
            if r and r.ping():
                checks["redis"] = "connected"
            else:
                checks["redis"] = "error: no response"
                all_ok = False
        except Exception as e:
            checks["redis"] = f"error: {e}"
            all_ok = False

        # Celery check
        try:
            from tasks import celery

            inspect = celery.control.inspect(timeout=2.0)
            pings = inspect.ping() or {}
            workers_count = len(pings)
            checks["celery"] = {"workers_online": workers_count}
        except Exception as e:
            checks["celery"] = f"error: {e}"

        # Disk check
        try:
            import shutil

            total, used, free = shutil.disk_usage("/")
            checks["disk"] = {
                "total_gb": round(total / (1024**3), 1),
                "used_gb": round(used / (1024**3), 1),
                "free_gb": round(free / (1024**3), 1),
            }
        except Exception:
            pass

        status_code = 200 if all_ok else 503
        return (
            jsonify(
                {
                    "status": "ok" if all_ok else "degraded",
                    "checks": checks,
                    "version": "1.0",
                    "python": platform.python_version(),
                }
            ),
            status_code,
        )

    @app.errorhandler(500)
    def handle_internal_error(e):
        return jsonify({"error": "Internal server error.", "code": "ERR_INTERNAL"}), 500

    return app


app = create_app()


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=5001, debug=debug_mode)
