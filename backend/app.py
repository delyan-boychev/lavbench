"""Flask application factory and Swagger/OpenAPI configuration."""

from __future__ import annotations

import logging
import os
from typing import Any

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
from flask import Response as FlaskResponse  # noqa: E402
from flask.json.provider import DefaultJSONProvider  # noqa: E402
from flask_cors import CORS  # noqa: E402
from spectree import Response  # noqa: E402
from werkzeug.datastructures import FileStorage  # noqa: E402
from werkzeug.middleware.proxy_fix import ProxyFix  # noqa: E402

from config import Config  # noqa: E402
from config.log_config import setup_logging  # noqa: E402
from models import db  # noqa: E402
from schemas.responses import HealthResponse  # noqa: E402
from utils.error_utils import err  # noqa: E402
from utils.spec import api  # noqa: E402
from utils.version import __version__  # noqa: E402


class _LavBenchJSONProvider(DefaultJSONProvider):
    """Handles FileStorage in Pydantic validation errors for file-upload forms."""

    def default(self, obj: object) -> Any:
        if isinstance(obj, FileStorage):
            return {
                "filename": obj.filename,
                "mimetype": obj.content_type,
                "size": obj.content_length,
            }
        return super().default(obj)


def _warn_insecure_cookie_deployment() -> None:
    """Surface an insecure deployment loudly at startup.

    When SECURE_COOKIES=false the 24h JWT auth cookie + CSRF cookie are sent in
    cleartext and can be sniffed on shared networks (a real risk for the
    school-LAN audience). This is a loud warning, not a hard failure —
    operators may legitimately run HTTP on an isolated LAN — but it must not be
    silent. nginx terminates TLS in front of this container; the compose
    default is SECURE_COOKIES=true.
    """
    if Config.IS_EVAL_WORKER or Config.SECURE_COOKIES:
        return
    main_host = Config.MAIN_SERVER_URL.split("://")[-1].split("/")[0].split(":")[0]
    if main_host in ("localhost", "127.0.0.1", "::1"):
        return
    logger.warning(
        "SECURE_COOKIES is disabled while MAIN_SERVER_URL=%s is not localhost. "
        "Auth cookies are transmitted in cleartext. Set SECURE_COOKIES=true and "
        "terminate TLS at nginx for production deployments.",
        Config.MAIN_SERVER_URL,
    )


_SCHEMA_BOOTSTRAP_LOCK = 727376317


def _ensure_database_schema(app: Flask) -> None:
    """Create tables on first boot without racing across app/worker containers.

    Gunicorn workers import ``app`` (``utils.wsgi:app``) and only the ``__main__``
    path called ``db.create_all()``, so a fresh deployment served 500s until
    ``setup-admin`` ran. ``create_all`` is idempotent; a PostgreSQL advisory
    session lock merely serialises the first-boot stampede. Eval and scheduler
    workers never reach this (they do not hold the app/DB role). Failures
    degrade /api/health instead of blocking boot.
    """
    if not Config.HAS_APP:
        return
    with app.app_context():
        try:
            if db.engine.dialect.name == "postgresql":
                with db.engine.begin() as conn:
                    conn.execute(
                        db.text("SELECT pg_advisory_lock(:k)"),
                        {"k": _SCHEMA_BOOTSTRAP_LOCK},
                    )
                    db.metadata.create_all(bind=conn)
                    conn.execute(
                        db.text("SELECT pg_advisory_unlock(:k)"),
                        {"k": _SCHEMA_BOOTSTRAP_LOCK},
                    )
            else:
                db.create_all()
        except Exception:
            logger.exception(
                "Schema bootstrap failed — the app will boot and /api/health "
                "will report the database as degraded."
            )


def create_app() -> Flask:
    setup_logging("backend")
    _warn_insecure_cookie_deployment()
    app = Flask(__name__)
    app.json = _LavBenchJSONProvider(app)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)  # type: ignore[method-assign]
    app.config.from_object(Config)

    # Enable CORS - restrict origins in production
    cors_origins = Config.CORS_ORIGINS.split(",")
    CORS(app, resources={r"/api/*": {"origins": cors_origins}})

    db.init_app(app)
    _ensure_database_schema(app)

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
    def health_check() -> tuple[HealthResponse, int]:
        """Health check for Docker and load balancer monitoring.

        Probes the database, Redis (cache/SSE/broker) and disk space so a
        degraded stack never reports healthy.
        """
        checks: dict[str, str] = {}

        try:
            db.session.execute(db.text("SELECT 1"))
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "degraded"

        try:
            from utils.cache_utils import get_redis_client

            redis_client = get_redis_client()
            if redis_client is not None and redis_client.ping():
                checks["redis"] = "ok"
            else:
                checks["redis"] = "degraded"
        except Exception:
            checks["redis"] = "degraded"

        try:
            import shutil

            probe_dir = Config.BACKUPS_DIR
            if not os.path.isdir(probe_dir):
                probe_dir = Config.LOG_DIR
            if not os.path.isdir(probe_dir):
                probe_dir = os.path.dirname(os.path.abspath(__file__))
            free_bytes = shutil.disk_usage(probe_dir).free
            checks["disk"] = "ok" if free_bytes >= 512 * 1024 * 1024 else "degraded"
        except Exception:
            checks["disk"] = "degraded"

        ok = all(value == "ok" for value in checks.values())
        return HealthResponse(
            status="ok" if ok else "degraded",
            version=__version__,
            checks=checks,
        ), 200 if ok else 503

    # ── spectree / OpenAPI setup ─────────────────────────────────────
    api.register(app)

    @app.errorhandler(500)
    def handle_internal_error(e: Exception) -> tuple[FlaskResponse, int]:
        return err("ERR_INTERNAL", 500)

    return app


app = create_app()


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=5001, debug=debug_mode)  # noqa: S104
