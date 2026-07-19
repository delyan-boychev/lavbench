"""Custom evaluator for IOAI Home Task 2: Grid delivery robot.

Requires submission.parquet columns:
  - id: unique row identifier (e.g. "test_0000_300000")
  - actions: list of int action IDs (0-5)

Requires labels.parquet columns:
  - id: unique row identifier (must match submission)
  - walls: list of [[row, col], ...]
  - depots: list of [[row, col], ...]
  - agent_row: int, start row
  - agent_col: int, start col
  - package_location: int (0-5), which depot has the package
  - destination: int (0-5), which depot is the goal

Metric: delivery_success_rate (fraction of episodes that delivered the package).
"""

METRIC_NAME = "delivery_success_rate"

SUBMISSION_COLUMNS = [
    {"name": "id", "type": "string"},
    {"name": "actions", "type": "list[int]"},
]

LABELS_COLUMNS = [
    {"name": "id", "type": "string"},
    {"name": "walls", "type": "list[list[int]]"},
    {"name": "depots", "type": "list[list[int]]"},
    {"name": "agent_row", "type": "int"},
    {"name": "agent_col", "type": "int"},
    {"name": "package_location", "type": "int"},
    {"name": "destination", "type": "int"},
]

EVALUATOR_OPTIONS = {
    "max_steps": 120,
    "grid_size": 8,
}

ACTION_DELTAS = {0: (1, 0), 1: (-1, 0), 2: (0, 1), 3: (0, -1)}


def evaluate(df_sub, df_labels, options=None):
    import numpy as np

    opts = options or {}
    max_steps = int(opts.get("max_steps", 120))
    grid_size = int(opts.get("grid_size", 8))
    n_depots = 6

    ids = sorted(set(df_sub["id"].tolist()) & set(df_labels["id"].tolist()))

    solved_list, steps_list, invalid_list = [], [], []

    for sid in ids:
        sub_row = df_sub[df_sub["id"] == sid].iloc[0]
        label_row = df_labels[df_labels["id"] == sid].iloc[0]

        actions = sub_row.get("actions", [])
        if not isinstance(actions, (list, tuple)):
            actions = []

        walls = set(map(tuple, label_row.get("walls", [])))
        depots = list(map(tuple, label_row.get("depots", [])))
        r, c = int(label_row["agent_row"]), int(label_row["agent_col"])
        carrying = False
        package_loc = int(label_row["package_location"])
        destination = int(label_row["destination"])
        step, invalid = 0, 0
        solved = False

        for action in actions:
            if step >= max_steps:
                break
            step += 1
            if action in ACTION_DELTAS:
                dr, dc = ACTION_DELTAS[action]
                nr, nc = r + dr, c + dc
                if 0 <= nr < grid_size and 0 <= nc < grid_size and (nr, nc) not in walls:
                    r, c = nr, nc
            elif action == 4 and not carrying and (r, c) == depots[package_loc]:
                carrying = True
            elif action == 5 and carrying and (r, c) == depots[destination]:
                solved = True
                break
            elif action in (4, 5):
                invalid += 1

        solved_list.append(1.0 if solved else 0.0)
        steps_list.append(step)
        invalid_list.append(invalid)

    return {
        "delivery_success_rate": float(np.mean(solved_list)),
        "avg_steps": float(np.mean(steps_list)),
        "avg_invalid": float(np.mean(invalid_list)),
    }
