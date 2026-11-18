# Administrator Portal Complete Guide

Welcome to the LavBench Platform Administrator Portal. This guide details every aspect of configuring, managing, and maintaining the platform, executing worker nodes, configuring security rules, building task Docker images, and implementing custom evaluator scripts.

## Initial Setup

After deploying the platform, initialize the admin account via the Makefile target (recommended) or the script directly:

```bash
make setup-admin            # docker compose exec backend + fetch credentials into admin_credentials.txt
# or, on a bare deployment without the compose stack:
python backend/scripts/setup-admin.py
```

This generates an initial administrator account, creates master credentials, and outputs them to `admin_credentials.txt` in the root directory. Log in through the main web interface with these credentials.

> [!TIP]
> End-to-end verification of the running platform (auth/CSRF, role matrix, rate limits, backups, SSE) is available via `python3 scripts/api_smoke_test.py` — exit code 0 on success.

> [!IMPORTANT]
> Run `setup-admin.py` only once on a fresh deployment. Re-running this script will reset system administrator access.

---

## Table of Contents

1. [Challenge and Stage Lifecycle Management](#1-challenge-and-stage-lifecycle-management)
2. [Sandbox Customization and Image Build Error Remediation](#2-sandbox-customization-and-image-build-error-remediation)
3. [Hugging Face Data: One ZIP per Task](#3-hugging-face-data-one-zip-per-task)
4. [AST Code Security and Dynamic Metrics Engine](#4-ast-code-security-and-dynamic-metrics-engine)
5. [Custom Evaluator Scripts Logic and Baseline Verification](#5-custom-evaluator-scripts-logic-and-baseline-verification)
6. [User Management, CSV Imports and One-Time Credentials](#6-user-management-csv-imports-and-one-time-credentials)
7. [Automated and Manual Backup Retention Rules](#7-automated-and-manual-backup-retention-rules)
8. [Worker Authentication, CLI Setup and SSE Telemetry](#8-worker-authentication-cli-setup-and-sse-telemetry)
9. [Audit Logging and Score Justification Trail](#9-audit-logging-and-score-justification-trail)
10. [Student Workspaces (nanoColab)](#10-student-workspaces-nanocolab)
11. [Task Evaluation Modes and Workspace Submissions](#11-task-evaluation-modes-and-workspace-submissions)

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
| **Grace Period** | After `end_time` (timer turns orange) | 3 minutes (`DEADLINE_GRACE_PERIOD_SECONDS`, default 180) during which new submissions are still accepted. A submission accepted then runs to completion and stays viewable. |
| **Frozen (Emergency)** | `is_frozen=True` | Instantly halts all incoming submissions and locks leaderboards across active stages during infrastructure issues without needing to alter `end_time`. |
| **Ended** | `end_time` < current time | Submissions closed. Automated scoring stops. Jury performs manual evaluations and code audits. |
| **Finalized** | `scores_finalized=True` | Standings locked. Competitor aliases de-anonymized. Post-finalization score edits require mandatory audit justification reasons. |
| **Archived** | `is_archived=True` | Read-only mode. Hidden from competitor dashboards; accessible only to Admins and Jury for historical analysis. |

> [!NOTE]
> Setting `is_frozen=True` allows administrators to pause evaluation queues instantly without corrupting competition deadline metadata or timer state history.

### Challenge ZIP Export and Import Limits

Challenge export creates a portable ZIP containing `challenge.json` and task files under
`tasks/<task-id>/`. Import accepts that layout and is bounded by five server settings:

| Variable | Default | Meaning |
| :--- | :--- | :--- |
| `CHALLENGE_ARCHIVE_MAX_COMPRESSED_BYTES` | `209715200` bytes (200 MiB) | Maximum uploaded ZIP stream size, enforced even when `Content-Length` is absent or untrusted. |
| `CHALLENGE_ARCHIVE_MAX_UNCOMPRESSED_BYTES` | `2147483648` bytes (2 GiB) | Maximum aggregate uncompressed size. |
| `CHALLENGE_ARCHIVE_MAX_MEMBER_BYTES` | `524288000` bytes (500 MiB) | Maximum uncompressed size of one member. |
| `CHALLENGE_ARCHIVE_MAX_MEMBERS` | `1000` entries | Maximum ZIP entry count. |
| `CHALLENGE_ARCHIVE_MAX_COMPRESSION_RATIO` | `100:1` | Maximum uncompressed-to-compressed ratio per non-empty member. |

Imports are rejected when any limit is exceeded. Validation also rejects duplicate member names
or normalized targets, encrypted or special-file entries, absolute/traversal/backslash paths,
unexpected archive layouts, a missing `challenge.json`, and unsafe task-file extensions.

The export leaves each task's Hugging Face ZIP out; `challenge.json` records its SHA-256, size and
folders. An imported task shows "The Hugging Face data was not included in the import. Upload the
ZIP again." on its **Environment** tab until you upload the ZIP or remove the data (see
[section 3](#3-hugging-face-data-one-zip-per-task)).

### Editing Forms

Every form with several fields opens as an editor in place of the list: **Edit** on a competition or a stage, **Add Stage**, **Add Task** and **Edit Config** on a task, and **Edit** on a competitor (**Competitor Registrations**) or a user account (**User Management**).

- The editor opens at its top with the cursor in the first field. Its title and **Back** are at the top; **Cancel** and the save button are at the bottom and stay visible while you scroll.
- Saving, **Cancel** or **Back** returns to the list at the button that opened the editor.
- With unsaved changes, **Back**, **Cancel** or another tab of the admin sidebar asks "Discard unsaved changes?": **Discard changes** leaves the form, **Keep editing** stays. The browser also warns before you leave the page.
- When a save fails, the form jumps to the first field with a problem and shows the message under it: a missing required field, an invalid email or a check made by the server.
- The task editor starts with **Evaluation mode** (see [section 11](#11-task-evaluation-modes-and-workspace-submissions)). A notebook task has five tabs: **General**, **Evaluation**, **Sandbox**, **Environment** and **Files**; a file task runs no code and has no **Sandbox** tab, and its **Environment** tab holds only the Hugging Face data. A failed save first opens the tab that holds the field, for example **Environment** for an invalid Docker image, or **Files** for a missing baseline notebook, shown under its drop zone. A missing `labels.parquet` or `baseline_submission.parquet` does not block the save: it shows under **Task Problems** until the file is uploaded. Until `labels.parquet` is uploaded, the task refuses every submission, staff test runs included ("This task is not ready for submissions yet."); nothing is recorded and no quota is used.

### The Upload List

Task data files can be large, so the task editor saves in two steps:

1. **Create Task** or **Save Changes** sends the settings, the baseline or starter notebook and the evaluator script (each at most 16 MiB). After a create, the editor becomes the saved task: its title changes to "Edit Task" and a second save never creates a second task.
2. The **Uploads** list at the top of the editor then works through the file changes one at a time. First the removals: every file you marked with **Delete** and, if you clicked **Remove**, the Hugging Face data, each as a row "Remove <name>". Then every data file you dropped (public and hidden, including `labels.parquet` and `baseline_submission.parquet`) and the Hugging Face ZIP upload. `labels.parquet` goes first, because `baseline_submission.parquet` is checked against it. A new `labels.parquet` is never refused because of the stored `baseline_submission.parquet`; if the stored one no longer fits the new labels, the task shows the mismatch under **Task Problems**, with how many ids differ, and refuses submissions until you upload a fitting one.

Each upload row shows the file name, its size, a progress bar with the percent and the time left, and a state:

| State | Meaning |
| :--- | :--- |
| **Waiting** | Queued behind the file that is uploading. **Cancel** removes it from the queue. |
| **Uploading** | The bytes are being sent. **Cancel** stops the upload. |
| **Checking** | Every byte arrived and the server is checking the file (for example the labels schema). It cannot be cancelled any more. |
| **Done** | The file is stored and listed with the task's files. |
| **Failed** | The reason is shown under the row, for example a file that is too large (with the limit), too little free disk space on the server, or an invalid `labels.parquet`. **Retry** sends it again. When the server asks to wait, the row shows "Try again in N seconds." and **Retry** waits for it. |
| **Cancelled** | You stopped it. **Retry** sends it again. |
| **Removing** | A removal row: the server is removing the file. |

A removal row has no size or progress bar. It shows **Waiting** (with **Cancel**), **Removing**, then **Done** or **Failed** with the reason and **Retry**. A file whose removal failed stays with the task until **Retry** succeeds.

- The line above the rows sums up the progress, for example "2 of 4 files, 1.3 GB of 5.2 GB".
- A failed file does not stop the others: the list continues with the next file.
- When you save the same file again, its earlier **Failed** or **Cancelled** row is replaced by the new one.
- A file is stored only once it arrived completely and passed its checks; a replaced file stays in use until its replacement passes. An interrupted upload starts again from the beginning.
- When every file is **Done**, the editor closes with the usual confirmation. When a file failed or was cancelled, the editor stays open with "The task is saved, but some files were not uploaded or removed. Retry them in the upload list."
- While files upload, **Back**, **Cancel** or closing the browser tab asks first ("Stop the uploads?"). **Close and cancel** stops the files not yet finished; the files already uploaded stay with the task. **Keep uploading** stays in the editor.
- A data file may be up to `TASK_FILE_MAX_BYTES` (10 GiB by default); a larger one fails with the limit in its message.

A new competition starts in your browser's time zone and with **GPU** off; change either in the form before you save.

The forms that are always open (the **Create Competition** tab, **Manual Competitor Registration**, **Import Competitors CSV** and **Register User Account**) use the same layout without **Back** or **Cancel**, and also show their errors under the fields.

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
| `--storage-opt size` | Mandatory size cap for the container root writable layer (default `8g`, `WORKER_SANDBOX_STORAGE_OPT`). Evaluation fails closed unless the Docker storage driver supports per-container quotas (for example XFS with `pquota`). The separate disposable anonymous volume at `/app` is not covered by this quota. |
| Output collection caps | `MAX_COLLECT_BUFFER_BYTES` / `MAX_EXTRACT_MEMBER_BYTES` (default 512 MB) cap how much output is pulled back from the sandbox. Oversized archives and individual members are skipped and logged rather than buffered unbounded on the host — protects the worker from decompression bombs. |

### Docker Image Build Pipeline & Error Troubleshooting

Each task gets a persistent container directory at `TASK_IMAGES_DIR/task_{id}/` containing a generated `Dockerfile` and `requirements.txt`. The container image is tagged `lavbench_task_{task_id}` and built automatically when task settings change.

#### Image Build Error Taxonomy:
1. **Base Image Failure**: The specified `base_docker_image` repository tag does not exist or fails registry authentication.
2. **APT Package Failure**: Invalid Ubuntu `apt_packages` names (e.g. typos or deprecated package names) cause `apt-get install` errors.
3. **Pip Dependency Failure**: Incompatible Python `pip_requirements` or version conflicts cause `pip install` resolution errors.
4. **Disk Space Exhaustion**: If the worker host falls below `MIN_BUILD_DISK_GB` (5 GB), task image compilation is aborted.

#### Inspecting & Resolving Build Errors:
1. Open **Admin Panel** → **Manage Competitions & Tasks** and click **Edit Config** on the failing task.
2. The **Environment** tab of the task editor shows a **Task Problems** banner listing every machine-readable problem code (e.g. `ERR_TASK_BUILD_FAILED`, `ERR_BASELINE_FAILED`) with a human-readable explanation.
3. Fix the base image, APT package string, or Pip requirements on the **Environment** tab and click **Save Changes**.
4. Saving a change to the base image, packages, task files or evaluator code changes the image's configuration hash, so the next build (the baseline run that follows the change, or the next submission) builds a fresh image. A successful build removes the remaining build-family codes automatically; baseline problems clear when the baseline evaluation completes.
5. **Re-uploading a task file (or `labels.parquet`) under the same filename always replaces the previous copy**: the platform stores uploads under unique `saved_name`s, so the worker cache detects the change, re-syncs the new bytes into `TASK_IMAGES_DIR/task_{id}/data` (snapshotted into the per-run sandbox at `/app/data` at launch) and re-bakes the image — students always see the current file, never a stale copy.

---

## 3. Hugging Face Data: One ZIP per Task

Notebooks work offline: the sandbox of a submission runs with `--network none`, and a notebook must behave the same in the workspace. Models and datasets a task needs therefore come with the task, as one ZIP that you build once and upload in the task editor. Scoring itself never reads these files; only the student's notebook does.

### Building the ZIP

The ZIP holds only the folders that `hf download ... --local-dir` creates, one per repository:

```bash
hf download <org>/<name> --local-dir models/<org>/<name>
hf download <org>/<name> --repo-type dataset --local-dir datasets/<org>/<name>
zip -r hf-data.zip models datasets
```

- Every file must sit under `models/<org>/<name>/` or `datasets/<org>/<name>/`, and the ZIP must hold at least one such file. Anything else is refused, and the message names the offending path.
- Hidden files and folders (any path part that starts with `.`, such as `.cache/huggingface/` or `.gitattributes`) are skipped, not refused. The editor shows how many were skipped.
- Entries must be plain files, stored or deflated, without encryption or links.
- Every model must fit in the workspace memory and, for a notebook task, in the task's RAM limit.

### Uploading, Replacing and Removing

1. Open **Edit Config** (or **Add Task**) and the **Environment** tab. **Hugging Face data** is there for notebook and file tasks.
2. Drop the ZIP on **ZIP with models/ and datasets/** (or **Replace with another ZIP**). The ZIP uploads after you save, as the last row of the upload list (see [The Upload List](#the-upload-list)).
3. When it is **Done**, the section shows the folders, the unpacked size, the number of files, the hidden files skipped and the start of the ZIP's SHA-256.
4. **Remove** marks the data for removal: the folders are struck through with "Removed when you save. Notebooks that read these folders fail until you upload a ZIP again." **Undo Delete** keeps the data. **Save Changes** removes it as a row of the upload list, before the uploads. Dropping a new ZIP instead replaces the data without a separate removal.

Administrators and the jury can upload and remove the data. Once the task's workspace environment is published, the data is fixed like the public files ("The workspace environment is published, so these files are fixed.").

### Limits

| Limit | Default | When it is exceeded |
| :--- | :--- | :--- |
| `HF_ZIP_MAX_BYTES` | 10 GiB | The upload fails with the limit in its message. |
| `NANOCOLAB_PACKAGE_MAX_BYTES` | 10 GiB | With workspaces on, the public files, notebooks and every HF ZIP of the same environment together must fit; the message gives the projected size and the limit. |
| Files in the workspace package | 2,000 | Counted the same way; the message gives the projected count. |

With workspaces on, two tasks of the same environment may carry the same folder (for example `models/<org>/<name>`) only with identical content; otherwise the upload is refused and the message names the folder and the other task.

### Where Students Find the Data

- In the workspace, the folders sit at the root next to the task folders: `/workspace/models/<org>/<name>` and `/workspace/datasets/<org>/<name>`, read-only.
- In the notebook run of a submission, the same folders are mounted read-only next to the task folder, so the same relative paths work: from the notebook, `../models/<org>/<name>` and `../datasets/<org>/<name>`. Only this task's data is visible, and `HF_HUB_OFFLINE`, `HF_DATASETS_OFFLINE` and `TRANSFORMERS_OFFLINE` are set.
- The task page lists the folders with these relative paths, only where the data reaches the student: always for a notebook task, and for a file task only when the competition has workspaces.

Workers download a task's ZIP from the server the first time a submission needs it, check its SHA-256 and size, unpack it into `HF_CACHE_DIR` and reuse it; a cache unused for `HF_CACHE_UNUSED_DAYS` (14) days is removed. A download or unpacking failure is a platform failure (**Platform error**) and never counts against the student.

---

## 4. AST Code Security and Dynamic Metrics Engine

### Pre-Execution AST Validation

Before any submission is queued for execution, the server executes static application security testing (AST):

1. **IPython Magic Stripping**: Regex strips all IPython shell commands (`%matplotlib inline`, `!pip install`, `%timeit`) before AST parsing.
2. **Module Access Verification**:
   - `banned_imports`: Explicit list of forbidden Python modules (e.g., `os, sys, subprocess, socket, requests, urllib, shutil`).
   - `whitelisted_imports`: Restrictive allowed module list (when strict mode is activated).
3. **Quota Preservation**: If AST validation fails (syntax error or restricted import), the
   request returns detailed diagnostics before a Submission row is created and before daily or
   task-period quota accounting. **No submission entry is created and no quota is consumed.**
   Baseline runs and platform failures (`detailed_status` `failed_infra`: the submission could
   not be enqueued, no worker took it within an hour, its worker was lost, or the worker could
   not sync task files, get a GPU, reach Docker, build the image or finish within the Celery time
   limit) never count either. The daily limit resets at midnight in the challenge's timezone.

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

Custom evaluators run on the CPU evaluation workers as a limited process, with the worker's Python libraries, at most 1024 MiB of memory and 300 seconds (`CUSTOM_EVALUATOR_MEMORY_MB`, `CUSTOM_EVALUATOR_TIME_LIMIT_SECONDS`). The process is not isolated from the network or the worker's files, so only admins and the jury may upload evaluators, and every upload is audited.

> [!IMPORTANT]
> Custom evaluator scripts are validated via AST on upload. If required variables (`METRIC_NAME`, `SUBMISSION_COLUMNS`, `LABELS_COLUMNS`, or `evaluate`) are missing, upload returns HTTP 400 with an error description.

### Baseline Solution Testing (`is_baseline`)

Each task's baseline notebook is evaluated automatically to verify the task:
- A baseline run is queued when the task is created and whenever its environment, files or scoring change; there is no manual toggle. Several changes in a row (a save, then its file uploads) give one run, about 60 seconds after the last change.
- Baseline runs are queued at priority 0, like admin and jury test runs, ahead of every competitor submission.
- Baseline runs never count toward any quota.
- Every way a baseline run ends settles the task the same way: the worker report, a run no worker picked up, a lost worker, the Celery time limit, **Kill**, or **Clear Queue** while it waits. A completed baseline removes `ERR_BASELINE_FAILED` from the task. A failed, killed or cleared baseline sets it, which blocks competitor submissions; saving the task queues a new baseline run.
- A baseline that ends with a platform failure (`detailed_status` `failed_infra`: never picked up, lost worker, GPU, Docker or the Celery time limit) is retried automatically as a new baseline run, at most 2 times (3 attempts in total). Each attempt stays in the submission list with its own logs. After the last retry fails, the task gets `ERR_BASELINE_FAILED`.
- There is no retry when the task already has another problem code, such as an image build or file sync failure, because every run would fail the same way: fix the task and save it to queue a new baseline. There is no retry either when the queue refused the run (the broker was unavailable): save the task again once the queue is back.
- Successfully evaluated baseline solutions populate the downloadable **starter baseline notebook** for competitors and appear as a **Baseline** row on that task's leaderboard tab only, never on the general or stage tabs. The row shows the fixed label "Baseline" and its scores, never the staff account that ran it. It is an unranked reference line placed where its score falls in the task's metric direction (lower-is-better tasks too), so the best competitor is #1 on every tab. It is hidden once the challenge is finalized and results are revealed, because tabs are then ordered by manual points.

---

## 6. User Management, CSV Imports and One-Time Credentials

### Bulk Competitor Onboarding via CSV

Administrators can onboard competitors in bulk via the `/admin` portal using standard CSV files.

#### Required CSV Header Structure:
```text
name,surname,middle_name,birth_date,grade,school,city
```

#### Optional Fields:
`email` and `is_anonymous` can be included in the CSV header.

#### Example CSV Content:
```text
name,surname,middle_name,birth_date,grade,school,city,email,is_anonymous
Alice,Smith,Ivanova,2008-05-12,11,Tech High,Sofia,alice@example.com,false
Bob,Jones,Petrov,2007-09-20,12,Math Gym,Plovdiv,,false
```

### Jury Accounts

1. Open **Admin Panel** → **User Management**.
2. In **Register User Account**, set **Role** to **Jury** and fill in the name.
3. Choose at least one competition in **Assign Competitions**. Without one, the account is refused with "Assign the jury member to at least one competition." under the field, because a jury member without a competition can see nothing.
4. Click **Register User** and hand over the username and password shown.

The same rule applies when you edit an account: removing a jury member's last competition, or changing a competitor to **Jury** without choosing one, is refused with the same message under **Assign Competitions**.

### One-Time Credential Slips

To distribute credentials securely during on-site competitions:

1. Open **Admin Panel** → **Competitor Registrations**.
2. Click **Reset All Passwords in Challenge**, choose the **Competition** in the **Bulk Reset Passwords** dialog, click **Continue**, and confirm in **Confirm Bulk Reset** (3 resets per 300 s).
3. Every competitor in that challenge gets a new random password, and the browser immediately saves a CSV file (`<competition>_competitors_credentials_<date>.csv`) with each competitor's ID, name, middle name, surname, birth date, username and new password.
4. The passwords exist only in that response: the server keeps no copy and the file cannot be downloaded again. Keep it safe; if it is lost, reset the passwords again.

Print a slip per competitor from the CSV. Only administrators can run a bulk reset, so the jury never receives competitors' passwords.

---

## 7. Automated and Manual Backup Retention Rules

LavBench maintains an automated backup subsystem to safeguard competition data. Full archives contain a complete PostgreSQL database dump along with the `uploads/` assets in a `.tar.gz`; database-only archives contain the dump alone.

| Backup Type | Trigger Frequency | Retention Policy | Management & API Constraints |
| :--- | :--- | :--- | :--- |
| **Auto-Backup (full)** | Every **6 hours**, during active competitions and when idle. | Keeps the newest **3** (`BACKUP_RETENTION_COUNT`). Older ones are purged automatically. | System managed (`auto_YYYYMMDD_HHMMSS.tar.gz`). Cannot be deleted manually via API (returns HTTP 403). |
| **Auto-Backup (database only)** | Every **20 minutes** during active competitions. | Keeps the newest **18** (`BACKUP_DB_RETENTION_COUNT`), about 6 hours of history, which reaches back to the previous full backup. | System managed (`auto_db_YYYYMMDD_HHMMSS.tar.gz`). Cannot be deleted manually via API (returns HTTP 403). |
| **Manual Backup** | Triggered on demand via **"Force Backup Now"** button. | Retained **indefinitely**. Never auto-deleted by retention routines. | Administrator managed (`manual_YYYYMMDD_HHMMSS.tar.gz`). Downloadable or deletable via Admin Panel; deleting asks for confirmation first (**Delete backup?**). |

A backup is skipped unless the disk has at least twice the size of the previous backup of the same kind free (and at least `MIN_BACKUP_DISK_GB`). A skipped or failed automatic backup is retried at the next 20-minute check. Rotated log files are not backed up.

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

External workers are **evaluation-only**. The former `internal` and `both` worker types no longer exist — the only internal worker is the `celery_worker` service inside Docker Compose (`-Q celery,internal`), which handles system tasks (backups, watchdog, leaderboard recalculation). Every evaluation worker consumes `cpu_queue`; a host set up with GPUs (`GPU_WORKER_CONCURRENCY` above 0) also runs a second worker on `gpu_queue`. The weekly Docker image prune and the daily task-directory sweep are scheduled on both queues, so each host cleans up after itself.

The `make setup-worker` wizard guides you through:
1. **Execution Engine Mode**: Docker sandbox container (recommended) or local environment.
2. **GPU Configuration**: Select GPU IDs detected via `nvidia-smi`.
3. **CPU Core Allocation**: Set CPU core limits per task container.
4. **Worker Concurrency**: Auto-calculates optimal worker concurrency based on GPU and CPU availability.

#### Per-Worker Hardening Knobs

Workers are configured **individually** in `worker.env` — there is no server-side inheritance. The wizard and `deploy-worker.sh` recognize the following extra settings:

| Variable | Purpose |
| :--- | :--- |
| `WORKER_GPU_ID` | Comma-separated GPU IDs this worker may use (e.g. `0,1,3`), written by `scripts/setup-worker.sh`. Each GPU sandbox locks one free device in Redis and pins it (`DeviceRequest(device_ids=[...])`). When unset, a GPU sandbox uses `count=-1` (requests all GPUs) and logs a warning. |
| `WORKER_SANDBOX_STORAGE_OPT`, `MAX_COLLECT_BUFFER_BYTES`, `MAX_EXTRACT_MEMBER_BYTES` | Per-worker task-execution caps mirroring the server defaults. All are hard limits; the Docker storage driver must enforce `storage-opt`. |
| `MAX_WORKER_LOG_BYTES` | Rotation threshold for the worker remote log (`worker_remote.log` shipped to the server via `/api/workers/logs`). Default 10 MB. |

The compose `celery_worker` service (system tasks only) runs with `init`, `cap-drop: ALL` plus the minimal `CHOWN`/`SETUID`/`SETGID` capabilities needed to drop privileges to `nobody`, `no-new-privileges`, and memory/CPU caps set via `WORKER_MEM_LIMIT`/`WORKER_CPU_LIMIT`. It never executes untrusted submission code — evaluation runs in the separate eval-worker sandboxes.

> [!NOTE]
> Workers need no Hugging Face access: they download each task's Hugging Face ZIP from the server (see [section 3](#3-hugging-face-data-one-zip-per-task)).

#### Deploying and Editing Workers:

```bash
# Launch worker process:
make deploy-worker

# Re-configure worker parameters via menu editor:
make edit-worker
```

> [!WARNING]
> When running an evaluation worker on the primary web server host, reserve at least 2 CPU cores for Gunicorn, PostgreSQL, and Redis processes.

### System Status Panel

The **Workers and queues** panel in the Admin Panel (admins and jury) polls `GET /api/admin/system-status` every 15 seconds. It never queries the workers directly; everything comes from worker heartbeats, the broker and the database:
- **Status**: the overall status and its `api` and `scoring` components, in Statuspage terms (`operational`, `degraded_performance`, `partial_outage`, `major_outage`).
- **Queues**: live consumers and pending messages for each evaluation queue (`cpu_queue`, `gpu_queue`).
- **Workers**: every worker that has sent a heartbeat, with its queues, online or stale state, last heartbeat, concurrency, CPU cores, RAM and GPU. Workers send a heartbeat every 30 seconds (`WORKER_HEARTBEAT_SECONDS`) and count as stale after 90 seconds (`WORKER_HEARTBEAT_STALE_SECONDS`).
- **Submissions**: queued and running submissions, how long the oldest queued one has waited, and completions and failures in the last 15 minutes.
- **Dead Letter Queue (`/api/admin/dead-letters`)**: Displays permanently failed Celery evaluation tasks with complete error tracebacks for diagnostic debugging.

Scoring is `major_outage` when no live worker consumes `cpu_queue`, `partial_outage` when another queue has pending work but no consumer, and `degraded_performance` when the oldest queued submission has waited longer than 10 minutes (`STATUS_QUEUE_DEGRADED_SECONDS`).

`GET /api/status` is a public, unauthenticated summary with the same status words, cached for 30 seconds. Point an external uptime check at it and alert on `major_outage`. `GET /api/health` stays a liveness check (database, both Redis instances, disk) for the container health checks.

---

## 9. Audit Logging and Score Justification Trail

### Audit Logging System

Every sensitive administrative and jury operation is permanently recorded in the system audit trail (`AuditLog` database table).

- **Tracked Operations**:
  - Challenge, stage, and task creation, modification, or deletion.
  - Lifecycle state transitions (`finalize`, `archive`, `freeze`).
  - Account creation, CSV user imports, and password resets.
  - Manual score modifications, by jury members or admins.
  - Workspace environments: **Publish**, **Extend** (with its reason), **Sync** (a problem that appears or clears, shown as **System**) and **Open workspace**, with the student who opened it as the actor. Changes to the **Student workspaces** setting are logged with the competition's **Update**.

### Post-Finalization Score Modification Justifications

If an administrator or jury member modifies a competitor score after a competition has been finalized (`scores_finalized=True`):

1. The manual points dialog on the **Leaderboard** shows a mandatory **Reason / Changelog note** field.
2. The user must enter a detailed justification reason explaining the adjustment (e.g., *"Re-evaluation approved by jury due to baseline dataset formatting revision"*). Without it, the dialog does not save and shows the message under the field.
3. The backend records an immutable log entry containing:
   - User ID & Role of the editor
   - Target Competitor & Submission ID
   - Original Score vs Updated Score
   - ISO Timestamp
   - Textual Justification Reason

Administrators can inspect these audit trails at any time via **Admin Panel** → **Audit Logs**.

---

## 10. Student Workspaces (nanoColab)

When the platform is connected to nanoColab (`NANOCOLAB_API_URL` is set), students can work in a JupyterLab workspace that already holds their task files. Without that connection, no workspace setting or card appears anywhere.

You choose the workspace setting once per competition. Every stage, the test stage included, gets its own workspaces from that setting; a competition without stages uses it directly. Each task gets a folder in the workspace root, named by the task's folder name (from its title, for example `image-classification/`), holding the task's public files and its baseline notebook as `solution.ipynb`. Hidden files such as `labels.parquet` never reach the workspaces.

### Choosing the Setting

1. Open **Admin Panel** → **Create Competition**, or **Manage Competitions & Tasks** → **Edit** on the competition. The **Student workspaces** section is part of the form.
2. Turn on **Give students a nanoColab workspace** and fill in:
   - **Workspace image**: chosen from nanoColab's catalog. Hover the info icon to see its installed libraries.
   - **CPU profile**: one of the profiles nanoColab publishes, for example "CPU Compact (2 vCPU, 8 GiB memory)" or "CPU Standard (2 vCPU, 12 GiB memory)". The profiles differ in memory, and a single model must fit in memory, so pick the larger profile for bigger models. When nanoColab does not list profiles, these two are offered.
   - **Work space (GiB)**: the student's own room for files and outputs, 10 GiB by default, from 10 to 98 GiB.
   - **Publish automatically 24 h before the start**, if you want it.
   - **Keep archives until**: optional. Left empty, each stage's archives are kept for 30 days after its end. A chosen date must be after the competition ends and at most 365 days later.
3. Check the disk line shown for each stage, for example "Round 1: 10 GiB work space + 3 GiB task data = 13 GiB". The task data is the size of the stage's package (the tasks' public files and solution notebooks), rounded up to whole GiB, and is recomputed when tasks change, until publish.
4. Click **Create Competition** or **Save Changes**. The setting is saved with the rest of the form.

The setting applies to every stage. Stages that are not published yet follow later changes; published stages keep the setting they were published with. When every stage is published, the setting can no longer change (`ERR_ENVIRONMENT_LOCKED`). Stages have no setting of their own: the stage form only points to the competition's **Student workspaces** section, with a button (**Open the competition's settings**) that opens it.

Adding the first stage to a competition moves the workspaces from the competition to its stages, and deleting the last stage moves them back. Once a competition without stages has published its workspaces, it can no longer get stages (`ERR_ENVIRONMENT_LOCKED`).

### Publishing

1. On the competition card, click **Workspaces**. The view opens at its top and lists each stage, or the whole competition when it has no stages; **Back** returns to the competition card.
2. Watch the status chip of each stage. It updates by itself: **Uploading** with a percentage, then **Preparing**, then **Ready**.
3. Click **Publish to nanoColab** and confirm, or let the automatic switch publish 24 h before the start. Publishing cannot be undone.

Workspaces open at each stage's start and close at its end plus the grace period. For each stage the view also shows the window, the places (registered students plus a margin), the task folders, the image, the resources and the disk, whether it is published or will publish automatically, and the archive date.

### After Publishing

- The stage's workspace settings, its start, the task folder names, the public task files and the baseline are locked. Hidden files (the labels, the baseline submission) and the evaluator can still be replaced by an administrator with a reason, see [section 11](#11-task-evaluation-modes-and-workspace-submissions).
- To give more time, click **Extend**, choose the **New end** and give a **Reason** of 8 to 2000 characters. It moves this stage's end later and works only before the current end plus the grace period; students keep working until the new end plus the grace period. The reason goes to nanoColab and the audit log.
- **Show student workspaces** lists every registered student: alias and username, **First opened** (or **Not opened**), **Last opened** and the **Latest submission** with its status.

### Status Chip

| Chip | Meaning | What to do |
| :--- | :--- | :--- |
| **Off** | No workspaces for this stage or competition. | Turn them on in **Edit** on the competition → **Student workspaces**. |
| **Uploading** | The task files are being packaged and uploaded. | Wait until **Ready**. |
| **Preparing** (**Preparing for N min** after publishing) | nanoColab is preparing the environment. A red flag and "Preparing is taking longer than expected. Check nanoColab." appear after `NANOCOLAB_PREPARING_ALERT_MINUTES` (10 by default). | Wait until **Ready**; if the flag appears, check nanoColab or contact its team. |
| **Ready** | Before publishing: ready to publish. After publishing: students can open their workspaces during the window. | Publish, or let it publish automatically 24 h before the start. |
| **Problem** | The reason is shown under the chip, with nanoColab's details. | Fix what is shown, often the task files. The next check, within a minute, picks up the fix. |
| **Unknown** | The last status from nanoColab is out of date. | It refreshes by itself; if it stays, check that the workers and the beat scheduler run. Students can still try to open their workspace. |

### Errors and Troubleshooting

A refused value in **Student workspaces** is shown under its field and in a notification; the overlap and service errors appear as a notification only:

| Message | Cause |
| :--- | :--- |
| "Choose a workspace image from the list." | The image is not in nanoColab's catalog (`ERR_INVALID_WORKSPACE_IMAGE`). |
| "Profile must be one of: CPU Compact, CPU Standard." | The profile is not one nanoColab offers (`ERR_INVALID_WORKSPACE_PROFILE`). |
| "Work space must be between 10 and 98 GiB." | nanoColab accepts CPU disks of 10 to 100 GiB, and the 98 GiB maximum leaves room for a task package of up to 2 GiB (`ERR_INVALID_WORKSPACE_SIZE`). |
| "Keep archives until a date after the competition ends, at most 365 days later." | The archive date is out of range (`ERR_INVALID_ARCHIVE_DATE`). |
| "Round 1, Round 2 would have workspaces open at the same time, counting the grace period after each end. A student has one workspace at a time, so leave a gap between them." | Two stages overlap, counting the grace period after each end (`ERR_ENVIRONMENT_OVERLAP`). It is checked when you turn workspaces on, add a stage or move one; move a stage so they leave a gap. |
| "The workspace service is unavailable" | nanoColab did not answer while you changed the image or profile (`ERR_NANOCOLAB_UNAVAILABLE`). Other edits of the competition still save; try the change again later. |

- **Stuck in Preparing:** the chip flags it after `NANOCOLAB_PREPARING_ALERT_MINUTES`. LavBench cannot fix this itself; check nanoColab.
- **"The environment has no free places left."** The places are the registered students plus a `NANOCOLAB_ATTENDANCE_HEADROOM_PERCENT` margin, fixed at publish. Students registered after publishing use up that margin, so register students before you publish.
- **Problem** states name their cause: no task files to package, a package too large, more than 16 tasks, a package nanoColab rejected, or a failed sync with nanoColab's message. Fix the tasks; the next check retries.

---

## 11. Task Evaluation Modes and Workspace Submissions

Every task is scored in one of two modes, chosen first in the task editor (**Evaluation mode**):

| Mode | What the student submits | What LavBench runs |
| :--- | :--- | :--- |
| **Notebook** | Selected cells of a notebook, uploaded or loaded from the workspace | The cells in the sandbox; the `submission.parquet` they write is scored |
| **File** | `submission.parquet` and `solution.ipynb` from the task folder of the workspace | Nothing: the Parquet is checked and scored directly |

The mode is locked once a competitor has submitted to the task: the editor then shows it read-only with "Locked: competitors have already submitted to this task."

### Creating a Notebook Task

1. Open **Manage Competitions & Tasks** and click **Add Task** on the competition.
2. Leave **Evaluation mode** on **Notebook**. Fill in the **Task Title**; the **Workspace folder** is made from the title unless you type one.
3. Set the scoring in **Evaluation**, the limits, the GPU switch and the import rules in **Sandbox**, and the image in **Environment**. When no GPU worker reports in, "No GPU worker online" appears next to the GPU switch; it blocks nothing, but GPU submissions wait until a GPU worker connects.
4. In **Files**, drop the baseline notebook and the data students need into **Students get these**, and `labels.parquet` into **Hidden: labels, baseline submission**. Models and datasets go in **Environment** as one ZIP ([section 3](#3-hugging-face-data-one-zip-per-task)).
5. Click **Create Task**. The task is saved with its baseline notebook, then the data files upload in the upload list ([The Upload List](#the-upload-list)). The baseline notebook runs; the task opens for submissions once it completes.

### Creating a File Task

1. Click **Add Task** and set **Evaluation mode** to **File**. The **Sandbox** tab disappears, and **Environment** keeps only the Hugging Face data.
2. Set the scoring in **Evaluation** as for a notebook task.
3. In **Files**:
   - **Students get these**: the data, and optionally a starter notebook (`.ipynb`), which students find as `solution.ipynb` in the task folder. It should save `submission.parquet` next to itself.
   - **Hidden: labels, baseline submission**: `labels.parquet` and `baseline_submission.parquet`, a correct submission that is scored as the task's baseline. Both are required; until both are uploaded, the task shows them under **Task Problems**. `labels.parquet` and `baseline_submission.parquet` always go to the hidden list, even when dropped among the public files.
4. Click **Create Task**. The task is saved, then the files upload in the upload list, `labels.parquet` first. The baseline submission is checked against the labels when it arrives ("A file task needs a hidden baseline_submission.parquet that matches labels.parquet." in its row when it does not match), and again whenever the labels are replaced, and then scored like a student's file.

File tasks need student workspaces ([section 10](#10-student-workspaces-nanocolab)): students submit from their workspace, and a file task without a published environment refuses submissions (`ERR_TASK_NOT_WORKSPACE_BACKED`).

### Files and the Workspace Folder

- Public file names must be plain names that a workspace accepts; a name nanoColab would refuse is rejected at upload ("Invalid filename").
- `labels.parquet` is checked when it arrives (the row shows **Checking**). Labels with more ids than a submission can be checked against within `SUBMISSION_CHECK_MAX_MEMORY_MB` (4096 by default) are refused with "labels.parquet holds more ids than a submission can be checked against (4096 MB)." (`ERR_LABELS_TOO_LARGE`), and labels with repeated ids or wrong columns with "Invalid labels.parquet schema." (`ERR_INVALID_LABELS_SCHEMA`). Both appear in the file's row of the upload list, and the stored labels stay in use.
- The **Workspace folder** follows the title until you type a name or the environment is published. Use lowercase letters, digits and hyphens, at most 40 characters, not `models` or `datasets`. Empty it to go back to the name made from the title.

### Changing Files After Publish

Once the task's environment is published:

- **Workspace folder**, **Students get these** and the Hugging Face data are fixed and shown read-only.
- An administrator can still replace or remove hidden files or the evaluator: make the change, fill in **Reason for changing hidden files**, and save. The reason goes with every hidden file uploaded or removed in that save and is kept in the audit log, and the baseline runs again.
- The jury sees the reason field disabled with "Only an administrator can replace hidden files or the evaluator after publish."

### Emergency Uploads During a nanoColab Outage

When students cannot reach their workspaces, an administrator can let a file task take the two files as an emergency upload:

1. Open **Edit Config** on the file task. In **General**, turn on **Allow the emergency upload (nanoColab outage)**.
2. Type the reason in the confirmation and click **Allow uploads**. The switch applies at once, without **Save Changes**, and is recorded in the audit log.
3. Students then see an upload area for `submission.parquet` and `solution.ipynb` under **Submit from workspace**. The same checks and limits apply.
4. When the outage is over, turn the switch off and confirm with **Stop uploads**.

### Reviewing Submissions

In a submission's details, administrators and the jury see:

- a badge with how it arrived: **Cells** (notebook task), **Workspace** or **Emergency upload**;
- for a file submission, **Submitted files**: the time, the size of `submission.parquet` and the SHA-256 of both files, with **Download Parquet** and **Download notebook**. The files are named after the alias while the competition is double-blind;
- **Timing**: **Execution** (the sandbox run, for notebook tasks only) and **Evaluation** (the scoring). Competitors see only the execution time; neither time affects the ranking.

### Errors Students May Report

| Message | Cause |
| :--- | :--- |
| "No submission.parquet in image-classification/ of your workspace. Save it from solution.ipynb, then Submit again." | The notebook did not save the file in the task folder (`ERR_WORKSPACE_FILE_MISSING`). |
| "No solution.ipynb in image-classification/ of your workspace." | The notebook was renamed or moved (`ERR_WORKSPACE_NOTEBOOK_MISSING`). |
| "The submission file cannot be scored: ..." | Wrong columns or ids; the message gives the counts. No submission is created and no attempt is used (`ERR_SUBMISSION_FILE_INVALID`). |
| "You already submitted this exact file for this task." | The same Parquet again (`ERR_SUBMISSION_DUPLICATE`). Only a submission that failed with a platform error can be sent again unchanged. |
| "The file exceeds the 20 MB limit." | `NANOCOLAB_EXPORT_MAX_BYTES` (`ERR_WORKSPACE_FILE_TOO_LARGE`). |
| "Your workspace files cannot be read right now. Please try again shortly." | The workspace server is stopped or its archive is not ready; the button waits for the time the server asks, then can be pressed again. |
| "The file could not be checked because of a platform problem. Please try again shortly." | The check of the file failed on the server, not because of the file (`ERR_SUBMISSION_CHECK_FAILED`); nothing is submitted and no attempt is used. If it repeats, check the backend logs. |
