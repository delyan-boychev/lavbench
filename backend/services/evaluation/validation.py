"""Parquet schema validation for competitor submissions and ground truth labels."""

from __future__ import annotations

import os

import pandas as pd
from pandas.api.types import (
    infer_dtype,
    is_bool_dtype,
    is_datetime64_any_dtype,
    is_numeric_dtype,
    is_string_dtype,
)

from services.evaluation.exceptions import EvaluationError


def read_parquet_bounded(
    path: str | os.PathLike[str],
    *,
    max_file_bytes: int,
    max_uncompressed_bytes: int,
    max_rows: int,
    max_columns: int,
) -> pd.DataFrame:
    """Inspect Parquet metadata limits before materializing the frame in memory."""
    import pyarrow.parquet as pq

    try:
        file_size = os.path.getsize(path)
        parquet = pq.ParquetFile(path)
        metadata = parquet.metadata
    except Exception as exc:
        raise EvaluationError(
            "EVALUATION_INVALID_PARQUET",
            "Evaluation output is not a readable Parquet file.",
        ) from exc

    if file_size > max_file_bytes:
        raise EvaluationError(
            "EVALUATION_PARQUET_LIMIT_EXCEEDED",
            f"Parquet file exceeds the {max_file_bytes}-byte file-size limit.",
        )
    if metadata.num_rows > max_rows:
        raise EvaluationError(
            "EVALUATION_PARQUET_LIMIT_EXCEEDED",
            f"Parquet file exceeds the {max_rows}-row limit.",
        )
    if metadata.num_columns > max_columns:
        raise EvaluationError(
            "EVALUATION_PARQUET_LIMIT_EXCEEDED",
            f"Parquet file exceeds the {max_columns}-column limit.",
        )

    uncompressed_bytes = 0
    for row_group_index in range(metadata.num_row_groups):
        row_group = metadata.row_group(row_group_index)
        for column_index in range(row_group.num_columns):
            uncompressed_bytes += row_group.column(column_index).total_uncompressed_size
            if uncompressed_bytes > max_uncompressed_bytes:
                raise EvaluationError(
                    "EVALUATION_PARQUET_LIMIT_EXCEEDED",
                    "Parquet data exceeds the configured uncompressed-size limit.",
                )

    try:
        frame = parquet.read().to_pandas()
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("Parquet decoder did not return a DataFrame")
        return frame
    except Exception as exc:
        raise EvaluationError(
            "EVALUATION_INVALID_PARQUET",
            "Evaluation output could not be decoded as Parquet.",
        ) from exc


# ── 2. SCHEMA VALIDATION ENGINE ──


def validate_parquet_schema(
    df: pd.DataFrame, is_submission: bool = True
) -> tuple[bool, str | None]:
    """Validates a pandas DataFrame against the standardized schema columns."""
    is_retrieval = "query_id" in df.columns or "doc_id" in df.columns
    required = ["query_id", "doc_id"] if is_retrieval else ["id"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        role = "Submission" if is_submission else "Labels/Ground Truth"
        return (
            False,
            f"{role} parquet missing required column: {missing}. Found columns: {list(df.columns)}",
        )
    return True, None


def validate_parquet_schema_columns(
    column_names: list[str], is_submission: bool = True
) -> tuple[bool, str | None]:
    """Validates a list of column names (from pyarrow schema) against the standardized schema."""
    is_retrieval = "query_id" in column_names or "doc_id" in column_names
    required = ["query_id", "doc_id"] if is_retrieval else ["id"]
    missing = [column for column in required if column not in column_names]
    if missing:
        role = "Submission" if is_submission else "Labels/Ground Truth"
        return (
            False,
            f"{role} parquet missing required column: {missing}. Found columns: {column_names}",
        )
    return True, None


def _compatible_identifier_types(left: pd.Series, right: pd.Series) -> bool:
    """Return whether two identifier columns have compatible scalar types."""
    left_dtype = left.dtype
    right_dtype = right.dtype
    if is_bool_dtype(left_dtype) or is_bool_dtype(right_dtype):
        return is_bool_dtype(left_dtype) and is_bool_dtype(right_dtype)
    if is_numeric_dtype(left_dtype) or is_numeric_dtype(right_dtype):
        return is_numeric_dtype(left_dtype) and is_numeric_dtype(right_dtype)
    if is_datetime64_any_dtype(left_dtype) or is_datetime64_any_dtype(right_dtype):
        return is_datetime64_any_dtype(left_dtype) and is_datetime64_any_dtype(right_dtype)
    left_kind = infer_dtype(left, skipna=True)
    right_kind = infer_dtype(right, skipna=True)
    string_kinds = {"string", "unicode", "bytes"}
    if left_kind in string_kinds or right_kind in string_kinds:
        return left_kind in string_kinds and right_kind in string_kinds
    return left_kind == right_kind and is_string_dtype(left_dtype) == is_string_dtype(right_dtype)


def _validate_identifier_column(df: pd.DataFrame, column: str, role: str) -> None:
    if column not in df.columns:
        raise EvaluationError(
            "EVALUATION_MISSING_ID_COLUMN",
            f"{role} parquet is missing required identifier column '{column}'.",
        )
    if df[column].isna().any():
        raise EvaluationError(
            "EVALUATION_NULL_ID",
            f"{role} parquet contains null values in '{column}'.",
        )
    try:
        for value in df[column]:
            hash(value)
    except TypeError as exc:
        raise EvaluationError(
            "EVALUATION_INVALID_ID",
            f"{role} parquet contains a non-scalar value in '{column}'.",
        ) from exc


def _validate_unique(df: pd.DataFrame, columns: list[str], role: str) -> None:
    if df.duplicated(subset=columns).any():
        joined = ", ".join(columns)
        raise EvaluationError(
            "EVALUATION_DUPLICATE_ID",
            f"{role} parquet contains duplicate identifier values for {joined}.",
        )


def _validate_type_pair(df_sub: pd.DataFrame, df_labels: pd.DataFrame, column: str) -> None:
    if not _compatible_identifier_types(df_sub[column], df_labels[column]):
        raise EvaluationError(
            "EVALUATION_ID_TYPE_MISMATCH",
            f"Submission and labels use incompatible types for '{column}'.",
        )


def validate_evaluation_frames(
    df_sub: pd.DataFrame, df_labels: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Validate identifiers and return deterministically aligned evaluation frames."""
    retrieval = "query_id" in df_labels.columns
    if retrieval:
        for role, frame in (("Submission", df_sub), ("Labels", df_labels)):
            _validate_identifier_column(frame, "query_id", role)
            _validate_identifier_column(frame, "doc_id", role)
            _validate_unique(frame, ["query_id", "doc_id"], role)
        submission_queries = set(df_sub["query_id"].tolist())
        label_queries = set(df_labels["query_id"].tolist())
        if bool(df_sub.empty) != bool(df_labels.empty):
            raise EvaluationError(
                "EVALUATION_QUERY_SET_MISMATCH",
                "Submission query IDs must exactly match the ground-truth query IDs.",
            )
        _validate_type_pair(df_sub, df_labels, "query_id")
        _validate_type_pair(df_sub, df_labels, "doc_id")
        if submission_queries != label_queries:
            raise EvaluationError(
                "EVALUATION_QUERY_SET_MISMATCH",
                "Submission query IDs must exactly match the ground-truth query IDs.",
            )
        return df_sub.copy(), df_labels.copy()

    for role, frame in (("Submission", df_sub), ("Labels", df_labels)):
        _validate_identifier_column(frame, "id", role)
        _validate_unique(frame, ["id"], role)
    submission_ids = set(df_sub["id"].tolist())
    label_ids = set(df_labels["id"].tolist())
    if bool(df_sub.empty) != bool(df_labels.empty):
        raise EvaluationError(
            "EVALUATION_ID_SET_MISMATCH",
            "Submission IDs must exactly match the ground-truth IDs.",
        )
    _validate_type_pair(df_sub, df_labels, "id")
    if submission_ids != label_ids:
        raise EvaluationError(
            "EVALUATION_ID_SET_MISMATCH",
            "Submission IDs must exactly match the ground-truth IDs.",
        )

    labels_aligned = df_labels.set_index("id", drop=False)
    submission_aligned = df_sub.set_index("id", drop=False).loc[labels_aligned.index]
    return submission_aligned.reset_index(drop=True), labels_aligned.reset_index(drop=True)
