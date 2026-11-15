"""Database migration helpers: upgrade to head and verify the revision."""

from __future__ import annotations

import logging
import os

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

from config import Config

logger = logging.getLogger(__name__)

MIGRATION_LOCK_ID = 727376317


def migration_config(database_url: str | None = None) -> AlembicConfig:
    """Build an Alembic configuration for the current database."""
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    alembic_config = AlembicConfig(os.path.join(backend_dir, "alembic.ini"))
    alembic_config.set_main_option(
        "sqlalchemy.url", (database_url or Config.SQLALCHEMY_DATABASE_URI).replace("%", "%%")
    )
    return alembic_config


def _render_database_url(engine: Engine) -> str:
    """Render the connection URL without SQLAlchemy masking its password."""
    return engine.url.render_as_string(hide_password=False)


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


def migrate_database(engine: Engine) -> None:
    """Upgrade the database to the latest revision under an advisory lock."""
    alembic_config = migration_config(_render_database_url(engine))
    lock_connection = engine.connect()
    try:
        if engine.dialect.name == "postgresql":
            lock_connection.execute(
                text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK_ID}
            )
        command.upgrade(alembic_config, "head")
        verify_database_revision(engine)
    finally:
        if engine.dialect.name == "postgresql":
            lock_connection.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_ID}
            )
        lock_connection.close()
