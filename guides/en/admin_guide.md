# Administrator Portal Complete Guide

Welcome to the NAI Platform Administrator Portal. This guide details every aspect of configuring, managing, and maintaining the platform.

## Table of Contents
1. [Challenge Lifecycle Management](#1-challenge-lifecycle-management)
2. [Sandbox Customization & Resource Limits](#2-sandbox-customization--resource-limits)
3. [Metrics & Rules Engine Configuration](#3-metrics--rules-engine-configuration)
4. [Custom Evaluation Scripts](#4-custom-evaluation-scripts)
5. [User Management & CSV Imports](#5-user-management--csv-imports)
6. [Disaster Recovery & Backups](#6-disaster-recovery--backups)

---

## 1. Challenge Lifecycle Management

The Admin Panel (`/admin`) is your central hub for creating and transitioning challenges through their lifecycle.

### Challenge States
* **Draft / Not Started:** `start_time` > current time. Visible only to Admins and Jury. Use this phase to safely test configuration, metric scripts, and resource limits.
* **Active:** `start_time` <= current time <= `end_time` and `is_frozen=False`. Competitors can actively browse tasks and submit code. Note the new **Grace Period** feature allows valid last-second attempts immediately following the exact `end_time`.
* **Frozen (Emergency Manual Freeze):** If `is_frozen=True`. This toggle allows you to immediately halt all submissions and freeze the leaderboard during infrastructure emergencies or critical bugs *without* needing to manually adjust and extend the `end_time` deadline.
* **Ended:** `end_time` < current time. Submissions are closed, but scores are not yet finalized. Jury members can perform manual scoring audits.
* **Finalized:** `scores_finalized=True`. Ranks are locked, and competitor aliases are de-anonymized. Post-finalization manual score edits are permitted but strictly require an audit justification log.
* **Archived:** `is_archived=True`. Read-only mode. **Crucially**, archived competitions are strictly hidden from competitor accounts. Only Admins and Jury retain access to archived statistics.

---

## 2. Sandbox Customization & Resource Limits

To safeguard the execution cluster and ensure fair play, every task must be explicitly configured.

### Resource Allocations
* **RAM Limit:** (MB) Defines the Docker container's strict `-m` limit. If the student's dataset processing or model size exceeds this, the kernel terminates immediately with an Out-Of-Memory (OOM) kill signal.
* **Time Limit:** (Seconds) The maximum wall-clock runtime for the Celery process. Exceeding this triggers a Timeout failure.
* **Requires GPU:** A boolean flag that routes the execution job specifically to the high-performance GPU Celery queue.

### Custom Docker Image Setup
* **Base Image:** Provide a valid public Docker registry image (e.g., `pytorch/pytorch:2.0.1-cuda11.7-cudnn8-runtime`).
* **Apt Packages:** A comma-separated list of Ubuntu packages to install (e.g., `libglib2.0-0, build-essential`).
* **Pip Requirements:** Define standard Python dependencies needed to evaluate or execute the task.

> [!NOTE]
> The worker infrastructure auto-builds these dependencies dynamically on the first execution and caches the resulting container.

---

## 3. Metrics & Rules Engine Configuration

### Dynamic Metrics Schema
A JSON configuration dictates how the final public and private scores are averaged.

**Example: Accuracy and F1 Score Optimization**
```json
{
  "accuracy": { "weight": 0.5, "higher_is_better": true },
  "f1_score": { "weight": 0.5, "higher_is_better": true }
}
```

### Pre-Execution AST Rule Enforcement
Before any submission reaches the Celery queue, it undergoes strict Static Application Security Testing (AST):
* **Require Submit Tag:** Code blocks must contain `# SUBMIT`.
* **Ban Magic Commands:** Automatically strips or rejects Jupyter `%` or `!` shell commands.
* **Banned Imports:** Define modules (like `os, sys, subprocess, requests, socket`) that are strictly forbidden to prevent cluster breakout attempts.

---

## 4. Custom Evaluation Scripts

When a task requires evaluation beyond simple Hugging Face metrics, provide a custom Python evaluator.

### Evaluator Template Structure
Your script runs sequentially *after* the student's `predict` function successfully returns. It must securely write the resulting metrics to `eval_results.json`.

```python
import json
import traceback

test_inputs = ["Data 1", "Data 2"]
test_labels = [0, 1]

try:
    if 'predict' not in globals():
        raise AttributeError("Student code must define 'predict(inputs_list)'.")
        
    predictions = predict(test_inputs)
    
    # ... Calculate Accuracy/MSE ...
    accuracy = 1.0 # Example
    
    with open("eval_results.json", "w") as f:
        json.dump({
            "status": "success",
            "public_score": float(accuracy),
            "private_score": float(accuracy),
            "metrics_payload_public": {"accuracy": float(accuracy)},
            "execution_time_ms": 45
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

## 5. User Management & CSV Imports

Efficiently onboard entire classrooms or competition cohorts via the `/admin` portal.
1. Navigate to the **Users** tab.
2. Click **Import CSV**.
3. Format requirements:
   ```csv
   username,email,password,name,surname,class_number,school,city,challenge_id
   student_a,studA@ai.edu,TempPass1,Alice,Smith,12,Tech High,Sofia,1
   ```

---

## 6. Disaster Recovery & Backups

The platform features an automated, resilient backup protocol to prevent data loss.
* **Schedule:** Backups trigger automatically every **10 minutes**.
* **Retention Policy:** The system strictly retains only the **5 most recent** snapshots, automatically purging older files to conserve disk space.
* **Archive Contents:** Each backup contains:
  1. A full `pg_dump` of the PostgreSQL relational database.
  2. A zipped archive of the `uploads/` directory, safeguarding the decoupled submission code (`.ipynb` segments) and execution logs.
