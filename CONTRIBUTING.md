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
   # Backend (pytest)
   python -m pytest backend/tests/ -v

   # Frontend (vitest)
   cd frontend && npm run test
   ```
3. **Format your code** — Both formatters run in CI and will block unformatted code:
   ```bash
   black backend/
   cd frontend && npm run format
   ```
4. **Verify formatting** — Run format checks before pushing:
   ```bash
   black --check backend/
   cd frontend && npm run format:check
   ```
5. **Verify type integrity** — `npm run check-types` must pass with 0 errors.
   ```bash
   cd frontend && npm run check-types
   ```
6. **Check translations** — English and Bulgarian locale keys must be in sync:
   ```bash
   python3 frontend/scripts/check_translations.py
   ```
7. **Regenerate API types** if backend endpoints are modified:
   ```bash
   # Start the backend on port 5001, then run:
   cd frontend && npm run generate-api-types
   python3 frontend/scripts/_annotate_types.py
   ```
8. **Adhere to project patterns** — Use `@type` JSDoc annotations for API responses, maintain component prop defaults, and rely on `tsc --noEmit` for validation.

## Code Conventions

### Backend (Python)

- Formatted with **Black** (line-length 100, configured in `backend/pyproject.toml`)
- Tests in `backend/tests/`, one file per route module
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

## Pre-commit Hooks

Formatting is enforced automatically via pre-commit hooks. Install once:

```bash
pip install pre-commit
pre-commit install
```

After that, `git commit` will run **Black** (Python) and **Prettier** (JS/CSS/JSON) automatically. If formatting fails, the commit is blocked — run the format commands, stage the changes, and commit again.

The same checks run in CI (`backend-format` and `frontend-format` jobs) on every push and PR.

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
