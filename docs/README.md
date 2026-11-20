# LavBench Developer & Documentation Guide

Welcome to the LavBench platform technical documentation directory. This folder contains developer guides, Sphinx documentation sources, architectural specifications, and custom evaluator script templates.

---

## Quick Access & Sitemap

| Resource | URL / Path | Target Audience | Description |
| :--- | :--- | :--- | :--- |
| **API Reference** | [`source/api/spec.json`](source/api/spec.json) | All Developers | The OpenAPI document of every REST and SSE endpoint, rendered as the REST API pages of the Sphinx build; a running backend also serves it at `/apidoc/swagger/`. |
| **Architecture Specification** | [`source/architecture.md`](source/architecture.md) | Contributors & DevOps | System architecture, worker budgeting, SSE pipelines, and security layers. |
| **Administrator Guide** | [`../guides/en/admin_guide.md`](../guides/en/admin_guide.md) | Admins & Organizers | Challenge lifecycle, Docker build troubleshooting, custom evaluators, worker setup, and backup rules. |
| **Jury Portal Guide** | [`../guides/en/jury_guide.md`](../guides/en/jury_guide.md) | Competition Jury | Submission monitoring, build diagnostics, double-blind privacy, and manual scoring. |
| **Competitor Guide** | [`../guides/en/competitor_guide.md`](../guides/en/competitor_guide.md) | Participants | Notebook submission, AST pre-validation, status pipeline, and troubleshooting. |
| **nanoColab Integration Note** | [`source/ops/nanocolab-integration.md`](source/ops/nanocolab-integration.md) | nanoColab team & DevOps | How LavBench drives nanoColab's `/v1` API: sync loop, one event per stage or competition, publish, folder-per-task package, workspaces and submissions from them, error mapping, fallback and requests to nanoColab. |

---

## 1. Developer Guidelines

The coding rules and procedures live in one place, [`AGENTS.md`](../AGENTS.md):
- backend layout and canonical imports, route patterns, Pydantic and spectree validation, and error codes (`err()`, `SchemaError`);
- frontend conventions and translations (`api.ERR_*` keys, plurals, the Bulgarian translator);
- the API type pipeline: regenerate `frontend/src/types/api.d.ts` and `docs/source/api/spec.json` from a running backend with `npm run generate-api-types` and `make -C docs fetch-spec` (over the compose stack, set `API_SPEC_URL=http://localhost:80/apidoc/openapi.json`); the `docker-build` CI job fails when either drifts;
- the checks to run before pushing.

---

## 2. Custom Evaluators & Templates

When creating custom evaluator scripts for tasks:
- Refer to section 5 of the [Administrator Guide](../guides/en/admin_guide.md#5-custom-evaluator-scripts-logic-and-baseline-verification) for the module contract (`METRIC_NAME`, `SUBMISSION_COLUMNS`, `LABELS_COLUMNS`, `EVALUATOR_OPTIONS`), the `evaluate()` signature, the rules for results and where evaluators run.
- Check template examples in `docs/evaluator_templates/`:
  - [`evaluator_custom_template.py`](evaluator_templates/evaluator_custom_template.py) — Comprehensive reference template.
  - [`evaluator_ht1_audio.py`](evaluator_templates/evaluator_ht1_audio.py) — Audio classification.
  - [`evaluator_ht2_delivery.py`](evaluator_templates/evaluator_ht2_delivery.py) — Grid delivery navigation.
  - [`evaluator_ht3_animal.py`](evaluator_templates/evaluator_ht3_animal.py) — Animal deduction logic.

---

## 3. Building Sphinx Documentation

Sphinx compiles project documentation and autodoc API references into HTML:

```bash
cd docs

# 1. Install Sphinx requirements
pip install -r requirements.txt

# 2. Build HTML output
make html

# Output is generated in docs/build/ (open docs/build/index.html in a browser)

# 3. Bulgarian build (sources: docs/source/bg/ — guides symlinked from
#    guides/bg/, architecture.md translated via scripts/translate_gemini.py):
make html-bg
# Output is generated in docs/build/html-bg/
```

### Language switcher (EN ↔ BG)

A language button is rendered on every page (sidebar + mobile top bar) and links
to the **same page** in the other build. It assumes the bg build is deployed
under `bg/` relative to the en build root — e.g.:

```bash
# Serve docs/build/ at /docs/ and docs/build/html-bg/ as /docs/bg/
python3 -m http.server 8080 --directory docs/build
# open http://localhost:8080/ -> EN docs, button links to /bg/competitor_guide
```

The switcher lives in `docs/source/_templates/layout.html`
(`lang_switch_link` macro, styled in `_static/css/custom.css`).

### Translation workflow

Bulgarian translations are generated with [`../scripts/translate_gemini.py`](../scripts/translate_gemini.py) (Gemini API, key in `.gemini-api-key` at the repo root — gitignored). It translates `frontend/public/locales`, `guides/en/` → `guides/bg/`, `docs/README.md` → `docs/README.bg.md`, and with `--docs` the `docs/source/*.md` files into `docs/source/bg/`. Guides symlinked from `guides/` are mirrored into `docs/source/bg/` (never retranslated); the bg docs build entry point is `docs/source/bg/index.rst`. Run `python3 scripts/translate_gemini.py --dry-run` to preview, and verify with `python3 frontend/scripts/check_translations.py` and `make html-bg`. See CONTRIBUTING.md → "Translating UI strings and docs".
