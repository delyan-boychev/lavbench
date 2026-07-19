# Custom Evaluators

Custom evaluators replace the old simulator/action-metric approach with a simple Python script that the judge uploads per task.

## Format

Each evaluator script **must** define four module-level variables:

```python
METRIC_NAME = "my_metric_name"

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
    ...
    return {"metric_key": float_value, ...}
```

### Variable reference

| Variable | Required | Type | Description |
|---|---|---|---|
| `METRIC_NAME` | yes | `str` | Metric identifier used as the key in `evaluate()` return dict and displayed on the leaderboard |
| `SUBMISSION_COLUMNS` | yes | `list[dict]` | Expected columns in `submission.parquet`; each entry has `name` (str) and `type` (str) |
| `LABELS_COLUMNS` | yes | `list[dict]` | Expected columns in `labels.parquet` (same format); set to `[]` if no labels are needed |
| `EVALUATOR_OPTIONS` | no | `dict` | Default option values passed to `evaluate()` as the `options` argument |
| `evaluate(df_sub, df_labels, options=None)` | yes | function | Receives parquet DataFrames and the options dict; returns `dict[str, float]` |

- `METRIC_NAME` must be a key in the `evaluate()` return dict.
- `SUBMISSION_COLUMNS` and `LABELS_COLUMNS` are used for frontend schema visualization (read-only cards).
- All returned metrics are **higher-is-better**.
- The script is **validated on upload** — the backend parses all module-level variables via AST and returns a 400 error if any required variable is missing or malformed.

## Fields

| Field | Type | Description |
|---|---|---|
| `custom_eval_code` | text | Raw Python script content (stored in DB) |
| `evaluator_metric_name` | string | Extracted `METRIC_NAME` from the script |
| `evaluator_script_path` | string | Path to the uploaded `.py` file on disk |

## Template Scripts

See `docs/evaluator_templates/` for IOAI task examples:

- [`evaluator_ht1_audio.py`](evaluator_templates/evaluator_ht1_audio.py) — Audio classification
- [`evaluator_ht2_delivery.py`](evaluator_templates/evaluator_ht2_delivery.py) — Grid delivery path
- [`evaluator_ht3_animal.py`](evaluator_templates/evaluator_ht3_animal.py) — Animal deduction

## Migration from Old Action Metrics

The old action/simulator system (`action_success_rate`, `action_avg_steps`, `action_invalid_count`, `action_cumulative_reward`) has been removed. Any existing tasks using these metrics must be migrated to a custom evaluator script.

## API

- **Upload**: `POST /api/challenges/{id}/tasks` or `PUT /api/tasks/{id}` with `evaluator_script` (multipart file field `.py`)
- **Delete**: `PUT /api/tasks/{id}` with `delete_evaluator=true`
- **Response**: Task response includes `evaluator_metric_name` and `evaluator_script_path`
