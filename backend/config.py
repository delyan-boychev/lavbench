"""Application configuration loaded from environment variables."""

import logging
import os
import sys
from typing import ClassVar

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables from .env in workspace root
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))


def _require_env(key, message=None):
    val = os.environ.get(key)
    if not val:
        msg = message or f"Required environment variable '{key}' is not set."
        logger.error(f"FATAL: {msg}", file=sys.stderr)
        sys.exit(1)
    return val


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or _require_env("SECRET_KEY")

    # Database configuration - PostgreSQL strictly enforced
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or _require_env("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Celery configuration
    CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
    CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")
    CELERY_RESULT_EXPIRES = int(os.environ.get("CELERY_RESULT_EXPIRES", 3600))
    CELERY_BROKER_TRANSPORT_OPTIONS: ClassVar[dict] = {
        "socket_timeout": int(os.environ.get("CELERY_BROKER_SOCKET_TIMEOUT", 10)),
        "socket_connect_timeout": int(os.environ.get("CELERY_BROKER_SOCKET_CONNECT_TIMEOUT", 3)),
    }

    # Redis client connection timeouts
    REDIS_SOCKET_CONNECT_TIMEOUT = int(os.environ.get("REDIS_SOCKET_CONNECT_TIMEOUT", 5))
    REDIS_SOCKET_TIMEOUT = int(os.environ.get("REDIS_SOCKET_TIMEOUT", 5))

    # SSE (Server-Sent Events) connection limits
    SSE_MAX_PER_USER = int(os.environ.get("SSE_MAX_PER_USER", 5))
    SSE_MAX_GLOBAL = int(os.environ.get("SSE_MAX_GLOBAL", 50))
    SSE_IDLE_TIMEOUT = int(os.environ.get("SSE_IDLE_TIMEOUT", 1800))
    SSE_LOG_TTL = int(os.environ.get("SSE_LOG_TTL", 86400))
    SSE_LOG_MAX_LINES = int(os.environ.get("SSE_LOG_MAX_LINES", 10000))

    # Admin search / pagination limits
    USER_SEARCH_LIMIT = int(os.environ.get("USER_SEARCH_LIMIT", 500))
    AUDIT_LOG_YIELD_PER = int(os.environ.get("AUDIT_LOG_YIELD_PER", 500))

    # Backup (Postgres + audit log dump) settings
    MIN_BACKUP_DISK_GB = int(os.environ.get("MIN_BACKUP_DISK_GB", 1))
    BACKUP_TIMEOUT = int(os.environ.get("BACKUP_TIMEOUT", 600))

    # Docker image builder settings
    MIN_BUILD_DISK_GB = int(os.environ.get("MIN_BUILD_DISK_GB", 5))
    BUILD_LOCK_EXPIRY = int(os.environ.get("BUILD_LOCK_EXPIRY", 3600))

    # Upload folder
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER") or os.path.join(
        os.path.abspath(os.path.dirname(__file__)), "uploads"
    )
    MAX_CONTENT_LENGTH = 150 * 1024 * 1024  # 150 MB limit

    # Hugging Face Settings
    HF_CACHE_DIR = os.environ.get(
        "HF_CACHE_DIR",
        os.path.join(os.path.abspath(os.path.dirname(__file__)), "hf_cache"),
    )

    # SQLAlchemy connection pool settings (only for PostgreSQL)
    SQLALCHEMY_ENGINE_OPTIONS: ClassVar[dict] = {}
    if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith("postgresql"):
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_size": 50,
            "pool_timeout": 30,
            "max_overflow": 50,
            "pool_pre_ping": True,
            "pool_recycle": 600,
        }

    # Pagination defaults
    DEFAULT_PER_PAGE = int(os.environ.get("DEFAULT_PER_PAGE", 10))
    MAX_PER_PAGE = int(os.environ.get("MAX_PER_PAGE", 100))

    # Cache timeout (seconds) for cached_or_compute helpers
    CACHE_TIMEOUT = int(os.environ.get("CACHE_TIMEOUT", 300))

    # Fallback defaults for task/challenge metadata
    DEFAULT_TIME_LIMIT_SEC = int(os.environ.get("DEFAULT_TIME_LIMIT_SEC", 300))
    DEFAULT_RAM_LIMIT_MB = int(os.environ.get("DEFAULT_RAM_LIMIT_MB", 8192))
    DEFAULT_PUBLIC_EVAL_PERCENTAGE = int(os.environ.get("DEFAULT_PUBLIC_EVAL_PERCENTAGE", 30))

    # Worker utils
    WORKER_MAX_LOG_LINES = int(os.environ.get("WORKER_MAX_LOG_LINES", 10000))
    WORKER_REPORT_MAX_RETRIES = int(os.environ.get("WORKER_REPORT_MAX_RETRIES", 3))
    WORKER_REPORT_TIMEOUT = int(os.environ.get("WORKER_REPORT_TIMEOUT", 10))
    WORKER_DOWNLOAD_TIMEOUT = int(os.environ.get("WORKER_DOWNLOAD_TIMEOUT", 30))

    # Grace period (seconds) for submissions after the official deadline
    DEADLINE_GRACE_PERIOD_SECONDS = int(os.environ.get("DEADLINE_GRACE_PERIOD_SECONDS", 60))

    # Encryption key for PII fields
    ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY") or _require_env("ENCRYPTION_KEY")

    # CORS origins
    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*")

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
    API_BASE = os.environ.get("API_BASE", "http://localhost:5001/api")

    # Worker identity / tokens
    RUNNING_AS_WORKER = os.environ.get("RUNNING_AS_WORKER", "").lower() in ("1", "true", "yes")
    CELERY_WORKER_CONCURRENCY = int(os.environ.get("CELERY_WORKER_CONCURRENCY", 2))
    INTERNAL_ONLY_WORKER = os.environ.get("INTERNAL_ONLY_WORKER", "").lower() in (
        "1",
        "true",
        "yes",
    )
    EVALUATION_ONLY_WORKER = os.environ.get("EVALUATION_ONLY_WORKER", "").lower() in (
        "1",
        "true",
        "yes",
    )
    WORKER_GPU_ID = os.environ.get("WORKER_GPU_ID", "")
    WORKER_PUBLIC_KEY = os.environ.get("WORKER_PUBLIC_KEY", "")
    WORKER_PRIVATE_KEY = os.environ.get("WORKER_PRIVATE_KEY", "")

    # Worker sandbox resource allocation
    GPU_RAM_PER_TASK_GB = int(os.environ.get("GPU_RAM_PER_TASK_GB", 8))
    CPU_RAM_PER_TASK_GB = int(os.environ.get("CPU_RAM_PER_TASK_GB", 8))
    RESERVED_RAM_GB = int(os.environ.get("RESERVED_RAM_GB", 4))
    RESERVED_CPU_CORES = int(os.environ.get("RESERVED_CPU_CORES", 1))
    RAM_CLAMP_FACTOR = float(os.environ.get("RAM_CLAMP_FACTOR", 1.05))

    # Redis SSL settings
    REDIS_SSL_CA_CERTS = os.environ.get("REDIS_SSL_CA_CERTS", "")
    REDIS_SSL_CERTFILE = os.environ.get("REDIS_SSL_CERTFILE", "")
    REDIS_SSL_KEYFILE = os.environ.get("REDIS_SSL_KEYFILE", "")
    REDIS_SSL_CERT_REQS = os.environ.get("REDIS_SSL_CERT_REQS", "required")
