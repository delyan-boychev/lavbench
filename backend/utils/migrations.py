"""Database migration and schema compatibility helpers."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config as AlembicConfig
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text

from config import Config
from models import db

logger = logging.getLogger(__name__)

BASELINE_REVISION = "20260829_01"
MIGRATION_LOCK_ID = 727376317
_EXPRESSION_INDEXES = {
    "idx_sub_challenge_created",
    "idx_sub_task_created",
    "idx_sub_task_user_created",
}


def migration_config(database_url: str | None = None) -> AlembicConfig:
    """Build an Alembic configuration for the current database."""
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    alembic_config = AlembicConfig(os.path.join(backend_dir, "alembic.ini"))
    alembic_config.set_main_option(
        "sqlalchemy.url", (database_url or Config.SQLALCHEMY_DATABASE_URI).replace("%", "%%")
    )
    return alembic_config


def expected_database_heads(alembic_config: AlembicConfig | None = None) -> set[str]:
    """Return the revision heads shipped with this application build."""
    config = alembic_config or migration_config()
    return set(ScriptDirectory.from_config(config).get_heads())


def current_database_heads(connection: object) -> set[str]:
    """Return the revisions recorded by the connected database."""
    return set(MigrationContext.configure(connection).get_current_heads())  # type: ignore[arg-type]


def verify_database_revision(engine: Engine) -> None:
    """Refuse to serve when PostgreSQL is not at the application revision."""
    if engine.dialect.name != "postgresql":
        return
    with engine.connect() as connection:
        current = current_database_heads(connection)
    expected = expected_database_heads()
    if current != expected:
        current_label = ", ".join(sorted(current)) or "unversioned"
        expected_label = ", ".join(sorted(expected)) or "none"
        msg = (
            f"Database revision is {current_label}; expected {expected_label}. "
            "Run 'python scripts/migrate.py' before starting the application."
        )
        raise RuntimeError(msg)


def _format_differences(differences: Iterable[object]) -> str:
    values = [str(difference) for difference in differences]
    preview = "; ".join(values[:5])
    if len(values) > 5:
        preview += f"; and {len(values) - 5} more"
    return preview


def _is_expression_index_rendering_difference(difference: object) -> bool:
    """Ignore dialect-specific reflection noise for known descending indexes."""
    if not isinstance(difference, tuple) or len(difference) < 2:
        return False
    if difference[0] not in {"add_index", "remove_index"}:
        return False
    return getattr(difference[1], "name", None) in _EXPRESSION_INDEXES


def _adopt_legacy_schema(engine: Engine, alembic_config: AlembicConfig) -> None:
    """Stamp an exact pre-Alembic schema at the baseline revision."""
    with engine.connect() as connection:
        existing_tables = set(inspect(connection).get_table_names())
        application_tables = set(db.metadata.tables)
        if not existing_tables.intersection(application_tables):
            return
        raw_differences = compare_metadata(
            MigrationContext.configure(connection, opts={"compare_type": True}), db.metadata
        )
        differences = [
            difference
            for difference in raw_differences
            if not _is_expression_index_rendering_difference(difference)
        ]
        reflected_indexes = (
            {index["name"] for index in inspect(connection).get_indexes("submissions")}
            if "submissions" in existing_tables
            else set()
        )
        missing_expression_indexes = (
            _EXPRESSION_INDEXES - reflected_indexes if "submissions" in existing_tables else set()
        )
        differences.extend(
            f"missing index {index_name}" for index_name in sorted(missing_expression_indexes)
        )
    if differences:
        details = _format_differences(differences)
        msg = (
            f"Existing unversioned database does not match the LavBench baseline schema: {details}"
        )
        raise RuntimeError(msg)
    logger.info("Adopting compatible pre-Alembic database at revision %s", BASELINE_REVISION)
    command.stamp(alembic_config, BASELINE_REVISION)


def migrate_database(engine: Engine) -> None:
    """Adopt a compatible legacy schema and upgrade it to the latest revision."""
    alembic_config = migration_config(str(engine.url))
    lock_connection = engine.connect()
    try:
        if engine.dialect.name == "postgresql":
            lock_connection.execute(
                text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK_ID}
            )
        with engine.connect() as connection:
            current = current_database_heads(connection)
        if not current:
            _adopt_legacy_schema(engine, alembic_config)
        command.upgrade(alembic_config, "head")
        verify_database_revision(engine)
    finally:
        if engine.dialect.name == "postgresql":
            lock_connection.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_ID}
            )
        lock_connection.close()
