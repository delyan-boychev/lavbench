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
- **Intelligent Worker Routing:** Celery queue routing separates GPU and CPU workloads across distinct evaluation worker pools.
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
    Client([Browser<br>React SPA]) <-->|HTTPS / SSE| Nginx[Nginx<br>Port 443]
    Nginx <-->|Reverse Proxy| API[Flask API<br>Port 5001]

    %% Core Data & Message Broker
    subgraph Core [Backend Infrastructure — Docker Compose]
        direction TB
        API -->|Read/Write| DB[(PostgreSQL<br>Primary DB)]
        API <-->|Queue / PubSub| Redis[(Redis<br>Broker & Cache)]
        Beat([Celery Beat<br>Scheduler]) -->|Triggers| Redis
        Internal([Internal Celery Worker<br>System tasks only]) -->|Pulls Tasks| Redis
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
| **Redis** | Redis 7 | `6379` | Celery message broker, SSE pub/sub channels, cache, rate limits, and token revocation. |
| **Flask API** | Flask 3.1 + Spectree | `5001` | REST API endpoints and Server-Sent Event (SSE) streaming server. |
| **Celery Beat** | Celery Beat 5.4 | — | Periodic task scheduler (submission watchdog, automated backup schedule). |
| **Celery Worker (Int)** | Celery 5.4 | — | System task worker (backups, watchdog, leaderboard recalculation) running inside Docker Compose. |
| **Celery Worker (Ext)** | Celery 5.4 | — | Evaluation worker running on remote machines or dedicated containers, managing sibling sandboxes. |
| **Nginx / Frontend** | Nginx + React 19 | `443` | Reverse proxy and static Web SPA delivery. |

---

## Directory Structure

```text
lavbench/
├── backend/
│   ├── app.py                   # Flask application factory
│   ├── config.py                # Config class reading environment variables
│   ├── models/                  # SQLAlchemy models (User, Challenge, Stage, Task, Submission)
│   ├── auth_utils.py            # JWT auth, httpOnly cookies, rate limiting, token revocation
│   ├── cache_utils.py           # Redis caching, connection pool, locks
│   ├── error_utils.py           # err() helper & DEFAULT_ERROR_MESSAGES
│   ├── evaluation_engine.py     # Parquet evaluation engine (44 metrics across 12 categories + custom evaluators)
│   ├── sse_utils.py             # SSE pub/sub helpers
│   ├── worker_utils.py          # Worker runtime & Docker sandbox status reporting
│   ├── tasks.py                 # Celery task definitions + beat schedule
│   ├── setup-admin.py           # Account creation script for master admin
│   ├── scripts/                 # Maintenance scripts (check_error_codes.py)
│   ├── routes/                  # Flask blueprints (admin, auth, challenges, tasks, leaderboard, etc.)
│   ├── services/                # Business logic
│   ├── task_modules/            # Submission runner, image builder, execution templates
│   └── tests/                   # Backend Pytest test suite (946 tests)
├── frontend/
│   ├── src/
│   │   ├── components/          # React components (admin, challenge, leaderboard, submissions, ui)
│   │   ├── pages/               # Route page components
│   │   ├── services/            # ApiService, AuthContext, AppContext
│   │   └── types/               # Auto-generated TypeScript declarations (api.d.ts)
│   ├── scripts/                 # Translation key parity checker (check_translations.py)
│   ├── public/locales/          # i18n translation JSON files (en, bg)
│   ├── tsconfig.json            # TypeScript config for JSDoc type checking
│   └── nginx.conf               # Nginx reverse proxy configuration
├── guides/                      # Comprehensive user documentation (competitor, jury, admin)
├── docs/                        # Sphinx documentation, custom evaluator guides, architecture specs
├── scripts/                     # Interactive setup, worker, deployment, and configuration scripts
├── docker-compose.yml           # Docker Compose infrastructure configuration
├── Makefile                     # Build & management targets (setup-server, setup-worker, dev, edit, docs, lint)
├── LICENSE                      # AGPL v3 License
└── NOTICE                       # Copyright notice
```

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
| `DATABASE_URL` | PostgreSQL connection URL string. | `postgresql://lavbench:...` |
| `ENCRYPTION_KEY` | Fernet key for encrypting user PII demographics at rest. | Generated by `make setup-server` |
| `WORKER_PUBLIC_KEY` | Ed25519 public key (server-side worker auth). | Generated by `make setup-server` |
| `WORKER_PRIVATE_KEY` | Ed25519 private key (worker-side auth token signing). | Generated by `make setup-worker` |

### Infrastructure Configuration Parameters

| Variable | Description | Default |
| :--- | :--- | :--- |
| `CELERY_BROKER_URL` | Redis URL for Celery task dispatch queue. | `redis://localhost:6379/0` |
| `CELERY_RESULT_BACKEND` | Redis URL for Celery task result backend. | `redis://localhost:6379/0` |
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

Includes 946 unit and integration tests covering routes, authentication, AST security, rate limiting, and all 44 evaluation engine metric paths.

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
| [System Architecture](docs/ARCHITECTURE.md) | Developers & DevOps | Architectural overview, sandbox security, worker budgeting, SSE telemetry. |
| [API Swagger Documentation](http://localhost:5001/apidoc/swagger/) | Developers | Interactive OpenAPI 3.0 documentation for all backend endpoints. |

---

## License

Released under the [GNU Affero General Public License v3.0](LICENSE).
