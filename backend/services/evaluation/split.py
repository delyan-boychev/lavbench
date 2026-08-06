"""Secret-keyed public/private evaluation splitting."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from services.evaluation.exceptions import EvaluationError
from services.evaluation.validation import validate_evaluation_frames


def derive_task_split_key(secret: str, task_id: Any) -> str:
    """Derive a task-scoped key without disclosing the root split secret."""
    if not secret:
        raise EvaluationError(
            "EVALUATION_SPLIT_SECRET_MISSING",
            "Evaluation split secret is not configured.",
        )
    return hmac.new(secret.encode(), str(task_id).encode(), hashlib.sha256).hexdigest()


def _identifier_bytes(value: Any) -> bytes:
    """Serialize scalar identifiers with a type tag for stable HMAC ordering."""
    if isinstance(value, np.datetime64):
        canonical = pd.Timestamp(value).isoformat()
        return f"datetime:{canonical}".encode()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, (pd.Timestamp, datetime, date)):
        canonical = pd.Timestamp(value).isoformat()
        return f"datetime:{canonical}".encode()
    try:
        serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise EvaluationError(
            "EVALUATION_INVALID_ID",
            f"Evaluation identifier {value!r} is not a supported scalar value.",
        ) from exc
    return f"{type(value).__name__}:{serialized}".encode()


def _public_identifiers(values: list[Any], percentage: int, task_split_key: str) -> set[Any]:
    if not 0 <= percentage <= 100:
        raise EvaluationError(
            "EVALUATION_INVALID_SPLIT",
            "Public evaluation percentage must be between 0 and 100.",
        )
    try:
        key = bytes.fromhex(task_split_key)
    except ValueError as exc:
        raise EvaluationError(
            "EVALUATION_INVALID_SPLIT_KEY",
            "Task evaluation split key is invalid.",
        ) from exc
    if len(key) != hashlib.sha256().digest_size:
        raise EvaluationError(
            "EVALUATION_INVALID_SPLIT_KEY",
            "Task evaluation split key is invalid.",
        )

    ordered = sorted(
        values,
        key=lambda value: hmac.new(key, _identifier_bytes(value), hashlib.sha256).digest(),
    )
    count = int(len(ordered) * (percentage / 100.0))
    count = max(0, min(count, len(ordered)))
    if count == 0 and ordered and percentage > 0:
        count = 1
    return set(ordered[:count])


def split_evaluation_frames(
    df_sub: pd.DataFrame,
    df_labels: pd.DataFrame,
    public_percentage: int,
    task_split_key: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Validate inputs and split them using an unpredictable stable ordering."""
    df_sub, df_labels = validate_evaluation_frames(df_sub, df_labels)
    retrieval = "query_id" in df_labels.columns
    split_column = "query_id" if retrieval else "id"
    identifiers = df_labels[split_column].drop_duplicates().tolist()
    public_ids = _public_identifiers(identifiers, public_percentage, task_split_key)
    labels_public = df_labels[df_labels[split_column].isin(public_ids)].copy()
    labels_private = df_labels[~df_labels[split_column].isin(public_ids)].copy()
    sub_public = df_sub[df_sub[split_column].isin(public_ids)].copy()
    sub_private = df_sub[~df_sub[split_column].isin(public_ids)].copy()
    return sub_public, labels_public, sub_private, labels_private
