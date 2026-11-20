## Why

<!-- The problem this solves and who it affects. Link the issue. -->

Closes #

## What changes

<!-- Grouped by area (backend, frontend, workers, docs, CI). Say why, not only what. -->

## Verification

<!-- What you ran and the results: test counts, smoke test, UI check scenarios. -->

## Not in this PR

<!-- Optional: related work left for later, and why. -->

## Deploy notes

<!-- Optional: migrations, new environment variables, settings to apply, worker and server updated together. -->

## Checklist

Commands and details: [CONTRIBUTING.md](https://github.com/delyan-boychev/lavbench/blob/main/CONTRIBUTING.md) and the "CI Checks" section of [AGENTS.md](https://github.com/delyan-boychev/lavbench/blob/main/AGENTS.md).

- [ ] Backend checks pass: ruff check and format, `check_error_codes.py`, mypy, pytest
- [ ] Frontend checks pass: lint, format, tests, type check, `check_translations.py`
- [ ] Model changes come with an Alembic revision (`test_migrations_pytest.py` passes)
- [ ] Endpoint or schema changes: `api.d.ts` and `docs/source/api/spec.json` regenerated
- [ ] New `ERR_*` codes are in `DEFAULT_ERROR_MESSAGES` and in both locale files
- [ ] Docs updated in English and Bulgarian; `make docs` and `translate_gemini.py --check` pass
- [ ] Backend, worker, nginx or compose changes: full-stack smoke test passed
- [ ] Frontend changes: targeted UI check (`run.sh --only`) reviewed for every role, viewport, language and theme
- [ ] Conventional commits; no AI attribution lines and no emojis
