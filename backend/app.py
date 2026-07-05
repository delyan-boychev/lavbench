"""Flask application factory and Swagger/OpenAPI configuration."""

import logging
import os

# Attempt to raise file descriptor limit for high concurrency (fallback when
# entrypoint.sh ulimit or docker-compose ulimits are not in effect, e.g. in
# dev/debug mode). Safe to call even if already raised by the parent process.
try:
    import resource

    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    target = int(os.environ.get("GUNICORN_ULIMIT_NOFILE", 65536))
    if soft < target:
        resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
except (ImportError, ValueError, OSError):
    pass

# Load .env before any module that reads environment variables
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
logger = logging.getLogger(__name__)

from flask import Flask  # noqa: E402
from flask.json.provider import DefaultJSONProvider  # noqa: E402
from flask_cors import CORS  # noqa: E402
from spectree import Response  # noqa: E402
from werkzeug.datastructures import FileStorage  # noqa: E402
from werkzeug.middleware.proxy_fix import ProxyFix  # noqa: E402

from config import Config  # noqa: E402
from error_utils import err  # noqa: E402
from log_config import setup_logging  # noqa: E402
from models import db  # noqa: E402
from schemas.responses import HealthResponse  # noqa: E402
from spec import api  # noqa: E402
from version import __version__  # noqa: E402


class _LavBenchJSONProvider(DefaultJSONProvider):
    """Handles FileStorage in Pydantic validation errors for file-upload forms."""

    def default(self, obj):
        if isinstance(obj, FileStorage):
            return {
                "filename": obj.filename,
                "mimetype": obj.content_type,
                "size": obj.content_length,
            }
        return super().default(obj)


def create_app():
    setup_logging("backend")
    app = Flask(__name__)
    app.json = _LavBenchJSONProvider(app)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config.from_object(Config)

    # Enable CORS - restrict origins in production
    cors_origins = Config.CORS_ORIGINS.split(",")
    CORS(app, resources={r"/api/*": {"origins": cors_origins}})

    db.init_app(app)

    # Register Service Blueprints
    from routes.admin import admin_bp
    from routes.auth import auth_bp
    from routes.challenges import challenges_bp
    from routes.docs import docs_bp
    from routes.leaderboard import leaderboard_bp
    from routes.submissions import submissions_bp
    from routes.tasks import tasks_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(admin_bp, url_prefix="/api/admin")
    app.register_blueprint(challenges_bp, url_prefix="/api/challenges")
    app.register_blueprint(submissions_bp, url_prefix="/api")
    app.register_blueprint(leaderboard_bp, url_prefix="/api")
    app.register_blueprint(tasks_bp, url_prefix="/api")
    app.register_blueprint(docs_bp, url_prefix="/api/docs")

    @app.route("/api/health", methods=["GET"])
    @api.validate(resp=Response(HTTP_200=HealthResponse, HTTP_503=HealthResponse), tags=["Health"])
    def health_check():
        """Health check for Docker and load balancer monitoring."""
        db_ok = True
        try:
            db.session.execute(db.text("SELECT 1"))
        except Exception:
            db_ok = False
        return HealthResponse(
            status="ok" if db_ok else "degraded",
            version=__version__,
        ), 200 if db_ok else 503

    # ── spectree / OpenAPI setup ─────────────────────────────────────
    api.register(app)

    @app.errorhandler(500)
    def handle_internal_error(e):
        return err("ERR_INTERNAL", 500)

    return app


app = create_app()


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=5001, debug=debug_mode)  # noqa: S104
