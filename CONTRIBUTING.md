# Contributing to LavBench

## Setup

```bash
cp .env.example .env
# Edit .env — set SECRET_KEY, ENCRYPTION_KEY, DATABASE_URL, etc.
python backend/setup-admin.py
./scripts/deploy-debug.sh
```

The backend runs on `http://localhost:5001`, the frontend on `http://localhost:5173`.

## Pull Request Checklist

1. **Create tests for new code** — When adding new API endpoints, React components, or services, include accompanying tests to maintain coverage standards.
2. **Run all tests**:

   ```bash
   # Backend (pytest — 946 tests, requires micromamba env)
   cd backend && micromamba run -n lavbench_backend python -m pytest tests/ -v

   # Frontend (vitest — 363 tests)
   cd frontend && npm run test
   ```

3. **Format and lint your code** — Both formatters and linters run in CI and will block unformatted or failing code:

   ```bash
   ruff format backend/ --config backend/pyproject.toml
   ruff check --fix backend/ --config backend/pyproject.toml
   cd frontend && npm run format
   python backend/scripts/check_error_codes.py
   ```

4. **Verify formatting and linting** — Run format checks before pushing:
   ```bash
   ruff format --check backend/ --config backend/pyproject.toml
   ruff check backend/ --config backend/pyproject.toml
   cd frontend && npm run format:check
   python backend/scripts/check_error_codes.py
   ```
5. **Verify type integrity** — `npm run check-types` must pass with 0 errors.
   ```bash
   cd frontend && npm run check-types
   ```
6. **Regenerate API types** if backend endpoints are modified:
   ```bash
   # Start the backend on port 5001, then run:
   cd frontend && npm run generate-api-types
   ```
7. **Check translation parity** — Every `ERR_*` code in the backend must have a matching `api.ERR_*` key in both locales. Run the error code linter (already covered in step 3/4):
   ```bash
   python backend/scripts/check_error_codes.py
   ```
8. **Adhere to project patterns** — Use the `err()` helper for error responses (never `jsonify({"error": ...})`), add `api.ERR_*` translation keys for new codes, and rely on `tsc --noEmit` for frontend validation.

## Code Conventions

### Backend (Python)

- Formatted and linted with **Ruff** (configuration in `backend/pyproject.toml`, line‑length 100, rules matching the project’s standards)
- Error responses must use the `err(code, status, message=...)` helper from `error_utils.py` — never `jsonify({"error": ...})` directly
- Every `ERR_*` code must be defined in `DEFAULT_ERROR_MESSAGES` in `backend/error_utils.py` and referenced by at least one `err()` call
- Tests in `backend/tests/`, one file per route module or service
- Dev dependencies (pytest, pytest-mock, Faker, etc.) are in `dev-requirements.in` — compile with `pip-compile dev-requirements.in`
- Use pytest fixtures from `backend/conftest.py` for common setups
- New routes go in `backend/routes/`, register blueprints in `backend/app.py`
- Security-sensitive code must include rate limiting and auth checks

### Frontend (JavaScript/React)

- Formatted with **Prettier** (configured via `frontend/.prettierrc`)
- **JSDoc `@type` annotations** over raw TypeScript — referencing `src/types/api.d.ts`
- Component props must use default values (e.g., `prop = 'default'`) for optionality
- Service wrappers follow the signature: `(...args: any[]) => Promise<{ok, data: Type}>`
- Never use `@ts-ignore` or `@type {any}` — use specific type assertions or narrow types with `typeof` guards
- Tests use vitest + happy-dom, co-located with components as `*.test.jsx`

### Translations

- Translation keys use dot-notation (e.g., `section.subsection.key`)
- Keys map directly to the JSON structure in `public/locales/{en,bg}/translation.json`
- Both English and Bulgarian locale files must always have matching keys
- Backend error code translations live under `api.ERR_*` (not the legacy `error.ERR_*` namespace). When adding a new `ERR_*` code, add an `api.ERR_*` key to both locale files — the linter (`check_error_codes.py`) enforces parity

## Pre-commit Hooks

Formatting is enforced automatically via pre-commit hooks. Install once:

```bash
pip install pre-commit
pre-commit install
```

After that, `git commit` will run **Ruff format** and **Ruff check** (with safe fixes) for Python, and **Prettier** for JS/CSS/JSON automatically. If formatting or linting fails, the commit is blocked — run the format and fix commands (see step 3 above), stage the changes, and commit again.

The same checks run in CI (`backend-lint`, `backend-format`, `frontend-format` jobs) on every push and PR. The error code linter (`check_error_codes.py`) runs as part of `backend-lint`.

## Frontend Type System

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

API response types use precise paths from the generated file:

```
paths['/api/endpoint']['method']['responses']['200']['content']['application/json']
```

## Security

The platform evaluates untrusted student code in hardened Docker containers. When modifying the execution pipeline (`backend/task_modules/submission_runner.py`), ensure that:

- No new network access is introduced
- No new Linux capabilities are granted
- Writable paths are limited to `/app/` (volume) and `/tmp/` (tmpfs)
- Resource limits (RAM, CPU, PIDs, time) remain enforced
- Labels/ground truth never enter the sandbox — they are evaluated post-execution on the host

## License

By contributing, you agree that your contributions will be licensed under the [AGPL v3](LICENSE).
