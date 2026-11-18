"""single admin account

Revision ID: 20261118_03
Revises: 20261118_02
Create Date: 2026-11-18 21:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261118_03"
down_revision: str | Sequence[str] | None = "20261118_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow at most one row with the admin role."""
    op.create_index(
        "uq_users_single_admin",
        "users",
        ["role"],
        unique=True,
        postgresql_where=sa.text("role = 'admin'"),
        sqlite_where=sa.text("role = 'admin'"),
    )


def downgrade() -> None:
    """Drop the single-admin index."""
    op.drop_index("uq_users_single_admin", table_name="users")
