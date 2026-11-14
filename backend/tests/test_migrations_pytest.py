"""Tests for the migration runner and for drift between the revisions and the models."""

from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from models import db
from utils.migrations import _render_database_url, expected_database_heads, migrate_database

# SQLite reflects these descending expression indexes differently from how the models
# declare them, so autogenerate reports a spurious add/remove pair for each
_EXPRESSION_INDEXES = {
    "idx_sub_challenge_created",
    "idx_sub_task_created",
    "idx_sub_task_user_created",
}


def _sqlite_engine(tmp_path, name):
    return create_engine(f"sqlite:///{tmp_path / name}")


def _is_expression_index_noise(difference: object) -> bool:
    if not isinstance(difference, tuple) or len(difference) < 2:
        return False
    if difference[0] not in {"add_index", "remove_index"}:
        return False
    return getattr(difference[1], "name", None) in _EXPRESSION_INDEXES


def test_migrate_database_creates_fresh_schema_at_head(tmp_path):
    engine = _sqlite_engine(tmp_path, "fresh.db")

    migrate_database(engine)

    with engine.connect() as connection:
        heads = set(MigrationContext.configure(connection).get_current_heads())
        tables = set(inspect(connection).get_table_names())
    assert heads == expected_database_heads()
    assert set(db.metadata.tables) <= tables
    engine.dispose()


def test_migrate_database_is_idempotent(tmp_path):
    engine = _sqlite_engine(tmp_path, "twice.db")

    migrate_database(engine)
    migrate_database(engine)

    with engine.connect() as connection:
        heads = set(MigrationContext.configure(connection).get_current_heads())
    assert heads == expected_database_heads()
    engine.dispose()


def test_revisions_at_head_match_the_models(tmp_path):
    engine = _sqlite_engine(tmp_path, "drift.db")
    migrate_database(engine)

    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = [
            difference
            for difference in compare_metadata(context, db.metadata)
            if not _is_expression_index_noise(difference)
        ]
        indexes = {index["name"] for index in inspect(connection).get_indexes("submissions")}
    engine.dispose()

    assert differences == [], (
        f"The models differ from the migrations at head; add an Alembic revision: {differences}"
    )
    assert indexes >= _EXPRESSION_INDEXES


def test_migration_url_preserves_database_password():
    engine = create_engine("postgresql://lavbench:secret-password@db:5432/lavbench")

    assert _render_database_url(engine) == "postgresql://lavbench:secret-password@db:5432/lavbench"
    engine.dispose()
