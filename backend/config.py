import os
import sys
from dotenv import load_dotenv

# Load environment variables from .env in workspace root
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

def _require_env(key, message=None):
    val = os.environ.get(key)
    if not val:
        msg = message or f"Required environment variable '{key}' is not set."
        print(f"FATAL: {msg}", file=sys.stderr)
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
    
    # Upload folder
    UPLOAD_FOLDER = os.path.join(os.path.abspath(os.path.dirname(__file__)), "uploads")
    MAX_CONTENT_LENGTH = 150 * 1024 * 1024  # 150 MB limit
    
    # Hugging Face Settings
    HF_CACHE_DIR = os.environ.get("HF_CACHE_DIR", os.path.join(os.path.abspath(os.path.dirname(__file__)), "hf_cache"))
    
    # SQLAlchemy connection pool settings (only for PostgreSQL)
    SQLALCHEMY_ENGINE_OPTIONS = {}
    if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith("postgresql"):
        SQLALCHEMY_ENGINE_OPTIONS = {
            'pool_size': 30,
            'pool_timeout': 30,
            'max_overflow': 60,
            'pool_pre_ping': True,
            'pool_recycle': 600
        }
    
    # Grace period (seconds) for submissions after the official deadline
    DEADLINE_GRACE_PERIOD_SECONDS = int(os.environ.get("DEADLINE_GRACE_PERIOD_SECONDS", 60))
