# LavBench Architecture

## System Overview

```
Browser (React) → Nginx (port 443, HTTPS) → Flask API (port 5001)
                                        ├── PostgreSQL (users, challenges, tasks, submissions)
                                        ├── Redis (Celery broker, SSE pub/sub, cache, rate limits, optional TLS)
                                        ├── Celery Beat (watchdog, backup scheduler)
                                        ├── Internal Celery Worker (system tasks only, inside Docker Compose)
                                        └── Remote Evaluation Workers (Docker container or host, sibling sandbox containers)
```

## Components

| Component        | Technology                        | Role                                                                                |
| ---------------- | --------------------------------- | ----------------------------------------------------------------------------------- |
| **Frontend**     | React 19 + Vite + Tailwind 4      | SPA with SSE live updates, i18n (en/bg), JSDoc type annotations, tsc validation     |
| **API Server**   | Flask + Gunicorn + gevent         | REST endpoints, SSE streaming, JWT auth                                             |
| **Database**     | PostgreSQL 15                     | Users, challenges, tasks, submissions, audit logs                                   |
| **Cache/Broker** | Redis                             | Celery message broker, SSE pub/sub, caching, rate limiting, token revocation        |
| **Task Queue**   | Celery                            | Async job dispatch (evaluation, backups)                                            |
| **Scheduler**    | Celery Beat                       | Watchdog (stuck submissions), automated backups                                     |
| **Worker**       | `start-worker.sh --docker` (container) or `start-worker.sh` on host | Sibling Docker sandbox execution (not Docker-in-Docker)                          |

## Authentication Flow

```
1. Browser → POST /api/auth/login (username + SHA256(password))
2. Server → verify credentials → generate JWT with jti → set httpOnly cookie
3. Browser → all subsequent requests auto-attach cookie
4. Server → verify_token() → check revocation (Redis) → DB role lookup → authorize
5. Logout → clear cookie + revoke jti in Redis (TTL = remaining token lifetime)
```

## Submission Pipeline

```
1. User uploads .ipynb → POST /api/challenges/<id>/parse-notebook
2. User selects cells → POST /api/challenges/<id>/submit
3. Server: AST validation → rate limit check → create Submission → dispatch Celery task
4. Worker: pick up task → fetch HF key from server → preload datasets → Docker build
5. Docker sandbox: --network none, --cap-drop ALL, --read-only rootfs, --no-new-privileges, CPU/RAM/PIDs limits → execute student code
6. Student code writes submission.parquet → worker compares against labels.parquet → calculate scores
7. Worker: report scores to server → update Submission → invalidate cache → publish SSE → leaderboard update
```

## Evaluation Engine

`evaluation_engine.py` resolves 44 metrics across 12 categories, dispatching by metric name and input data type:

| #   | Category         | Metric Names                                                                         |
| --- | ---------------- | ------------------------------------------------------------------------------------ |
| 1   | Classification   | `accuracy`, `f1`\*, `precision`, `recall`\*, `cohen_kappa`, `matthews_corrcoef`      |
| 2   | Probabilistic    | `auc_roc`, `logloss`, `brier_score`                                                  |
| 3   | Regression       | `rmse`, `mse`, `mae`, `r_squared`, `mape`, `median_ae`                               |
| 4   | Seq-label (NER)  | `seqeval_f1`, `seqeval_precision`, `seqeval_recall`                                  |
| 5   | Generative NLP   | `bleu`, `rouge`, `rouge_l`, `meteor`, `chrf`, `ter`                                  |
| 6   | QA Extractive    | `exact_match`, `f1`\* (word-overlap)                                                 |
| 7   | Object Detection | `map_50`, `map_75`, `map_50_95`, `recall`\* (box recall)                             |
| 8   | Segmentation     | `mean_iou`, `dice`, `pixel_accuracy`                                                 |
| 9   | Keypoints        | `oks`, `pck`                                                                         |
| 10  | Image Quality    | `psnr`, `ssim`                                                                       |
| 11  | Audio Quality    | `snr`, `mel_lsd`, `si_sdr`                                                           |
| 12  | Clustering       | `adjusted_rand_index`, `normalized_mutual_info`, `adjusted_mutual_info`, `v_measure` |
| +   | Retrieval        | `ndcg_k`, `recall_k`, `mrr`                                                          |

\* `f1` and `recall` auto-dispatch: string inputs → QA word-overlap / exact-match; list-of-dict inputs → object detection box recall; scalar inputs → sklearn classification.

## API Type Pipeline

```
Backend route docstrings (flasgger YAML, OpenAPI 3.0)
       │
       ▼
  /apispec_1.json (auto-generated by flasgger)
       │
       ▼
  openapi-typescript (npm run generate-api-types)
       │
       ▼
  src/types/api.d.ts (2700 lines, all endpoint types) — JSDoc @type annotations
       │
       ▼
  tsc --noEmit (npm run check-types — validates all annotations + component props)
```

Response types use `content: application/json: schema:` format. The `components.schemas` (User, Challenge, Task, Submission, Cell, Error) are defined in `app.py`'s Swagger template and referenced via `$ref: '#/components/schemas/...'`.

## Error Response Standardization

All API error responses use the `err()` helper from `error_utils.py`:

```python
err("ERR_INVALID_CREDENTIALS", 401)                           # uses default message
err("ERR_FILE_TOO_LARGE", 400, message="Custom message here") # custom override
```

Response shape: `{"error": "<message>", "code": "<ERR_*>"}` (no `key` field). The frontend looks up translations by code via `t(\`api.\${data.code}\`, data.error)`.

Every `ERR_*` code must be:
1. Defined in `DEFAULT_ERROR_MESSAGES` dict in `backend/error_utils.py`
2. Used by at least one `err()` call in the codebase
3. Translated in both `en/translation.json` and `bg/translation.json` under the `api.ERR_*` namespace

The script `backend/scripts/check_error_codes.py` enforces all three rules in CI.

## SSE Streaming

7 endpoints use Server-Sent Events for real-time updates:

| Endpoint                                | Data                            | Triggers                                |
| --------------------------------------- | ------------------------------- | --------------------------------------- |
| `/api/challenges/<id>/leaderboard/live` | Full challenge leaderboard JSON | Recalculation complete (SSE publish)    |
| `/api/tasks/<id>/leaderboard/live`      | Full leaderboard JSON           | Submission status change, manual points |
| `/api/tasks/<id>/submissions/live`      | Submission list                 | New submission, status change           |
| `/api/submissions/<id>/logs/live`       | Execution log lines             | New log output from worker              |
| `/api/admin/workers/stats/live`         | Worker cluster status           | Worker connect/disconnect               |
| `/api/worker-status/live`               | Cluster health (navbar)         | Worker status change                    |
| `/api/admin/backups/live`               | Backup file list                | Backup completion                       |

## Backup System

| Type                      | Frequency                        | Retention               | Location                           |
| ------------------------- | -------------------------------- | ----------------------- | ---------------------------------- |
| **Auto**                  | Every 20min (active) / 6h (idle) | Latest 6                | `/backups/auto_*.tar.gz`           |
| **Manual**                | On demand via UI                 | Never auto-deleted      | `/backups/manual_*.tar.gz`         |
| **Competition lifecycle** | On deadline, grace end, finalize | Until challenge deleted | `/backups/challenge_{id}/*.tar.gz` |

Contents: `pg_dump` + `uploads/` directory in `.tar.gz`.

## Worker Resource Management

### Overview

Each evaluation worker independently manages its resources (CPU cores and RAM) to avoid overcommitting the host. During the interactive first-run setup (`make worker`), the worker detects its hardware and guides the admin through resource allocation.

### Detection

- **CPU cores**: detected via `nproc` / `sysctl hw.ncpu`
- **Total RAM**: parsed from `/proc/meminfo` (Linux) or `sysctl hw.memsize` (macOS), fallback 8 GB
- **GPUs**: discovered via `nvidia-smi --query-gpu=index,name`; grouped by model with compact index ranges (e.g., `2 × RTX 3090  [indices: 0-1]`)

### Reserved Resources

The following are never available to evaluation tasks (hardcoded, not user-configurable):

| Resource | Reserved | Purpose |
|---|---|---|
| RAM | 4 GB | OS, Docker daemon, Celery process, networking |
| CPU cores | 1 core | OS scheduler, Docker daemon, Celery main process |

### Interactive Per-Task Budgets

During `make worker`, the admin is prompted to set per-task budgets. Each value is capped by both CPU cores and RAM:

```
CORES_AVAILABLE = TOTAL_CORES - 1 (reserved)
RAM_AVAILABLE   = TOTAL_RAM_GB - 4 (reserved)

GPU_COUNT = min(NUM_GPUS,                # selected GPUs
                CORES_AVAILABLE / GPU_CORES_PER_TASK,
                RAM_AVAILABLE   / GPU_RAM_PER_TASK_GB)

RAM_REMAINING  = RAM_AVAILABLE   - GPU_COUNT * GPU_RAM_PER_TASK_GB
CORES_REMAINING = CORES_AVAILABLE - GPU_COUNT * GPU_CORES_PER_TASK

CPU_COUNT = min(RAM_REMAINING  / CPU_RAM_PER_TASK_GB,
                CORES_REMAINING / CPU_CORES_PER_TASK)

CONCURRENCY = GPU_COUNT + CPU_COUNT
```

If remaining resources are insufficient for a single CPU task (< 2 cores or < 4 GB), CPU_COUNT is set to 0 (only GPU tasks run).

### Env Vars (saved to `worker.env`)

| Variable | Default | Prompted | Description |
|---|---|---|---|
| `GPU_RAM_PER_TASK_GB` | 8 | Yes | RAM budget per GPU sandbox container |
| `CPU_RAM_PER_TASK_GB` | 4 | Yes | RAM budget per CPU sandbox container |
| `RESERVED_RAM_GB` | 4 | No | System reserve |
| `RESERVED_CPU_CORES` | 1 | No | System reserve |
| `RAM_CLAMP_FACTOR` | 1.05 | No (editable via `make edit-worker`) | Max task_ram / budget ratio before rejection |

### Runtime Clamping

When a task arrives from the Celery queue, its `ram_limit_mb` (set per-challenge or per-task in the database) is compared to the worker's budget:

```
budget_mb = GPU_RAM_PER_TASK_GB if gpu_required else CPU_RAM_PER_TASK_GB
budget_mb *= 1024

if task_ram <= budget_mb:
    # Within budget — use the task's value as-is
    pass
elif task_ram <= budget_mb * RAM_CLAMP_FACTOR (1.05):
    # Slightly over (≤5%) — clamp to budget, log a warning
    container gets budget_mb
else:
    # Exceeds budget by more than 5% — task is rejected
    Celery retries → dead letter queue
```

The sandbox container always receives `--memory=<clamped_value> --memory-swap=<clamped_value>`, which disables swap and guarantees an immediate OOM kill if the process exceeds the limit.

### Worker Spec Registration

On startup, each worker registers its hardware specs in Redis (`worker_spec:<hostname>`, 24h TTL) via the `register_worker_specs` Celytask signal. The spec includes:

```python
{
  "name": worker_name,
  "concurrency": N,
  "ram_gb": total_host_ram,
  "gpu_ram_per_task_gb": 8,
  "cpu_ram_per_task_gb": 4,
  "reserved_ram_gb": 4,
  "reserved_cpu_cores": 1,
  "ram_clamp_factor": 1.05,
  ...
}
```

These fields are served by the cluster status API (`/api/admin/workers/stats`, `/api/worker-status`) and visible in the admin panel.

### Internal Workers

Internal workers (system tasks: backups, watchdog, leaderboard recalculation) are configured separately — they do not create Docker sandboxes and have no RAM/core budgeting. Their Celery concurrency is simply `max(1, TOTAL_CORES / 2)`.

## Security Layers

| Layer                | Implementation                                                                                                                    |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| **Auth**             | httpOnly cookie + JWT (24h expiry, jti-based revocation)                                                                          |
| **AuthZ**            | Role-based (admin, jury, competitor), DB-backed role lookup                                                                       |
| **Rate limiting**    | Per-user per-endpoint Lua atomic counters                                                                                         |
| **Token revocation** | jti in Redis blacklist with TTL                                                                                                   |
| **PII encryption**   | Fernet symmetric (optional ENCRYPTION_KEY for rotation)                                                                           |
| **Sandbox**          | Docker --network none, --cap-drop ALL, --read-only rootfs, --no-new-privileges, --cpus <CPU_CORES_PER_TASK or GPU_CORES_PER_TASK>, --pids-limit 64, RAM/swap limits, tmpfs |
| **IP trust**         | ProxyFix middleware (trusts X-Forwarded-For from Nginx only)                                                                      |
| **HF keys**          | Fetched on-demand via authenticated API, never in Redis                                                                           |
