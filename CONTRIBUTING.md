# Contributing to LavBench

## Setup

```bash
cp .env.example .env
# Edit .env — set SECRET_KEY, ENCRYPTION_KEY, DATABASE_URL, etc.
python backend/scripts/setup-admin.py
./scripts/deploy-debug.sh
```

The backend runs on `http://localhost:5001`, the frontend on `http://localhost:5173`.

## Pull Request Checklist

1. **Create tests for new code** — When adding new API endpoints, React components, or services, include accompanying tests to maintain coverage standards.
2. **Run all tests**:

   ```bash
   # Backend (requires the lavbench_backend micromamba env)
   cd backend && micromamba run -n lavbench_backend python -m pytest tests/ -v

   # Frontend (vitest)
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
8. **Adhere to project patterns** — Use the `err()` helper or `SchemaError` for error responses (never `jsonify({"error": ...})`), add `api.ERR_*` translation keys for new codes, and rely on `tsc --noEmit` for frontend validation.
9. **Add a database migration** with every model/schema change. Run `cd backend && alembic revision --autogenerate -m "short description"`, review the generated operations, and verify `python scripts/migrate.py` against a fresh and upgraded database.

## Code Conventions

### Backend (Python)

- Formatted and linted with **Ruff** (configuration in `backend/pyproject.toml`, line‑length 100, rules matching the project’s standards)
- Error responses must use the `err(code, status, message=...)` helper from `backend/utils/error_utils.py` or raise `SchemaError(code, message)` in Pydantic validators — never `jsonify({"error": ...})` directly
- Schema validators go in `backend/schemas/` with Pydantic v2 `BaseModel` classes; use `@api.validate(json=..., resp=Response(...))` decorators on route handlers
- Every `ERR_*` code must be defined in `DEFAULT_ERROR_MESSAGES` in `backend/utils/error_utils.py` and referenced by at least one `err()` or `SchemaError()` call
- Tests in `backend/tests/`, one file per route module or service
- Dev dependencies (pytest, pytest-mock, Faker, etc.) are in `dev-requirements.in` — compile with `pip-compile dev-requirements.in`
- Use pytest fixtures from `backend/config/conftest.py` for common setups
- New routes go in `backend/routes/`, new schemas go in `backend/schemas/`, register blueprints in `backend/app.py`
- Security-sensitive code must include rate limiting and auth checks
- Database schema changes require a reviewed Alembic revision in `backend/migrations/versions/`; application processes must never create or mutate schema at startup

### Frontend (JavaScript/React)

- Formatted with **Prettier** (configured via `frontend/.prettierrc`)
- **JSDoc `@type` annotations** over raw TypeScript — referencing `src/types/api.d.ts`
- Component props must use default values (e.g., `prop = 'default'`) for optionality
- Service wrappers follow the signature: `(...args: any[]) => Promise<{ok, data: Type}>`
- Never use `@ts-ignore` or `@type {any}` — use specific type assertions or narrow types with `typeof` guards
- Tests use vitest + happy-dom, co-located with components as `*.test.jsx`

### Comments & Docstrings

Comment style is enforced for Python by `backend/scripts/check_comments.py` (run it before pushing; the frontend has an advisory equivalent via `npm run lint:comments`):

- Every Python module needs a **one-line summary docstring** as its first statement (`"""Describe the module."""`); skip only for empty `__init__.py` files
- Function docstrings are optional one-liners (`"""Short summary."""`) — no argument lists unless they add value
- Inline comments explain **why**, not what — `# ` + capitalized sentence, no trailing period
- Section dividers use `# ── Title ──` (U+2500 `─`, at least 3 dashes per side). Forbidden styles: `# ===`, `# ---`, `# ═══`, box banners, or decorative `# **` blocks
- Never leave commented-out code in the tree
- Lint pragmas keep their codes: `# noqa: CODE` and `# type: ignore[code]`; a bare `# noqa` is forbidden
- TODOs must be actionable: `# TODO: <imperative> ...` (e.g. `# TODO: add pagination to this endpoint`)
- Security comments (e.g. about key derivation or sandbox flags) stay — they document intent

### Translations

- Translation keys use dot-notation (e.g., `section.subsection.key`)
- Keys map directly to the JSON structure in `public/locales/{en,bg}/translation.json`
- Both English and Bulgarian locale files must always have matching keys
- Backend error code translations live under `api.ERR_*` (not the legacy `error.ERR_*` namespace). When adding a new `ERR_*` code, add an `api.ERR_*` key to both locale files — the linter (`check_error_codes.py`) enforces parity

### Translating UI strings and docs (EN → BG)

Bulgarian translations are generated from the English sources with `scripts/translate_gemini.py` (Gemini API). The script covers:

| Target | Source → Output |
| :--- | :--- |
| Frontend UI + error messages | `frontend/public/locales/en/translation.json` → `bg/translation.json` |
| Role guides | `guides/en/*.md` → `guides/bg/*.md` |
| Docs README | `docs/README.md` → `docs/README.bg.md` |
| Sphinx docs | `docs/source/*.md` → `docs/source/bg/*.md` (only with `--docs`; guide files are symlinked, not retranslated) |

Procedure:

1. The API key lives in `.gemini-api-key` at the repo root (gitignored) as `GEMINI-API-KEY=...`. The script reads it and exports it as `GEMINI_API_KEY`. An exported `GEMINI_API_KEY` env var takes precedence over the file.
2. Run the script:
   ```bash
   # Everything (frontend + guides + docs README):
   python3 scripts/translate_gemini.py
   # Include docs/source:
   python3 scripts/translate_gemini.py --docs
   # Single target:
   python3 scripts/translate_gemini.py --only locales|guides|docs|readme
   # Preview without writing:
   python3 scripts/translate_gemini.py --dry-run
   ```
   Options: `--model` (default `gemini-3.6-flash`), `--key-file`, `--docs`, `--dry-run`.
3. The system prompt embeds LavBench context + a fixed EN→BG glossary (e.g. challenge→състезание, stage→етап, sandbox→пясъчна среда) and a role-specific context per guide, so translations stay consistent across files. Markdown anchors are re-linked to the translated headings automatically; guides symlinked into `docs/source` are mirrored into `docs/source/bg` instead of being retranslated.
4. Verify:
   ```bash
   python3 frontend/scripts/check_translations.py   # 0 symmetry/missing issues
   make -C docs html-bg                              # bg Sphinx build
   ```
5. Never hand-edit `docs/source/bg/*` guide files — they are symlinks to `guides/bg/*`. Translate via the script (or edit `guides/bg/` directly).
6. Never commit `.gemini-api-key`.

## Pre-commit Hooks

Formatting is enforced automatically via pre-commit hooks. Install once:

```bash
pip install pre-commit
pre-commit install
```

After that, `git commit` will run **Ruff format** and **Ruff check** (with safe fixes) for Python, and **Prettier** for JS/CSS/JSON automatically. If formatting or linting fails, the commit is blocked — run the format and fix commands (see step 3 above), stage the changes, and commit again.

> [!NOTE]
> With ruff v0.15.19 the pre-commit hook currently false-positives on test files (S101/S106 despite per-file-ignores). CI does not have this problem — you can bypass the local hook with `git commit --no-verify`; the checks below still run on push.

The same checks run in CI (`backend-lint`, `backend-format`, `frontend-format` jobs) on every push and PR. The error code linter (`check_error_codes.py`) runs as part of `backend-lint`.

## Frontend Type System

```
Backend Pydantic models + spectree decorators
       │
       ▼
  openapi-typescript
       │
       ▼
  frontend/src/types/api.d.ts    (auto-generated, includes JSDoc @type annotations)
       │
       ▼
  tsc --noEmit                   (validates all types)
```

API response types use precise paths from the generated file:

```
paths['/api/endpoint']['method']['responses']['200']['content']['application/json']
```

## Security

The platform evaluates untrusted competitor code in hardened Docker containers. When modifying the execution pipeline (`backend/tasks/task_modules/submission_runner.py`), ensure that:

- No new network access is introduced
- No new Linux capabilities are granted
- Writable paths are limited to `/app/` (volume) and `/tmp/` (tmpfs)
- Resource limits (RAM, CPU, PIDs, time) remain enforced
- Labels/ground truth never enter the sandbox — they are evaluated post-execution on the host

## License

By contributing, you agree that your contributions will be licensed under the [AGPL v3](LICENSE).
