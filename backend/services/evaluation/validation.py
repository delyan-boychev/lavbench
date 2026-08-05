"""Parquet schema validation for competitor submissions and ground truth labels."""

from __future__ import annotations

import pandas as pd

# ── 2. SCHEMA VALIDATION ENGINE ──


def validate_parquet_schema(
    df: pd.DataFrame, is_submission: bool = True
) -> tuple[bool, str | None]:
    """Validates a pandas DataFrame against the standardized schema columns."""
    if "id" not in df.columns:
        role = "Submission" if is_submission else "Labels/Ground Truth"
        return (
            False,
            f"{role} parquet missing required column: ['id']. Found columns: {list(df.columns)}",
        )
    return True, None


def validate_parquet_schema_columns(
    column_names: list[str], is_submission: bool = True
) -> tuple[bool, str | None]:
    """Validates a list of column names (from pyarrow schema) against the standardized schema."""
    if "id" not in column_names:
        role = "Submission" if is_submission else "Labels/Ground Truth"
        return (
            False,
            f"{role} parquet missing required column: ['id']. Found columns: {column_names}",
        )
    return True, None
