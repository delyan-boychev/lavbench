# Administrator Portal Complete Guide

Welcome to the LavBench Platform Administrator Portal. This guide details every aspect of configuring, managing, and maintaining the platform.

### Initial Setup

After deploying the platform, create the admin account:

```bash
python backend/setup-admin.py
```

This drops and recreates the database, generates a random admin username and master key, and saves them to `admin_credentials.txt` in the project root. Use those credentials on the login page with the "Sign In as Administrator" checkbox enabled.

> [!IMPORTANT]
> Run this only once on a fresh database. Re-running it resets all data.

## Table of Contents

1. [Challenge Lifecycle Management](#1-challenge-lifecycle-management)
2. [Sandbox Customization & Resource Limits](#2-sandbox-customization--resource-limits)
3. [Metrics & Rules Engine Configuration](#3-metrics--rules-engine-configuration)
4. [User Management & CSV Imports](#4-user-management--csv-imports)
5. [Backup Management](#5-backup-management)
6. [Monitoring & Diagnostics](#6-monitoring--diagnostics)

---

## 1. Challenge Lifecycle Management

The Admin Panel (`/admin`) is your central hub for creating and transitioning challenges through their lifecycle.

### Challenge States

- **Draft / Not Started:** `start_time` > current time. Visible only to Admins and Jury members. Use this phase to safely test task configurations, metric scripts, and resource limits.
- **Active:** `start_time` <= current time <= `end_time` and `is_frozen=False`. Competitors can actively browse tasks and submit their notebooks. Note that the **Grace Period** feature allows valid last-second attempts immediately following the exact `end_time`.
- **Frozen (Emergency Manual Freeze):** If `is_frozen=True`. This toggle allows you to immediately halt all submissions and freeze the leaderboard during infrastructure emergencies or critical bugs _without_ needing to manually adjust and extend the `end_time` deadline.
- **Ended:** `end_time` < current time. Submissions are closed, but scores are not yet finalized. Jury members can perform manual scoring audits.
- **Finalized:** `scores_finalized=True`. Ranks are locked, and competitor aliases are de-anonymized. Post-finalization manual score edits are permitted but strictly require an audit justification log.
- **Archived:** `is_archived=True`. Read-only mode. **Crucially**, archived competitions are strictly hidden from competitor accounts. Only Admins and Jury members retain access to archived statistics.

---

## 2. Sandbox Customization & Resource Limits

To safeguard the execution cluster and ensure fair play, every task must be explicitly configured.

### Resource Allocations

- **RAM Limit:** (MB) Defines the Docker container's strict `-m` limit. If the participant's data processing or model memory footprint exceeds this, the kernel terminates immediately with an Out-Of-Memory (OOM) kill signal.
- **Time Limit:** (Seconds) The maximum wall-clock runtime for the Celery process. Exceeding this triggers a Timeout failure.
- **Requires GPU:** A boolean flag that routes the execution job specifically to the high-performance hardware accelerator (GPU) Celery queue.

### Sandbox Security

Every submission executes in a hardened Docker container with enforced isolation:

| Restriction                            | Purpose                                                                                         |
| -------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `--network none`                       | Blocks all network access — no data exfiltration or downloads                                   |
| `--cap-drop ALL`                       | Removes all Linux capabilities — no raw sockets, `mount()`, `ptrace()`, or privilege escalation |
| `--read-only`                          | Root filesystem is read-only — student code cannot modify system binaries                       |
| `--no-new-privileges`                  | Prevents suid binary escalation                                                                 |
| `--tmpfs /tmp:noexec,nosuid,size=128m` | In-memory, size-capped temp — cannot fill host disk                                             |
| `--memory-swap` = RAM limit            | Disables swap — no memory pressure bypass                                                       |
| `--pids-limit 64`                      | Prevents fork bombs                                                                             |
| `--ulimit nofile=256:256`              | Limits open file descriptors                                                                    |
| `--cpus` (configurable)                | Limits CPU — set via `CPU_CORES_PER_TASK` / `GPU_CORES_PER_TASK` in `worker.env`                 |

### Custom Docker Image Setup

- **Base Image:** Provide a valid public Docker registry image (e.g., `pytorch/pytorch:2.0.1-cuda11.7-cudnn8-runtime`).
- **Apt Packages:** A comma-separated list of Ubuntu packages to install (e.g., `libglib2.0-0, build-essential`).
- **Pip Requirements:** Define standard Python dependencies needed to evaluate or execute the task.

> [!NOTE]
> The worker infrastructure auto-builds these dependencies dynamically on the first execution and caches the resulting sandbox container.

---

## 3. Metrics & Rules Engine Configuration

### Dynamic Metrics Schema

A JSON configuration dictates how the final public and private scores are calculated and weighted.

**Example: Accuracy and F1 Score Optimization**

```json
{
  "accuracy": { "weight": 0.5, "higher_is_better": true },
  "f1": { "weight": 0.5, "higher_is_better": true }
}
```

**Example: Multi-metric Regression Task**

```json
{
  "rmse": { "weight": 0.6 },
  "mae": { "weight": 0.3 },
  "r_squared": { "weight": 0.1 }
}
```

### Supported Metric Categories

The evaluation engine supports 44 metrics across 12 task types:

| Category             | Metric Keys                                                                          |
| -------------------- | ------------------------------------------------------------------------------------ |
| **Classification**   | `accuracy`, `f1`, `precision`, `recall`, `cohen_kappa`, `matthews_corrcoef`          |
| **Probabilistic**    | `auc_roc`, `logloss`, `brier_score`                                                  |
| **Regression**       | `rmse`, `mse`, `mae`, `r_squared`, `mape`, `median_ae`                               |
| **Seq-label (NER)**  | `seqeval_f1`, `seqeval_precision`, `seqeval_recall`                                  |
| **Generative NLP**   | `bleu`, `rouge`, `rouge_l`, `meteor`, `chrf`, `ter`                     |
| **QA Extractive**    | `exact_match`, `f1` (word-overlap)                                                   |
| **Object Detection** | `map_50`, `map_75`, `map_50_95`, `recall` (box recall)                               |
| **Segmentation**     | `mean_iou`, `dice`, `pixel_accuracy`                                                 |
| **Keypoints**        | `oks`, `pck`                                                                         |
| **Image Quality**    | `psnr`, `ssim`                           |
| **Audio Quality**    | `snr`, `mel_lsd`, `si_sdr`                                          |
| **Clustering**       | `adjusted_rand_index`, `normalized_mutual_info`, `adjusted_mutual_info`, `v_measure` |
| **Retrieval**        | `ndcg_k`, `recall_k`, `mrr`                                                          |

> [!NOTE]
> `f1` and `recall` automatically dispatch based on input type: string values → QA word-overlap; list-of-dict values → object detection box recall; integer/float values → sklearn classification.

### Pre-Execution AST Rule Enforcement

Before any submission reaches the Celery queue, it undergoes strict Static Application Security Testing (AST):

- **Strip Magic Commands:** Jupyter `%` and `!` shell commands (e.g., `%matplotlib inline`, `!pip install`) are automatically removed via regex before AST parsing. They have no effect inside the sandbox.

### Banned Imports

Define modules (like `os, sys, subprocess, requests, socket`) that are forbidden. These are configured per-task — you can enforce different restrictions for different machine learning problems.

### How Evaluation Works

Participants submit Jupyter notebooks. Their code executes in an isolated Docker sandbox and must write a **`submission.parquet`** file containing their predictions. The system calculates evaluation metrics by comparing this against the hidden **`labels.parquet`** (uploaded per task).

- The participant's code must produce `submission.parquet` with an `id` column and the respective prediction columns.
- The `labels.parquet` file contains the ground truth — you must upload it when creating the task.
- The task's `metrics_config` defines which metrics to compute and how to weight them.
- `public_eval_percentage` controls the data split between the public leaderboard and the private test set used for final standings.

---

## 4. User Management & CSV Imports

Efficiently onboard entire classrooms or competition cohorts via the `/admin` portal.

1. Navigate to the **Users** tab.
2. Click **Import CSV**.
3. Format requirements:
   ```text
   username,email,password,name,surname,class_number,school,city,challenge_id
   student_a,studA@ai.edu,TempPass1,Alice,Smith,12,Tech High,Sofia,1
   ```

---

## 5. Backup Management

The platform features an automated backup protocol to prevent data loss. All backups include a full PostgreSQL dump and the `uploads/` directory compressed into a `.tar.gz` archive.

### Backup Types

| Type       | Frequency                                                                      | Retention          | Location                                       |
| ---------- | ------------------------------------------------------------------------------ | ------------------ | ---------------------------------------------- |
| **Auto**   | Every **20 minutes** when competitions are active, every **6 hours** when idle | Latest **6**       | `auto_YYYYMMDD_HHMMSS.tar.gz` in `/backups/`   |
| **Manual** | On demand via "Force Backup Now" button                                        | Never auto-deleted | `manual_YYYYMMDD_HHMMSS.tar.gz` in `/backups/` |

### Backup Management UI

Go to the **Admin Panel** → **Backups** tab:

- View the list of all auto and manual backups with file sizes and timestamps.
- **Force Backup Now** — creates an immediate manual backup. Shows a loading spinner while in progress via SSE.
- **Download** — download any backup file.
- **Delete** — delete manual backups only (auto-backups cannot be deleted manually, returns 403).

### Retention Rules

- **Auto-backups**: Only the 6 most recent are kept. The oldest ones are auto-deleted.
- **Manual backups**: Never auto-deleted. Only removed via the delete button.

---

## 6. Monitoring & Diagnostics

### Health Endpoint

`GET /api/health` — verifies database connectivity. Returns:

```json
{ "status": "ok", "database": "connected" }
```

Returns 503 if the database is unreachable. Used by Docker health checks and load balancers.

### Dead Letter Queue

When a Celery evaluation task fails permanently (all retries exhausted), it is logged to a Redis dead letter queue. Inspect it via:
`GET /api/admin/dead-letters` (admin only).

Each entry shows the submission ID, task ID, challenge ID, failure timestamp, and the error message. This is highly useful for debugging systemic evaluation or container failures.

### Audit Logs

The platform implements a comprehensive audit trail to track all administrative actions. This is crucial for verifying the integrity of the grading process, user management, and configuration changes.

- **Accessing Logs**: Go to the **Admin Panel** → **Audit Logs** tab (accessible only to users with the `admin` role).
- **Logged Actions**:
  - `create` / `update` / `delete` of challenges, stages, and tasks.
  - `finalize` and `archive` transitions.
  - Password resets (both individual and bulk/competition-wide).
  - Manual score changes (which strictly require entering a justification reason).
- **Filtering**: Search or filter audit records by **Action Type** (create, update, delete, etc.) or look up actions associated with a specific challenge.
- **Log Payload Details**: Click **View** on any log entry to view the exact payload/meta-details in JSON format, along with any provided justification/reason (such as why a manual score edit was made).

### Worker Status Monitoring

The **Cluster** badge in the navbar shows worker node status in real-time via SSE:

- Green: workers are connected and healthy.
- Red: workers are disconnected.
- Click for a modal showing per-worker specs (CPU cores, RAM, GPU type, VRAM, concurrency).

Workers are split into two categories to isolate system tasks from heavy evaluation workloads:

1. **Internal Task Worker**: Runs inside the main web server's Docker Compose setup (`celery_worker` service). It executes system tasks (like database backups, watchdog checks, and leaderboard recalculations). By default, its concurrency is capped at `2` (using `CELERY_WORKER_CONCURRENCY`) to preserve host resources for Flask, PostgreSQL, Redis, and SSE.
2. **Evaluation Workers**: Run directly on host/remote machines (with CPU or GPU resources) to build and run student submission Docker sandboxes.

#### Launching Evaluation Workers

The recommended way is via the interactive setup:

```bash
# Copy worker.env from the server (generated by make setup-server):
scp user@server:~/lavbench/worker.env .

# Interactive config (mode, type, GPUs, cores):
make setup-worker
```

On first run, the setup detects available CPUs and GPUs, then guides you through:
1. **Run mode** — Docker (recommended) or local micromamba
2. **Worker type** — evaluation, internal, or both
3. **GPU IDs** — select which GPUs to use (requires `nvidia-smi`)
4. **CPU cores per task** — allocated per GPU and per CPU evaluation container
5. **Concurrency** — auto-calculated (GPU count + remaining CPU slots)

Then deploy from the saved config:

```bash
make deploy-worker
```

To edit the saved configuration:

```bash
make edit-worker    # menu-based editor (type, GPUs, cores, concurrency)
```

_Note: If running evaluation workers on the main backend web host, leave at least 2 CPU cores free to prevent resource starvation for the Gunicorn and Postgres containers._

### Worker Specs Registration

When a worker node starts, it automatically registers its hardware specs in Redis (if running as an evaluation worker). These appear in the cluster modal dashboard. If Redis is unavailable, worker specs will not be registered until the next worker restart. Internal workers are excluded from cluster metrics and telemetry.
