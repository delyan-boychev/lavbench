"""task hugging face zip

Revision ID: 20261118_02
Revises: 20261118_01
Create Date: 2026-11-18 18:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261118_02"
down_revision: str | Sequence[str] | None = "20261118_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replace the Hugging Face repo lists and API key with one ZIP per task."""
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_column("hf_datasets")
        batch_op.drop_column("hf_models")
        batch_op.drop_column("hf_api_key")
        batch_op.add_column(sa.Column("hf_zip_sha256", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("hf_zip_size", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("hf_unpacked_bytes", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("hf_file_count", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("hf_folders", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("hf_skipped_count", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "hf_zip_not_imported", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch_op.add_column(sa.Column("problem_fields", sa.JSON(), nullable=True))
    with op.batch_alter_table("submissions") as batch_op:
        batch_op.add_column(sa.Column("hf_zip_sha256", sa.String(length=64), nullable=True))
    with op.batch_alter_table("environments") as batch_op:
        batch_op.drop_column("package_error_limit")
        batch_op.add_column(sa.Column("package_error_fields", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Restore the repo list and API key columns, empty."""
    with op.batch_alter_table("environments") as batch_op:
        batch_op.drop_column("package_error_fields")
        batch_op.add_column(sa.Column("package_error_limit", sa.String(length=32), nullable=True))
    with op.batch_alter_table("submissions") as batch_op:
        batch_op.drop_column("hf_zip_sha256")
    with op.batch_alter_table("tasks") as batch_op:
        for column in (
            "problem_fields",
            "hf_zip_not_imported",
            "hf_skipped_count",
            "hf_folders",
            "hf_file_count",
            "hf_unpacked_bytes",
            "hf_zip_size",
            "hf_zip_sha256",
        ):
            batch_op.drop_column(column)
        batch_op.add_column(sa.Column("hf_api_key", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("hf_models", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("hf_datasets", sa.JSON(), nullable=True))
