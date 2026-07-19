"""Comprehensive custom evaluator template covering all edge cases.

This template serves as a reference for implementing robust custom evaluators.
It demonstrates proper handling of:
  - Column validation and missing columns
  - Data type coercion (numpy arrays, lists, None)
  - Missing/null values
  - ID mismatches between submission and labels
  - Empty submissions
  - Malformed data
  - Options validation with defaults
  - Score edge cases (all pass, all fail, partial)
  - Truncated data (actions exceeding limits)
  - Aggregate statistics logging
  - JSON-serializable return values

Replace METRIC_NAME, SUBMISSION_COLUMNS, LABELS_COLUMNS, EVALUATOR_OPTIONS
and the evaluate() body with your task-specific logic.
"""

METRIC_NAME = "custom_metric"

SUBMISSION_COLUMNS = [
    {"name": "id", "type": "string"},
    {"name": "predictions", "type": "list[float]"},
]

LABELS_COLUMNS = [
    {"name": "id", "type": "string"},
    {"name": "target", "type": "float"},
    {"name": "metadata", "type": "string"},
]

EVALUATOR_OPTIONS = {
    "threshold": 0.5,
    "max_items": 1000,
}


def _coerce_list(value):
    """Safely convert a value to a Python list.

    Handles numpy arrays, tuples, None, scalars, and pandas extensions.
    """
    import numpy as np

    if value is None:
        return []
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (list, tuple)):
        return list(value)
    if hasattr(value, "to_list"):
        return value.to_list()
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, (int, float, str, bool)):
        return [value]
    return list(value)


def _validate_columns(df, required, label="DataFrame"):
    """Check required columns exist and return missing list."""
    missing = [c["name"] for c in required if c["name"] not in df.columns]
    if missing:
        raise ValueError(
            f"{label} missing required columns: {missing}. "
            f"Available: {list(df.columns)}"
        )
    return True


def _get_option(opts, key, default):
    """Safely read an option with type-appropriate default."""
    if opts is None:
        return default
    value = opts.get(key, default)
    if value is None:
        return default
    try:
        return type(default)(value)
    except (TypeError, ValueError):
        return default


def _warn(msg, *args):
    """Emit a warning log once."""
    import logging
    logging.getLogger(__name__).warning(msg, *args)


def evaluate(df_sub, df_labels, options=None):
    import numpy as np
    import math

    # --- 1. Options with safe defaults ---
    opts = options or {}
    threshold = _get_option(opts, "threshold", 0.5)
    max_items = _get_option(opts, "max_items", 1000)

    # --- 2. Column validation ---
    _validate_columns(df_sub, SUBMISSION_COLUMNS, "Submission")
    _validate_columns(df_labels, LABELS_COLUMNS, "Labels")

    # --- 3. Align IDs (intersection) ---
    sub_ids = set(df_sub["id"].tolist())
    label_ids = set(df_labels["id"].tolist())
    ids = sorted(sub_ids & label_ids)

    missing_in_labels = sub_ids - label_ids
    missing_in_sub = label_ids - sub_ids
    if missing_in_labels:
        _warn("%d submission IDs not found in labels (ignored)", len(missing_in_labels))
    if missing_in_sub:
        _warn("%d label IDs not found in submission (ignored)", len(missing_in_sub))

    if not ids:
        return {
            METRIC_NAME: 0.0,
            "n_evaluated": 0,
            "n_skipped": 0,
            "error": "no matching IDs between submission and labels",
        }

    # --- 4. Iterate over scenarios ---
    scores = []
    skipped = 0
    n_truncated = 0

    for sid in ids[:max_items]:
        try:
            sub_row = df_sub[df_sub["id"] == sid].iloc[0]
            label_row = df_labels[df_labels["id"] == sid].iloc[0]
        except IndexError:
            skipped += 1
            continue

        # --- 5. Coerce list-typed columns ---
        predictions = _coerce_list(sub_row.get("predictions"))

        if not predictions:
            skipped += 1
            continue

        # --- 6. Read scalar target with NaN guard ---
        target = label_row.get("target")
        if target is None or (isinstance(target, float) and math.isnan(target)):
            skipped += 1
            continue

        target = float(target)

        # --- 7. Task-specific logic (replace this block) ---
        # Example: accuracy against a threshold
        correct = sum(
            1 for p in predictions
            if isinstance(p, (int, float)) and not math.isnan(float(p))
        )
        total = len(predictions)
        score = correct / max(total, 1)
        # --- end task-specific logic ---

        scores.append(score)

    # --- 8. Aggregate ---
    if not scores:
        return {
            METRIC_NAME: 0.0,
            "n_evaluated": 0,
            "n_skipped": skipped,
            "error": "no valid scenarios to score",
        }

    if skipped:
        _warn(
            "Skipped %d/%d scenarios — score reflects only %d evaluated",
            skipped, len(ids), len(scores),
        )

    result = {
        METRIC_NAME: float(np.mean(scores)),
        "n_evaluated": len(scores),
        "n_skipped": skipped,
        "n_truncated": n_truncated if n_truncated else 0,
    }

    return result
