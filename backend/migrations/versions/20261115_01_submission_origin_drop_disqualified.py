"""submission origin; drop is_disqualified

Revision ID: 20261115_01
Revises: 20260829_01
Create Date: 2026-11-15 02:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261115_01"
down_revision: str | Sequence[str] | None = "20260829_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add Submission.origin and drop the never-used disqualification flag."""
    with op.batch_alter_table("submissions") as batch_op:
        batch_op.add_column(sa.Column("origin", sa.String(length=16), nullable=True))
        batch_op.drop_column("is_disqualified")


def downgrade() -> None:
    """Restore the disqualification flag and drop Submission.origin."""
    with op.batch_alter_table("submissions") as batch_op:
        batch_op.add_column(sa.Column("is_disqualified", sa.Boolean(), nullable=True))
        batch_op.drop_column("origin")
