# LavBench System Architecture & Infrastructure

## 1. System Overview

```text
Browser (React SPA) ──> Nginx (Port 80 / 443, HTTP(S) / SSE Reverse Proxy)
                            ├── Flask API Server (Port 5001, Gunicorn + gevent)
                            │     ├── PostgreSQL 15 (Primary Database)
                            │     ├── Redis (Celery Broker + Coordination: SSE pub/sub fan-out, worker_spec registry, submission fallback key, dirty-challenges set, dead-letter queue, GPU/build locks)
                            │     ├── Redis Cache (Private, server-only: leaderboard caches, locks, rate-limit counters, JWT blacklist — CACHE_REDIS_URL never given to external workers)
                            │     ├── Celery Beat (Periodic Scheduler: Backups, Watchdog)
                            │     └── Internal Celery Worker (System tasks only, inside Docker Compose, -Q celery,internal)
                            └── Remote Execution Workers (Celery evaluation-only workers: Docker container or host, consume cpu_queue)
                                  └── Sibling Sandbox Containers (--network none, --read-only, --cap-drop ALL)
```

---

## 2. Component Technology Stack

| Component | Technology | Role & Key Responsibilities |
| :--- | :--- | :--- |
| **Frontend** | React 19 + Vite + Vanilla/Tailwind CSS | SPA with SSE live updates, i18n (en/bg), JSDoc `@type` validation (`tsc --noEmit`). |
| **API Server** | Flask 3.1 + Gunicorn + gevent + spectree | REST API endpoints, Pydantic v2 request/response validation, SSE event streaming. |
| **Primary Database** | PostgreSQL 15 | Users, challenges, stages, tasks, submissions, audit logs (`AuditLog`). |
| **Cache & Broker** | Redis | Celery task broker + **coordination client** for all cross-machine shared state: SSE pub/sub fan-out, worker spec registry (`worker_spec:<hostname>`), submission fallback key, dirty-challenges set, dead-letter queue, GPU/build locks. |
| **Dedicated Cache** | Redis (DB 1, `noeviction`, no persistence) | Private, server-only cache: leaderboard caches, distributed locks, rate-limit counters, and JWT token blacklist (`CACHE_REDIS_URL`). Internal container — no host port; external workers never receive this URL. |
| **Task Queue** | Celery 5.4 | Asynchronous job execution (submission evaluation, image compilation, database backups). |
| **Scheduler** | Celery Beat | Periodic tasks (watchdog for stuck submissions, automated backup schedule). |
| **Worker Nodes** | Celery Evaluation Worker | **Evaluation-only** workers consuming `cpu_queue`; run competitor code in sibling Docker sandbox containers (`deploy-worker.sh` / `worker.env`). |

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
4. Worker Node: picks up job → ensures task Docker image (lavbench_task_<id>) is compiled → seeds the run directory (submission script + task data snapshot) into the sandbox via put_archive
5. Hardened Sandbox Container: launches execution with zero-trust security parameters
6. Competitor Code: executes inside container → writes submission.parquet output (pulled back via get_archive)
7. Worker Evaluation Engine: evaluates submission.parquet against labels.parquet server-side (or runs evaluator.py) → updates Submission status & scores → publishes SSE event → invalidates leaderboard cache
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

> **Known non-blocker:** the per-run anonymous volume mounted at `/app` (rw) has **no disk quota**
> of its own — a competitor can fill it until host disk pressure is hit. It is a deliberate
> trade-off accepted because memory, CPU, pid count, and wall-clock time are all capped, and
> `TASK_IMAGES_DIR` free-space (`MIN_BUILD_DISK_GB`) is monitored at build time.

### Persistent Storage Layout

No host paths are bind-mounted into workers or sandboxes. Task images, the HF cache and the
worker workspace live in Docker **named volumes**, mounted at fixed container paths
(`/var/lib/lavbench/task_images`, `/var/lib/lavbench/hf_cache`, `/var/lib/lavbench/workspace`):

- **Docker mode** (`scripts/deploy-worker.sh`): named volumes `lavbench_task_images`,
  `lavbench_hf_cache`, `lavbench_workspace`, created automatically on deploy.
- **Compose** (`docker-compose.yml`): `task_images_data`, `workspace_data` plus the shared
  `hf_cache` volume, mounted at the same container paths.
- **CI**: the eval worker uses job-local named volumes with the same layout.
- **Local micromamba mode**: the worker runs as a host process and uses plain host directories
  (`TASK_IMAGES_DIR`, `HF_CACHE_DIR`, `LAVBENCH_WORKSPACE_DIR`) — no Docker volumes involved.

### Sandbox `/app`: per-run anonymous volume

Each submission gets a disposable anonymous Docker volume mounted at `/app` (rw). The worker
streams the run directory into it with `put_archive` before the container starts and pulls the
output back with `get_archive` afterwards; the volume is removed together with the container.
Tar metadata is normalized to the sandbox user (uid/gid 65534, dirs 0777, files 0644 + exec bits)
so the non-root process can read and write `/app`. This removes the host-path bind-mount
requirement entirely — the host daemon never needs to resolve a worker-side path, so the same
runner code works in docker, compose, CI and micromamba setups. Labels (`labels.parquet`) are
never written into the sandbox; they stay server-side.

### Stale-Dir Sweep
Submission workspace dirs (`LAVBENCH_WORKSPACE_DIR`) are normally removed in a `finally` block,
but a killed/restarted worker can leave plaintext behind. Two complementary sweeps delete any
workspace subdirectory not modified in 24h:
1. **Worker startup** (tasks.py `_stale_dir_sweep_on_start`, `celeryd_init`, fcntl-serialized);
2. **Daily beat** (`task-dir-sweep-daily`).

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
- Build/environment failures are recorded as a **problem registry** — a list of machine-readable codes on `task.problem_codes` (e.g. `ERR_HF_DOWNLOAD_FAILED`, `ERR_TASK_BUILD_FAILED`, `ERR_BASELINE_FAILED`). Any non-empty registry blocks new submissions with `ERR_TASK_NOT_READY` (403) and every root cause is translated client-side.
- The registry is lifecycle-managed: worker-reported build failures add codes, a successful build clears the build-family codes, baseline completion removes `ERR_BASELINE_FAILED`, and environment config changes (base image, apt/pip/HF settings) clear stale build-family problems.
- If a build lock is stuck due to worker interruption, an admin can clear it on the worker host with the worker-side `clear_build_lock(task_id)` helper (`task_modules/image_builder.py`) — e.g. from a worker shell. There is no UI button or admin HTTP route for this.
- Saving semantic task edits (base image, apt/pip/HF settings, task files, evaluator code) publishes a Redis `task_rebuild` notification; the worker's rebuild listener (`_rebuild_listener`) re-fetches the task config and rebuilds with `force_rebuild=True`, bypassing the config-hash fast path. HuggingFace assets are re-resolved against the latest upstream revision (etag revalidation, changed bytes only) and the image is rebuilt from the fresh data.

### Task File & Label Replacement (unique `saved_name`)
Uploaded task resource files (including `labels.parquet`) are stored under a UUID-prefixed
`saved_name` (extension preserved). Because re-uploading a file with the *same* public filename
rotates the `saved_name`, the worker-side asset cache — which uses `saved_name` as its change
marker — detects the replacement and re-syncs the new bytes into `TASK_IMAGES_DIR/task_{id}/data`
(and the host-only `labels/` cache), and image builds re-bake the fresh data. `update_task` keeps
exactly one manifest entry per public filename and reclaims the replaced on-disk file after a
successful commit.

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

The spec is reachable through nginx at `:80/apidoc/openapi.json` (no backend host port needed). The `docker-build` CI job regenerates `api.d.ts` from the live stack and fails on any drift; the committed spec snapshots in `docs/source/api/` are refreshed with `make -C docs fetch-spec`. End-to-end behavior (auth, role matrix, rate limits, backups, SSE) is exercised by `scripts/api_smoke_test.py` against the running compose stack in CI.

### Error Standardization (`err()` & `check_error_codes.py`)
All backend API error responses use `err("ERR_CODE", status_code)` returning `{"error": "<message>", "code": "ERR_CODE"}`. The script `backend/scripts/check_error_codes.py` validates in CI that every error code is registered in `DEFAULT_ERROR_MESSAGES` and translated in both `en` and `bg` locale files.

---

## 8. SSE Real-Time Streaming Architecture

7 backend endpoints utilize Server-Sent Events (SSE) for real-time telemetry and data streaming:

| Endpoint | Streamed Data | Trigger Event |
| :--- | :--- | :--- |
| `/api/challenges/<id>/leaderboard/live` | Live Challenge Leaderboard JSON | Submission score computed or manual score edited. |
| `/api/tasks/<id>/submissions/live` | Submission List Updates | New submission queued or state transition. |
| `/api/submissions/<id>/logs/live` | Execution Log Lines | Live stdout/stderr log output from worker sandbox. |
| `/api/admin/workers/stats/live` | Worker Cluster Telemetry | Worker connection/disconnection or slot update. |
| `/api/admin/backups/live` | Backup Archives List | Automated or manual backup completion. |
| `/api/admin/submissions/queue/live` | Live Submission Queue State | Queue enqueue/acknowledge/reject events. |
| `/api/worker-status/live` | Cluster Health (Navbar Badge) | Worker heartbeats and status changes. |

SSE capacity is governed by two environment variables: `SSE_MAX_GLOBAL` (default `2000` concurrent connections platform-wide) and `SSE_MAX_PER_USER` (default `15` per client), both overridable via `.env`.

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

On the `worker_ready` signal, workers write their hardware specifications to the Redis coordination client (`worker_spec:<hostname>`, 24h TTL), which are served via `/api/admin/workers/stats` and displayed in the Admin navbar. Worker registration is fully signal-driven — no registration task exists anymore.
