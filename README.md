# LavBench

<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/source/_static/brand_logo_dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="docs/source/_static/brand_logo.svg">
    <img src="docs/source/_static/brand_logo.svg" alt="LavBench" width="300">
  </picture>
</div>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL%20v3-blue.svg" alt="License"></a>
  <a href="https://github.com/delyan-boychev/lavbench/actions/workflows/ci.yml"><img src="https://github.com/delyan-boychev/lavbench/actions/workflows/ci.yml/badge.svg" alt="LavBench CI"></a>
</p>

**LavBench** derives its name from the "Lav" (Lion), a proud national symbol of Bulgaria.

It is a secure, sandboxed machine learning competition platform. Participants submit Jupyter notebooks or raw Python code which are executed in isolated Docker containers under strict resource constraints. Real-time leaderboards stream via Server-Sent Events (SSE), with double-blind review for anonymous jury scoring.

Created by the Bulgarian AI Olympiad Committee for IOAI selection and national competitions. Other countries' AI olympiad committees, teams, and the IOAI board are welcome to use and contribute.

---

## Key Features

- **Hardened Sandbox Execution:** User code runs in isolated Docker containers with `--network none`, `--cap-drop ALL`, `--read-only` rootfs, `--security-opt no-new-privileges`, CPU/RAM/process limits, and `--tmpfs /tmp` mounts.
- **Double-Blind Review:** Competitor demographics are encrypted at rest (Fernet) and hidden behind pseudonyms (`alias_id`) during active competition.
- **Live Telemetry & Leaderboards:** Server-Sent Events (SSE) push real-time score updates, container build status, and worker logs to connected clients.
- **Multi-Stage Competitions:** Support for stage lifecycles with independent start/end times, grace periods, and visibility controls.
- **Custom Evaluators:** Jury members can upload Python evaluation scripts (`evaluator.py`) with per-metric weighting, schema validation, and custom option schemas.
- **Intelligent Worker Routing:** Celery queue routing dispatches evaluation workloads to external evaluation workers on `cpu_queue`, while system tasks stay on the internal `celery` queue consumed only by the in-compose worker.
- **Automated Backups:** Database dumps (`pg_dump`) and uploaded assets are backed up every 20 minutes during active competitions (every 6 hours when idle), retaining the 6 most recent auto-backups.
- **Audit Logs:** Complete logging of administrative actions (creating/deleting challenges, resetting passwords, editing finalized scores) with mandatory justification prompts logged to `AuditLog`.
- **i18n Support:** Full internationalization in English and Bulgarian across the web app and user guides.
- **Strict Security:** Includes httpOnly cookie authentication, JWT token revocation with a Redis blacklist, atomic rate limiting, encrypted PII, and ProxyFix middleware.
- **Typed API & Validation:** OpenAPI 3.0 specification auto-generated via spectree Pydantic v2 schemas, coupled with TypeScript declaration generation (`src/types/api.d.ts`) and JSDoc `@type` validation (`tsc --noEmit`).

---

## Quick Start

```bash
# 1. One-command server setup (creates env, generates security keys, installs dependencies)
make setup-server

# 2. Launch local debug server (Flask on :5001 + Vite on :5173)
make dev

# 3. Open Web Platform
# Frontend -> http://localhost:5173
# API      -> http://localhost:5001/api
```

Press `Ctrl+C` to stop all services.

See the [Admin Guide](guides/en/admin_guide.md) for prerequisites, TLS/HTTPS setup, Docker Compose deployment, remote worker nodes, and configuration editing (`make edit`).

---

## Architecture Overview

```mermaid
flowchart TD
    %% Client & Gateway
    Client([Browser<br>React SPA]) <-->|HTTP / SSE| Nginx[Nginx<br>Port 80 / 443]
    Nginx <-->|Reverse Proxy| API[Flask API<br>Port 5001]

    %% Core Data & Message Broker
    subgraph Core [Backend Infrastructure — Docker Compose]
        direction TB
        API -->|Read/Write| DB[(PostgreSQL<br>Primary DB)]
        API <-->|Queue / PubSub / Coordination| Redis[(Redis<br>Broker + Coordination)]
        API <-->|Cache / Locks / Rate Limits / JWT Blacklist| Cache[(Redis Cache<br>DB 1, noeviction, server-only)]
        Beat([Celery Beat<br>Scheduler]) -->|Triggers| Redis
        Internal([Internal Celery Worker<br>System tasks only<br>-Q celery,internal]) -->|Pulls Tasks| Redis
    end

    %% Remote Worker Nodes
    subgraph Remote [Remote Worker Machines]
        direction TB
        W1[Worker Container<br>lavbench-worker] -->|Sibling Containers| S1{{Docker Sandbox<br>--network none<br>CPU/RAM/PIDs limit}}
        W2[Worker Local<br>micromamba + deploy-worker.sh] -->|Sibling Containers| S2{{Docker Sandbox<br>--network none<br>CPU/RAM/PIDs limit}}
    end

    %% Connections from Redis to Workers
    Redis -.-|SSL/TLS| W1
    Redis -.-|SSL/TLS| W2

    %% Styling
    classDef default fill:#1e293b,stroke:#cbd5e1,stroke-width:1px,color:#f8fafc;
    classDef database fill:#0f172a,stroke:#f59e0b,stroke-width:2px,color:#f8fafc;
    class DB,Redis database;
```

### Core Services

| Service | Technology | Default Port | Role |
| :--- | :--- | :--- | :--- |
| **PostgreSQL** | PostgreSQL 15 | `5432` | Primary database for users, challenges, tasks, submissions, and audit logs. |
| **Redis** | Redis 7 | `6379` | Celery message broker + **coordination client** for all cross-machine shared state: SSE pub/sub fan-out, worker spec registry, dead-letter queue, build/GPU locks. |
| **Redis Cache** | Redis 7 | — | Dedicated cache instance (DB 1, `noeviction`, no persistence) for leaderboard caches, locks, rate-limit counters, and JWT revocation (`CACHE_REDIS_URL`). Server-only — external workers never receive this URL; no host port. |
| **Flask API** | Flask 3.1 + Spectree | `5001` | REST API endpoints and Server-Sent Event (SSE) streaming server. |
| **Celery Beat** | Celery Beat 5.4 | — | Periodic task scheduler (submission watchdog, automated backup schedule). |
| **Celery Worker (Int)** | Celery 5.4 | — | System task worker (backups, watchdog, leaderboard recalculation) running inside Docker Compose (`-Q celery,internal`). |
| **Celery Worker (Ext)** | Celery 5.4 | — | Evaluation-only worker running on remote machines or dedicated containers (`cpu_queue`), managing sibling sandboxes. |
| **Nginx / Frontend** | Nginx + React 19 | `80` (`NGINX_PORT`, `443` for HTTPS deployments) | Reverse proxy and static Web SPA delivery. |

---

## Configuration Reference

Copy and configure environment settings:

```bash
cp .env.example .env
```

### Core Security & Database Settings

| Variable | Description | Default / Source |
| :--- | :--- | :--- |
| `SECRET_KEY` | Secret key for JWT signing. | Generated by `make setup-server` |
| `POSTGRES_PASSWORD` | Password for the application database user. | Generated by `make setup-server` |
| `DATABASE_URL` | PostgreSQL connection URL string. | `postgresql://lavbench_user:...@localhost:5432/lavbench_db` |
| `ENCRYPTION_KEY` | Fernet key for encrypting user PII demographics at rest. | Generated by `make setup-server` |
| `WORKER_PUBLIC_KEYS_JSON` | JSON registry of `worker_id → Ed25519 public key` (server-side worker auth). | Generated by `make setup-server` |
| `WORKER_CAPABILITY_SECRET` | Secret for signing per-attempt worker capability tokens. | Generated by `make setup-server` |
| `EVALUATION_SPLIT_SECRET` | Secret for deriving the per-task public/private evaluation split. | Generated by `make setup-server` |
| `WORKER_ID` | Unique worker identity (part of the worker key registry). | Generated by `make setup-worker` |
| `WORKER_PRIVATE_KEY` | Ed25519 private key (worker-side auth token signing). | Generated by `make setup-worker` |

### Infrastructure Configuration Parameters

| Variable | Description | Default |
| :--- | :--- | :--- |
| `REDIS_PASSWORD` | Password for the Redis broker and cache instances. | Generated by `make setup-server` |
| `CELERY_BROKER_URL` | Redis URL for Celery task dispatch queue. | `redis://:...@localhost:6379/0` |
| `CELERY_RESULT_BACKEND` | Redis URL for Celery task result backend. | `redis://:...@localhost:6379/0` |
| `CACHE_REDIS_URL` | Redis URL for the dedicated cache instance (DB 1). | `redis://:...@localhost:6379/1` |
| `REDIS_BIND` | Host bind address for the Redis broker port. | `127.0.0.1` (set `0.0.0.0` for remote workers) |
| `SECURE_COOKIES` | `true` when serving over HTTPS (Secure-flag auth cookie). | `true` (set `false` for plain HTTP) |
| `NGINX_PORT` | Host port mapped to the frontend/nginx container. | `80` |
| `HTTPS_PORT` | Host port mapped to the optional nginx TLS listener (auto-enabled when `certs/web/server.crt` exists). | `443` |
| `CORS_ORIGINS` | Allowed browser origins (comma-separated). | `http://localhost:80` |
| `WORKER_MEM_LIMIT` | Memory limit for the compose internal-worker container. | `1g` |
| `WORKER_CPU_LIMIT` | CPU limit for the compose internal-worker container. | `2` |
| `WORKER_GPU_IDS` | Comma-separated GPU device IDs available for round-robin pinning on eval workers (e.g. `0,1,3`). Unset → `count=-1` fallback. | unset |
| `WORKER_ROLE` | Unified worker role. `server` = full API (default; requires `SECRET_KEY`/`DATABASE_URL`/`ENCRYPTION_KEY`); `scheduler` = Celery beat only (no app, no secrets); `internal` = app booted for system tasks (DB only, never evaluates); `eval` = remote evaluation worker (no DB, Ed25519 nonce auth, runs eval/image tasks only). | `server` |
| `WORKER_SANDBOX_STORAGE_OPT` | `--storage-opt size` cap for submission sandboxes (best-effort; ignored on drivers without quota support, e.g. ext4/overlay2). | `8g` |
| `MAX_WORKER_LOG_BYTES` | Worker remote-log file rotation threshold (bytes). | `10485760` (10 MB) |
| `MAX_COLLECT_BUFFER_BYTES` | Max in-memory buffer while pulling sandbox output archives; larger archives are skipped. | `536870912` (512 MB) |
| `MAX_EXTRACT_MEMBER_BYTES` | Max size for a single member inside collected archives; oversized members are skipped. | `536870912` (512 MB) |
| `GPU_RAM_PER_TASK_GB` | Memory limit allocated per GPU sandbox container (GB). | `8` |
| `CPU_RAM_PER_TASK_GB` | Memory limit allocated per CPU sandbox container (GB). | `4` |
| `RESERVED_RAM_GB` | Host RAM reserved for OS and Docker overhead (GB). | `4` |
| `RESERVED_CPU_CORES` | Host CPU cores reserved for system scheduler. | `1` |
| `RAM_CLAMP_FACTOR` | Maximum task RAM overshoot ratio before rejection. | `1.05` (5%) |

---

## Testing & Quality Assurance

### Backend Tests & Quality Suite

```bash
# 1. Check error codes and translation parity
python backend/scripts/check_error_codes.py

# 2. Strict Mypy type checking
cd backend && micromamba run -n lavbench_backend mypy . --no-incremental

# 3. Run Pytest suite in parallel
cd backend && micromamba run -n lavbench_backend pytest tests -n auto -q
```

The suite covers routes, authentication, AST security, rate limiting, OpenAPI spec consistency, and the evaluation engine metric paths.

### Full-Stack Smoke Test (live Docker stack)

After `make setup-admin`, verify the entire platform end-to-end against the running compose stack (auth/CSRF, role matrix for admin/jury/competitor/anonymous, rate limits, backups, SSE, edge cases — no task evaluation):

```bash
python3 scripts/api_smoke_test.py            # exit code 0 on success
```

### Database upgrades

Docker Compose runs the one-shot `migrate` service before the API and internal worker start. For a local backend process, apply the same migrations explicitly:

```bash
cd backend
python scripts/migrate.py
```

The first migration run can adopt a pre-Alembic LavBench database only when its schema exactly matches the recorded baseline. The API then verifies the revision at startup and fails fast if a deployment skipped an upgrade.

### Frontend Tests & Type Checking

```bash
cd frontend

# 1. Run vitest unit/component test suite
npm run test

# 2. Check TypeScript types (JSDoc checkJs mode)
npm run check-types

# 3. Check translation key symmetry across EN and BG
python scripts/check_translations.py
```

### Sphinx Documentation Build

```bash
cd docs
pip install -r requirements.txt
make html        # Generates HTML documentation at docs/build/html/index.html
```

---

## Documentation Sitemap

| Documentation File | Target Audience | Primary Focus |
| :--- | :--- | :--- |
| [Competitor Guide](guides/en/competitor_guide.md) | Competitors | Notebook cell submission, AST pre-validation, error matrix, leaderboard navigation. |
| [Jury Portal Guide](guides/en/jury_guide.md) | Jury Members | Submissions monitoring, build error diagnostics, double-blind privacy, manual scoring. |
| [Admin Guide](guides/en/admin_guide.md) | Administrators | Full setup, TLS/HTTPS, worker nodes, task image builds, backups, audit trails. |
| [Custom Evaluators Guide](docs/custom-evaluators.md) | Challenge Organizers | Full module contract, AST validation, and script templates for custom metrics. |
| [System Architecture](docs/source/architecture.md) | Developers & DevOps | Architectural overview, sandbox security, worker budgeting, SSE telemetry. |
| [API Swagger Documentation](http://localhost:5001/apidoc/swagger/) | Developers | Interactive OpenAPI 3.0 documentation for all backend endpoints. |

---

## License

Released under the [GNU Affero General Public License v3.0](LICENSE).
