# AGENTS.md — LavBench

Rules, patterns, and practices for working on this project efficiently.

---

## Agent Workflow Rules

### Subagent Delegation

When a task involves **3+ distinct conceptual steps** or requires searching multiple files, **delegate to a subagent**:

| Task type | When | Subagent |
|---|---|---|
| Bulk file edits (5+ files) | Always | `general` |
| Searching patterns across codebase | Always | `explore` |
| Reading multiple files for context | >3 files | `explore` |
| Running test suites / lint checks | Always (in parallel) | — (use `bash` directly) |
| Multi-step refactoring | Touching >2 files | `general` |

**Rules:**
1. Launch subagents **in parallel** when work is independent
2. Give subagents a clear **return contract** — exactly what info to return
3. Never duplicate work after delegating
4. Verify subagent results by running tests/lint after merging
5. For `explore` subagents, specify depth: `"quick"` / `"medium"` / `"very thorough"`
6. Do **NOT** delegate single reads, edits, or greps — do them directly

---

## Project Structure

```
lavbench/
├── AGENTS.md
├── Makefile
├── docker-compose.yml
├── scripts/                           # Deployment & setup scripts
├── backend/
│   ├── app.py                         # Flask factory, blueprint registration, error handlers
│   ├── config.py                      # Config from env vars
│   ├── error_utils.py                 # err() helper + DEFAULT_ERROR_MESSAGES dict
│   ├── auth_utils.py                  # JWT auth, rate limiting, token revocation
│   ├── cache_utils.py                 # Redis caching, locks
│   ├── evaluation_engine.py           # Parquet-based evaluation
│   ├── sse_utils.py                   # SSE pub/sub
│   ├── worker_utils.py                # Docker sandbox management
│   ├── tasks.py                       # Celery tasks + beat schedule
│   ├── models/                        # SQLAlchemy models (challenge, task, submission, user, stage...)
│   ├── schemas/                       # Pydantic v2 validation schemas
│   │   ├── __init__.py                # validate_json / validate_form decorators
│   │   ├── exceptions.py              # SchemaError(code, message)
│   │   ├── common.py                  # Shared validators (_parse_datetime_strict, PaginationParams)
│   │   └── admin.py, auth.py, challenge.py, task.py, submission.py, leaderboard.py, stage.py
│   ├── routes/                        # Flask blueprints
│   ├── services/                      # Business logic
│   ├── utils/
│   ├── task_modules/                  # Submission runner, image builder
│   ├── scripts/check_error_codes.py   # Lint: err() + SchemaError usage + translation parity
│   └── tests/                         # pytest (conftest.py: client, auth, model fixtures)
├── frontend/
│   ├── src/
│   │   ├── components/, pages/, services/, context/, hooks/
│   │   └── types/api.d.ts             # Auto-generated from OpenAPI
│   ├── scripts/check_translations.py  # i18n key parity checker
│   └── public/locales/{en,bg}/translation.json  # 930 keys, always symmetrical
├── guides/                            # User docs (admin, competitor, jury — en/bg)
├── docs/                              # Sphinx documentation
├── .github/workflows/ci.yml
└── CONTRIBUTING.md
```

---

## Environment & CI

### Setup
```
micromamba create -n lavbench_backend python=3.12
micromamba run -n lavbench_backend pip install -r backend/requirements.txt -r backend/dev-requirements.txt
cd frontend && npm ci
make dev   # or: flask on :5001 + vite on :5173
```

### CI Checks (run all before pushing)
```
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

### CI Pipeline
| Job | What it runs |
|---|---|
| `backend-tests` | `pytest -n auto --timeout=120 --cov` (≥70%) |
| `backend-lint` | `ruff check`, `ruff format --check`, `check_error_codes.py` |
| `frontend-lint` | `npm run lint` |
| `frontend-format` | `npm run format:check` |
| `frontend-tests` | `npm run test:coverage` |
| `translations-check` | `json.tool` + `check_translations.py` |
| `frontend-types` | `npm run check-types` (tsc --noEmit) |
| `docker-build` | `docker build` + `docker compose up` |

### Pre-commit Hook Issue
The pre-commit hook (`ruff check --fix --config backend/pyproject.toml`) fails on test files with S101/S106 despite correct per-file-ignores in ruff v0.15.19. Use `git commit --no-verify` to bypass.

---

## Pydantic Schema Validation

### Two Decorators
```python
from schemas import validate_json, validate_form

@validate_json(SomeSchema)       # JSON body → kwargs["data"] (model object)
@validate_form(SomeFormSchema)   # multipart/form-data → kwargs["form_data"] (model object)
```

### Key Rules
- Validated **model object** is injected (not `model_dump()` dict) — access via `data.field`
- Validation failure returns `422` with specific error code (e.g. `ERR_INVALID_DOCKER_IMAGE`)
- `_validation_error` in `schemas/__init__.py` extracts `SchemaError` from Pydantic's `ctx["error"]`; falls back to `ERR_VALIDATION`
- `SchemaError(code, message)` base class is `ValueError` — raise in `@field_validator` and `@model_validator`

### SchemaError
```python
# schemas/exceptions.py
class SchemaError(ValueError):
    def __init__(self, code: str, message: str = ""): ...
```

### Form Data Coercion
Form fields arrive as strings. Each schema defines `@field_validator(mode="before")` helpers:
```python
@field_validator("gpu_required", mode="before")
@classmethod
def _coerce_bool(cls, v):
    if isinstance(v, str):
        return v.lower() in ("true", "1", "yes")
    return v

@field_validator("ram_limit_mb", mode="before")
@classmethod
def _coerce_int(cls, v):
    if v is None or v == "":
        return None
    return int(v)
```

### Fully Parsed Fields (routes receive native types, not strings)
- `start_time`, `end_time` → `datetime` (via `_parse_datetime_strict` in `schemas/common.py`)
- `hf_datasets`, `hf_models` → `list[str]` (via `_validate_hf_json_list` in `schemas/task.py`)
- `metrics_config` → `dict` (via `_validate_metrics_config` in `schemas/task.py`)
- Route handlers never call `parse_datetime()` or `json.loads()` for these

---

## Route Patterns

### CREATE
```python
@challenges_bp.route("", methods=["POST"])
@role_required(["admin"])
@validate_json(CreateChallengeSchema)
def create_challenge(data):
    challenge = Challenge(title=data.title, description=data.description)
    db.session.add(challenge)
    db.session.commit()
    return jsonify(challenge.to_dict()), 201
```

### PATCH (use `model_fields_set`)
```python
@challenges_bp.route("/<uuid:challenge_id>", methods=["PUT"])
@validate_json(UpdateChallengeSchema)
def update_challenge(challenge_id, data):
    challenge = db.get_or_404(Challenge, challenge_id)
    fields = data.model_fields_set
    if "title" in fields:
        challenge.title = data.title
    if "description" in fields:
        challenge.description = data.description
    db.session.commit()
    return jsonify(challenge.to_dict())
```

### Auth Decorator Order
```python
@login_required                            # JWT cookie required
@role_required(["admin", "jury"])          # Role check
@rate_limit(max_requests=10, window_seconds=60)
@validate_json(SomeSchema)
def handler(data): ...
```

---

## Error Handling

### Route Errors — use `err()`
```python
from error_utils import err
return err("ERR_SOME_CODE", 400)                        # Default message
return err("ERR_SOME_CODE", 403, message="Custom msg")  # Override
```
Response: `{"error": "<message>", "code": "ERR_*"}` (no `key` field). Frontend does `t('api.' + data.code, data.error)`.

### Schema Validator Errors — use `SchemaError`
```python
# In a @field_validator or @model_validator
raise SchemaError("ERR_SPECIFIC_CODE", "Human-readable message")
```
This produces the same `{"error": "...", "code": "ERR_SPECIFIC_CODE"}` response shape via `_validation_error`.

### Error Code Rules (enforced by `check_error_codes.py`)
1. Every `ERR_*` must be defined in `DEFAULT_ERROR_MESSAGES` in `error_utils.py`
2. Every code must be referenced by ≥1 `err()` or `SchemaError()` call
3. Every code must have `api.ERR_*` translation key in both `en` and `bg` locale files
4. No orphaned `api.ERR_*` keys in translation files
5. No `jsonify({"error": ...})` — must use `err()` or `SchemaError`
6. `err()` first arg must be a string literal `ERR_[A-Z0-9_]+`
7. `check_error_codes.py` scans `schemas/*.py` for `SchemaError()` + `_validate_hf_json_list(err_code=...)`

---

## Testing

### Backend
```bash
# All tests in parallel
micromamba run -n lavbench_backend pytest tests -n auto -q

# Single test
micromamba run -n lavbench_backend pytest tests/test_auth_routes_pytest.py -v
micromamba run -n lavbench_backend pytest tests/test_exceptions_pytest.py::TestClass::test_method -x --tb=long
```

**Key fixtures** from `conftest.py`: `client`, `app`, `db_session`, `admin_token`, `jury_token`, `competitor_token`, `challenge_a`, `task_a`, `stage_a`

**Conventions:**
- One test file per route module (`test_X_routes_pytest.py`)
- Assert status code + error code: `assert resp.status_code == 422` / `assert resp.get_json()["code"] == "ERR_VALIDATION"`
- `selected_cells` must be `list[dict]`: `[{"source": "print(1)"}]`, not `["print(1)"]`
- Tests work with `sqlite:///:memory:` — no Docker needed

### Frontend
```bash
npm run test                # vitest
npm run test:coverage
npm run check-types         # tsc --noEmit
```

---

## Linting

### Ruff (backend)
```
line-length: 100
Rules: E, F, I, N, W, UP, B, SIM, S, A, T, C4, RUF, PERF, LOG
Per-file: tests/* → S101, T201, PERF; admin.py → RUF001 (intentional Cyrillic→Latin transliteration)
```

### Frontend
```
npm run format          # Prettier write
npm run format:check    # Prettier check
npm run lint            # ESLint
```

---

## Translation System (i18n)

- `frontend/public/locales/{en,bg}/translation.json` — **always symmetrical** (same keys in both)
- Dot-notation keys: `section.subsection.key`
- Backend `ERR_*` codes under `api.ERR_*` namespace
- Frontend: `t('key')` or `t('key', 'fallback')`; dynamic: `t('api.' + errorCode)`
- ~147 orphaned keys exist (safe to keep for future use)

### Adding a New Translation Key
1. Add key + value to **both** `en/translation.json` and `bg/translation.json`
2. If it's an `ERR_*` code, also add to `DEFAULT_ERROR_MESSAGES` in `backend/error_utils.py`
3. Run both checkers: `python backend/scripts/check_error_codes.py && python frontend/scripts/check_translations.py`

---

## Common Task Procedures

### Add a New Route
1. Create Pydantic schema in `backend/schemas/` (if validation needed)
2. Add route to appropriate `backend/routes/*.py`, decorate with `@validate_json`/`@validate_form`
3. Register blueprint in `backend/app.py` (if new file)
4. Add `err()` code to `DEFAULT_ERROR_MESSAGES` in `error_utils.py` (or raise `SchemaError` in validators)
5. Add `api.ERR_*` translation keys to both locale files
6. Write tests in `backend/tests/`
7. Update API types: `cd frontend && npm run generate-api-types`

### Add a New Schema Validator
```python
from schemas.exceptions import SchemaError

@field_validator("some_field", mode="before")
@classmethod
def _validate_some_field(cls, v):
    if isinstance(v, str) and not MY_REGEX.match(v):
        raise SchemaError("ERR_SPECIFIC_CODE", "Description of what's wrong")
    return v
```

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

---

## Security Model (must preserve)

| Layer | Mechanism |
|---|---|
| Auth | httpOnly cookie + JWT (24h, jti revocation) |
| AuthZ | Role-based: `@role_required(["admin", "jury", "competitor"])` |
| CSRF | JWT csrf token in non-GET requests |
| Rate limiting | Per-user per-endpoint Lua atomic counters (fails open with warning) |
| PII | Fernet-encrypted at rest |
| Sandbox | `--network none --cap-drop ALL --read-only --security-opt no-new-privileges --pids-limit 64`, no swap, tmpfs /tmp |
| Ground truth | labels.parquet evaluated server-side, never in sandbox |
| HF keys | Fetched on-demand via API, never stored in Redis |

---

## Important Gotchas

- **`selected_cells` must be `list[dict]`** — tests send `[{"source": "..."}]`, not `["..."]`
- **`model_fields_set`** for PATCH — not `"key" in data`
- **Form data arrives as strings** — use `mode="before"` validators with `_coerce_bool`/`_coerce_int`
- **`validate_json` does NOT support `exclude_unset`** — use `model_fields_set` in PATCH handlers
- **NEVER `jsonify({"error": ...})`** — use `err()` or raise `SchemaError`
- **Removing error codes** requires cleanup in 3 places: `error_utils.py`, `en/translation.json`, `bg/translation.json`
- **RUF001 in admin.py** is intentional (Bulgarian→Latin transliteration) — ignore via per-file-ignores
- **Pre-commit hook broken** with ruff v0.15.19 (S101/S106 false positives on tests) — use `--no-verify`
- **Docker not needed for tests** — uses `sqlite:///:memory:`
