"""nanoColab environments and workspaces; task folder name

Revision ID: 20261116_02
Revises: 20261116_01
Create Date: 2026-11-16 12:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from models.base import GUID

revision: str = "20261116_02"
down_revision: str | Sequence[str] | None = "20261116_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the environment and workspace tables and Task.folder_name."""
    op.create_table(
        "environments",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("stage_id", GUID(), nullable=True),
        sa.Column("challenge_id", GUID(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("auto_publish", sa.Boolean(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("compute_kind", sa.String(length=8), nullable=False),
        sa.Column("cpu_cores", sa.Integer(), nullable=False),
        sa.Column("memory_gib", sa.Integer(), nullable=False),
        sa.Column("disk_gib", sa.Integer(), nullable=False),
        sa.Column("gpu_type", sa.String(length=100), nullable=True),
        sa.Column("image_id", sa.String(length=63), nullable=False),
        sa.Column("image_digest", sa.String(length=500), nullable=True),
        sa.Column("archive_until", sa.DateTime(), nullable=True),
        sa.Column("max_attendance", sa.Integer(), nullable=True),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("asset_version", sa.String(length=100), nullable=True),
        sa.Column("package_state", sa.String(length=16), nullable=False),
        sa.Column("package_progress", sa.Integer(), nullable=False),
        sa.Column("package_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("package_error_code", sa.String(length=64), nullable=True),
        sa.Column("package_error", sa.String(length=500), nullable=True),
        sa.Column("package_error_limit", sa.String(length=32), nullable=True),
        sa.Column("event_id", sa.String(length=64), nullable=True),
        sa.Column("sync_error", sa.String(length=500), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "(stage_id IS NULL) != (challenge_id IS NULL)", name="ck_environment_one_owner"
        ),
        sa.ForeignKeyConstraint(["challenge_id"], ["challenges.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stage_id"], ["stages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("challenge_id"),
        sa.UniqueConstraint("stage_id"),
    )
    op.create_table(
        "workspaces",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("environment_id", GUID(), nullable=False),
        sa.Column("user_id", GUID(), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_launched_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["environment_id"], ["environments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("environment_id", "user_id", name="uq_workspace_environment_user"),
    )
    op.create_index(
        op.f("ix_workspaces_environment_id"), "workspaces", ["environment_id"], unique=False
    )
    op.create_index(op.f("ix_workspaces_user_id"), "workspaces", ["user_id"], unique=False)
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(sa.Column("folder_name", sa.String(length=40), nullable=True))
        batch_op.add_column(
            sa.Column("folder_name_custom", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    """Drop Task.folder_name and the environment and workspace tables."""
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_column("folder_name_custom")
        batch_op.drop_column("folder_name")
    op.drop_index(op.f("ix_workspaces_user_id"), table_name="workspaces")
    op.drop_index(op.f("ix_workspaces_environment_id"), table_name="workspaces")
    op.drop_table("workspaces")
    op.drop_table("environments")
