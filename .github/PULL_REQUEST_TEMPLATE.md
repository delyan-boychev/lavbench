## Description
<!-- Briefly describe the change. Link the issue if applicable. -->

Closes #

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Refactor / chore
- [ ] Documentation

## Checklist
- [ ] Code follows project style and conventions
- [ ] Tests pass (`pytest` / `npm run test`)
- [ ] Lint + format pass (`npm run lint` / `ruff check`)
- [ ] Type check passes (`npm run check-types`)
- [ ] Model changes come with a schema-only Alembic revision (`pytest tests/test_migrations_pytest.py` passes)
- [ ] Endpoint or schema changes: `api.d.ts` and `docs/source/api/spec.json` regenerated
- [ ] New `ERR_*` codes are in `DEFAULT_ERROR_MESSAGES` and in both locale files (`check_error_codes.py` passes)
- [ ] Documentation updated in English and Bulgarian (if needed)
- [ ] Frontend changes: `make ui-check` run and its contact sheets reviewed (`scripts/ui_check/README.md`)
