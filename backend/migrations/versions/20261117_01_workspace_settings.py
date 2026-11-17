"""Competition workspace setting and the environment's work space size

Revision ID: 20261117_01
Revises: 20261116_02
Create Date: 2026-11-17 18:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from models.base import GUID

revision: str = "20261117_01"
down_revision: str | Sequence[str] | None = "20261116_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the workspace_settings table and Environment.workspace_gib."""
    op.create_table(
        "workspace_settings",
        sa.Column("challenge_id", GUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("auto_publish", sa.Boolean(), nullable=False),
        sa.Column("image_id", sa.String(length=63), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("cpu_cores", sa.Integer(), nullable=False),
        sa.Column("memory_gib", sa.Integer(), nullable=False),
        sa.Column("workspace_gib", sa.Integer(), nullable=False),
        sa.Column("archive_until", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["challenge_id"], ["challenges.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("challenge_id"),
    )
    with op.batch_alter_table("environments") as batch_op:
        batch_op.add_column(
            sa.Column("workspace_gib", sa.Integer(), nullable=False, server_default="10")
        )


def downgrade() -> None:
    """Drop Environment.workspace_gib and the workspace_settings table."""
    with op.batch_alter_table("environments") as batch_op:
        batch_op.drop_column("workspace_gib")
    op.drop_table("workspace_settings")
