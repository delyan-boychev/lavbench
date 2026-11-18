# LavBench Backend Service

The backend component of LavBench is a robust Flask, Celery, and PostgreSQL application that manages ML competitions, user authentication, AST security validation, custom evaluators, worker nodes, and live telemetry streaming via Server-Sent Events (SSE).

---

## 1. Prerequisites & Environment Setup

Recommended Python environment manager: **Micromamba** or **Conda** (Python 3.12).

```bash
# 1. Create and activate environment
micromamba create -n lavbench_backend python=3.12
micromamba activate lavbench_backend

# 2. Install production and development dependencies
pip install -r requirements.txt -r dev-requirements.txt

# 3. Create environment file from template
cp ../.env.example ../.env
```

---

## 2. Quick Start & Initial Setup

### Initialize Admin Account

After starting the database, apply schema migrations from the `backend/` directory before
starting the API, workers, or admin setup:

```bash
python scripts/migrate.py
```

The runner upgrades the database to the latest revision (`alembic upgrade head`). Then run the
admin setup script to generate master credentials:

```bash
python scripts/setup-admin.py
```

This creates the initial administrator account, prints its credentials, and writes them to
`/app/admin_credentials.txt` (mode 600). In Docker that path is inside the backend container, and
`make setup-admin` copies the file to `./admin_credentials.txt` in the repository root. Outside
Docker, where `/app` usually does not exist, the credentials are only printed, so copy them then.

### Running Backend Services

```bash
# Option A: Run everything locally in debug mode (Flask + Celery + Frontend)
make dev

# Option B: Run Flask API server standalone (Port 5001)
python app.py

# Option C: Run Celery worker standalone
celery -A tasks.celery worker --loglevel=info

# Option D: Run Celery Beat periodic scheduler standalone
celery -A tasks.celery beat --loglevel=info
```

### Local stack with nanoColab

`make dev-nanocolab` runs `scripts/dev-nanocolab.sh`. It starts nanoColab's local kind stack (`deploy/local/up.sh`, then `api.sh`) from a checkout at `../nano-colab` (or `NANOCOLAB_ROOT`), then LavBench: Postgres on 127.0.0.1:5433 (`LB_PG_PORT`), Redis on 127.0.0.1:6381 (`LB_REDIS_PORT`), Flask on 127.0.0.1:5001, Vite on http://localhost:5173, a Celery internal worker, beat, and one CPU evaluation worker in Docker. Everything it writes lives in `.local-nanocolab/`, including the nanoColab API key file and the admin login it prints.

| Requirement | Version |
| :--- | :--- |
| Python (micromamba env `lavbench_backend`) | 3.12 |
| Node | 26 |
| kind, kubectl, helm | kind v0.33.0, kubectl v1.37.2, helm v3.22.1 (Helm 3, not 4) |
| Machine | 8 cores, 16 GB RAM, 15 GB free disk; one workspace takes half of the kind worker node, so test one student at a time |

Open LavBench at `http://localhost:5173`, not `127.0.0.1`: the Hub accepts launches only from that origin. `make e2e-nanocolab` runs the admin, student and jury paths against the stack. `make dev-nanocolab-down` stops it and keeps the data; `make dev-nanocolab-down PURGE=1` also deletes LavBench's local data and nanoColab's cluster.

---

## 3. Directory Structure

```text
backend/
├── app.py                      # Flask factory, blueprint registration, error handlers
├── alembic.ini                 # Alembic configuration (commands run from backend/)
├── config/                     # Config class (__init__), logging setup (log_config), pytest fixtures (conftest)
├── migrations/                 # Alembic environment and reviewed schema revisions
├── models/                     # SQLAlchemy models (User, Challenge, Stage, Task, Submission, AuditLog)
├── routes/                     # Flask blueprints (admin, auth, challenges, tasks, submissions, leaderboard, etc.)
├── schemas/                    # Pydantic v2 validation schemas & spectree before-handlers
│   ├── common.py               # Shared validators (_parse_datetime_strict, PaginationParams)
│   ├── exceptions.py           # SchemaError(code, message) base exception class
│   └── responses/              # Pydantic response schemas (10 domain modules)
├── scripts/                    # Migration, maintenance & CI scripts (migrate.py, setup-admin.py, checks)
├── services/                   # Core business logic (challenge_service, submission_service, evaluation/, etc.)
│   └── evaluation/             # Parquet evaluation engine (metrics, validation, engine — 44 metrics, custom evaluators)
├── tasks/                      # Celery app (__init__.py) + task_modules/ (runner, image builder, system, templates)
├── tests/                      # pytest test suite (1368 tests)
└── utils/                      # Helpers — migrations, error_utils, worker_utils, auth_utils, wsgi, spec, ...
```

---

## 4. Architecture & Key Systems

### A. Pydantic v2 Schema Validation (spectree 2.0.1)
Routes use spectree `@api.validate` decorators for automatic request parsing and response validation:

```python
from utils.spec import api
from schemas.challenge import CreateChallengeSchema
from schemas.responses.challenge import ChallengeResponse

@challenges_bp.route("", methods=["POST"])
@role_required(["admin"])
@api.validate(json=CreateChallengeSchema, resp=Response(HTTP_201=ChallengeResponse))
def create_challenge(json: CreateChallengeSchema):
    ...
```

- Request JSON is parsed directly into `json` as a Pydantic model.
- Validation failures trigger `_format_validation_error_for_response`, returning `HTTP 422` with machine-readable `code` (e.g. `ERR_INVALID_DOCKER_IMAGE`).
- Custom schema validators raise `SchemaError("ERR_CODE", "Message")`.

### B. Standardized Error Handling
All API route errors **must** use the `err()` helper function from `utils/error_utils.py`:

```python
from utils.error_utils import err
return err("ERR_INVALID_CREDENTIALS", 401)
```

This returns `{"error": "<message>", "code": "<ERR_*>"}` without a legacy `key` field, enabling frontend i18n translation mapping.

### C. Worker Sandbox Execution & Custom Evaluators
- Competitor code is executed inside hardened Docker containers (`--network none`, `--cap-drop ALL`, `--user 65534`, `--read-only`, `--tmpfs /tmp:noexec,nosuid,size=128m`).
- Custom evaluators (`evaluator.py`) are parsed via AST on upload (`services/evaluator_script.py`) and run on the worker as a limited subprocess (`services/evaluation/custom_evaluator.py`): the worker's own Python, a temporary folder with only the predictions, labels and options, no secrets in its environment, `CUSTOM_EVALUATOR_MEMORY_MB` and `CUSTOM_EVALUATOR_TIME_LIMIT_SECONDS` limits, and the whole process group killed at the time limit.

---

## 5. Testing, Linting & Quality Assurance

Before pushing code, run all backend CI quality checks:

```bash
# 1. Check error codes and translation parity
python scripts/check_error_codes.py

# 2. Run Ruff linter and formatter check
ruff check .
ruff format --check .

# 3. Strict Mypy type checking
mypy . --no-incremental

# 4. Run pytest test suite in parallel
pytest tests -n auto -q
```

---

## 6. Docker Build

```bash
# Build backend application container
docker build -t lavbench-backend -f Dockerfile .

# Build lightweight worker container
docker build -t lavbench-worker -f Dockerfile.worker .
```
