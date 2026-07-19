"""Custom evaluator for IOAI Home Task 1: Audio incremental classification.

Requires submission.parquet columns:
  - id: unique row identifier
  - prediction: predicted class ID (int)

Requires labels.parquet columns:
  - id: unique row identifier
  - label: ground-truth class ID (int, 0-28)

Metric: competition_score = 0.5 * acc_old + 0.5 * acc_new
where acc_old = accuracy on classes 0-15, acc_new = accuracy on classes 16-28.
"""

METRIC_NAME = "competition_score"

SUBMISSION_COLUMNS = [
    {"name": "id", "type": "string"},
    {"name": "prediction", "type": "int"},
]

LABELS_COLUMNS = [
    {"name": "id", "type": "string"},
    {"name": "label", "type": "int"},
]

EVALUATOR_OPTIONS = {
    "num_old_classes": 16,
}


def evaluate(df_sub, df_labels, options=None):
    import numpy as np
    from sklearn.metrics import accuracy_score

    merged = df_sub.merge(df_labels, on="id", suffixes=("_sub", "_label"))
    y_true = merged["label"].values
    y_pred = merged["prediction"].values

    num_old = (options or {}).get("num_old_classes", 16)
    is_old = y_true < num_old
    acc_old = accuracy_score(y_true[is_old], y_pred[is_old]) if is_old.any() else 0.0
    acc_new = accuracy_score(y_true[~is_old], y_pred[~is_old]) if (~is_old).any() else 0.0
    score = 0.5 * acc_old + 0.5 * acc_new

    return {
        "competition_score": float(score),
        "acc_old": float(acc_old),
        "acc_new": float(acc_new),
    }
