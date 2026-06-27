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

## Demo

Interact with a live simulation of the real-time leaderboard at [`/demo/leaderboard`](http://localhost:5173/demo/leaderboard) (start the frontend with `npm run dev`, no backend required).

Scores auto-shuffle every 4 seconds to demonstrate the SSE-like rank changes, medal styling, and expandable per-task score breakdown. Toggle streaming on/off or click **Shuffle Now** to trigger manual updates.

![Live leaderboard updating scores in real-time](docs/source/_static/demo/leaderboard-live.gif)

---

## Features

- **Sandboxed Execution:** User code runs in hardened Docker containers with `--network none`, `--cap-drop ALL`, `--read-only` rootfs, `--security-opt no-new-privileges`, CPU/RAM/process limits, and `tmpfs` mounts.
- **Double-Blind Review:** Competitor demographics are encrypted at rest (Fernet) and only revealed after scores are finalized.
- **Live Leaderboards:** Server-Sent Events push real-time score updates to all connected clients.
- **Multi-Stage Competitions:** Support for stages with independent deadlines, grace periods, and score visibility controls.
- **Custom Evaluators:** Jury members can upload Python evaluation scripts with per-metric weighting and configuration.
- **GPU/CPU Routing:** Celery queue routing intelligently separates GPU and CPU workloads across different worker pools.
- **Automated Backups:** Database and uploaded files are backed up every 20 minutes during active competitions (every 6 hours when idle).
- **Audit Logs:** Full logging of administrative actions (e.g. creating/deleting challenges, resetting passwords, editing scores) with detailed metadata payloads and justification tracking.
- **i18n Support:** Available in English and Bulgarian (contributions for additional languages are welcome).
- **Strict Security:** Includes httpOnly cookie auth, token revocation with a Redis blacklist, rate limiting, encrypted PII, and ProxyFix for trusted reverse proxies.
- **Typed API & Validation:** OpenAPI 3.0 spec with auto-generated TypeScript type declarations and JSDoc `@type` annotations on all frontend API calls. `tsc --noEmit` verifies all JSDoc annotations and component props.

---

## Quick Start

```bash
# 1. One-command setup (creates env, generates keys, installs deps)
make setup

# 2. Launch locally
make dev

# 3. Open
# Frontend -> http://localhost:5173
# API      -> http://localhost:5001/api
```

Press `Ctrl+C` to stop all services.

### Deploy with Docker

```bash
make deploy-docker
# http://localhost — full stack in containers
```

### Remote Workers

```bash
# After make setup, worker.env is ready — copy it to the worker:
scp worker.env user@worker-machine:~/

# On the worker machine (Docker only, no repo needed):
make worker          # interactive first-run setup, then start

# Or skip the interactive prompts:
make worker-docker   # starts directly from saved worker.env
```

On first `make worker` you'll be guided through:

- Docker or local (micromamba) mode
- Worker type: evaluation, internal, or both
- GPU selection (with automatic detection via `nvidia-smi`)
- CPU cores per task (GPU and CPU)
- Auto-calculated Celery concurrency

Saved to `worker.env` — subsequent runs skip the setup.

### Editing Configuration

```bash
make edit          # Menu-based editor for server .env (address, HTTPS, Redis TLS, CORS)
make edit-worker   # Menu-based editor for worker.env (type, GPUs, cores, concurrency)
```

Both editors protect auto-generated keys — only safe properties are modifiable.

See the [Admin Guide](guides/en/admin_guide.md) for production deployment.

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

| Service           | Role                                                                                             | Port   |
| ----------------- | ------------------------------------------------------------------------------------------------ | ------ |
| **PostgreSQL**    | Primary database for users, challenges, tasks, and submissions                                   | `5432` |
| **Redis**         | Celery message broker, SSE pub/sub, caching, and rate limiting                                   | `6379` |
| **Flask API**     | REST API and SSE streaming endpoints                                                             | `5001` |
| **Celery Worker** | Runs on the host via `scripts/start-worker.sh` to build Docker sandboxes and execute submissions | —      |
| **Celery Beat**   | Handles periodic tasks like the submission watchdog and automated backups                        | —      |
| **Nginx/React**   | Static file serving and API reverse proxy                                                        | `80`   |

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
│   ├── error_utils.py           # err() helper + DEFAULT_ERROR_MESSAGES (128 error codes)
│   ├── evaluation_engine.py     # Parquet-based evaluation with 70+ metrics across 12 categories
│   ├── sse_utils.py             # SSE pub/sub helpers
│   ├── worker_utils.py          # Worker runtime (Docker commands, status reporting)
│   ├── tasks.py                 # Celery task definitions + beat schedule
│   ├── Dockerfile               # Backend container (Flask + Celery)
│   ├── Dockerfile.worker        # Minimal worker-only container (~100 MB)
│   ├── setup-admin.py            # Creates admin user account + admin_credentials.txt
│   ├── scripts/                 # Lint/CI scripts (check_error_codes.py)
│   ├── utils/                  # Utility modules (access, audit, cache, dates, files, etc.)
│   ├── routes/                  # Flask blueprints (admin, auth, challenges, etc.)
│   ├── services/                # Business logic
│   ├── task_modules/            # Submission runner, templates, system tasks
│   └── tests/                   # Backend tests (pytest, 946 tests, 75% coverage)
├── frontend/
│   ├── src/
│   │   ├── components/          # Reusable components (admin, challenge, ui, layout)
│   │   ├── pages/               # Page components
│   │   ├── services/            # ApiService, AuthContext, AppContext
│   │   ├── context/             # React context providers
│   │   ├── hooks/               # Custom hooks
│   │   └── types/               # Auto-generated TypeScript declarations (api.d.ts)
│   ├── scripts/
│   │   └── check_translations.py # Validates i18n keys
│   ├── public/locales/          # i18n (en, bg)
│   ├── tsconfig.json            # TypeScript config for JSDoc type checking
│   └── nginx.conf               # Nginx configuration
├── guides/                      # User documentation (student, jury, admin, API)
├── docs/                        # Project documentation (Sphinx, architecture)
├── scripts/
│   ├── setup.sh                 # First-time server setup (prereqs, micromamba, keys)
│   ├── generate-keys.sh         # Interactive key/cert generator (.env + worker.env)
│   ├── edit-config.sh           # Menu-based config editor (server + worker)
│   ├── start-worker.sh          # Worker launcher (docker + local, interactive first-run)
│   ├── deploy-docker.sh         # Docker Compose deployment
│   └── deploy-debug.sh          # Local debug mode (micromamba + Flask + Celery)
├── docker-compose.yml           # Docker Compose (db, redis, backend, beat, frontend)
├── Makefile                     # Top-level targets (setup, worker, edit, deploy-docker, docs)
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

| Variable                        | Description                             | Example / Requirement                                                                            |
| ------------------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `SECRET_KEY`                    | Flask secret for JWT signing            | **Required** — generate a random 64+ char string                                                 |
| `DATABASE_URL`                  | PostgreSQL connection string            | `postgresql://user:pass@localhost:5432/dbname`                                                   |
| `CELERY_BROKER_URL`             | Redis broker for Celery                 | `redis://localhost:6379/0`                                                                       |
| `CELERY_RESULT_BACKEND`         | Redis result backend                    | `redis://localhost:6379/0`                                                                       |
| `WORKER_SECRET_KEY`             | Shared secret for worker to server auth | **Required for workers**                                                                         |
| `ENCRYPTION_KEY`                | Fernet key for PII encryption           | Run: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `HF_CACHE_DIR`                  | HuggingFace dataset cache directory     | `./backend/hf_cache`                                                                             |
| `CORS_ORIGINS`                  | Allowed CORS origins                    | `http://localhost:80`                                                                            |
| `MAIN_SERVER_URL`               | Server URL for worker callbacks         | `http://localhost:5001`                                                                          |
| `FLASK_DEBUG`                   | Enable Flask debug mode                 | `false`                                                                                          |
| `DEADLINE_GRACE_PERIOD_SECONDS` | Grace period after a deadline           | `60`                                                                                             |
| `UPLOAD_FOLDER`                | Upload storage path                      | `./backend/uploads`                                                                              |
| `BACKUPS_DIR`                  | Backup file storage path                 | `./backend/backups`                                                                              |
| `WORKER_GPU_ID`                | GPU device(s) for GPU workers            | `0` (comma-separated for multiple)                                                               |
| `WORKER_PUBLIC_KEY`            | Ed25519 public key for worker auth       | **Required for workers** — base64 encoded                                                        |
| `WORKER_PRIVATE_KEY`           | Ed25519 private key for worker auth      | **Required for workers** — base64 encoded                                                        |
| `REDIS_PASSWORD`               | Redis auth password                      | `your_redis_password`                                                                            |
| `REDIS_SSL_CA_CERTS`           | Redis SSL CA certificate path (container)| `/etc/ssl/certs/redis/redis-ca.crt`                                                              |
| `REDIS_SSL_CERTFILE`           | Redis SSL client certificate path        | `/etc/ssl/certs/redis/redis-client.crt`                                                          |
| `REDIS_SSL_KEYFILE`            | Redis SSL client key path                | `/etc/ssl/certs/redis/redis-client.key`                                                          |
| `REDIS_SSL_CERT_REQS`          | Redis SSL certificate verification level | `required`                                                                                       |
| `INTERNAL_ONLY_WORKER`         | Restrict worker to system tasks only     | `false`                                                                                          |
| `EVALUATION_ONLY_WORKER`       | Restrict worker to evaluation tasks only | `false`                                                                                          |
| `WORKER_MODE`                  | Worker run mode (worker.env)             | `docker` / `local` — set by first-run setup                                                      |
| `WORKER_TYPE`                  | Worker task role (worker.env)            | `eval` / `internal` / `both` — set by first-run setup                                            |
| `GPU_CORES_PER_TASK`           | CPU cores per GPU evaluation container   | `4` — set by first-run setup                                                                     |
| `CPU_CORES_PER_TASK`           | CPU cores per CPU evaluation container   | `2` — set by first-run setup                                                                     |
| `CELERY_WORKER_CONCURRENCY`    | Max concurrent worker processes          | Auto-calculated from GPU/CPU core allocation                                                     |

---

## Testing

### Backend Testing

```bash
cd backend
micromamba run -n lavbench_backend python -m pytest -n auto tests/ -v
```

Includes 946 tests covering routes, auth, evaluation (all 44 metric paths), caching, rate limiting, models, submission runner, and evaluation engine edge cases.

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

# Unit / component tests (vitest — 527 tests)
npm run test

# Type checking (JSDoc annotations + component props)
npm run check-types

# Error code & translation parity check
python ../backend/scripts/check_error_codes.py

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

#### Quick Start (Interactive)

```bash
# Copy the worker.env from the server (generated by make setup):
scp worker.env user@worker-machine:~/

# On the worker machine:
make worker   # interactive first-run — asks mode, type, GPUs, cores
              # subsequent runs skip the prompts
```

The first-run setup detects available CPUs and GPUs (via `nvidia-smi`), then guides you through:

1. **Run mode** — Docker container (recommended) or local micromamba
2. **Worker type** — evaluation, internal, or both
3. **GPU selection** — which GPU devices to use (if detected)
4. **CPU cores per task** — allocated per GPU evaluation container and per CPU evaluation container
5. **Concurrency** — auto-calculated from your selections

#### Building the Worker Image

```bash
# Build the minimal worker image locally (Celery + tasks only, ~100 MB):
make build-worker

# Or pull the version tagged in your release:
WORKER_IMAGE=lavbench-worker:latest make worker
```

#### Direct Invocation

```bash
scripts/start-worker.sh --docker                    # interactive if no worker.env
scripts/start-worker.sh --docker redis://:pass@...   # non-interactive

# Local mode (micromamba):
make start-worker REDIS_URL=redis://:password@server:6379/0
```

**Options**:
- `-g, --gpu <GPU_ID>`: Override GPU device(s) from worker.env
- `-c, --concurrency <N>`: Override worker concurrency
- `-i, --internal`: Force internal-only mode

---

## Security Highlights

| Layer                | Mechanism                                                                                                                                                                                                  |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Authentication**   | httpOnly cookies with JWTs (XSS-immune), 24h expiry.                                                                                                                                                       |
| **Authorization**    | Role-based (admin, jury, competitor) with DB-backed role lookup.                                                                                                                                           |
| **Token Revocation** | Redis blacklist using `jti` — logging out instantly invalidates tokens.                                                                                                                                    |
| **Rate Limiting**    | Lua atomic counters per-user and per-endpoint; fails open if Redis is down.                                                                                                                                |
| **PII Encryption**   | Fernet symmetric encryption secures competitor demographics at rest.                                                                                                                                       |
| **Sandbox**          | Hardened container: `--network none`, `--cap-drop ALL`, `--read-only` rootfs, `--security-opt no-new-privileges`, `--cpus 2`, `--pids-limit 64`, `--tmpfs /tmp`, `--memory-swap` disabled, and RAM limits. |
| **Ground Truth**     | `labels.parquet` is strictly evaluated server-side and never mounted into the user's evaluation sandbox.                                                                                                   |
| **IP Trust**         | `ProxyFix` middleware ensures only the `X-Forwarded-For` headers from Nginx are trusted.                                                                                                                   |
| **HF API Keys**      | Fetched dynamically on-demand by workers via authenticated API routes, never stored in Redis.                                                                                                              |

---

## Documentation

| Guide                                                       | Target Audience | Focus Areas                                                                        |
| ----------------------------------------------------------- | --------------- | ---------------------------------------------------------------------------------- |
| [Student Guide](guides/en/student_guide.md)                 | Competitors     | Logging in, understanding tasks, submitting notebooks, leaderboard navigation.     |
| [Jury Guide](guides/en/jury_guide.md)                       | Jury Members    | Monitoring submissions, manual scoring, competitor registration, exports.          |
| [Admin Guide](guides/en/admin_guide.md)                     | Administrators  | Challenge/task management, backups, worker health monitoring, user administration. |
| [API Reference](http://localhost:5001/apidocs)              | Developers      | Interactive Swagger UI detailing all 72 backend endpoints.                         |
| [Error Code Linter](backend/scripts/check_error_codes.py) | Developers      | Validates `err()` usage and `api.ERR_*` translation parity across EN/BG.           |
| [Sphinx Documentation](https://lavbench.readthedocs.io/)    | Developers      | Full auto-generated API reference (autodoc) and rendered OpenAPI spec.             |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full pull request checklist, setup guide, code conventions, and type system overview.

---

## License

Released under the [GNU Affero General Public License v3.0](LICENSE).
