# AGENTS.md — LavBench

Comprehensive reference for AI agents working on the LavBench sandboxed ML competition platform.

---

## Agent Workflow Rules

### Subagent Delegation

When a task involves 3+ distinct conceptual steps or requires searching multiple files, **delegate to a subagent** rather than doing everything inline:

| Task type | When to delegate | Subagent type |
|---|---|---|
| Bulk file edits (5+ files) | Always | `general` |
| Searching for patterns across the codebase | Always | `explore` |
| Reading multiple files for context | >3 files | `explore` |
| Running test suites or lint checks | Always (in parallel) | — (use `bash` directly) |
| Multi-step refactoring | Any refactoring touching >2 files | `general` |

**Rules:**
1. Launch subagents in parallel whenever work is independent
2. Give subagents a clear return contract — tell them exactly what info to return
3. Never duplicate work yourself after delegating to a subagent
4. Verify subagent results by running tests/lint after merging their changes
5. For `explore` subagents, specify depth: `"quick"`, `"medium"`, or `"very thorough"`
6. Do NOT delegate when the task is a single read, edit, or grep — do it directly

---

## Repository Overview

LavBench is a secure, sandboxed machine learning competition platform. Competitors submit Jupyter notebooks or Python code, executed in hardened Docker containers with strict resource constraints. Real-time leaderboards stream via SSE with double-blind review for anonymous jury scoring.

- **Stack:** Flask (Python 3.12), Celery + Redis, PostgreSQL, React (JavaScript/JSX), Docker
- **License:** AGPL v3
- **CI:** GitHub Actions — tests, lint, format, types, translations, Docker build

---

## Project Structure

```
lavbench/
├── AGENTS.md                          ← This file
├── Makefile                           # Top-level targets (setup, dev, lint, docs)
├── docker-compose.yml                 # Full stack (db, redis, backend, beat, frontend)
├── scripts/                           # Deployment & setup scripts
│   ├── setup.sh                       # Server prerequisites + micromamba + npm
│   ├── setup-worker.sh                # Worker interactive setup
│   ├── generate-keys.sh               # Interactive key generator
│   ├── deploy-server.sh / deploy-docker.sh
│   ├── deploy-worker.sh               # Worker build + deploy
│   └── deploy-debug.sh                # Local dev mode (micromamba + Flask + Celery)
│
├── backend/
│   ├── app.py                         # Flask application factory
│   ├── config.py                      # Config class reads ALL env vars
│   ├── version.py                     # Reads version from pyproject.toml
│   ├── pyproject.toml                 # Ruff config, pytest config, coverage
│   ├── error_utils.py                 # err() helper + DEFAULT_ERROR_MESSAGES
│   ├── auth_utils.py                  # JWT auth, rate limiting, token revocation
│   ├── cache_utils.py                 # Redis caching, locks
│   ├── evaluation_engine.py           # Parquet-based evaluation (70+ metrics)
│   ├── sse_utils.py                   # Server-Sent Events pub/sub
│   ├── worker_utils.py                # Docker sandbox management
│   ├── tasks.py                       # Celery task definitions + beat schedule
│   ├── models/                        # SQLAlchemy models
│   │   ├── __init__.py
│   │   ├── challenge.py, task.py, submission.py, user.py, stage.py
│   │   └── ...
│   ├── schemas/                       # Pydantic v2 validation schemas
│   │   ├── __init__.py                # validate_json / validate_form decorators
│   │   ├── exceptions.py              # SchemaError exception class
│   │   ├── admin.py, auth.py, challenge.py
│   │   ├── task.py, submission.py, leaderboard.py
│   │   └── common.py
│   ├── routes/                        # Flask blueprints
│   │   ├── admin.py, auth.py, challenges.py
│   │   ├── tasks.py, submissions.py, leaderboard.py
│   │   └── ...
│   ├── services/                      # Business logic
│   ├── utils/                         # Utility modules
│   ├── task_modules/                  # Submission runner, templates
│   ├── scripts/
│   │   └── check_error_codes.py       # Lint: err() usage + translation parity
│   ├── tests/                         # 982 tests (pytest)
│   │   ├── conftest.py                # Fixtures: client, auth, models
│   │   ├── test_admin_routes_pytest.py
│   │   ├── test_auth_routes_pytest.py
│   │   ├── test_challenges_routes_pytest.py
│   │   ├── test_task_crud.py
│   │   ├── test_submission_routes_pytest.py
│   │   ├── test_leaderboard_routes_pytest.py
│   │   ├── test_exceptions_pytest.py
│   │   ├── test_remaining_routes.py
│   │   └── test_routes_pytest.py
│   └── Dockerfile / Dockerfile.worker
│
├── frontend/
│   ├── src/
│   │   ├── components/                # Reusable components
│   │   ├── pages/                     # Page components
│   │   ├── services/                  # ApiService, AuthContext
│   │   ├── context/                   # React contexts
│   │   ├── hooks/                     # Custom hooks
│   │   └── types/api.d.ts             # Auto-generated TS types from OpenAPI
│   ├── scripts/
│   │   └── check_translations.py      # i18n key checker
│   ├── public/locales/                # i18n translation files
│   │   ├── en/translation.json        # English (935 keys)
│   │   └── bg/translation.json        # Bulgarian (935 keys)
│   └── nginx.conf                     # Nginx config for reverse proxy
│
├── guides/                            # User documentation
├── docs/                              # Sphinx documentation
├── .github/workflows/ci.yml           # CI pipeline
└── CONTRIBUTING.md                    # PR checklist & conventions
```

---

## Setup & Environment

### Prerequisites

- **micromamba** (conda-forge package manager) — installs Python 3.12 and all deps
- **Docker** (for sandbox execution and full-stack deployment)
- **Node.js 26** (for frontend)

### Setup Commands

```bash
# One-command server setup
make setup-server

# Or manually:
micromamba create -n lavbench_backend python=3.12
micromamba run -n lavbench_backend pip install -r backend/requirements.txt -r backend/dev-requirements.txt
cd frontend && npm ci
```

### Quick Start

```bash
# Full local dev mode
make dev

# Or separate terminals:
micromamba run -n lavbench_backend python backend/app.py          # Flask on :5001
cd frontend && npm run dev                                         # React on :5173
```

### Environment Variables

Copy `.env.example` → `.env`. Key variables:

| Variable | Purpose | Default |
|---|---|---|
| `SECRET_KEY` | Flask/JWT signing key | **Required** |
| `ENCRYPTION_KEY` | Fernet key for PII | **Required** |
| `DATABASE_URL` | PostgreSQL connection | **Required** |
| `CELERY_BROKER_URL` | Redis broker | `redis://localhost:6379/0` |
| `REDIS_URL` | Redis client connection | `redis://localhost:6379/0` |

---

## CI Pipeline (`.github/workflows/ci.yml`)

| Job | Command | What it checks |
|---|---|---|
| `backend-tests` | `pytest -n auto --timeout=120 --cov` | 982 tests, ≥70% coverage |
| `backend-lint` | `ruff check`, `ruff format --check`, `check_error_codes.py` | Ruff rules, formatting, error code parity |
| `frontend-lint` | `npm run lint` | ESLint |
| `frontend-format` | `npm run format:check` | Prettier formatting |
| `frontend-tests` | `npm run test:coverage` | Vitest unit tests |
| `translations-check` | `json.tool` + `check_translations.py` | JSON validity + key parity + missing/orphaned keys |
| `frontend-types` | `npm run check-types` | `tsc --noEmit` on JSDoc types |
| `docker-build` | `docker build` + `docker compose up` | Full stack smoke test |

### Running CI Checks Locally

```bash
# Backend
cd backend
ruff check .
ruff format --check .
python scripts/check_error_codes.py
micromamba run -n lavbench_backend pytest tests -n auto -q

# Frontend
cd frontend
npm run lint
npm run format:check
npm run test
npm run check-types
python scripts/check_translations.py
```

---

## Backend Architecture

### Flask Application (`app.py`)

- Factory function `create_app()` with config class loaded from env vars
- Blueprints registered in `app.py`
- Error handlers for 400/403/404/405/422/429/500
- Swagger/OpenAPI via Flasgger (auto-generated from docstrings)
- `ProxyFix` middleware for trusted reverse proxy headers
- `CORS` configured from `CORS_ORIGINS` env var

### Database (SQLAlchemy + PostgreSQL)

- Models in `backend/models/` package
- Migrations handled by Flask-Migrate/Alembic (`backend/migrations/`)
- Tests use `sqlite:///:memory:`
- PII (competitor demographics) encrypted at rest with Fernet

### Pydantic v2 Validation (`backend/schemas/`)

**Two decorators:**

```python
from schemas import validate_json, validate_form

@validate_json(SomeSchema)       # JSON request body → validated model → kwargs["data"]
@validate_form(SomeFormSchema)   # multipart/form-data → validated model → kwargs["form_data"]
```

**Key behavior:**
- Decorator returns `422` + `ERR_VALIDATION` with field-level error details if validation fails
- The validated Pydantic **model object** (not `model_dump()` dict) is injected as `data` or `form_data`
- Route handlers access fields via `data.field_name` (attribute access, not dict)
- PATCH routes use `data.model_fields_set` to check which fields were explicitly provided

**Schema structure:**

| Schema | Used By | Fields |
|---|---|---|
| `LoginSchema` | `auth.py` POST /login | username, password |
| `RegisterCompetitorSchema` | `admin.py` POST /register-competitor | name, surname, middle_name, birth_date, grade, school, city, challenge_id, email |
| `CreateUserSchema` | `admin.py` POST /register-user | username, email, password, name, surname, middle_name, birth_date, grade, school, city, role, challenge_id, is_anonymous, jury_challenges |
| `UpdateUserSchema` | `admin.py` PUT /users/{id} | All fields optional (None on omitted) |
| `CreateChallengeSchema` | `challenges.py` POST /challenges | title, description, gpu_required=True, double_blind=True, start_time, end_time, timezone="UTC", is_frozen=False, limits, test_stage_* |
| `UpdateChallengeSchema` | `challenges.py` PUT /challenges/{id} | All fields optional |
| `CreateTaskMetaSchema` | `tasks.py` POST /tasks (form) | title, description, ram*, time*, gpu, docker, hf*, metrics, stage_id, +validators for bool/int coercion from form strings |
| `UpdateTaskMetaSchema` | `tasks.py` PUT /tasks/{id} (form) | All fields optional + deleted_files, delete_evaluator, delete_baseline |
| `SubmitCodeSchema` | `submissions.py` POST /submit | task_id, selected_cells: list[dict] |
| `ManualPointsSchema` | `leaderboard.py` POST /manual-points | user_id, points: dict, reason |

**Default values for CREATE routes (Pydantic provides them when client omits):**
- `gpu_required: bool = True` — GPU enabled by default
- `double_blind: bool = True` — double-blind by default
- `timezone: str = "UTC"` — UTC timezone
- `is_frozen: bool = False` — not frozen
- `ban_magic_commands: bool = False` — magic commands allowed
- `public_eval_percentage: int | None = None` (default 30 via form coercion)

### Error Handling (`error_utils.py`)

```python
from error_utils import err

return err("ERR_SOME_CODE", 400)                         # Uses default message
return err("ERR_SOME_CODE", 403, message="Custom msg")   # Custom override
```

- All error codes defined in `DEFAULT_ERROR_MESSAGES` dict (83 codes)
- Every `err()` call must reference a code in that dict
- Every code in the dict must be referenced by at least one `err()` call (enforced by `check_error_codes.py`)
- Every code must have an `api.ERR_*` translation key in both `en` and `bg` translation files (also enforced by `check_error_codes.py`)
- Frontend displays the `error` message string, not the code

**Dead codes removed from `error_utils.py`** (caught by Pydantic, never raised anymore):
`ERR_MISSING_CREDENTIALS`, `ERR_MISSING_SELECTED_CELLS`, `ERR_MISSING_TASK_ID`, `ERR_VALID_ROLE_REQUIRED`, `ERR_TITLE_REQUIRED`, `ERR_MISSING_FIELDS`, `ERR_POINTS_MUST_BE_INT`, `ERR_INVALID_LIMITS`

### Route Patterns

**CREATE route pattern:**
```python
@challenges_bp.route("", methods=["POST"])
@role_required(["admin", "jury"])
@validate_json(CreateChallengeSchema)
def create_challenge(data):
    title, description = data.title, data.description
    # ... business logic ...
    challenge = Challenge(title=title, ...)
    db.session.add(challenge)
    db.session.commit()
    return jsonify(challenge.to_dict()), 201
```

**PATCH route pattern:**
```python
@challenges_bp.route("/<uuid:challenge_id>", methods=["PUT"])
@validate_json(UpdateChallengeSchema)
def update_challenge(challenge_id, data):
    challenge = db.get_or_404(Challenge, challenge_id)
    fields = data.model_fields_set
    if "title" in fields:
        challenge.title = data.title
    if "max_eval_requests" in fields and data.max_eval_requests is not None:
        challenge.max_eval_requests = data.max_eval_requests
    # ...
    db.session.commit()
    return jsonify(challenge.to_dict())
```

---

## Security Model

| Layer | Mechanism |
|---|---|
| **Authentication** | httpOnly cookies with JWTs, 24h expiry |
| **Authorization** | Role-based (admin, jury, competitor) via `@role_required` decorator |
| **CSRF** | CSRF token in non-GET requests (JWT csrf token) |
| **Token Revocation** | Redis blacklist using `jti`, instant invalidation on logout |
| **Rate Limiting** | Lua atomic counters per-user and per-endpoint; fails open with warning log |
| **PII Encryption** | Fernet symmetric encryption on competitor demographics at rest |
| **Sandbox** | `--network none`, `--cap-drop ALL`, `--read-only`, `--security-opt no-new-privileges`, CPU/RAM/PIDs limits, `tmpfs /tmp`, no swap |
| **Ground Truth** | `labels.parquet` evaluated server-side, never in sandbox |
| **IP Trust** | `ProxyFix` trusts only Nginx `X-Forwarded-For` |
| **HF API Keys** | Fetched on-demand by workers via authenticated API routes, never stored in Redis |

### Auth Decorators

```python
@login_required                            # Requires valid JWT cookie
@role_required(["admin", "jury"])          # Requires specific role(s)
@jury_access_required                      # Jury/admin access check
@rate_limit(max_requests=10, window_seconds=60)  # Per-endpoint rate limiting
@validate_json(Schema) / @validate_form(Schema)  # Pydantic validation
```

---

## Testing

### Backend (982 tests)

```bash
cd backend

# Run all tests in parallel
micromamba run -n lavbench_backend pytest tests -n auto -q

# Single file
micromamba run -n lavbench_backend pytest tests/test_auth_routes_pytest.py -v

# Single test
micromamba run -n lavbench_backend pytest tests/test_exceptions_pytest.py::TestBackendExceptionAndErrorCases::test_submit_code_missing_cells_and_rate_limits -x --tb=long
```

**Key test fixtures** (from `conftest.py`):
- `client` — Flask test client
- `app` — Flask app instance
- `db_session` — SQLAlchemy session (rolled back after each test)
- `admin_token`, `jury_token`, `competitor_token` — pre-authenticated tokens
- Pre-created models: `challenge_a`, `task_a`, `stage_a`

**Test conventions:**
- One test file per route module (`test_X_routes_pytest.py`)
- Tests assert status code + error code (`resp.status_code == 422`, `resp.get_json()["code"] == "ERR_VALIDATION"`)
- `selected_cells` in submission tests must be `list[dict]`, not `list[str]` (e.g., `[{"source": "print(1)"}]`)

### Frontend (vitest)

```bash
cd frontend
npm run test        # Unit tests
npm run test:coverage  # With coverage
npm run check-types # tsc --noEmit for JSDoc types
```

---

## Linting & Formatting

### Backend (Ruff)

```bash
cd backend

# Check
ruff check .
ruff format --check .

# Auto-fix
ruff check --fix .
ruff format .
```

Ruff config in `pyproject.toml`:
- line-length: 100
- Rules: E, F, I, N, W, UP, B, SIM, S, A, T, C4, RUF, PERF, LOG
- Per-file-ignores: tests get S101, T201, PERF; admin.py gets RUF001 (Cyrillic transliteration is intentional)

### Frontend (Prettier + ESLint)

```bash
cd frontend
npm run format       # Prettier write
npm run format:check # Prettier check
npm run lint         # ESLint
```

### Error Code Linter

```bash
python backend/scripts/check_error_codes.py
```

Checks:
1. No `jsonify({"error": ...})` — must use `err()` helper
2. `err()` first argument must be a string-literal `ERR_[A-Z0-9_]+`
3. Code must exist in `DEFAULT_ERROR_MESSAGES`
4. Every code in `DEFAULT_ERROR_MESSAGES` must be used by at least one `err()` call
5. Every code must have `api.ERR_*` translation in both en/bg locale files
6. No orphaned `api.ERR_*` keys in translation files

### Translation Checker

```bash
cd frontend
python scripts/check_translations.py
```

Checks:
1. Symmetry — same keys in en and bg
2. Missing — keys used in source code but absent from translations (Error, exit 1)
3. Orphaned — keys in translations but never referenced in source code (Warning)

---

## Translation System (i18n)

- Files: `frontend/public/locales/{en,bg}/translation.json`
- 935 keys per locale, perfectly in sync
- Keys use dot-notation: `section.subsection.key`
- Backend error codes live under `api.ERR_*`
- Frontend uses `react-i18next` via `useTranslation()` hook: `t('key')` or `t('key', 'fallback')`
- Dynamic keys: `t('admin.actions.' + action)`, `t('api.' + errorCode)`, `t('badge.' + role)`
- Both locales must always have matching key sets (enforced by CI)
- Pre-existing: 147 orphaned keys (translation entries not referenced in source — safe to keep for future use)

### Adding a New Translation Key

1. Add the key + value to both `en/translation.json` and `bg/translation.json`
2. If it's an `ERR_*` code, also add to `DEFAULT_ERROR_MESSAGES` in `backend/error_utils.py`
3. Run `python backend/scripts/check_error_codes.py` and `python frontend/scripts/check_translations.py`

---

## Common Tasks

### Add a New Route

1. Create schema in `backend/schemas/` (if validation needed)
2. Add route to appropriate file in `backend/routes/`
3. Register blueprint in `backend/app.py` (if new file)
4. Add `err()` code to `DEFAULT_ERROR_MESSAGES` in `error_utils.py`
5. Add `api.ERR_*` translation keys to both en/bg locale files
6. Write tests in `backend/tests/`
7. Update API types: `cd frontend && npm run generate-api-types`

### Add a New Test

```python
def test_something(client, db_session, admin_token, challenge_a):
    res = client.post(
        "/api/admin/some-endpoint",
        json={"field": "value"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    assert res.get_json()["field"] == "expected"
```

### Debugging

- **Flask debug mode:** set `FLASK_DEBUG=true` in `.env`
- **See SQL queries:** add `echo=True` to `SQLALCHEMY_ENGINE_OPTIONS` in config
- **Run a single test:** `pytest tests/test_file.py::TestClass::test_method -x --tb=long`
- **Check error codes:** `python backend/scripts/check_error_codes.py`
- **Docker not running:** tests work with `sqlite:///:memory:` — no Docker needed
- **Test auth:** use fixtures `admin_token`, `jury_token`, `competitor_token` from `conftest.py`

### Important Gotchas

- **`selected_cells` must be `list[dict]`** in `SubmitCodeSchema` — tests must send `[{"source": "..."}]`, not `["..."]`
- **`model_fields_set`** is the correct way to check which fields a PATCH client actually sent (not `"key" in data`)
- **Form data comes as strings** — `validate_form` uses `@field_validator(mode="before")` with `_coerce_bool`/`_coerce_int` helpers for type coercion
- **`validate_json` does NOT accept `exclude_unset` parameter** — use `model_fields_set` in PATCH handlers instead
- **DO NOT use `jsonify({"error": ...})`** — always use `err(code, status, message=...)`
- **DO NOT remove error codes from `DEFAULT_ERROR_MESSAGES`** without also removing from both locale translation files and the `check_error_codes.py` scan path
- **RUF001 in admin.py** is intentional (Bulgarian→Latin transliteration mappings) — ignored via per-file-ignores
