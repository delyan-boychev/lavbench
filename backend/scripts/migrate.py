"""Adopt and upgrade the LavBench database schema."""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from utils.migrations import migrate_database


def main() -> None:
    """Upgrade the configured database and fail on incompatible legacy schemas."""
    if not Config.SQLALCHEMY_DATABASE_URI:
        msg = "DATABASE_URL must be configured before running migrations"
        raise RuntimeError(msg)
    engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
    try:
        migrate_database(engine)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
