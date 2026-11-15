"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
import sys
from typing import Any, ClassVar

from dotenv import load_dotenv

# Load environment variables from .env in workspace root
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))


def _worker_role() -> str:
    """Resolve the unified worker role from ``WORKER_ROLE`` (default ``server``).

    Roles:
      - ``server``    main Flask server. Full app, all tasks.
      - ``scheduler`` Celery beat only: schedules tasks, executes nothing.
                      No app, no server secrets.
      - ``internal``  system-tasks worker (backups, leaderboard recalc, watchdog).
                      Boots the app (DB/Redis) for system tasks; never runs
                      submission/evaluation code.
      - ``eval``      remote evaluation worker. No DB access; reports results over
                      HTTP; runs only evaluation/image-build tasks.
    """
    role = os.environ.get("WORKER_ROLE", "").strip().lower()
    return role if role in ("server", "scheduler", "internal", "eval") else "server"


_WORKER_ROLE = _worker_role()


def _role_required_env(role: str) -> set[str]:
    """Env vars a role needs to boot (everything else is left empty).

    - server: full API server — all secrets + the database.
    - internal: app boots for system tasks — the database only.
    - scheduler / eval: no app — no server secrets.
    """
    if role == "server":
        return {"SECRET_KEY", "DATABASE_URL", "ENCRYPTION_KEY"}
    if role == "internal":
        return {"DATABASE_URL"}
    return set()


_WORKER_REQUIRED_ENV = _role_required_env(_WORKER_ROLE)


def _warn_insecure_redis(url: str, what: str) -> None:
    """Warn when Redis is reached over plaintext to a non-loopback host.
    Internal compose service names like ``redis`` are intentionally
    loopback-free, so this is a warning, not a fail-fast."""
    if not url:
        return
    try:
        parsed = url.split("://", 1)[1].split("/", 1)[0]
        host = parsed.rsplit("@", 1)[-1]
        if ":" in host and not host.startswith("["):
            host = host.rsplit(":", 1)[0]
        host = host.strip("[]")
        if url.startswith("redis://") and host not in ("localhost", "127.0.0.1", "::1"):
            sys.stderr.write(
                f"WARNING: {what} uses plaintext redis:// to {host!r} over the network. "
                "Prefer rediss:// + TLS when the broker is reachable outside the host.\n"
            )
    except Exception:  # noqa: S110
        pass


def _postgres_engine_options(
    database_uri: str,
    *,
    pool_size: int,
    max_overflow: int,
    statement_timeout_ms: int,
    idle_in_transaction_timeout_ms: int | None = None,
) -> dict[str, Any]:
    """Build the SQLAlchemy engine options for PostgreSQL; empty for other databases."""
    if not database_uri.startswith("postgresql"):
        return {}
    # Abort runaway statements (leaderboard rebuilds, unindexed scans)
    options = f"-c statement_timeout={statement_timeout_ms}"
    if idle_in_transaction_timeout_ms is not None:
        options += f" -c idle_in_transaction_session_timeout={idle_in_transaction_timeout_ms}"
    return {
        "pool_size": pool_size,
        "pool_timeout": 30,
        "max_overflow": max_overflow,
        "pool_pre_ping": True,
        "pool_recycle": 600,
        "connect_args": {"options": options},
    }


def _require_env(key: str, message: str | None = None) -> str:
    val = os.environ.get(key)
    if not val:
        msg = message or f"Required environment variable '{key}' is not set."
        sys.stderr.write(f"FATAL: {msg}\n")
        sys.exit(1)
    return val


class Config:
    # JWT signing key. Required for the API server, but NEVER shipped to
    # Workers (a compromised eval worker must not be able to mint tokens)
    # Workers run without SECRET_KEY (they authenticate via Ed25519 nonces)
    SECRET_KEY = os.environ.get("SECRET_KEY") or (
        "" if "SECRET_KEY" not in _WORKER_REQUIRED_ENV else _require_env("SECRET_KEY")
    )
    # Root secret used only to derive per-task evaluation split keys on the server
    EVALUATION_SPLIT_SECRET = os.environ.get("EVALUATION_SPLIT_SECRET") or SECRET_KEY

    # Database configuration - PostgreSQL strictly enforced
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or (
        "" if "DATABASE_URL" not in _WORKER_REQUIRED_ENV else _require_env("DATABASE_URL")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Celery configuration
    CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
    # Dedicated cache instance (defaults to broker when unset, e.g. dev/tests)
    CACHE_REDIS_URL = os.environ.get("CACHE_REDIS_URL", "")
    _warn_insecure_redis(CELERY_BROKER_URL, "CELERY_BROKER_URL")
    _warn_insecure_redis(CACHE_REDIS_URL, "CACHE_REDIS_URL")
    CELERY_BROKER_TRANSPORT_OPTIONS: ClassVar[dict[str, Any]] = {
        "socket_timeout": int(os.environ.get("CELERY_BROKER_SOCKET_TIMEOUT", 10)),
        "socket_connect_timeout": int(os.environ.get("CELERY_BROKER_SOCKET_CONNECT_TIMEOUT", 3)),
        # Must exceed the 1h watchdog cutoff so queued tasks are never
        # redelivered/duplicated right before the watchdog marks them failed
        "visibility_timeout": int(os.environ.get("CELERY_VISIBILITY_TIMEOUT", 7200)),
    }

    # Max queued+accepted evaluations before submissions are rejected (per queue)
    MAX_QUEUED_EVALUATIONS = int(os.environ.get("MAX_QUEUED_EVALUATIONS", 100))
    # Broker message expiry for evaluation tasks (seconds). Must stay at least 15 min
    # Below the watchdog's 1 h "never picked up" cutoff: a worker that takes a message
    # Just before it expires still needs time to build the image and start the container
    CELERY_MESSAGE_EXPIRES = int(os.environ.get("CELERY_MESSAGE_EXPIRES", 2700))
    # Celery limits for one evaluation (image build plus sandbox run). A task's time
    # Limit stays at least 60 s below the soft limit, so the sandbox's own timeout
    # Always ends a run before Celery does (R65)
    CELERY_TASK_SOFT_TIME_LIMIT = int(os.environ.get("CELERY_TASK_SOFT_TIME_LIMIT", 1200))
    CELERY_TASK_TIME_LIMIT = int(os.environ.get("CELERY_TASK_TIME_LIMIT", 1500))
    MAX_TASK_TIME_LIMIT_SEC = CELERY_TASK_SOFT_TIME_LIMIT - 60

    # Redis client connection timeouts
    REDIS_SOCKET_CONNECT_TIMEOUT = int(os.environ.get("REDIS_SOCKET_CONNECT_TIMEOUT", 5))
    REDIS_SOCKET_TIMEOUT = int(os.environ.get("REDIS_SOCKET_TIMEOUT", 5))
    REDIS_HEALTH_MIN_FREE_PERCENT = int(os.environ.get("REDIS_HEALTH_MIN_FREE_PERCENT", 10))

    # PostgreSQL statement timeout (milliseconds) — applied via connect_args
    PG_STATEMENT_TIMEOUT_MS = int(os.environ.get("PG_STATEMENT_TIMEOUT_MS", 30000))
    # Web process only: abort transactions left idle (a backstop for leaked ones); generous
    # Because multipart task routes do long file I/O after touching ORM objects
    PG_IDLE_IN_TRANSACTION_TIMEOUT_MS = int(
        os.environ.get("PG_IDLE_IN_TRANSACTION_TIMEOUT_MS", 300000)
    )
    DB_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", 10))
    DB_MAX_OVERFLOW = int(os.environ.get("DB_MAX_OVERFLOW", 10))

    # SSE (Server-Sent Events) connection limits
    SSE_MAX_PER_USER = int(os.environ.get("SSE_MAX_PER_USER", 15))
    SSE_MAX_GLOBAL = int(os.environ.get("SSE_MAX_GLOBAL", 2000))
    SSE_IDLE_TIMEOUT = int(os.environ.get("SSE_IDLE_TIMEOUT", 1800))
    # Reconnect delay sent in the SSE retry field; every stream jitters it by +/-30%
    SSE_RETRY_MS = int(os.environ.get("SSE_RETRY_MS", 5000))
    SSE_LOG_TTL = int(os.environ.get("SSE_LOG_TTL", 3600))
    SSE_LOG_MAX_LINES = int(os.environ.get("SSE_LOG_MAX_LINES", 500))
    # Longer pushed log lines are cut (with a marker): 500 lines stay under ~4 MiB
    SSE_LOG_MAX_LINE_BYTES = int(os.environ.get("SSE_LOG_MAX_LINE_BYTES", 8192))

    # Worker heartbeat and status reporting (GET /api/status, /api/admin/system-status)
    WORKER_HEARTBEAT_SECONDS = int(os.environ.get("WORKER_HEARTBEAT_SECONDS", 30))
    WORKER_HEARTBEAT_STALE_SECONDS = int(os.environ.get("WORKER_HEARTBEAT_STALE_SECONDS", 90))
    STATUS_CACHE_SECONDS = int(os.environ.get("STATUS_CACHE_SECONDS", 30))
    STATUS_QUEUE_DEGRADED_SECONDS = int(os.environ.get("STATUS_QUEUE_DEGRADED_SECONDS", 600))

    # Admin search / pagination limits
    USER_SEARCH_LIMIT = int(os.environ.get("USER_SEARCH_LIMIT", 500))
    AUDIT_LOG_YIELD_PER = int(os.environ.get("AUDIT_LOG_YIELD_PER", 500))

    # Backup (Postgres + audit log dump) settings
    MIN_BACKUP_DISK_GB = int(os.environ.get("MIN_BACKUP_DISK_GB", 1))
    BACKUP_TIMEOUT = int(os.environ.get("BACKUP_TIMEOUT", 600))
    # Automatic backups kept per kind: full backups, and database-only backups
    # (18 x 20 min covers the 6 h between two full backups)
    BACKUP_RETENTION_COUNT = int(os.environ.get("BACKUP_RETENTION_COUNT", 3))
    BACKUP_DB_RETENTION_COUNT = int(os.environ.get("BACKUP_DB_RETENTION_COUNT", 18))
    # During a contest the database is backed up every 20 min, uploads only this often
    BACKUP_UPLOADS_INTERVAL_SECONDS = int(os.environ.get("BACKUP_UPLOADS_INTERVAL_SECONDS", 21600))

    # Upload folder
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER") or os.path.join(
        os.path.abspath(os.path.dirname(__file__)), "uploads"
    )
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024 * 1024  # 2 GB limit
    CHALLENGE_ARCHIVE_MAX_COMPRESSED_BYTES = int(
        os.environ.get("CHALLENGE_ARCHIVE_MAX_COMPRESSED_BYTES", 200 * 1024 * 1024)
    )
    CHALLENGE_ARCHIVE_MAX_UNCOMPRESSED_BYTES = int(
        os.environ.get("CHALLENGE_ARCHIVE_MAX_UNCOMPRESSED_BYTES", 2 * 1024 * 1024 * 1024)
    )
    CHALLENGE_ARCHIVE_MAX_MEMBER_BYTES = int(
        os.environ.get("CHALLENGE_ARCHIVE_MAX_MEMBER_BYTES", 500 * 1024 * 1024)
    )
    CHALLENGE_ARCHIVE_MAX_MEMBERS = int(os.environ.get("CHALLENGE_ARCHIVE_MAX_MEMBERS", 1000))
    CHALLENGE_ARCHIVE_MAX_COMPRESSION_RATIO = int(
        os.environ.get("CHALLENGE_ARCHIVE_MAX_COMPRESSION_RATIO", 100)
    )

    # Hugging Face Settings
    HF_CACHE_DIR = os.environ.get(
        "HF_CACHE_DIR",
        os.path.join(os.path.abspath(os.path.dirname(__file__)), "hf_cache"),
    )

    # SQLAlchemy connection pool settings (only for PostgreSQL)
    SQLALCHEMY_ENGINE_OPTIONS: ClassVar[dict[str, Any]] = _postgres_engine_options(
        SQLALCHEMY_DATABASE_URI,
        pool_size=DB_POOL_SIZE,
        max_overflow=DB_MAX_OVERFLOW,
        statement_timeout_ms=PG_STATEMENT_TIMEOUT_MS,
    )

    @classmethod
    def use_web_process_engine_options(cls) -> None:
        """Add the web-only idle transaction timeout; call before ``create_app``.

        Celery processes never call this: their tasks may legitimately keep a
        transaction open across slow non-SQL work.
        """
        cls.SQLALCHEMY_ENGINE_OPTIONS = _postgres_engine_options(
            cls.SQLALCHEMY_DATABASE_URI,
            pool_size=cls.DB_POOL_SIZE,
            max_overflow=cls.DB_MAX_OVERFLOW,
            statement_timeout_ms=cls.PG_STATEMENT_TIMEOUT_MS,
            idle_in_transaction_timeout_ms=cls.PG_IDLE_IN_TRANSACTION_TIMEOUT_MS,
        )

    # Pagination defaults
    DEFAULT_PER_PAGE = int(os.environ.get("DEFAULT_PER_PAGE", 10))
    MAX_PER_PAGE = int(os.environ.get("MAX_PER_PAGE", 100))

    # Cache timeout (seconds) for cached_or_compute helpers
    CACHE_TIMEOUT = int(os.environ.get("CACHE_TIMEOUT", 300))

    # Fallback defaults for task/challenge metadata
    DEFAULT_TIME_LIMIT_SEC = int(os.environ.get("DEFAULT_TIME_LIMIT_SEC", 300))

    # Upper bound for a worker-reported execution_time_ms. Generous ceiling for
    # Long-running evaluations; anything above is a corrupt/adversarial report
    MAX_EXECUTION_TIME_MS = int(os.environ.get("MAX_EXECUTION_TIME_MS", 30 * 24 * 3600 * 1000))
    DEFAULT_RAM_LIMIT_MB = int(os.environ.get("DEFAULT_RAM_LIMIT_MB", 8192))
    DEFAULT_PUBLIC_EVAL_PERCENTAGE = int(os.environ.get("DEFAULT_PUBLIC_EVAL_PERCENTAGE", 30))

    # Worker utils
    WORKER_MAX_LOG_LINES = int(os.environ.get("WORKER_MAX_LOG_LINES", 10000))
    WORKER_MAX_STDOUT_CHARS = int(os.environ.get("WORKER_MAX_STDOUT_CHARS", 1024 * 1024))
    # Cumulative size cap for the server-side worker_remote.log; the file is
    # Rotated (kept as .1) once it would exceed this bound.
    MAX_WORKER_LOG_BYTES = int(os.environ.get("MAX_WORKER_LOG_BYTES", 10 * 1024 * 1024))
    WORKER_REPORT_MAX_RETRIES = int(os.environ.get("WORKER_REPORT_MAX_RETRIES", 3))
    WORKER_REPORT_TIMEOUT = int(os.environ.get("WORKER_REPORT_TIMEOUT", 10))
    WORKER_DOWNLOAD_TIMEOUT = int(os.environ.get("WORKER_DOWNLOAD_TIMEOUT", 30))
    MAX_WORKER_REPORT_BYTES = int(os.environ.get("MAX_WORKER_REPORT_BYTES", 512 * 1024))
    MAX_WORKER_AUTH_BODY_BYTES = int(os.environ.get("MAX_WORKER_AUTH_BODY_BYTES", 8 * 1024))
    MAX_WORKER_LOG_SHIP_BYTES = int(os.environ.get("MAX_WORKER_LOG_SHIP_BYTES", 1024 * 1024))
    # Caps for sandbox output collection: never buffer
    # More than MAX_COLLECT_BUFFER_BYTES of a tar stream in memory, and never
    # Extract a single archive member larger than MAX_EXTRACT_MEMBER_BYTES
    MAX_COLLECT_BUFFER_BYTES = int(os.environ.get("MAX_COLLECT_BUFFER_BYTES", 512 * 1024 * 1024))
    MAX_EXTRACT_MEMBER_BYTES = int(os.environ.get("MAX_EXTRACT_MEMBER_BYTES", 512 * 1024 * 1024))
    MAX_PARQUET_FILE_BYTES = int(os.environ.get("MAX_PARQUET_FILE_BYTES", 512 * 1024 * 1024))
    MAX_PARQUET_UNCOMPRESSED_BYTES = int(
        os.environ.get("MAX_PARQUET_UNCOMPRESSED_BYTES", 1024 * 1024 * 1024)
    )
    MAX_PARQUET_ROWS = int(os.environ.get("MAX_PARQUET_ROWS", 10_000_000))
    MAX_PARQUET_COLUMNS = int(os.environ.get("MAX_PARQUET_COLUMNS", 512))
    MAX_EVALUATOR_RESULT_BYTES = int(os.environ.get("MAX_EVALUATOR_RESULT_BYTES", 64 * 1024))
    # Mandatory --storage-opt size cap for sandbox containers
    WORKER_SANDBOX_STORAGE_OPT = os.environ.get("WORKER_SANDBOX_STORAGE_OPT", "8g")

    # Grace period (seconds) for submissions after the official deadline
    DEADLINE_GRACE_PERIOD_SECONDS = int(os.environ.get("DEADLINE_GRACE_PERIOD_SECONDS", 180))

    # Encryption key for PII fields. Servers use ENCRYPTION_KEY; remote workers
    # Use their own independent WORKER_ENCRYPTION_KEY (shipped via worker.env)
    # So the server JWT key never leaves the server host
    WORKER_ENCRYPTION_KEY = os.environ.get("WORKER_ENCRYPTION_KEY", "")
    ENCRYPTION_KEY = (
        os.environ.get("ENCRYPTION_KEY")
        or os.environ.get("WORKER_ENCRYPTION_KEY")
        or ("" if "ENCRYPTION_KEY" not in _WORKER_REQUIRED_ENV else _require_env("ENCRYPTION_KEY"))
    )

    # Secure cookies (set True when behind HTTPS)
    SECURE_COOKIES = os.environ.get("SECURE_COOKIES", "false").lower() in ("1", "true", "yes")

    # CORS origins (explicit allow-list; dev defaults, override in production)
    CORS_ORIGINS = os.environ.get(
        "CORS_ORIGINS", "http://localhost:5173,http://localhost:5001,http://127.0.0.1:5173"
    )

    # Directories
    BACKUPS_DIR = os.environ.get("BACKUPS_DIR", "/backups")
    TASK_IMAGES_DIR = os.environ.get(
        "TASK_IMAGES_DIR",
        os.path.join(os.path.abspath(os.path.dirname(__file__)), "task_images"),
    )
    _default_workspace = os.path.join(os.path.abspath(os.path.dirname(__file__)), "workspace")
    LAVBENCH_WORKSPACE_DIR = os.environ.get("LAVBENCH_WORKSPACE_DIR", "") or (
        _default_workspace if os.path.isdir(_default_workspace) else ""
    )

    # Main server URL (for worker callbacks)
    MAIN_SERVER_URL = os.environ.get("MAIN_SERVER_URL", "http://localhost:5001")

    # Unified worker role + derived capabilities (see _worker_role)
    WORKER_ROLE = _WORKER_ROLE
    HAS_APP = WORKER_ROLE in ("server", "internal")
    IS_EVAL_WORKER = WORKER_ROLE == "eval"
    RUNS_EVALUATION = WORKER_ROLE in ("server", "eval")
    RUNS_INTERNAL = WORKER_ROLE in ("server", "internal")
    CELERY_WORKER_CONCURRENCY = int(os.environ.get("CELERY_WORKER_CONCURRENCY", 2))
    WORKER_GPU_ID = os.environ.get("WORKER_GPU_ID", "")
    GPU_ACQUISITION_TIMEOUT = int(os.environ.get("GPU_ACQUISITION_TIMEOUT", 600))
    WORKER_PUBLIC_KEYS_JSON = os.environ.get("WORKER_PUBLIC_KEYS_JSON", "{}")
    WORKER_PRIVATE_KEY = os.environ.get("WORKER_PRIVATE_KEY", "")
    WORKER_ID = os.environ.get("WORKER_ID", "")
    WORKER_CAPABILITY_SECRET = os.environ.get("WORKER_CAPABILITY_SECRET", SECRET_KEY)
    WORKER_CAPABILITY_TTL = int(os.environ.get("WORKER_CAPABILITY_TTL", 3600))
    WORKER_ATTEMPT_LEASE_TTL = int(os.environ.get("WORKER_ATTEMPT_LEASE_TTL", 1500))

    # Worker sandbox resource allocation
    GPU_RAM_PER_TASK_GB = int(os.environ.get("GPU_RAM_PER_TASK_GB", 8))
    CPU_RAM_PER_TASK_GB = int(os.environ.get("CPU_RAM_PER_TASK_GB", 8))
    RESERVED_RAM_GB = int(os.environ.get("RESERVED_RAM_GB", 4))
    GPU_CORES_PER_TASK = int(os.environ.get("GPU_CORES_PER_TASK", 0))
    CPU_CORES_PER_TASK = int(os.environ.get("CPU_CORES_PER_TASK", 0))
    RESERVED_CPU_CORES = int(os.environ.get("RESERVED_CPU_CORES", 1))
    RAM_CLAMP_FACTOR = float(os.environ.get("RAM_CLAMP_FACTOR", 1.05))

    # Gunicorn settings (consumed by entrypoint.sh, documented here for discovery)
    # 0 disables worker recycling, which would drop every open SSE stream at once
    GUNICORN_MAX_REQUESTS = int(os.environ.get("GUNICORN_MAX_REQUESTS", 0))
    GUNICORN_MAX_REQUESTS_JITTER = int(os.environ.get("GUNICORN_MAX_REQUESTS_JITTER", 2000))
    GUNICORN_ULIMIT_NOFILE = int(os.environ.get("GUNICORN_ULIMIT_NOFILE", 65536))
    # "-" is stdout, which Docker captures and rotates; gunicorn never rotates its own files
    GUNICORN_ACCESS_LOGFILE = os.environ.get("GUNICORN_ACCESS_LOGFILE", "-")
    GUNICORN_ERROR_LOGFILE = os.environ.get("GUNICORN_ERROR_LOGFILE", "-")

    # Logging directory
    LOG_DIR = os.environ.get("LOG_DIR", "/app/logs")

    # Log shipping endpoint for remote workers
    WORKER_LOG_SHIP_URL = os.environ.get("WORKER_LOG_SHIP_URL", "")

    # Submission file size limits (prevents OOM on property access)
    MAX_LOG_CHARS = int(os.environ.get("MAX_LOG_CHARS", 100 * 1024))  # 100 KB
    MAX_SELECTED_CELLS = int(os.environ.get("MAX_SELECTED_CELLS", 500))
    MAX_CODE_CELL_CHARS = int(os.environ.get("MAX_CODE_CELL_CHARS", 1024 * 1024))
    MAX_CODE_CELLS_CHARS = int(
        os.environ.get("MAX_CODE_CELLS_CHARS", 5 * 1024 * 1024)  # 5 MB
    )
    MAX_SUBMISSION_REQUEST_BYTES = int(
        os.environ.get("MAX_SUBMISSION_REQUEST_BYTES", 6 * 1024 * 1024)
    )

    # Redis SSL settings
    REDIS_SSL_CA_CERTS = os.environ.get("REDIS_SSL_CA_CERTS", "")
    REDIS_SSL_CERTFILE = os.environ.get("REDIS_SSL_CERTFILE", "")
    REDIS_SSL_KEYFILE = os.environ.get("REDIS_SSL_KEYFILE", "")
    REDIS_SSL_CERT_REQS = os.environ.get("REDIS_SSL_CERT_REQS", "required")
