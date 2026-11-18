"""task evaluation mode and submission files

Revision ID: 20261118_01
Revises: 20261117_01
Create Date: 2026-11-18 10:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261118_01"
down_revision: str | Sequence[str] | None = "20261117_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add Task.evaluation_mode, the emergency upload switch and the submission file columns."""
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(
            sa.Column(
                "evaluation_mode", sa.String(length=16), nullable=False, server_default="notebook"
            )
        )
        batch_op.add_column(
            sa.Column(
                "emergency_upload_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
    with op.batch_alter_table("submissions") as batch_op:
        batch_op.add_column(sa.Column("artifact_path", sa.String(length=512), nullable=True))
        batch_op.add_column(sa.Column("artifact_sha256", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("artifact_size", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("notebook_path", sa.String(length=512), nullable=True))
        batch_op.add_column(sa.Column("notebook_sha256", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("workspace_meta", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Drop the submission file columns, the emergency switch and Task.evaluation_mode."""
    with op.batch_alter_table("submissions") as batch_op:
        for column in (
            "workspace_meta",
            "notebook_sha256",
            "notebook_path",
            "artifact_size",
            "artifact_sha256",
            "artifact_path",
        ):
            batch_op.drop_column(column)
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_column("emergency_upload_enabled")
        batch_op.drop_column("evaluation_mode")
