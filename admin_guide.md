# Administrator Portal Complete Guide

This guide details challenge management, Docker sandbox customization, custom metrics weighting, user database setup, diagnostics, and backups.

---

## 1. Challenge Lifecycle Control

The Admin Panel (`/admin`) allows you to manage active challenges. Each challenge moves through these states:
* **Draft / Inactive:** Visible only to admins. Used to test dataset paths and custom scoring codes.
* **Active:** Competitors can browse tasks, upload notebooks, and submit entries.
* **Leaderboard Frozen:** A challenge state where competitors can submit runs in the background, but the public leaderboard standings stop updating. Used in the final hours of competitions to build suspense.
* **Archived:** Read-only mode. Active queue processing stops, but leaderboards remain viewable.

---

## 2. Sandbox Customization & Task Config

Administrators can sandbox user code by customizing memory limits, execution time thresholds, and Docker containers:

### Resource Allocations
* **RAM Allocation:** Sets maximum memory in megabytes (Docker `-m` flag). If a student allocates more than this, the container is terminated with an OOM error.
* **Time Limit:** Maximum time limit in seconds.
* **Requires GPU:** Routes the Celery job to a GPU-designated worker queue.

### Custom Docker Image Specification
* **Base Docker Image:** Set target image (e.g. `pytorch/pytorch:2.0.1-cuda11.7-cudnn8-runtime`). Defaults to `python:3.10-slim`.
* **Apt Packages:** Comma-separated list of native libraries to install via apt-get (e.g., `libglib2.0-0, libsm6, libxrender1, libxext6`).
* **Pip Requirements:** Multi-line text block with python libraries to install (e.g., `transformers\ntorchvision\nscipy`).

> [!NOTE]
> The worker parses and hashes these values on receipt. If the image doesn't exist, it auto-builds the image dynamically and caches it, ensuring subsequent executions load instantly.

---

## 3. Metrics JSON Config & Rules Engine

### Metrics Configuration Schema
Administrators customize calculation weights using a JSON schema. Score averages are calculated dynamically using the configured weights:

#### Example A: Weighted Multiple Metrics
```json
{
  "accuracy": {
    "weight": 0.6,
    "higher_is_better": true
  },
  "f1": {
    "weight": 0.4,
    "higher_is_better": true
  }
}
```

#### Example B: Error minimization metric
```json
{
  "mse": {
    "weight": 1.0,
    "higher_is_better": false
  }
}
```

### Pre-Execution AST Rule Configuration
Set strict static verification filters to block malicious submissions:
* **Require Submit Tag:** Code blocks must contain `# SUBMIT`.
* **Ban Magic Commands:** Rejects cells containing `%` or `!` lines.
* **Banned Imports:** Comma-separated list of packages to block (e.g., `os,sys,subprocess,requests,socket`). The AST scanner rejects runs trying to bypass this.

---

## 4. Custom Evaluation Scripts

Instead of standard Hugging Face datasets, administrators can write a custom evaluator template. The template runs in the sandbox and must write its results as JSON to `/app/eval_results.json`.

### Boilerplate Custom Evaluator Code
```python
import json
import sys
import traceback

# 1. Load your secure evaluation dataset split
test_inputs = [
    "Sample text input 1",
    "Sample text input 2",
    "Sample text input 3"
]
test_labels = [1, 0, 1]

try:
    # 2. Check that the student's predict function exists
    if 'predict' not in globals():
        raise AttributeError("Student code must define 'predict(inputs_list)'.")
        
    # 3. Execute predictions
    predictions = predict(test_inputs)
    
    if len(predictions) != len(test_labels):
        raise ValueError(f"Expected {len(test_labels)} items, got {len(predictions)}")
        
    # 4. Calculate metrics
    correct = sum(1 for p, l in zip(predictions, test_labels) if p == l)
    accuracy = correct / len(test_labels)
    
    # 5. Write scores securely to eval_results.json (replaces stdout logging)
    with open("eval_results.json", "w") as f:
        json.dump({
            "status": "success",
            "public_score": float(accuracy),
            "private_score": float(accuracy),
            "metrics_payload_public": {"accuracy": float(accuracy)},
            "metrics_payload_private": {"accuracy": float(accuracy)},
            "execution_time_ms": 15
        }, f)
        
except Exception as e:
    with open("eval_results.json", "w") as f:
        json.dump({
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }, f)
```

---

## 5. CSV Import & Seeding Format

To import competitors in bulk:
1. Go to **Users** in the Admin panel.
2. Select **Import CSV**.
3. Upload a CSV file matching this format:
   ```csv
   username,email,password,name,surname,class_number,school,city,challenge_id
   competitor_1,comp1@ competition.ai,pass123,Alice,Lovelace,11,AI High,Sofia,1
   competitor_2,comp2@ competition.ai,pass223,Bob,Turing,12,Turing Academy,Varna,1
   ```

---

## 6. Backups & Disaster Recovery

* **On-Demand Backups:** Run the backup procedure from the diagnostics console. The system triggers `backup_db.sh` to generate an archived snapshot of the database state.
* **Recovery:** Backups are saved to the `/backups` directory on the host server and can be restored via standard SQL import commands.
