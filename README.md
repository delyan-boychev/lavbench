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

It is a secure, sandboxed machine learning competition platform. Participants submit Jupyter notebooks or raw Python code which are executed in isolated Docker containers under strict resource constraints. Real-time leaderboards stream via SSE, with double-blind review for anonymous jury scoring.

Created by the Bulgarian AI Olympiad Committee for IOAI selection and national competitions. Other countries AI olympiad committees, teams and IOAI board and others are welcome to use and contribute.

---

## Features

* **Sandboxed Execution:** User code runs in hardened Docker containers with `--network none`, `--cap-drop ALL`, `--read-only` rootfs, `--security-opt no-new-privileges`, CPU/RAM/process limits, and `tmpfs` mounts.
* **Double-Blind Review:** Competitor demographics are encrypted at rest (Fernet) and only revealed after scores are finalized.
* **Live Leaderboards:** Server-Sent Events push real-time score updates to all connected clients.
* **Multi-Stage Competitions:** Support for stages with independent deadlines, grace periods, and score visibility controls.
* **Custom Evaluators:** Jury members can upload Python evaluation scripts with per-metric weighting and configuration.
* **GPU/CPU Routing:** Celery queue routing intelligently separates GPU and CPU workloads across different worker pools.
* **Automated Backups:** Database and uploaded files are backed up every 20 minutes during active competitions (every 6 hours when idle), including competition lifecycle snapshots.
* **i18n Support:** Available in English and Bulgarian (contributions for additional languages are welcome).
* **Strict Security:** Includes httpOnly cookie auth, token revocation with a Redis blacklist, rate limiting, encrypted PII, and ProxyFix for trusted reverse proxies.
* **Typed API & Validation:** OpenAPI 3.0 spec with auto-generated TypeScript type declarations and JSDoc `@type` annotations on all frontend API calls. `tsc --noEmit` verifies all JSDoc annotations and component props.

---

## Quick Start

```bash
# 1. Configure
cp .env.example .env
# Edit .env — set SECRET_KEY, ENCRYPTION_KEY, and any other necessary values
# Generate ENCRYPTION_KEY: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Also run setup-admin.py after first deploy to create an admin user
python backend/setup-admin.py

# 2. Launch
./scripts/deploy-debug.sh

# 3. Open
# Frontend -> http://localhost:5173
# API      -> http://localhost:5001/api
```

Press `Ctrl+C` in your terminal to gracefully stop all services.

---

## Architecture

```mermaid
flowchart TD
    %% Client & Gateway
    Client([Browser<br>React]) <-->|HTTP / SSE| Nginx[Nginx<br>Port 80]
    Nginx <-->|Reverse Proxy| API[Flask API<br>Port 5001]

    %% Core Data & Message Broker
    subgraph Core [Backend Infrastructure]
        direction TB
        API -->|Read/Write| DB[(PostgreSQL<br>Primary DB)]
        API <-->|Queue / PubSub| Redis[(Redis<br>Broker & Cache)]
        Beat([Celery Beat<br>Scheduler]) -->|Triggers| Redis
    end

    %% Worker Nodes
    subgraph Workers [Worker Pool]
        direction TB
        Redis -->|Pulls Tasks| GPU[GPU Worker<br>scripts/start-worker.sh 0]
        Redis -->|Pulls Tasks| CPU1[CPU Worker<br>scripts/start-worker.sh]
        Redis -->|Pulls Tasks| CPU2[CPU Worker<br>scripts/start-worker.sh]
    end

    %% Execution Sandbox
    subgraph Execution [Sandboxed Environment]
        GPU --> Sandbox
        CPU1 --> Sandbox
        CPU2 --> Sandbox
        Sandbox{{Docker Sandbox<br>--network none<br>CPU/RAM/PIDs limit}}
    end

    %% Styling (Optional but keeps it clean)
    classDef default fill:#1e293b,stroke:#cbd5e1,stroke-width:1px,color:#f8fafc;
    classDef database fill:#0f172a,stroke:#f59e0b,stroke-width:2px,color:#f8fafc;
    class DB,Redis database;
```

### Components

| Service | Role | Port |
|---------|------|------|
| **PostgreSQL** | Primary database for users, challenges, tasks, and submissions | `5432` |
| **Redis** | Celery message broker, SSE pub/sub, caching, and rate limiting | `6379` |
| **Flask API** | REST API and SSE streaming endpoints | `5001` |
| **Celery Worker** | Runs on the host via `scripts/start-worker.sh` to build Docker sandboxes and execute submissions | — |
| **Celery Beat** | Handles periodic tasks like the submission watchdog and automated backups | — |
| **Nginx/React** | Static file serving and API reverse proxy | `80` |

---

## Project Structure

```text
lavbench/
├── backend/
│   ├── app.py                   # Flask application factory
│   ├── config.py                # Configuration from .env
│   ├── models.py                # SQLAlchemy models
│   ├── auth_utils.py            # JWT auth, rate limiting, token revocation
│   ├── cache_utils.py           # Redis caching, connection pool, locks
│   ├── evaluation_engine.py     # Parquet-based evaluation with 50+ metrics
│   ├── sse_utils.py             # SSE pub/sub helpers
│   ├── worker_utils.py          # Worker runtime (Docker commands, status reporting)
│   ├── tasks.py                 # Celery task definitions + beat schedule
│   ├── Dockerfile               # Backend container
│   ├── setup-admin.py            # Creates admin user account + admin_credentials.txt
│   ├── routes/                  # Flask blueprints (admin, auth, challenges, etc.)
│   ├── services/                # Business logic
│   ├── task_modules/            # Submission runner, templates, system tasks
│   └── tests/                   # Backend tests (pytest, 120 tests)
├── frontend/
│   ├── src/
│   │   ├── components/          # Reusable components (admin, challenge, ui, layout)
│   │   ├── pages/               # Page components
│   │   ├── services/            # ApiService, AuthContext, AppContext
│   │   ├── context/             # React context providers
│   │   ├── hooks/               # Custom hooks
│   │   └── types/               # Auto-generated TypeScript declarations (api.d.ts)
│   ├── scripts/
│   │   ├── _annotate_types.py    # Injects JSDoc @type annotations
│   │   └── check_translations.py # Validates i18n keys
│   ├── public/locales/          # i18n (en, bg)
│   ├── tsconfig.json            # TypeScript config for JSDoc type checking
│   └── nginx.conf               # Nginx configuration
├── guides/                      # User documentation (student, jury, admin, API)
├── docs/                        # Project documentation (Sphinx, architecture)
├── scripts/                     # Deployment and worker launcher scripts
├── docker-compose.yml           # Docker Compose (db, redis, backend, beat, frontend)
├── Makefile                     # Top-level targets (deploy-docker, deploy-debug, start-worker, docs)
├── .env.example                 # Environment template
├── LICENSE                      # AGPL v3
└── NOTICE                       # Copyright notice
```

---

## Configuration

Copy and edit the environment file:

```bash
cp .env.example .env
```

| Variable | Description | Example / Requirement |
|----------|-------------|-----------------------|
| `SECRET_KEY` | Flask secret for JWT signing | **Required** — generate a random 64+ char string |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://user:pass@localhost:5432/dbname` |
| `CELERY_BROKER_URL` | Redis broker for Celery | `redis://localhost:6379/0` |
| `CELERY_RESULT_BACKEND` | Redis result backend | `redis://localhost:6379/0` |
| `WORKER_SECRET_KEY` | Shared secret for worker to server auth | **Required for workers** |
| `ENCRYPTION_KEY` | Fernet key for PII encryption | Run: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `HF_CACHE_DIR` | HuggingFace dataset cache directory | `./backend/hf_cache` |
| `CORS_ORIGINS` | Allowed CORS origins | `http://localhost:80` |
| `MAIN_SERVER_URL` | Server URL for worker callbacks | `http://localhost:5001` |
| `FLASK_DEBUG` | Enable Flask debug mode | `false` |
| `DEADLINE_GRACE_PERIOD_SECONDS` | Grace period after a deadline | `60` |

---

## Testing

### Backend Testing

```bash
cd backend
micromamba run -n lavbench_backend python -m pytest tests/ -v
```
Includes ~780 tests covering routes, auth, evaluation, caching, rate limiting, and models.

### Sphinx Documentation

```bash
cd docs
pip install -r requirements.txt
make html        # generates build/ (open docs/build/index.html)
make clean       # removes build/
```

The Sphinx build runs automatically in CI (`.github/workflows/ci.yml`) and deploys to [Read the Docs](https://lavbench.readthedocs.io/) on push to `main`.

### Frontend Testing

```bash
cd frontend

# Unit / component tests (vitest — 362 tests)
npm run test

# Type checking (JSDoc annotations + component props)
npm run check-types

# Translation integrity (finds missing keys, symmetry, orphaned keys)
python3 scripts/check_translations.py

# Regenerate API types after backend spec changes
python3 scripts/_annotate_types.py

# Build Sphinx documentation
pip install -r docs/requirements.txt
cd docs && make html
```

---

## Deployment

### Docker Compose

```bash
./scripts/deploy-docker.sh
```
Starts PostgreSQL, Redis, Flask API, Celery Beat, and Nginx/React frontend. Workers run separately on host machines.

### Remote Workers

Workers require Docker and the NVIDIA Container Toolkit (for GPU tasks). No direct database access is needed.

```bash
# General Syntax
make start-worker REDIS_URL=redis://... [GPU_ID=0]

# GPU worker example
make start-worker REDIS_URL=redis://:password@server:6379/0 GPU_ID=0

# CPU worker example
make start-worker REDIS_URL=redis://:password@server:6379/0
```

---

## Security Highlights

| Layer | Mechanism |
|-------|-----------|
| **Authentication** | httpOnly cookies with JWTs (XSS-immune), 24h expiry. |
| **Authorization** | Role-based (admin, jury, competitor) with DB-backed role lookup. |
| **Token Revocation** | Redis blacklist using `jti` — logging out instantly invalidates tokens. |
| **Rate Limiting** | Lua atomic counters per-user and per-endpoint; fails open if Redis is down. |
| **PII Encryption** | Fernet symmetric encryption secures competitor demographics at rest. |
| **Sandbox** | Hardened container: `--network none`, `--cap-drop ALL`, `--read-only` rootfs, `--security-opt no-new-privileges`, `--cpus 2`, `--pids-limit 64`, `--tmpfs /tmp`, `--memory-swap` disabled, and RAM limits. |
| **Ground Truth** | `labels.parquet` is strictly evaluated server-side and never mounted into the user's evaluation sandbox. |
| **IP Trust** | `ProxyFix` middleware ensures only the `X-Forwarded-For` headers from Nginx are trusted. |
| **HF API Keys** | Fetched dynamically on-demand by workers via authenticated API routes, never stored in Redis. |

---

## Documentation

| Guide | Target Audience | Focus Areas |
|-------|-----------------|-------------|
| [Student Guide](guides/en/student_guide.md) | Competitors | Logging in, understanding tasks, submitting notebooks, leaderboard navigation. |
| [Jury Guide](guides/en/jury_guide.md) | Jury Members | Monitoring submissions, manual scoring, competitor registration, exports. |
| [Admin Guide](guides/en/admin_guide.md) | Administrators | Challenge/task management, backups, worker health monitoring, user administration. |
| [API Reference](http://localhost:5001/apidocs) | Developers | Interactive Swagger UI detailing all 68 backend endpoints. |
| [Translation Check](frontend/scripts/check_translations.py) | Developers | Validates i18n keys across EN/BG, highlighting missing or orphaned entries. |
| [Sphinx Documentation](https://lavbench.readthedocs.io/) | Developers | Full auto-generated API reference (autodoc) and rendered OpenAPI spec. |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full pull request checklist, setup guide, code conventions, and type system overview.

---

## License

Released under the [GNU Affero General Public License v3.0](LICENSE).