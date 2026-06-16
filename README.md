# LavBench

<div align="center">
  <svg width="96" height="96" viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect width="36" height="36" rx="8" fill="#0f172a" />
    <path d="M 18 11.5 L 18 6.5 M 21.8 12.6 Q 25.1 11.3 23.7 8.0 M 25.1 15.6 Q 28.6 15.6 28.6 12.1 M 27.2 20.2 Q 30.5 21.5 31.8 18.3 M 28 25.5 Q 30.5 28.0 33 25.5 M 14.2 12.6 Q 10.9 11.3 12.3 8.0 M 10.9 15.6 Q 7.4 15.6 7.4 12.1 M 8.8 20.2 Q 5.5 21.5 4.2 18.3 M 8 25.5 Q 5.5 28.0 3 25.5" stroke="#f59e0b" stroke-width="1.2" stroke-linecap="round" opacity="0.8"/>
    <circle cx="18" cy="6.5" r="1.2" fill="#f59e0b"/>
    <circle cx="12.3" cy="8.0" r="1.2" fill="#f59e0b"/>
    <circle cx="23.7" cy="8.0" r="1.2" fill="#f59e0b"/>
    <circle cx="7.4" cy="12.1" r="1.2" fill="#f59e0b"/>
    <circle cx="28.6" cy="12.1" r="1.2" fill="#f59e0b"/>
    <circle cx="4.2" cy="18.3" r="1.2" fill="#f59e0b"/>
    <circle cx="31.8" cy="18.3" r="1.2" fill="#f59e0b"/>
    <circle cx="3" cy="25.5" r="1.2" fill="#f59e0b"/>
    <circle cx="33" cy="25.5" r="1.2" fill="#f59e0b"/>
    <path d="M 8 25.5 A 10 14 0 0 1 28 25.5" stroke="#f59e0b" stroke-width="1.5" fill="none"/>
    <rect x="6.5" y="25.5" width="3" height="4" rx="1.5" fill="#f59e0b"/>
    <rect x="26.5" y="25.5" width="3" height="4" rx="1.5" fill="#f59e0b"/>
    <rect x="11.5" y="18.5" width="3" height="11" rx="1.5" fill="#f59e0b"/>
    <circle cx="13" cy="18.5" r="2.2" fill="#0f172a"/>
    <circle cx="13" cy="18.5" r="1.4" fill="#fff"/>
    <circle cx="13" cy="18.5" r="0.6" fill="#0f172a"/>
    <rect x="21.5" y="18.5" width="3" height="11" rx="1.5" fill="#f59e0b"/>
    <circle cx="23" cy="18.5" r="2.2" fill="#0f172a"/>
    <circle cx="23" cy="18.5" r="1.4" fill="#fff"/>
    <circle cx="23" cy="18.5" r="0.6" fill="#0f172a"/>
    <rect x="16.5" y="14.5" width="3" height="15" rx="1.5" fill="#f59e0b"/>
    <circle cx="18" cy="27.5" r="2.2" fill="#0f172a"/>
    <circle cx="18" cy="27.5" r="0.9" fill="#fff"/>
  </svg>
</div>

[![License](https://img.shields.io/badge/license-AGPL%20v3-blue.svg)](LICENSE)

A secure, sandboxed machine learning competition platform. Participants submit Jupyter notebooks or raw Python code which are executed in isolated Docker containers under strict resource constraints. Real-time leaderboards stream via SSE, with double-blind review for anonymous jury scoring.

Created by the Bulgarian Team. Contributions and use by others are welcome.

---

## Features

- **Sandboxed Execution** — User code runs in throwaway Docker containers with `--network none`, CPU/RAM/process limits, and `tmpfs` mounts
- **Double-Blind Review** — Competitor demographics encrypted at rest (Fernet), only revealed after scores are finalized
- **Live Leaderboards** — Server-Sent Events push real-time score updates to all connected clients
- **Multi-Stage Competitions** — Stages with independent deadlines, grace periods, and score visibility controls
- **Custom Evaluators** — Jury can upload Python evaluation scripts with per-metric weighting and configuration
- **GPU/CPU Routing** — Celery queue routing separates GPU and CPU workloads across worker pools
- **Automated Backups** — Database + uploaded files backed up every 20 minutes during active competitions (every 6 hours when idle), with competition lifecycle snapshots
- **i18n** — English and Bulgarian
- **Security** — httpOnly cookie auth, token revocation with Redis blacklist, rate limiting, encrypted PII, ProxyFix for trusted reverse proxies

---

## Quick Start

```bash
# 1. Configure
cp .env.example .env
# Edit .env — set SECRET_KEY and any other values

# 2. Launch
chmod +x deploy_debug.sh
./deploy_debug.sh

# 3. Open
# Frontend → http://localhost:5173
# API      → http://localhost:5001/api
```

Press `Ctrl+C` to stop all services.

---

## Architecture

```
┌──────────┐     ┌──────────────┐     ┌──────────────┐
│  Browser  │────▶│  Nginx/React  │────▶│  Flask API    │
│  (React)  │◀────│  (Port 80)    │◀────│  (Port 5001)  │
└──────────┘     └──────────────┘     └──────┬───────┘
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    │                         │                         │
              ┌─────▼─────┐           ┌──────▼──────┐          ┌──────▼──────┐
              │ PostgreSQL │           │    Redis     │          │ Celery Beat │
              │   (DB)     │           │  (Broker +   │          │ (Scheduler) │
              └───────────┘           │   Cache)     │          └─────────────┘
                                      └──────┬──────┘
                                              │
                              ┌───────────────┼───────────────┐
                              │               │               │
                       ┌──────▼──────┐ ┌─────▼─────┐  ┌──────▼──────┐
                       │  GPU Worker  │ │ CPU Worker │  │ CPU Worker  │
                       │ (start_worker│ │(start_worker│  │(start_worker│
                       │   .sh 0)     │ │   .sh)     │  │   .sh)      │
                       └──────┬──────┘ └─────┬─────┘  └──────┬──────┘
                              │               │               │
                              └───────────────┼───────────────┘
                                              │
                                    ┌─────────▼─────────┐
                                    │  Docker Sandbox     │
                                    │  (--network none)   │
                                    │  CPU/RAM/PIDs limit │
                                    └────────────────────┘
```

**Components**:

| Service | Role | Port |
|---------|------|------|
| **PostgreSQL** | Primary database — users, challenges, tasks, submissions | 5432 |
| **Redis** | Celery message broker, SSE pub/sub, caching, rate limiting | 6379 |
| **Flask API** | REST API + SSE streaming endpoints | 5001 |
| **Celery Worker** | Runs on host via `start_worker.sh` — builds Docker sandboxes, executes submissions | — |
| **Celery Beat** | Periodic tasks — watchdog (stuck submissions), automated backups | — |
| **Nginx/React** | Static file serving + API reverse proxy | 80 |

---

## Project Structure

```
lavbench-webplatform/
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
│   ├── routes/                  # Flask blueprints
│   │   ├── admin.py             # Admin dashboard, user management, backups
│   │   ├── auth.py              # Login, logout, rate limiting
│   │   ├── challenges.py        # Challenge CRUD, stages, finalize
│   │   ├── submissions.py       # Notebook parsing, submission pipeline
│   │   ├── tasks.py             # Task CRUD, worker endpoints
│   │   ├── leaderboard.py       # Leaderboard + manual points
│   │   └── docs.py              # In-app documentation
│   ├── services/                # Business logic
│   ├── task_modules/            # Submission runner, templates, system tasks
│   └── tests/                   # Backend tests (pytest, 129 tests)
├── frontend/
│   ├── src/
│   │   ├── components/          # Reusable components (admin, challenge, ui, layout)
│   │   ├── pages/               # Page components
│   │   ├── services/            # ApiService, AuthContext, AppContext
│   │   ├── context/             # React context providers
│   │   └── hooks/               # Custom hooks
│   ├── public/locales/          # i18n (en, bg)
│   └── nginx.conf               # Nginx configuration
├── guides/                      # User documentation (student, jury, admin, API)
├── docker-compose.yml           # Docker Compose (db, redis, backend, beat, frontend)
├── deploy_debug.sh              # Local dev launcher
├── deploy_docker.sh             # Production deployment
├── start_worker.sh              # Remote GPU/CPU worker bootstrap
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

| Variable | Description | Default / Example |
|----------|-------------|-------------------|
| `SECRET_KEY` | Flask secret for JWT signing | **Required** — generate a random 64+ char string |
| `DATABASE_URL` | PostgreSQL connection | `postgresql://user:pass@localhost:5432/dbname` |
| `CELERY_BROKER_URL` | Redis broker for Celery | `redis://localhost:6379/0` |
| `CELERY_RESULT_BACKEND` | Redis result backend | `redis://localhost:6379/0` |
| `WORKER_SECRET_KEY` | Shared secret for worker ↔ server auth | **Required for workers** |
| `ENCRYPTION_KEY` | Fernet key for PII encryption | Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `HF_CACHE_DIR` | HuggingFace dataset cache | `./backend/hf_cache` |
| `CORS_ORIGINS` | Allowed CORS origins | `http://localhost:80` |
| `MAIN_SERVER_URL` | Server URL for worker callbacks | `http://localhost:5001` |
| `FLASK_DEBUG` | Enable Flask debug mode | `false` |
| `DEADLINE_GRACE_PERIOD_SECONDS` | Grace period after deadline | `60` |

---

## Testing

### Backend

```bash
cd backend
source venv/bin/activate
python -m pytest tests/ -v
```

129 tests covering routes, auth, evaluation, caching, rate limiting, and models.

### Frontend

```bash
cd frontend
npm run test
```

149 tests covering all components, pages, auth context, and API service.

---

## Deployment

### Docker Compose

```bash
chmod +x deploy_docker.sh
./deploy_docker.sh
```

Starts PostgreSQL, Redis, Flask API, Celery Beat, and Nginx/React frontend. Workers run separately on host machines.

### Remote Workers

```bash
./start_worker.sh <REDIS_URL> [GPU_ID]

# GPU worker
./start_worker.sh redis://:password@server:6379/0 0

# CPU worker
./start_worker.sh redis://:password@server:6379/0
```

Workers require Docker and NVIDIA Container Toolkit (for GPU). No database access needed.

---

## Security

| Layer | Mechanism |
|-------|-----------|
| **Authentication** | httpOnly cookies with JWTs (XSS-immune), 24h expiry |
| **Authorization** | Role-based (admin, jury, competitor) with DB-backed role lookup |
| **Token Revocation** | Redis blacklist with `jti` — logout instantly invalidates tokens |
| **Rate Limiting** | Lua atomic counters per-user per-endpoint, Redis-down fails open |
| **PII Encryption** | Fernet symmetric encryption for competitor demographics |
| **Sandbox** | `--network none`, `--cpus 2`, `--pids-limit 64`, `--tmpfs /tmp`, RAM limits |
| **Ground Truth** | `labels.parquet` never mounted into evaluation sandbox |
| **IP Trust** | `ProxyFix` middleware — only trusts `X-Forwarded-For` from Nginx |
| **HF API Keys** | Fetched on-demand by workers via authenticated API, never in Redis |

---

## License

[GNU Affero General Public License v3.0](LICENSE)
