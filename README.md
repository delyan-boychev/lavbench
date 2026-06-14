# National AI Competition (NAI) Web Platform

A secure, sandboxed, and real-time NLP / ML competition platform. Participants submit Jupyter Notebooks or raw Python code, which are executed and evaluated inside isolated GPU/CPU container sandboxes under strict resource constraints.

---

## Table of Contents

1. [System Architecture](#system-architecture)
2. [Prerequisites](#prerequisites)
3. [Project Structure](#project-structure)
4. [Configuration & Environment](#configuration--environment)
5. [Setup & Local Debugging](#setup--local-debugging)
   - [Quick Start (All-in-one Debug Script)](#quick-start-all-in-one-debug-script)
   - [Manual Step-by-Step Setup](#manual-step-by-step-setup)
   - [Database Reset & Admin Creation](#database-reset--admin-creation)
6. [Docker Deployment](#docker-deployment)
7. [Remote GPU / CPU Worker Setup](#remote-gpu--cpu-worker-setup)
8. [Testing](#testing)
   - [Frontend Tests](#1-frontend-unit-tests-vitest--testing-library)
   - [Backend Tests](#2-backend-unit-tests-python-unittest)
   - [Pipeline Integration Testing](#3-pipeline-integration-testing)

---

## System Architecture

The NAI platform utilizes a decoupled, database-free worker node architecture:

```
Client (React)  <-->  Server (Flask API)  <-->  DB (PostgreSQL)
                    Server  <-->  Broker (Redis)
                    Broker  <-->  Worker (Remote GPU/CPU)
                    Worker  -->  Server (Score Callback)
```

- **Main Server**: Houses PostgreSQL, Flask API, React frontend, and Redis (Celery broker).
- **Worker Nodes**: Decoupled machines (`RUNNING_AS_WORKER=true`). They listen to Celery queues, download task files from the server via secure tokens, build Docker sandboxes, execute user code, and callback scores.

---

## Prerequisites

| Dependency    | Minimum Version | Purpose                     |
|---------------|-----------------|-----------------------------|
| Python        | 3.10            | Flask API + Celery worker   |
| Node.js       | 18              | React frontend (Vite)       |
| PostgreSQL    | 15              | Main database               |
| Redis         | 6+              | Celery message broker       |
| Docker        | 20+             | Containerized worker (optional for local debug) |

Recommended package managers: `npm` (Node), `pip` / `micromamba` (Python).

---

## Project Structure

```
nai-webplatform/
├── backend/
│   ├── app.py                  # Flask application factory + seed_database()
│   ├── config.py               # Configuration from .env
│   ├── models.py               # SQLAlchemy models (User, Challenge, Task, Submission)
│   ├── auth_utils.py           # JWT auth helpers
│   ├── evaluation_engine.py    # Parquet-based evaluation logic
│   ├── tasks.py                # Celery task definitions
│   ├── worker_utils.py         # Worker runtime helpers
│   ├── generate_master_key.py  # Full DB reset + seed + admin creation
│   ├── recreate_db.py          # Drop + recreate + seed (no admin)
│   ├── reset_for_fresh_start.py# Drop + recreate + admin only (no seed data)
│   ├── routes/                 # Flask blueprints (admin, challenges, tasks, auth)
│   ├── services/               # Business logic (submissions, scoring)
│   ├── task_modules/           # Submission runner, validation
│   ├── tests/                  # Backend unit tests (unittest)
│   ├── requirements.in        # Pinned dependency source
│   └── requirements.txt       # Compiled dependencies
├── frontend/
│   ├── src/
│   │   ├── components/         # Reusable React components (admin, challenge, ui)
│   │   ├── pages/              # Page-level components (AdminPanel, ChallengeView, etc.)
│   │   ├── services/           # ApiService, AuthContext, AppContext
│   │   ├── context/            # React context providers
│   │   └── hooks/              # Custom hooks
│   ├── public/locales/         # i18n translation files (en, bg)
│   └── package.json
├── docker-compose.yml          # Production compose: db, redis, backend, frontend, worker
├── deploy_debug.sh             # One-command local debug launcher
├── deploy_docker.sh            # Production deployment script
├── start_worker.sh             # Remote worker bootstrap
├── .env.example                # Environment variable template
└── AGENTS.md                   # AI assistant configuration (separate from README)
```

---

## Configuration & Environment

Copy the template and edit:

```bash
cp .env.example .env
```

### Key Environment Variables

| Variable                | Description                                      | Default / Example                                          |
|-------------------------|--------------------------------------------------|------------------------------------------------------------|
| `SECRET_KEY`            | Flask secret key for JWT / session signing        | `replace_with_a_secure_random_string`                      |
| `FIELD_ENCRYPTION_KEY`  | Fernet AES key for encrypting competitor PII      | Generated with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `DATABASE_URL`          | PostgreSQL connection string                      | `postgresql://nai_user:nai_password@localhost:5432/nai_competition` |
| `CELERY_BROKER_URL`     | Redis broker URL for Celery                        | `redis://localhost:6379/0`                                 |
| `CELERY_RESULT_BACKEND` | Redis result backend URL                          | `redis://localhost:6379/0`                                 |
| `MAIN_SERVER_URL`       | Server URL for worker callbacks                   | `http://localhost:5001`                                    |
| `WORKER_SECRET_KEY`     | Shared secret for worker ↔ server auth            | `nai-worker-default-secret-token`                          |
| `HF_CACHE_DIR`          | Hugging Face dataset/model cache directory        | `./backend/hf_cache`                                       |

### Generating `FIELD_ENCRYPTION_KEY`

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Add the output to your `.env` as:
```
FIELD_ENCRYPTION_KEY=<generated-key>
```

---

## Setup & Local Debugging

### Quick Start (All-in-one Debug Script)

```bash
chmod +x deploy_debug.sh
./deploy_debug.sh
```

This script:
1. Prepares a Python virtualenv and installs dependencies.
2. Checks for local PostgreSQL and Redis (starts them in Docker if not native).
3. Creates database schemas and seeds demo data.
4. Spawns Flask API, Celery worker, and Vite dev server.

Press `Ctrl + C` to stop all services.

### Manual Step-by-Step Setup

1. **Start Infrastructure**: Ensure PostgreSQL and Redis are running locally.

2. **Backend Setup**:
   ```bash
   cd backend
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt

   # Create tables + seed demo data
   python -c "from app import app, db, seed_database; with app.app_context(): db.create_all(); seed_database()"

   # Start Flask dev server (port 5001)
   python app.py
   ```

   **Managing Python Dependencies**:
   Edit `backend/requirements.in`, then re-compile:
   ```bash
   pip-compile backend/requirements.in --output-file backend/requirements.txt
   ```

3. **Celery Worker** (optional for local debugging):
   ```bash
   cd backend
   celery -A tasks.celery worker --loglevel=info
   ```

4. **Frontend Setup**:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

### Database Reset & Admin Creation

**Option A — Fresh start, no demo data (recommended for production setup):**

```bash
cd backend
source venv/bin/activate
python reset_for_fresh_start.py
```

This drops all tables, recreates the schema, and creates a single admin user with randomly generated credentials. Credentials are printed to the terminal and saved in `admin_credentials.txt`. No challenges, tasks, or competitor users are created.

**Option B — Full reset with demo data + admin:**

```bash
cd backend
source venv/bin/activate
python generate_master_key.py
```

This drops the database, seeds demo challenges (IMDb, SST-2) with tasks and sample submissions, and creates a master admin user. Useful for development and testing.

**Option C — Recreate schema without admin user:**

```bash
cd backend
source venv/bin/activate
python recreate_db.py
```

Drops and recreates all tables, seeds demo data, but does not create an admin user. Useful for testing DB migrations without admin side-effects.

---

## Docker Deployment (Production Compose)

```bash
chmod +x deploy_docker.sh
./deploy_docker.sh
```

This script:
- Tears down any existing containers (`docker-compose down`)
- Rebuilds images (`docker-compose build`)
- Starts PostgreSQL and waits for readiness (`pg_isready`)
- Launches Flask API, React/Nginx frontend, and Celery worker
- Seeds the database inside the container

**Useful Commands**:
- `docker-compose logs -f` — tail all container logs
- `docker-compose down` — stop all services

---

## Remote GPU / CPU Worker Setup

Worker nodes do **not** require direct database access.

### Prerequisites
- Docker installed and running.
- For GPU: NVIDIA Container Toolkit.
- Network access to the shared Redis broker port (6379).

### Worker Initialization

```bash
chmod +x start_worker.sh
./start_worker.sh <REDIS_URL> [GPU_ID]
```

**Examples**:
- **GPU Worker 0**: `./start_worker.sh redis://:password@server:6379/0 0`
- **CPU Worker**: `./start_worker.sh redis://:password@server:6379/0`

The script detects `micromamba` or falls back to a local `venv`, configures GPU visibility, and connects to the Celery queue.

---

## Testing

### 1. Frontend Unit Tests (Vitest + React Testing Library)

**Run the full suite**:
```bash
cd frontend
npm run test
```

**Test framework**: `vitest` with `happy-dom` environment.

**Testing libraries**: `@testing-library/react`, `@testing-library/jest-dom`, `@testing-library/user-event`.

#### Test Structure

Tests follow the naming convention `*.test.jsx` and are co-located with the components they test or placed in the same directory.

Example layout:
```
src/
├── components/
│   ├── admin/
│   │   ├── TaskForm.jsx
│   │   └── TaskForm.test.jsx       # co-located
│   └── ui/
│       ├── InputField.jsx
│       └── InputField.test.jsx
└── pages/
    ├── AdminPanel.jsx
    ├── AdminPanel.test.jsx          # page-level test
    ├── AdminPanelStages.test.jsx
    └── AdminPanelUnifiedParquet.test.jsx
```

#### Mocking Patterns

The test suite uses `vi.mock()` for three main categories:

**1. Auth & App Context** — every test file mocks these:
```javascript
vi.mock('../AuthContext', () => ({ useAuth: vi.fn() }));
vi.mock('../context/AppContext', () => ({ useApp: vi.fn() }));
```
`useAuth` returns `{ currentUser, token }`; `useApp` returns `{ challenges, selectedChallenge, showToast, ... }`.

**2. API Service** — the shared `ApiService` module is mocked per-suite:
```javascript
vi.mock('../services/ApiService', () => ({
  default: { fetch: vi.fn(), get: vi.fn(), post: vi.fn(), ... },
}));
import api from '../services/ApiService';
api.fetch.mockResolvedValue({ ok: true, json: async () => ({...}) });
```

**3. Global `fetch`** — some tests mock `global.fetch` directly (used by `api.fetch` internally):
```javascript
global.fetch = vi.fn().mockImplementation((url) => {
  if (url.includes('/metrics')) return Promise.resolve({ ok: true, json: async () => ({...}) });
  return Promise.resolve({ ok: true, json: async () => mockSystemStats });
});
```

#### Common Test Patterns

- **Async state updates**: Use `await act(async () => { fireEvent.click(button); })` or `await vi.waitFor(() => expect(...))`.
- **Finding elements**: Prefer `getByRole`, `getByText`, `getByPlaceholderText`. Use `getAllBy*` when text appears multiple times.
- **Combobox / Select**: Use `screen.getAllByRole('combobox')` and filter by option text or value, since parameter selects lack accessible names.
- **API calls**: Use `api.fetch.mock.calls` to verify request URLs and headers.

#### Running a Single Test File

```bash
npx vitest run src/pages/AdminPanel.test.jsx
npx vitest run src/pages/AdminPanel.test.jsx -t "switches to Workers"
```

### 2. Backend Unit Tests (Python unittest)

**Run the full suite**:
```bash
cd backend
source venv/bin/activate
python -m unittest discover -s tests
```

**Test files** (in `backend/tests/`):

| File | Tests |
|------|-------|
| `test_routes.py` | API endpoint happy-paths, rate limiting, auth (401/403), calendar deadlines |
| `test_exceptions.py` | Error handlers, payload validation |
| `test_services.py` | Service-layer logic, submission processing |
| `test_custom_eval_validation.py` | Custom eval code validation, AST sandbox rules |
| `test_unified_parquet_evaluation.py` | Parquet-based evaluation engine |

The suite uses Python's `unittest.TestCase` and can be run with verbose output:
```bash
python -m unittest discover -s tests -v
```

### 3. Pipeline Integration Testing

The `test_run.py` script tests the full pipeline (DB updates, SSE, Celery, Docker sandbox) without requiring a real Docker daemon:

```bash
python test_run.py
```

It prepends `mock_bin/` to `PATH`, activating a Docker CLI shim that simulates container builds and execution, verifying resource limits (RAM, processes, network isolation) are enforced correctly.
