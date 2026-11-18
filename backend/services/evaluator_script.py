"""Read the module-level settings an admin's custom evaluator script declares."""

from __future__ import annotations

import ast
from typing import Any


def parse_evaluator_script(code: str) -> tuple[dict[str, Any] | None, str | None]:
    """Parse and validate required module-level variables from an evaluator script.

    Required: METRIC_NAME (str), SUBMISSION_COLUMNS (list[dict{name, type}]),
              LABELS_COLUMNS (list[dict{name, type}])
    Optional: EVALUATOR_OPTIONS (dict)

    Returns (metadata_dict, None) on success or (None, error_message) on failure.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return None, f"Syntax error in evaluator script: {e}"

    def _get_value(var_name: str) -> Any:
        for node in ast.iter_child_nodes(tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == var_name
            ):
                try:
                    return ast.literal_eval(node.value)
                except (ValueError, TypeError, SyntaxError, RecursionError):
                    return None
        return None

    metric_name = _get_value("METRIC_NAME")
    if metric_name is None:
        return None, "Missing required variable: METRIC_NAME (str)"
    if not isinstance(metric_name, str) or not metric_name.strip():
        return None, "METRIC_NAME must be a non-empty string"

    sub_cols = _get_value("SUBMISSION_COLUMNS")
    if sub_cols is None:
        return None, "Missing required variable: SUBMISSION_COLUMNS (list of {name, type})"
    if not isinstance(sub_cols, list):
        return None, "SUBMISSION_COLUMNS must be a list"
    for i, col in enumerate(sub_cols):
        if not isinstance(col, dict) or "name" not in col or "type" not in col:
            return (
                None,
                f"SUBMISSION_COLUMNS[{i}]: each entry must be a dict with 'name' and 'type' keys",
            )
        if not isinstance(col["name"], str) or not isinstance(col["type"], str):
            return None, f"SUBMISSION_COLUMNS[{i}]: 'name' and 'type' must be strings"

    lbl_cols = _get_value("LABELS_COLUMNS")
    if lbl_cols is None:
        return None, "Missing required variable: LABELS_COLUMNS (list of {name, type})"
    if not isinstance(lbl_cols, list):
        return None, "LABELS_COLUMNS must be a list"
    for i, col in enumerate(lbl_cols):
        if not isinstance(col, dict) or "name" not in col or "type" not in col:
            return (
                None,
                f"LABELS_COLUMNS[{i}]: each entry must be a dict with 'name' and 'type' keys",
            )
        if not isinstance(col["name"], str) or not isinstance(col["type"], str):
            return None, f"LABELS_COLUMNS[{i}]: 'name' and 'type' must be strings"

    options = _get_value("EVALUATOR_OPTIONS")
    if options is not None and not isinstance(options, dict):
        return None, "EVALUATOR_OPTIONS must be a dict"

    return {
        "metric_name": metric_name.strip(),
        "submission_columns": sub_cols,
        "labels_columns": lbl_cols,
        "options": options or {},
    }, None


def evaluator_submission_columns(code: str | None) -> list[str]:
    """The SUBMISSION_COLUMNS names a valid evaluator script requires, else none."""
    if not code:
        return []
    parsed, _error = parse_evaluator_script(code)
    if parsed is None:
        return []
    return [str(col["name"]) for col in parsed["submission_columns"]]
