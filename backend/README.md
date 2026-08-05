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

After starting your database and Redis instances, run the admin setup script to generate master credentials:

```bash
python setup-admin.py
```

This creates the initial administrator account and writes credentials to `admin_credentials.txt` in the repository root.

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

---

## 3. Directory Structure

```text
backend/
├── app.py                      # Flask factory, blueprint registration, error handlers
├── cache_utils.py              # Redis connection pool, caching helpers, atomic locks
├── config.py                   # Config class reading environment variables
├── conftest.py                 # Pytest fixtures (client, auth tokens, models)
├── error_utils.py              # err() helper & DEFAULT_ERROR_MESSAGES dictionary
├── evaluation_engine.py        # Parquet evaluation engine (44 metrics across 12 categories + custom evaluators)
├── log_config.py               # Centralized logging setup (file rotation, worker prefixes)
├── setup-admin.py              # Script to generate administrator account
├── spec.py                     # Spectree OpenAPI spec instance & Swagger config
├── sse_utils.py                # Server-Sent Events streaming pub/sub helpers
├── version.py                  # Backend version string
├── worker_utils.py             # Docker container sandbox runtime & status reporting
├── wsgi.py                     # WSGI entrypoint (gunicorn)
├── models/                     # SQLAlchemy models (User, Challenge, Stage, Task, Submission, AuditLog)
├── routes/                     # Flask blueprints (admin, auth, challenges, tasks, submissions, leaderboard, etc.)
├── schemas/                    # Pydantic v2 validation schemas & spectree before-handlers
│   ├── common.py               # Shared validators (_parse_datetime_strict, PaginationParams)
│   ├── exceptions.py           # SchemaError(code, message) base exception class
│   └── responses/              # Pydantic response schemas (10 domain modules)
├── scripts/                    # Maintenance & CI scripts (check_error_codes.py)
├── services/                   # Core business logic (challenge_service, submission_service, etc.)
├── tasks/                      # Celery app (__init__.py) + task_modules/ (runner, image builder, system, templates)
├── tests/                      # pytest test suite (1282 tests)
└── utils/                      # Helpers — dates, files, sse, access, auth_utils (JWT, cookies, rate limiting)
```

---

## 4. Architecture & Key Systems

### A. Pydantic v2 Schema Validation (spectree 2.0.1)
Routes use spectree `@api.validate` decorators for automatic request parsing and response validation:

```python
from spec import api
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
All API route errors **must** use the `err()` helper function from `error_utils.py`:

```python
from error_utils import err
return err("ERR_INVALID_CREDENTIALS", 401)
```

This returns `{"error": "<message>", "code": "<ERR_*>"}` without a legacy `key` field, enabling frontend i18n translation mapping.

### C. Worker Sandbox Execution & Custom Evaluators
- Competitor code is executed inside hardened Docker containers (`--network none`, `--cap-drop ALL`, `--user 65534`, `--read-only`, `--tmpfs /tmp:noexec,nosuid,size=128m`).
- Custom evaluators (`evaluator.py`) are parsed via AST on upload (`routes/tasks.py`) and executed inside their own hardened container (`--network none --cap-drop ALL --user 65534 --read-only --pids-limit 64`, 300s cap) against ground-truth `labels.parquet` — never via `exec()` on the worker host. If the sandbox cannot start (image missing, no Docker), evaluation fails closed.

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
