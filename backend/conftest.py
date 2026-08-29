"""Pytest entry shim: env bootstrap must run BEFORE the config/ package import.

Importing ``config.conftest`` would first execute ``config/__init__.py``, which
requires these variables to be present. Fixtures live in ``config/conftest.py``.
"""

import os
from urllib.parse import urlsplit, urlunsplit

# ── Critical: set these BEFORE any app/config/model imports ───────────────
os.environ.setdefault(
    "SECRET_KEY", "conftest-test-secret-key-2024-abcdefgh"
)  # 32+ chars for HMAC-SHA256
os.environ.setdefault("ENCRYPTION_KEY", "tVG8-i368hyvsKNRoBKqZIXuExByVbQgKrUHKvqNFis=")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"  # Force isolation — never touch the dev DB
os.environ["LOG_DIR"] = "/tmp/nai-test-logs"

# Keep xdist workers isolated without touching the developer's default Redis database
_worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
_worker_number = _worker_id.removeprefix("gw")
_redis_database = min(int(_worker_number) + 1, 15) if _worker_number.isdigit() else 15
_redis_parts = urlsplit(os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"))
_test_redis_url = urlunsplit(_redis_parts._replace(path=f"/{_redis_database}"))
os.environ["CELERY_BROKER_URL"] = _test_redis_url
os.environ["CELERY_RESULT_BACKEND"] = _test_redis_url
os.environ["CACHE_REDIS_URL"] = _test_redis_url

from config.conftest import *  # noqa: E402, F403
