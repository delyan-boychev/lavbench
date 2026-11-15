"""submission infra_retry_count

Revision ID: 20261116_01
Revises: 20261115_01
Create Date: 2026-11-16 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261116_01"
down_revision: str | Sequence[str] | None = "20261115_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Count how often a submission was requeued after a platform failure."""
    with op.batch_alter_table("submissions") as batch_op:
        batch_op.add_column(
            sa.Column("infra_retry_count", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    """Drop the platform-failure retry counter."""
    with op.batch_alter_table("submissions") as batch_op:
        batch_op.drop_column("infra_retry_count")
