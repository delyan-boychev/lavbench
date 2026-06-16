# LavBench

<div align="center">
  <img src="frontend/public/favicon.svg" alt="LavBench Logo" width="96" height="96" />
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
- **i18n** — English and Bulgarian *(contributions for additional languages are welcome)*
- **Security** — httpOnly cookie auth, token revocation with Redis blacklist, rate limiting, encrypted PII, ProxyFix for trusted reverse proxies
- **Typed API** — OpenAPI 3.0 spec with auto-generated TypeScript type declarations and JSDoc `@type` annotations on all frontend API calls
- **Type Checking** — `tsc --noEmit` verifies all JSDoc annotations + component props, 0 errors in CI

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
micromamba run -n nai_backend python -m pytest tests/ -v
```

120 tests covering routes, auth, evaluation, caching, rate limiting, and models.

### Frontend

```bash
cd frontend

# Unit / component tests
npm run test       # vitest — 149 tests

# Type checking (JSDoc annotations + component props)
npm run check-types

# Translation integrity (missing keys, symmetry, orphaned keys)
python3 scripts/check_translations.py

# Regenerate API types after backend spec changes
python3 scripts/_annotate_types.py
```

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

---

## Documentation

| Guide | Audience |
|-------|----------|
| [Student Guide](guides/en/student_guide.md) | Competitors — logging in, understanding tasks, submitting notebooks, leaderboard |
| [Jury Guide](guides/en/jury_guide.md) | Jury members — monitoring, manual scoring, competitor registration, exports |
| [Admin Guide](guides/en/admin_guide.md) | Administrators — challenge/task management, backups, worker health, user admin |
| [API Reference](http://localhost:5001/apidocs) | Developers — interactive Swagger UI with all 65 endpoints |
| [Translation Check](frontend/scripts/check_translations.py) | Developers — validates i18n keys across en/bg, finds missing/orphaned keys |

---

## Contributing

### Pull Request Checklist

1. **Run all tests**: `npm run test` (frontend) + `python -m pytest tests/` (backend)
2. **Keep types clean**: `npm run check-types` must pass (0 errors)
3. **Check translations**: `python3 scripts/check_translations.py` must show 0 missing keys
4. **Regenerate API types** if you changed backend endpoints:
   ```bash
   # Start the backend on port 5001, then:
   npm run generate-api-types
   python3 scripts/_annotate_types.py
   ```
5. **Follow existing patterns** — use `@type` JSDoc annotations for API responses, keep component props with defaults, use `tsc --noEmit` for validation

### Type System

The frontend uses **JSDoc `@type` annotations** (not full TypeScript) referencing a generated `types/api.d.ts` file:

```
Backend flasgger docstrings
       │
       ▼
  openapi-typescript
       │
       ▼
  frontend/src/types/api.d.ts    (auto-generated)
       │
       ▼
  scripts/_annotate_types.py     (injects @type annotations)
       │
       ▼
  tsc --noEmit                   (validates all types)
```

**Key conventions**:
- API response types use `paths['/api/endpoint']['method']['responses']['200']['content']['application/json']`
- Component props use default values (`prop = 'default'`) to keep them optional
- Service wrappers use `(...args: any[]) => Promise<{ok, data: Type}>`
- Translations use dot-notation keys (`section.subsection.key`) matching the JSON structure
- Never use `@ts-ignore` or `@type {any}` — use specific type assertions or narrow types with `typeof` guards

### Project Structure

New code should follow the existing directory layout:
- **Backend routes**: `backend/routes/<feature>.py` with flasgger docstrings
- **Frontend components**: `frontend/src/components/<domain>/<Component>.jsx`
- **Frontend pages**: `frontend/src/pages/<Page>.jsx`
- **Services**: `frontend/src/services/<Service>.js`
- **Translations**: `frontend/public/locales/{en,bg}/translation.json`
