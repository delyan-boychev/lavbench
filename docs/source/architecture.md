# LavBench System Architecture & Infrastructure

## 1. System Overview

```text
Browser (React SPA) ──> Nginx (Port 443, HTTPS / SSE Reverse Proxy)
                            ├── Flask API Server (Port 5001, Gunicorn + gevent)
                            │     ├── PostgreSQL 15 (Primary Database)
                            │     ├── Redis (Celery Broker, SSE Pub/Sub, Rate Limits, Token Blacklist)
                            │     ├── Celery Beat (Periodic Scheduler: Backups, Watchdog)
                            │     └── Internal Celery Worker (System tasks only, inside Docker Compose)
                            └── Remote Execution Workers (Celery evaluation workers: Docker container or host)
                                  └── Sibling Sandbox Containers (--network none, --read-only, --cap-drop ALL)
```

---

## 2. Component Technology Stack

| Component | Technology | Role & Key Responsibilities |
| :--- | :--- | :--- |
| **Frontend** | React 19 + Vite + Vanilla/Tailwind CSS | SPA with SSE live updates, i18n (en/bg), JSDoc `@type` validation (`tsc --noEmit`). |
| **API Server** | Flask 3.1 + Gunicorn + gevent + spectree | REST API endpoints, Pydantic v2 request/response validation, SSE event streaming. |
| **Primary Database** | PostgreSQL 15 | Users, challenges, stages, tasks, submissions, audit logs (`AuditLog`). |
| **Cache & Broker** | Redis | Celery task broker, SSE pub/sub channels, atomic rate limit counters, JWT token blacklist. |
| **Task Queue** | Celery 5.4 | Asynchronous job execution (submission evaluation, image compilation, database backups). |
| **Scheduler** | Celery Beat | Periodic tasks (watchdog for stuck submissions, automated backup schedule). |
| **Worker Nodes** | Celery Evaluation Worker | Runs competitor code in sibling Docker sandbox containers (`deploy-worker.sh` / `worker.env`). |

---

## 3. Authentication & Authorization Flow

```text
1. User → POST /api/auth/login (username + SHA256(password))
2. API Server → verifies credentials → generates JWT with unique jti → sets httpOnly 'auth_token' cookie
3. Browser → subsequent API requests automatically transmit httpOnly cookie
4. Server → verify_token() middleware → checks Redis jti revocation blacklist → DB role lookup → authorizes
5. Logout → POST /api/auth/logout → clears cookie + blacklists jti in Redis (TTL = remaining token lifetime)
```

---

## 4. Submission Pipeline & Sandbox Isolation Security

```text
1. User uploads .ipynb → POST /api/challenges/<id>/parse-notebook
2. User selects code cells → POST /api/challenges/<id>/submit
3. Server: Pre-execution AST validation (IPython magic stripping, banned_imports check) → rate limit check → creates Submission → dispatches Celery evaluation job
4. Worker Node: picks up job → ensures task Docker image (lavbench_task_<id>) is compiled → mounts submission.parquet & hidden labels.parquet
5. Hardened Sandbox Container: launches execution with zero-trust security parameters
6. Competitor Code: executes inside container → writes submission.parquet output
7. Worker Evaluation Engine: evaluates submission.parquet against labels.parquet (or runs evaluator.py) → updates Submission status & scores → publishes SSE event → invalidates leaderboard cache
```

### Sandbox Container Isolation Parameters

Competitor code runs inside a zero-trust Docker container with strict Linux kernel caps:

| Parameter | Purpose & Security Guarantee |
| :--- | :--- |
| `--network none` | Completely disables container networking — prevents data exfiltration and external socket calls. |
| `--cap-drop ALL` | Drops all Linux kernel capabilities — blocks raw sockets, `mount()`, `ptrace()`, and privilege escalation. |
| `--read-only` | Mounts root filesystem as read-only — competitor code cannot modify system binaries or libraries. |
| `--no-new-privileges` | Prevents process privilege escalation via SUID binaries. |
| `--tmpfs /tmp:noexec,nosuid,size=128m` | Size-capped temporary memory directory that cannot execute binaries or consume host disk space. |
| `--memory-swap` = RAM Limit | Disables swap memory — guarantees immediate kernel OOM kill if RAM limit is exceeded. |
| `--pids-limit 64` | Restricts total process count to mitigate fork bombs. |
| `--ulimit nofile=256:256` | Caps open file descriptor counts. |
| `--cpus` | Restricts CPU core allocation per container (`CPU_CORES_PER_TASK` / `GPU_CORES_PER_TASK`). |

---

## 5. Task Image Build Pipeline & Build Error Taxonomy

Each task maintains a persistent build directory at `TASK_IMAGES_DIR/task_{id}/`. The container image is tagged `lavbench_task_{task_id}`.

### Image Build Sequence:
```text
[Base Image Pull] ──> [APT Packages Install] ──> [Pip Requirements Install] ──> [HF Pre-Fetch & Task Files]
```

### Image Build Error Taxonomy (`ERR_IMAGE_BUILD_FAILED`):
1. **Invalid Base Image**: Non-existent tag or 404/401 registry pull error.
2. **APT Resolution Failure**: Misspelled Ubuntu package names or missing apt repositories.
3. **Pip Dependency Conflict**: Incompatible Python library versions or missing C/C++ build tools (`build-essential`).
4. **HuggingFace Download Timeout / Auth Error**: Network drop, timeout limit, or missing `hf_api_key` for gated models.
5. **Disk Space Exhaustion**: Host free disk space below `MIN_BUILD_DISK_GB` (5 GB limit).

### Build Error Recovery & Troubleshooting:
- Build errors are written to `task.build_error` and displayed in the Admin Panel and task overview.
- If a build lock is stuck due to worker interruption, admins can execute `clear_build_lock(task_id)` or click **Force Clear Build Lock** in the UI.
- Saving task edits or clicking **Rebuild Container Image** publishes a Redis `task_rebuild` notification, clearing stale image caches and triggering a fresh container build.

---

## 6. Evaluation Engine Architecture

`evaluation_engine.py` supports 44 standard evaluation metrics across 12 problem categories, alongside custom evaluation scripts (`evaluator.py`).

| # | Category | Metric Keys | Primary Use |
| :--- | :--- | :--- | :--- |
| 1 | **Classification** | `accuracy`, `f1`, `precision`, `recall`, `cohen_kappa`, `matthews_corrcoef` | Discrete target classification. |
| 2 | **Probabilistic** | `auc_roc`, `logloss`, `brier_score` | Calibrated continuous confidence scores. |
| 3 | **Regression** | `rmse`, `mse`, `mae`, `r_squared`, `mape`, `median_ae` | Continuous target error measurement. |
| 4 | **Seq-Labeling (NER)** | `seqeval_f1`, `seqeval_precision`, `seqeval_recall` | Token-level entity classification. |
| 5 | **Generative NLP** | `bleu`, `rouge`, `rouge_l`, `meteor`, `chrf`, `ter` | Translation, summarization, and text generation. |
| 6 | **QA Extractive** | `exact_match`, `f1` (word-overlap) | Reading comprehension token overlap. |
| 7 | **Object Detection** | `map_50`, `map_75`, `map_50_95`, `recall` (box recall) | Bounding box IoU and mAP evaluation. |
| 8 | **Segmentation** | `mean_iou`, `dice`, `pixel_accuracy` | Semantic and instance mask evaluation. |
| 9 | **Keypoints** | `oks`, `pck` | Pose estimation object keypoint similarity. |
| 10 | **Image Quality** | `psnr`, `ssim` | Image reconstruction and restoration metrics. |
| 11 | **Audio Quality** | `snr`, `mel_lsd`, `si_sdr` | Speech and audio processing quality. |
| 12 | **Clustering** | `adjusted_rand_index`, `normalized_mutual_info`, `adjusted_mutual_info`, `v_measure` | Unsupervised cluster grouping similarity. |
| + | **Retrieval** | `ndcg_k`, `recall_k`, `mrr` | Information retrieval and ranking metrics. |
| * | **Custom Evaluators** | Dynamic `METRIC_NAME` returned by `evaluator.py` | Custom domain evaluation scripts (`evaluate(df_sub, df_labels, options)`). |

---

## 7. API Type Pipeline & Validation Architecture

```text
Pydantic v2 Schemas + spectree @api.validate Decorators
       │
       ▼
  /apidoc/openapi.json (auto-generated OpenAPI 3.0 spec)
       │
       ▼
  openapi-typescript (npm run generate-api-types)
       │
       ▼
  src/types/api.d.ts (Full TypeScript declaration file)
       │
       ▼
  tsc --noEmit (npm run check-types — validates JSDoc annotations & component props)
```

### Error Standardization (`err()` & `check_error_codes.py`)
All backend API error responses use `err("ERR_CODE", status_code)` returning `{"error": "<message>", "code": "ERR_CODE"}`. The script `backend/scripts/check_error_codes.py` validates in CI that every error code is registered in `DEFAULT_ERROR_MESSAGES` and translated in both `en` and `bg` locale files.

---

## 8. SSE Real-Time Streaming Architecture

7 backend endpoints utilize Server-Sent Events (SSE) for real-time telemetry and data streaming:

| Endpoint | Streamed Data | Trigger Event |
| :--- | :--- | :--- |
| `/api/challenges/<id>/leaderboard/live` | Live Challenge Leaderboard JSON | Submission score computed or manual score edited. |
| `/api/tasks/<id>/leaderboard/live` | Live Task Leaderboard JSON | Submission status change or manual points entry. |
| `/api/tasks/<id>/submissions/live` | Submission List Updates | New submission queued or state transition. |
| `/api/submissions/<id>/logs/live` | Execution Log Lines | Live stdout/stderr log output from worker sandbox. |
| `/api/admin/workers/stats/live` | Worker Cluster Telemetry | Worker connection/disconnection or slot update. |
| `/api/worker-status/live` | Cluster Health (Navbar Badge) | Worker heartbeats and status changes. |
| `/api/admin/backups/live` | Backup Archives List | Automated or manual backup completion. |

---

## 9. Automated & Manual Backup Retention Architecture

| Backup Type | Trigger Frequency | Retention Policy | Management & API Constraints |
| :--- | :--- | :--- | :--- |
| **Auto-Backup** | Every **20 minutes** during active competitions; every **6 hours** when idle. | Retains the **6 most recent** backups. Older auto-backups are automatically purged. | System managed (`auto_YYYYMMDD_HHMMSS.tar.gz`). Cannot be deleted manually via API (returns HTTP 403). |
| **Manual Backup** | Triggered on demand via **"Force Backup Now"** button. | Retained **indefinitely**. Never auto-deleted by retention routines. | Administrator managed (`manual_YYYYMMDD_HHMMSS.tar.gz`). Downloadable or deletable via Admin Panel. |

Each backup archive contains a complete PostgreSQL database dump (`pg_dump`) along with compressed `uploads/` assets in a `.tar.gz` format.

---

## 10. Worker Hardware Budgeting & Clamping

During initial setup (`make setup-worker`), workers inspect total CPU cores (`nproc`), RAM (`/proc/meminfo`), and GPUs (`nvidia-smi`), reserving 1 CPU core and 4 GB RAM for system overhead.

### Runtime RAM Clamping Formula:
```text
budget_mb = (GPU_RAM_PER_TASK_GB if task.gpu_required else CPU_RAM_PER_TASK_GB) * 1024

if task_ram <= budget_mb:
    use task_ram as-is
elif task_ram <= budget_mb * RAM_CLAMP_FACTOR (1.05):
    clamp container memory to budget_mb (log warning)
else:
    reject task → Celery retry → dead-letter queue (/api/admin/dead-letters)
```

Workers register their hardware specifications in Redis (`worker_spec:<hostname>`, 24h TTL), which are served via `/api/admin/workers/stats` and displayed in the Admin navbar.
