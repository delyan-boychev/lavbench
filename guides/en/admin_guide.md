# Administrator Portal Complete Guide

Welcome to the LavBench Platform Administrator Portal. This guide details every aspect of configuring, managing, and maintaining the platform, executing worker nodes, configuring security rules, building task Docker images, and implementing custom evaluator scripts.

### Initial Setup

After deploying the platform, initialize the admin account via the setup script:

```bash
python backend/setup-admin.py
```

This generates an initial administrator account, creates master credentials, and outputs them to `admin_credentials.txt` in the root directory. Log in via the main web interface with the **"Sign In as Administrator"** toggle enabled.

> [!IMPORTANT]
> Run `setup-admin.py` only once on a fresh deployment. Re-running this script will reset system administrator access.

---

## Table of Contents

1. [Challenge and Stage Lifecycle Management](#1-challenge-and-stage-lifecycle-management)
2. [Sandbox Customization and Image Build Error Remediation](#2-sandbox-customization-and-image-build-error-remediation)
3. [Hugging Face Pre-Fetching and Offline Assets](#3-hugging-face-pre-fetching-and-offline-assets)
4. [AST Code Security and Dynamic Metrics Engine](#4-ast-code-security-and-dynamic-metrics-engine)
5. [Custom Evaluator Scripts Logic and Baseline Verification](#5-custom-evaluator-scripts-logic-and-baseline-verification)
6. [User Management, CSV Imports and Credential PDFs](#6-user-management-csv-imports-and-credential-pdfs)
7. [Automated and Manual Backup Retention Rules](#7-automated-and-manual-backup-retention-rules)
8. [Worker Authentication, CLI Setup and SSE Telemetry](#8-worker-authentication-cli-setup-and-sse-telemetry)
9. [Audit Logging and Score Justification Trail](#9-audit-logging-and-score-justification-trail)

---

## 1. Challenge and Stage Lifecycle Management

The Admin Panel (`/admin`) is the central control point for configuring competitions (challenges) and managing multi-stage lifecycles.

### Stages Framework

Competitions on LavBench are structured around **Stages** (e.g., *Qualification Stage*, *Semifinals*, *Finals*). Each stage maintains independent configurations:
- **Timeframes**: Dedicated `start_time` and `end_time` deadlines per stage.
- **Task Allocations**: Specific machine learning tasks assigned to the stage.
- **Stage Navigation**: Competitors switch between active stages using the stage selector tab bar.

### Lifecycle States

| State | Condition / Indicator | System & Competitor Behavior |
| :--- | :--- | :--- |
| **Draft / Not Started** | `start_time` > current time | Visible only to Admins and assigned Jury members (`JuryChallenge`). Used for testing dataset uploads, metric scripts, and baseline runs. |
| **Active** | `start_time` ≤ current time ≤ `end_time` & `is_frozen=False` | Competitors browse active stage tasks, view rules, download starter code, and submit notebooks. |
| **Grace Period** | Post `end_time` (Timer turns orange) | Brief active buffer following deadline accepting pending or last-second submissions before pipeline closure. |
| **Frozen (Emergency)** | `is_frozen=True` | Instantly halts all incoming submissions and locks leaderboards across active stages during infrastructure issues without needing to alter `end_time`. |
| **Ended** | `end_time` < current time | Submissions closed. Automated scoring stops. Jury performs manual evaluations and code audits. |
| **Finalized** | `scores_finalized=True` | Standings locked. Competitor aliases de-anonymized. Post-finalization score edits require mandatory audit justification reasons. |
| **Archived** | `is_archived=True` | Read-only mode. Hidden from competitor dashboards; accessible only to Admins and Jury for historical analysis. |

> [!NOTE]
> Setting `is_frozen=True` allows administrators to pause evaluation queues instantly without corrupting competition deadline metadata or timer state history.

---

## 2. Sandbox Customization and Image Build Error Remediation

To safeguard worker nodes and guarantee fair hardware access, every machine learning task specifies resource limits, system packages, and container isolation settings.

### Hardware Allocations

- **RAM Limit (MB)**: Defines the Docker container memory limit (`--memory`). If competitor code exceeds this footprint, the process is instantly terminated by the kernel Out-Of-Memory (OOM) killer.
- **Time Limit (Seconds)**: Wall-clock runtime cap for execution inside the container. Exceeding this triggers a `TIMEOUT EXPIRED` failure.
- **GPU Required**: Boolean flag routing execution tasks to dedicated hardware acceleration GPU worker queues.
- **CPU Cores (`--cpus`)**: Number of CPU cores allocated per container (configured via `CPU_CORES_PER_TASK` / `GPU_CORES_PER_TASK` in `worker.env`).

### Sandbox Isolation Security

Competitor code runs within a hardened, zero-trust Docker container enforcing the following security parameters:

| Parameter | Purpose |
| :--- | :--- |
| `--network none` | Completely disables container networking — prevents data exfiltration and external downloads. |
| `--cap-drop ALL` | Drops all Linux kernel capabilities — blocks raw sockets, `mount()`, `ptrace()`, and privilege escalation. |
| `--read-only` | Mounts the root filesystem as read-only — competitor code cannot alter system libraries or binaries. |
| `--no-new-privileges` | Prevents process privilege escalation via SUID binaries. |
| `--tmpfs /tmp:noexec,nosuid,size=128m` | Provides a memory-backed, size-capped temporary directory that cannot execute binaries or fill host storage. |
| `--memory-swap` = RAM Limit | Disables disk swap — prevents memory footprint evasion. |
| `--pids-limit 64` | Restricts total process count to mitigate fork bombs. |
| `--ulimit nofile=256:256` | Caps open file descriptor counts. |

### Docker Image Build Pipeline & Error Troubleshooting

Each task gets a persistent container directory at `TASK_IMAGES_DIR/task_{id}/` containing downloaded Hugging Face assets, a generated `Dockerfile`, and `requirements.txt`. The container image is tagged `lavbench_task_{task_id}` and built automatically when task settings change.

#### Image Build Error Taxonomy:
1. **Base Image Failure**: The specified `base_docker_image` repository tag does not exist or fails registry authentication.
2. **APT Package Failure**: Invalid Ubuntu `apt_packages` names (e.g. typos or deprecated package names) cause `apt-get install` errors.
3. **Pip Dependency Failure**: Incompatible Python `pip_requirements` or version conflicts cause `pip install` resolution errors.
4. **HuggingFace Asset Timeout**: Network loss or invalid model/dataset IDs during pre-fetching cause download failures.
5. **Disk Space Exhaustion**: If the worker host falls below `MIN_BUILD_DISK_GB` (5 GB), task image compilation is aborted.

#### Inspecting & Resolving Build Errors:
1. Open **Admin Panel** → **Tasks** → select the failing task.
2. The UI highlights the `build_error` banner containing the exact Docker build stderr log traceback.
3. Fix the base image, APT package string, or Pip requirements in the task edit modal.
4. Saving the task re-triggers worker notification over Redis pub/sub (`rebuild_task_image`), clearing the error and building a fresh container.

---

## 3. Hugging Face Pre-Fetching and Offline Assets

Because execution sandboxes enforce `--network none` for security, model weights and datasets cannot be downloaded dynamically over the internet during competitor runs.

### Model and Dataset Pre-Fetching

Administrators can pre-configure Hugging Face assets for each task using the task administration panel:
- **`hf_datasets`**: Comma-separated list or JSON array of Hugging Face dataset IDs (e.g., `glue, sst2`).
- **`hf_models`**: Comma-separated list or JSON array of Hugging Face model repository IDs (e.g., `bert-base-uncased`, `distilbert-base-uncased`).

```json
{
  "hf_datasets": ["glue/sst2"],
  "hf_models": ["bert-base-uncased", "distilbert/distilbert-base-uncased"]
}
```

### Pre-Fetching Mechanism

1. During task setup or worker preparation, the background service triggers Hugging Face download routines (`huggingface_hub` / `datasets`).
2. Assets are fetched into the worker node's shared cache directory (`/root/.cache/huggingface`).
3. When sandbox containers launch, this local cache directory is read-only mounted into the container.
4. Competitor scripts using `transformers` or `datasets` load pre-cached models offline without network calls.

---

## 4. AST Code Security and Dynamic Metrics Engine

### Pre-Execution AST Validation

Before any submission is queued for execution, the server executes static application security testing (AST):

1. **IPython Magic Stripping**: Regex strips all IPython shell commands (`%matplotlib inline`, `!pip install`, `%timeit`) before AST parsing.
2. **Module Access Verification**:
   - `banned_imports`: Explicit list of forbidden Python modules (e.g., `os, sys, subprocess, socket, requests, urllib, shutil`).
   - `whitelisted_imports`: Restrictive allowed module list (when strict mode is activated).
3. **Quota Preservation**: If AST validation fails (syntax error or restricted import), the submission status is marked as `Failed`, detailed diagnostics are returned, and **the competitor's submission quota is preserved (not decremented)**.

### Dynamic Metrics Schema

Evaluation metrics are defined per task using a JSON schema weighting public and private score components.

**Example Multi-Metric Configuration:**
```json
{
  "accuracy": { "weight": 0.5, "higher_is_better": true },
  "f1": { "weight": 0.5, "higher_is_better": true }
}
```

### Supported Metric Categories (44 Metrics Across 12 Categories)

LavBench includes 44 evaluation metrics covering 12 problem domains:

| Category | Metric Keys | Description / Primary Use |
| :--- | :--- | :--- |
| **Classification** | `accuracy`, `f1`, `precision`, `recall`, `cohen_kappa`, `matthews_corrcoef` | Standard discrete prediction evaluation. |
| **Probabilistic** | `auc_roc`, `logloss`, `brier_score` | Calibrated continuous confidence scores. |
| **Regression** | `rmse`, `mse`, `mae`, `r_squared`, `mape`, `median_ae` | Continuous target error measurement. |
| **Seq-Labeling (NER)** | `seqeval_f1`, `seqeval_precision`, `seqeval_recall` | Entity extraction and token classification. |
| **Generative NLP** | `bleu`, `rouge`, `rouge_l`, `meteor`, `chrf`, `ter` | Translation, summarization, and text generation. |
| **QA Extractive** | `exact_match`, `f1` (word-overlap) | Reading comprehension token overlap. |
| **Object Detection** | `map_50`, `map_75`, `map_50_95`, `recall` (box recall) | Bounding box IoU and mAP evaluation. |
| **Segmentation** | `mean_iou`, `dice`, `pixel_accuracy` | Semantic and instance mask evaluation. |
| **Keypoints** | `oks`, `pck` | Pose estimation object keypoint similarity. |
| **Image Quality** | `psnr`, `ssim` | Image reconstruction and restoration metrics. |
| **Audio Quality** | `snr`, `mel_lsd`, `si_sdr` | Speech and audio processing quality. |
| **Clustering** | `adjusted_rand_index`, `normalized_mutual_info`, `adjusted_mutual_info`, `v_measure` | Unsupervised cluster grouping similarity. |
| **Retrieval** | `ndcg_k`, `recall_k`, `mrr` | Information retrieval and ranking metrics. |

---

## 5. Custom Evaluator Scripts Logic and Baseline Verification

### Custom Evaluator Script Architecture

For specialized ML problems where standard metrics are insufficient, admins can upload a custom Python evaluation script (`evaluator.py`).

#### Custom Evaluator Module Contract:
Each custom evaluator script **must** define the following module-level variables and entry-point function:

```python
METRIC_NAME = "custom_f1_score"

SUBMISSION_COLUMNS = [
    {"name": "id", "type": "string"},
    {"name": "prediction", "type": "int"},
]

LABELS_COLUMNS = [
    {"name": "id", "type": "string"},
    {"name": "label", "type": "int"},
]

EVALUATOR_OPTIONS = {
    "beta": 1.0,
}

def evaluate(df_sub, df_labels, options=None):
    """
    Evaluates competitor predictions against ground truth labels.
    
    :param df_sub: pandas.DataFrame loaded from competitor's submission.parquet
    :param df_labels: pandas.DataFrame loaded from hidden labels.parquet
    :param options: dict parsed from task's metrics_config / options_schema
    :return: dict[str, float] mapping metric names to score values
    """
    options = options or EVALUATOR_OPTIONS
    # Join DataFrames on 'id'
    merged = df_sub.merge(df_labels, on="id", suffixes=("_sub", "_gt"))
    
    # Calculate domain-specific metric logic
    correct = (merged["prediction"] == merged["label"]).sum()
    total = len(merged)
    score = float(correct / total) if total > 0 else 0.0
    
    return {METRIC_NAME: score}
```

#### Variable Specifications:
- `METRIC_NAME`: `str` — Identifier key returned in the dictionary and displayed on the leaderboard.
- `SUBMISSION_COLUMNS`: `list[dict]` — Expected columns and data types in `submission.parquet`. Used by UI for schema documentation cards.
- `LABELS_COLUMNS`: `list[dict]` — Expected columns in `labels.parquet`.
- `EVALUATOR_OPTIONS`: `dict` — Optional default parameters passed to `options`.
- `evaluate()`: `function` — Main evaluation logic receiving DataFrames and returning `dict[str, float]`. All returned metric scores are treated as **higher-is-better**.

> [!IMPORTANT]
> Custom evaluator scripts are validated via AST on upload. If required variables (`METRIC_NAME`, `SUBMISSION_COLUMNS`, `LABELS_COLUMNS`, or `evaluate`) are missing, upload returns HTTP 400 with an error description.

### Baseline Solution Testing (`is_baseline`)

Administrators and organizers can submit baseline solutions to verify task integrity:
- When submitting a notebook as an admin, check the **"Mark as Baseline Solution"** toggle (`is_baseline=True`).
- Baseline submissions bypass daily user quota limits.
- Successfully evaluated baseline solutions generate benchmark entries on the leaderboard and populate the downloadable **starter baseline notebook** for competitors.

---

## 6. User Management, CSV Imports and Credential PDFs

### Bulk Competitor Onboarding via CSV

Administrators can onboard competitors in bulk via the `/admin` portal using standard CSV files.

#### Required CSV Header Structure:
```csv
name,surname,middle_name,birth_date,grade,school,city
```

#### Optional Fields:
`email` and `is_anonymous` can be included in the CSV header.

#### Example CSV Content:
```csv
name,surname,middle_name,birth_date,grade,school,city,email,is_anonymous
Alice,Smith,Ivanova,2008-05-12,11,Tech High,Sofia,alice@example.com,false
Bob,Jones,Petrov,2007-09-20,12,Math Gym,Plovdiv,,false
```

### Printable PDF Credential Slips

To distribute credentials securely during on-site competitions:

1. Navigate to **Admin Panel** → **Challenges**.
2. Select the target challenge and click **Print Credentials PDF**.
3. The server calls `/api/admin/challenges/<id>/credentials-pdf` to generate a multi-page PDF document.
4. Each page contains formatted credential cut-out slips featuring:
   - Competitor Name & Alias
   - Auto-generated Username & Password
   - Platform Login URL & Scannable QR Code
   - Challenge Name & Stage Details

---

## 7. Automated and Manual Backup Retention Rules

LavBench maintains an automated backup subsystem to safeguard competition data. Each backup archive contains a complete PostgreSQL database dump along with compressed `uploads/` assets in a `.tar.gz` format.

| Backup Type | Trigger Frequency | Retention Policy | Management & API Constraints |
| :--- | :--- | :--- | :--- |
| **Auto-Backup** | Every **20 minutes** during active competitions; every **6 hours** when idle. | Keeps the **6 most recent** backups. Older auto-backups are automatically purged. | System managed (`auto_YYYYMMDD_HHMMSS.tar.gz`). Cannot be deleted manually via API (returns HTTP 403). |
| **Manual Backup** | Triggered on demand via **"Force Backup Now"** button. | Retained **indefinitely**. Never auto-deleted by retention routines. | Administrator managed (`manual_YYYYMMDD_HHMMSS.tar.gz`). Downloadable or deletable via Admin Panel. |

---

## 8. Worker Authentication, CLI Setup and SSE Telemetry

### Ed25519 Asymmetric Worker Authentication

Worker nodes communicate securely with the backend API using asymmetric Ed25519 signature keys:
- The worker node signs requests using its private key.
- Tokens are passed in the `X-Worker-Token` HTTP header.
- The backend verifies worker signatures against registered public keys before accepting job status updates.

### Interactive Worker Setup CLI (`make setup-worker`)

Execution workers are configured and launched using interactive CLI commands:

```bash
# 1. Fetch environment template from server:
scp user@server:~/lavbench/worker.env .

# 2. Run interactive setup wizard:
make setup-worker
```

The `make setup-worker` wizard guides you through:
1. **Execution Engine Mode**: Docker sandbox container (recommended) or local environment.
2. **Worker Node Type**: `evaluation` (runs competitor code), `internal` (handles system tasks/backups), or `both`.
3. **GPU Configuration**: Select GPU IDs detected via `nvidia-smi`.
4. **CPU Core Allocation**: Set CPU core limits per task container.
5. **Worker Concurrency**: Auto-calculates optimal worker concurrency based on GPU and CPU availability.

#### Deploying and Editing Workers:

```bash
# Launch worker process:
make deploy-worker

# Re-configure worker parameters via menu editor:
make edit-worker
```

> [!WARNING]
> When running an evaluation worker on the primary web server host, reserve at least 2 CPU cores for Gunicorn, PostgreSQL, and Redis processes.

### SSE Cluster Telemetry

Real-time worker cluster health is streamed to the administrator navbar via Server-Sent Events (SSE):
- **Status Indicator**: Green badge (workers connected and healthy) / Red badge (workers disconnected).
- **Cluster Modal**: Clicking the indicator displays live worker telemetry, including CPU cores, RAM, GPU model, VRAM usage, and active execution slots.
- **Dead Letter Queue (`/api/admin/dead-letters`)**: Displays permanently failed Celery evaluation tasks with complete error tracebacks for diagnostic debugging.

---

## 9. Audit Logging and Score Justification Trail

### Audit Logging System

Every sensitive administrative and jury operation is permanently recorded in the system audit trail (`AuditLog` database table).

- **Tracked Operations**:
  - Challenge, stage, and task creation, modification, or deletion.
  - Lifecycle state transitions (`finalize`, `archive`, `freeze`).
  - Account creation, CSV user imports, and password resets.
  - Competitor disqualifications (`is_disqualified`) and baseline flags (`is_baseline`).
  - Manual score modifications.

### Post-Finalization Score Modification Justifications

If an administrator or jury member modifies a competitor score after a competition has been finalized (`scores_finalized=True`):

1. The user interface presents a mandatory **Audit Justification Modal**.
2. The user must enter a detailed justification reason explaining the adjustment (e.g., *"Re-evaluation approved by jury due to baseline dataset formatting revision"*).
3. The backend records an immutable log entry containing:
   - User ID & Role of the editor
   - Target Competitor & Submission ID
   - Original Score vs Updated Score
   - ISO Timestamp
   - Textual Justification Reason

Administrators can inspect these audit trails at any time via **Admin Panel** → **Audit Logs**.
