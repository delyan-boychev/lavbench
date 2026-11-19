"""submission finished_at

Revision ID: 20261119_01
Revises: 20261118_03
Create Date: 2026-11-19 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261119_01"
down_revision: str | Sequence[str] | None = "20261118_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Record when a run reached a terminal status."""
    with op.batch_alter_table("submissions") as batch_op:
        batch_op.add_column(sa.Column("finished_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Drop the finish time."""
    with op.batch_alter_table("submissions") as batch_op:
        batch_op.drop_column("finished_at")
