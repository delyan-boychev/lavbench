"""Custom evaluator for IOAI Home Task 3: Animal deduction (20 questions).

Requires submission.parquet columns:
  - id: unique row identifier
  - solved: 1.0 if animal was correctly guessed, 0.0 otherwise
  - queries: number of questions asked (int)

Metric: mean_score = max(0, solved - 0.02 * queries) averaged over all rows.

There is no labels.parquet required for this task — the evaluation
is computed entirely from the submission's pre-computed results.
"""

METRIC_NAME = "mean_score"


def evaluate(df_sub, df_labels, options=None):
    import numpy as np

    penalty = (options or {}).get("penalty_per_query", 0.02)

    solved = df_sub.get("solved", [])
    queries = df_sub.get("queries", [])

    scores = []
    for sol, q in zip(solved, queries):
        scores.append(max(0.0, float(sol) - penalty * float(q)))

    return {"mean_score": float(np.mean(scores)) if scores else 0.0}
