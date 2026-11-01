"""stage compute, workspaces and workspace exports

Revision ID: 20261101_01
Revises: 20260829_01
Create Date: 2026-11-01 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from models.base import GUID

revision: str = "20261101_01"
down_revision: str | Sequence[str] | None = "20260829_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the schema revision."""
    op.add_column(
        "tasks", sa.Column("workspace_submission_path", sa.String(length=512), nullable=True)
    )
    op.add_column(
        "tasks", sa.Column("workspace_notebook_path", sa.String(length=512), nullable=True)
    )
    op.create_table(
        "stage_compute",
        sa.Column("stage_id", GUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("compute_kind", sa.String(length=8), nullable=False),
        sa.Column("cpu_cores", sa.Integer(), nullable=False),
        sa.Column("memory_gib", sa.Integer(), nullable=False),
        sa.Column("disk_gib", sa.Integer(), nullable=False),
        sa.Column("gpu_type", sa.String(length=100), nullable=True),
        sa.Column("image_id", sa.String(length=63), nullable=False),
        sa.Column("image_digest", sa.String(length=500), nullable=False),
        sa.Column("asset_version", sa.String(length=100), nullable=False),
        sa.Column("package_state", sa.String(length=16), nullable=False),
        sa.Column("package_error", sa.String(length=255), nullable=True),
        sa.Column("package_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("max_attendance", sa.Integer(), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("nanocolab_event_id", sa.String(length=64), nullable=True),
        sa.Column("sync_state", sa.String(length=16), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("last_sync_error", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["stage_id"], ["stages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("stage_id"),
    )
    op.create_table(
        "stage_workspaces",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("stage_id", GUID(), nullable=False),
        sa.Column("user_id", GUID(), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["stage_id"], ["stages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stage_id", "user_id", name="uq_stage_workspace_user"),
    )
    op.create_index(
        op.f("ix_stage_workspaces_stage_id"), "stage_workspaces", ["stage_id"], unique=False
    )
    op.create_index(
        op.f("ix_stage_workspaces_user_id"), "stage_workspaces", ["user_id"], unique=False
    )
    op.create_table(
        "workspace_exports",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("user_id", GUID(), nullable=False),
        sa.Column("task_id", GUID(), nullable=False),
        sa.Column("stage_id", GUID(), nullable=False),
        sa.Column("submission_id", GUID(), nullable=True),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("exported_at", sa.DateTime(), nullable=False),
        sa.Column("csv_path", sa.String(length=512), nullable=False),
        sa.Column("csv_sha256", sa.String(length=64), nullable=False),
        sa.Column("csv_size", sa.Integer(), nullable=False),
        sa.Column("notebook_path", sa.String(length=512), nullable=True),
        sa.Column("notebook_sha256", sa.String(length=64), nullable=True),
        sa.Column("notebook_size", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stage_id"], ["stages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_workspace_exports_user_id"), "workspace_exports", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_workspace_exports_task_id"), "workspace_exports", ["task_id"], unique=False
    )


def downgrade() -> None:
    """Revert the schema revision."""
    op.drop_index(op.f("ix_workspace_exports_task_id"), table_name="workspace_exports")
    op.drop_index(op.f("ix_workspace_exports_user_id"), table_name="workspace_exports")
    op.drop_table("workspace_exports")
    op.drop_index(op.f("ix_stage_workspaces_user_id"), table_name="stage_workspaces")
    op.drop_index(op.f("ix_stage_workspaces_stage_id"), table_name="stage_workspaces")
    op.drop_table("stage_workspaces")
    op.drop_table("stage_compute")
    op.drop_column("tasks", "workspace_notebook_path")
    op.drop_column("tasks", "workspace_submission_path")
