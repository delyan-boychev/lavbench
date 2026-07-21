# Custom Evaluators Guide & Reference

Custom evaluators allow competition judges and administrators to upload domain-specific Python scoring scripts (`evaluator.py`) per task. Custom evaluators replace generic metrics with custom evaluation algorithms for complex machine learning tasks (e.g. reinforcement learning paths, graph optimization, audio processing, or multi-class incremental accuracy).

---

## 1. Custom Evaluator Module Contract

Each custom evaluator script **must** be a valid Python module declaring four required module-level variables and a primary entry point function `evaluate()`:

```python
import pandas as pd
import numpy as np

# 1. Main metric identifier displayed on the leaderboard (Required, non-empty str)
METRIC_NAME = "custom_score"

# 2. Expected columns in competitor's submission.parquet (Required, list of dicts)
SUBMISSION_COLUMNS = [
    {"name": "id", "type": "string"},
    {"name": "prediction", "type": "float"},
]

# 3. Expected columns in ground truth labels.parquet (Required, list of dicts)
LABELS_COLUMNS = [
    {"name": "id", "type": "string"},
    {"name": "target", "type": "float"},
]

# 4. Default evaluation parameters (Optional, dict)
EVALUATOR_OPTIONS = {
    "tolerance": 0.05,
    "penalty_weight": 0.1,
}

def evaluate(df_sub, df_labels, options=None):
    """
    Evaluates competitor predictions against ground truth labels.

    :param df_sub: pandas.DataFrame loaded from competitor's submission.parquet
    :param df_labels: pandas.DataFrame loaded from task's hidden labels.parquet
    :param options: dict containing runtime options (passed from metrics_config / options_schema)
    :return: dict[str, float] mapping metric keys to score values
    """
    options = options or EVALUATOR_OPTIONS
    # Join predictions with labels on 'id'
    merged = pd.merge(df_sub, df_labels, on="id", suffixes=("_sub", "_gt"))
    if merged.empty:
        return {METRIC_NAME: 0.0, "secondary_metric": 0.0}

    # Custom evaluation logic
    pred_vals = pd.to_numeric(merged["prediction"], errors="coerce").fillna(0.0).to_numpy()
    target_vals = pd.to_numeric(merged["target"], errors="coerce").fillna(0.0).to_numpy()

    abs_diff = np.abs(pred_vals - target_vals)
    tolerance = float(options.get("tolerance", 0.05))
    accuracy = float(np.mean(abs_diff <= tolerance))

    return {
        METRIC_NAME: accuracy,
        "secondary_metric": float(np.mean(abs_diff)),
    }
```

---

## 2. Variable Specifications & Constraints

| Variable | Required | Type | Description |
| :--- | :--- | :--- | :--- |
| `METRIC_NAME` | **Yes** | `str` | Metric identifier key returned in `evaluate()` dict. Displayed as the primary score column on the public leaderboard. Must be a non-empty string. |
| `SUBMISSION_COLUMNS` | **Yes** | `list[dict]` | Expected columns in `submission.parquet`. Each entry must be a dict `{"name": str, "type": str}` (e.g. `[{"name": "id", "type": "string"}]`). Used by UI to render dataset schema documentation cards. |
| `LABELS_COLUMNS` | **Yes** | `list[dict]` | Expected columns in hidden `labels.parquet` (same format as above). Set to `[]` if no ground truth labels are needed. |
| `EVALUATOR_OPTIONS` | **No** | `dict` | Default options dictionary passed into the `options` argument of `evaluate()`. |
| `evaluate(df_sub, df_labels, options=None)` | **Yes** | `function` | Execution entry point receiving pandas DataFrames and options dict. Must return `dict[str, float]` containing `METRIC_NAME`. |

### Key Rules & Conventions:
- **Directionality**: All returned metric scores are treated as **higher-is-better** by the leaderboard engine.
- **AST Validation on Upload**: The server executes static AST validation (`backend/routes/tasks.py`) when an evaluator is uploaded or modified. If `METRIC_NAME`, `SUBMISSION_COLUMNS`, `LABELS_COLUMNS`, or `evaluate` signature are missing or malformed, the upload returns **HTTP 400 Bad Request** with a detailed error description.
- **Runtime Options Overrides**: When evaluation runs (`backend/evaluation_engine.py`), runtime options defined in the task's `metrics_config[m_name].get("options", {})` or `evaluator_options_schema` override default keys in `EVALUATOR_OPTIONS`.

---

## 3. Template Scripts & Examples

LavBench provides production-ready evaluator template scripts in `docs/evaluator_templates/`:

| Template File | Task Domain / Description | Link |
| :--- | :--- | :--- |
| **`evaluator_custom_template.py`** | **Comprehensive Reference Evaluator**: Handles column validation, missing ID intersection, list coercion, math guards (`math.isnan`), and JSON serialization. | [`evaluator_custom_template.py`](evaluator_templates/evaluator_custom_template.py) |
| **`evaluator_ht1_audio.py`** | **Audio Classification** (IOAI Home Task 1): Evaluates multi-class incremental accuracy (`acc_old` for classes 0-15 vs `acc_new` for 16-28). | [`evaluator_ht1_audio.py`](evaluator_templates/evaluator_ht1_audio.py) |
| **`evaluator_ht2_delivery.py`** | **Grid Delivery Path** (IOAI Home Task 2): Evaluates multi-step grid navigation actions against walls, depots, and target destinations. | [`evaluator_ht2_delivery.py`](evaluator_templates/evaluator_ht2_delivery.py) |
| **`evaluator_ht3_animal.py`** | **Animal Deduction** (IOAI Home Task 3): Evaluates discrete logical deduction and categorization accuracy. | [`evaluator_ht3_animal.py`](evaluator_templates/evaluator_ht3_animal.py) |

> [!NOTE]
> `backend/task_modules/templates.py` contains Jinja2 templates for sandbox container creation and competitor code execution wrappers (`DEFAULT_EVALUATION_TEMPLATE`), whereas domain-specific metric templates reside in `docs/evaluator_templates/`.

---

## 4. Best Practices & Resilience Guidelines

Custom evaluators run directly in the server evaluation process. Follow these defensive programming patterns to ensure resilience against malformed competitor submissions:

1. **Check Required Columns**: Always verify that `predictions` or required column names exist in `df_sub`. If missing, throw a descriptive `ValueError` so it displays in the competitor's submission error log.
2. **Sanitize `NaN` & `Inf` Values**: Use `pd.to_numeric(..., errors='coerce').fillna(0.0)` or `np.nan_to_num()` to prevent calculation crashes on invalid outputs.
3. **Native Float Return Values**: Cast all score dict values to standard Python `float` (e.g. `float(score)`), as raw `numpy.float64` objects may cause JSON serialization issues.
4. **Test via Baseline Solution Notebooks (`is_baseline=True`)**: Prior to contest launch, submit a reference solution as an Admin with **"Mark as Baseline Solution"** (`is_baseline=True`). This validates that your evaluator script executes cleanly against actual `submission.parquet` outputs.

---

## 5. API Reference

- **Upload Evaluator Script**: `POST /api/challenges/{id}/tasks` or `PUT /api/tasks/{id}` with `evaluator_script` (multipart `.py` file) or `custom_eval_code` string.
- **Delete Evaluator**: `PUT /api/tasks/{id}` with `delete_evaluator=true`.
- **Response**: Task object includes `evaluator_metric_name`, `evaluator_script_path`, and `custom_eval_code`.
