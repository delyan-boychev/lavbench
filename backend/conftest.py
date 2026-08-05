"""Pytest entry shim: env bootstrap must run BEFORE the config/ package import.

Importing ``config.conftest`` would first execute ``config/__init__.py``, which
requires these variables to be present. Fixtures live in ``config/conftest.py``.
"""

import os

# ── Critical: set these BEFORE any app/config/model imports ───────────────
os.environ.setdefault(
    "SECRET_KEY", "conftest-test-secret-key-2024-abcdefgh"
)  # 32+ chars for HMAC-SHA256
os.environ.setdefault("ENCRYPTION_KEY", "tVG8-i368hyvsKNRoBKqZIXuExByVbQgKrUHKvqNFis=")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"  # Force isolation — never touch the dev DB
os.environ["LOG_DIR"] = "/tmp/nai-test-logs"

from config.conftest import *  # noqa: F403
