"""audit log points as float

Revision ID: 20261119_02
Revises: 20261119_01
Create Date: 2026-11-19 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261119_02"
down_revision: str | Sequence[str] | None = "20261119_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Keep the decimals of manual points in the audit log."""
    with op.batch_alter_table("audit_logs") as batch_op:
        batch_op.alter_column("old_score", existing_type=sa.Integer(), type_=sa.Float())
        batch_op.alter_column("new_score", existing_type=sa.Integer(), type_=sa.Float())


def downgrade() -> None:
    """Store whole points again."""
    with op.batch_alter_table("audit_logs") as batch_op:
        batch_op.alter_column("old_score", existing_type=sa.Float(), type_=sa.Integer())
        batch_op.alter_column("new_score", existing_type=sa.Float(), type_=sa.Integer())
