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
6. **Regenerate the API types and the docs spec snapshot** if backend endpoints or schemas change (CI fails when either drifts):
   ```bash
   # Start the backend on port 5001 (or use the compose stack with
   # API_SPEC_URL=http://localhost:80/apidoc/openapi.json), then run:
   cd frontend && npm run generate-api-types   # frontend/src/types/api.d.ts
   make -C docs fetch-spec                      # docs/source/api/spec.json
   ```
7. **Check translation parity** — Every `ERR_*` code in the backend must have a matching `api.ERR_*` key in both locales. Run the error code linter (already covered in step 3/4):
   ```bash
   python backend/scripts/check_error_codes.py
   ```
8. **Adhere to project patterns** — Use the `err()` helper or `SchemaError` for error responses (never `jsonify({"error": ...})`), add `api.ERR_*` translation keys for new codes, and rely on `tsc --noEmit` for frontend validation.
9. **Update the docs in English and Bulgarian.** Edit the English guide or doc, then produce the Bulgarian copy with `python3 scripts/translate_gemini.py` (see below), review the Bulgarian diff, and run `python3 scripts/translate_gemini.py --check`.
10. **Add a database migration** with every model/schema change. Run `cd backend && alembic revision --autogenerate -m "short description"`, review the generated operations (schema only, no data migrations), run `python scripts/migrate.py` against a fresh database, and run `pytest tests/test_migrations_pytest.py`, whose drift test fails when the models and the revisions disagree.
11. **Run the visual check for frontend changes.** Add or update the scenarios of the screens you changed in `scripts/ui_check/capture.py`, run `scripts/ui_check/run.sh --only role--scenario[,...]` on a throwaway stack and review their contact sheets for every role, viewport, language and theme. Run the full `make ui-check` only when shared layout, navigation or many pages change. See [`scripts/ui_check/README.md`](scripts/ui_check/README.md).
12. **Run the full-stack smoke test for backend, worker, nginx or compose changes:** `scripts/ui_check/stack.sh up`, then `SMOKE_EVALUATE=1 python3 scripts/api_smoke_test.py`.

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

Bulgarian translations are generated from the English sources with `scripts/translate_gemini.py`, which calls the Gemini Interactions API through Google's `google-genai` SDK (pinned in `backend/dev-requirements.txt`; run it in the `lavbench_backend` environment, or `pip install -r backend/dev-requirements.txt`). Every interaction is sent with `store=false`, so Google keeps no copy. `--check` and `--dry-run` need neither the SDK nor the key. The script covers:

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
   # List what would be sent with an estimate of the tokens, without calling the API:
   python3 scripts/translate_gemini.py --dry-run
   # Refuse a run whose estimate is above a token limit:
   python3 scripts/translate_gemini.py --max-tokens 30000
   ```
   Options: `--model` (default `gemini-4-carbon`, at its lowest thinking level), `--flex` (Flex service tier, calls may take minutes), `--key-file`, `--docs`, `--dry-run`, `--max-tokens`, `--force` (re-translate everything; costly), `--check`.

   Only what changed since the Bulgarian file was last committed is sent: new or changed UI keys, and the changed blocks of a document (paragraphs, list items, table rows, headings, code blocks). A changed block goes with its previous English and Bulgarian so correct wording is reused; a new block goes with its section heading and a neighbouring Bulgarian block. Unchanged, reflowed and moved blocks keep their Bulgarian without a call. A section whose old English and Bulgarian do not have the same blocks is sent whole, and a reply whose blocks, headings, code fences, table columns or link targets do not match its English is retried once as whole sections; if that fails too, the file is left unchanged. When a document's sections no longer line up, that file is translated whole. Every run prints the tokens the API reports (input, cached, output, thinking) per document and in total; `--dry-run` prints an estimate of them.
3. `SYSTEM_PROMPT` in the script is the single source of Bulgarian terminology for the UI strings and every document (e.g. challenge→състезание, worker→работен възел, backup→резервно копие, sandbox→изолирана среда), with a role-specific context per document; documents also receive the real Bulgarian UI labels they mention, so translations stay consistent across files. The run ends with a consistency gate that fails on banned variants (run it alone with `--check`). Markdown anchors are re-linked to the translated headings automatically; guides symlinked into `docs/source` are mirrored into `docs/source/bg` instead of being retranslated.
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

After that, `git commit` runs `ruff check`, `ruff format --check` and `mypy` from `backend/` (through the `lavbench_backend` micromamba env from Setup), and `prettier --write` on staged frontend files. The hooks check and do not fix Python code: if one fails, run `ruff check --fix` / `ruff format` (see step 3 above), stage the changes, and commit again.

The same checks run in CI on every push and PR: `backend-lint` (`ruff check`, `ruff format --check` and the error code linter `check_error_codes.py`), `backend-types` (mypy) and `frontend-format` (Prettier).

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
