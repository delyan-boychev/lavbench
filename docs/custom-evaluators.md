# Custom Evaluators

Custom evaluators replace the old simulator/action-metric approach with a simple Python script that the judge uploads per task.

## Format

Each evaluator script must define:

```python
METRIC_NAME = "my_metric_name"

def evaluate(df_sub, df_labels, options=None):
    ...
    return {"metric_key": float_value, ...}
```

- `METRIC_NAME` — a string used as display name; must be a valid Python string literal.
- `evaluate(df_sub, df_labels, options=None)` — receives the submission parquet as a DataFrame, the labels parquet as a DataFrame, and an optional `options` dict from the task's metrics config.
- Returns a `dict[str, float]`. All returned metrics are **higher-is-better**.

## Fields

| Field | Type | Description |
|---|---|---|
| `custom_eval_code` | text | Raw Python script content (stored in DB) |
| `evaluator_metric_name` | string | Extracted `METRIC_NAME` from the script |
| `evaluator_options_schema` | text | JSON schema for options (optional, for future UI use) |
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
- **Response**: Task response includes `evaluator_metric_name`, `evaluator_options_schema`, and `evaluator_script_path`
