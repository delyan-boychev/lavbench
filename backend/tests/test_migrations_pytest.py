"""Tests for database migration bootstrap and legacy schema adoption."""

from __future__ import annotations

import pytest
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from models import db
from utils.migrations import BASELINE_REVISION, migrate_database


def _sqlite_engine(tmp_path, name):
    return create_engine(f"sqlite:///{tmp_path / name}")


def test_migrate_database_creates_fresh_schema(tmp_path):
    engine = _sqlite_engine(tmp_path, "fresh.db")

    migrate_database(engine)

    with engine.connect() as connection:
        revision = MigrationContext.configure(connection).get_current_revision()
        tables = set(inspect(connection).get_table_names())
    assert revision == BASELINE_REVISION
    assert set(db.metadata.tables) <= tables
    engine.dispose()


def test_migrate_database_adopts_matching_legacy_schema(tmp_path):
    engine = _sqlite_engine(tmp_path, "legacy.db")
    db.metadata.create_all(engine)

    migrate_database(engine)

    with engine.connect() as connection:
        revision = MigrationContext.configure(connection).get_current_revision()
    assert revision == BASELINE_REVISION
    engine.dispose()


def test_migrate_database_rejects_incompatible_legacy_schema(tmp_path):
    engine = _sqlite_engine(tmp_path, "incompatible.db")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE challenges (id VARCHAR(36) PRIMARY KEY)"))

    with pytest.raises(RuntimeError, match="does not match"):
        migrate_database(engine)

    assert "alembic_version" not in inspect(engine).get_table_names()
    engine.dispose()
