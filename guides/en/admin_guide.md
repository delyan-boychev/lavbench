# Administrator Portal Complete Guide

Welcome to the LavBench Platform Administrator Portal. This guide details every aspect of configuring, managing, and maintaining the platform.

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
* **Draft / Not Started:** `start_time` > current time. Visible only to Admins and Jury members. Use this phase to safely test task configurations, metric scripts, and resource limits.
* **Active:** `start_time` <= current time <= `end_time` and `is_frozen=False`. Competitors can actively browse tasks and submit their notebooks. Note that the **Grace Period** feature allows valid last-second attempts immediately following the exact `end_time`.
* **Frozen (Emergency Manual Freeze):** If `is_frozen=True`. This toggle allows you to immediately halt all submissions and freeze the leaderboard during infrastructure emergencies or critical bugs *without* needing to manually adjust and extend the `end_time` deadline.
* **Ended:** `end_time` < current time. Submissions are closed, but scores are not yet finalized. Jury members can perform manual scoring audits.
* **Finalized:** `scores_finalized=True`. Ranks are locked, and competitor aliases are de-anonymized. Post-finalization manual score edits are permitted but strictly require an audit justification log.
* **Archived:** `is_archived=True`. Read-only mode. **Crucially**, archived competitions are strictly hidden from competitor accounts. Only Admins and Jury members retain access to archived statistics.

---

## 2. Sandbox Customization & Resource Limits

To safeguard the execution cluster and ensure fair play, every task must be explicitly configured.

### Resource Allocations
* **RAM Limit:** (MB) Defines the Docker container's strict `-m` limit. If the participant's data processing or model memory footprint exceeds this, the kernel terminates immediately with an Out-Of-Memory (OOM) kill signal.
* **Time Limit:** (Seconds) The maximum wall-clock runtime for the Celery process. Exceeding this triggers a Timeout failure.
* **Requires GPU:** A boolean flag that routes the execution job specifically to the high-performance hardware accelerator (GPU) Celery queue.

### Custom Docker Image Setup
* **Base Image:** Provide a valid public Docker registry image (e.g., `pytorch/pytorch:2.0.1-cuda11.7-cudnn8-runtime`).
* **Apt Packages:** A comma-separated list of Ubuntu packages to install (e.g., `libglib2.0-0, build-essential`).
* **Pip Requirements:** Define standard Python dependencies needed to evaluate or execute the task.

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
  "f1_score": { "weight": 0.5, "higher_is_better": true }
}
```

### Pre-Execution AST Rule Enforcement
Before any submission reaches the Celery queue, it undergoes strict Static Application Security Testing (AST):
* **Ban Magic Commands:** Automatically strips or rejects Jupyter `%` or `!` shell commands.
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
   ```csv
   username,email,password,name,surname,class_number,school,city,challenge_id
   student_a,studA@ai.edu,TempPass1,Alice,Smith,12,Tech High,Sofia,1
   ```

---

## 5. Backup Management

The platform features an automated backup protocol to prevent data loss. All backups include a full PostgreSQL dump and the `uploads/` directory compressed into a `.tar.gz` archive.

### Backup Types

| Type | Frequency | Retention | Location |
|------|-----------|-----------|----------|
| **Auto** | Every **20 minutes** when competitions are active, every **6 hours** when idle | Latest **6** | `auto_YYYYMMDD_HHMMSS.tar.gz` in `/backups/` |
| **Manual** | On demand via "Force Backup Now" button | Never auto-deleted | `manual_YYYYMMDD_HHMMSS.tar.gz` in `/backups/` |
| **Competition Lifecycle** | Triggered on deadline, grace period end, and finalization | Until challenge is deleted | `challenge_{id}/{state}_YYYYMMDD_HHMMSS.tar.gz` |

### Backup Management UI
Go to the **Admin Panel** → **Backups** tab:
- View the list of all auto and manual backups with file sizes and timestamps.
- **Force Backup Now** — creates an immediate manual backup. Shows a loading spinner while in progress via SSE.
- **Download** — download any backup file.
- **Delete** — delete manual backups only (auto-backups cannot be deleted manually, returns 403).
- Competition-specific backups are viewable/downloadable from the **Competition Management** tab under each challenge's details.

### Retention Rules
- **Auto-backups**: Only the 6 most recent are kept. The oldest ones are auto-deleted.
- **Manual backups**: Never auto-deleted. Only removed via the delete button.
- **Competition backups**: Persist until the challenge is deleted. Deleting a challenge removes all its associated backup files.

### Competition Lifecycle Backups
The system automatically takes database snapshots during key lifecycle events:
- **Submission Ended** — when the official competition deadline passes.
- **Grace Period Ended** — when the grace period expires (no more submissions are accepted).
- **Scores Finalized** — when scores are locked and identities are revealed.

These snapshots appear in the Competition Management tab under each challenge.

---

## 6. Monitoring & Diagnostics

### Health Endpoint
`GET /api/health` — verifies database connectivity. Returns:
```json
{"status": "ok", "database": "connected"}
```
Returns 503 if the database is unreachable. Used by Docker health checks and load balancers.

### Dead Letter Queue
When a Celery evaluation task fails permanently (all retries exhausted), it is logged to a Redis dead letter queue. Inspect it via:
`GET /api/admin/dead-letters` (admin only).

Each entry shows the submission ID, task ID, challenge ID, failure timestamp, and the error message. This is highly useful for debugging systemic evaluation or container failures.

### Worker Status Monitoring
The **Cluster** badge in the navbar shows worker node status in real-time via SSE:
- Green: workers are connected and healthy.
- Red: workers are disconnected.
- Click for a modal showing per-worker specs (CPU cores, RAM, GPU type, VRAM, concurrency).

Workers run directly on the host machine via `start_worker.sh` — they are NOT part of Docker Compose because they require access to the host's Docker CLI to build and spawn sandbox containers dynamically.

### Worker Specs Registration
When a worker node starts, it automatically registers its hardware specs in Redis. These appear in the cluster modal dashboard. If Redis is unavailable, worker specs will not be registered until the next worker restart.