# LavBench Developer & Documentation Guide

Welcome to the LavBench platform technical documentation directory. This folder contains developer guides, Sphinx documentation sources, architectural specifications, and custom evaluator script templates.

---

## Quick Access & Sitemap

| Resource | URL / Path | Target Audience | Description |
| :--- | :--- | :--- | :--- |
| **Swagger UI** | `http://localhost:5001/apidoc/swagger/` | All Developers | Interactive REST API & SSE endpoint documentation. |
| **Architecture Specification** | [`ARCHITECTURE.md`](ARCHITECTURE.md) | Contributors & DevOps | System architecture, worker budgeting, SSE pipelines, and security layers. |
| **Custom Evaluator Guide** | [`custom-evaluators.md`](custom-evaluators.md) | Challenge Organizers | Full module contract, AST validation, and script templates for custom metrics. |
| **Administrator Guide** | [`../guides/en/admin_guide.md`](../guides/en/admin_guide.md) | Admins & Organizers | Challenge lifecycle, Docker build troubleshooting, worker setup, and backup rules. |
| **Jury Portal Guide** | [`../guides/en/jury_guide.md`](../guides/en/jury_guide.md) | Competition Jury | Submission monitoring, build diagnostics, double-blind privacy, and manual scoring. |
| **Competitor Guide** | [`../guides/en/competitor_guide.md`](../guides/en/competitor_guide.md) | Participants | Notebook submission, AST pre-validation, status pipeline, and troubleshooting. |

---

## 1. Frontend Developer Guidelines

### API Type Pipeline

The frontend uses an automated type pipeline to derive TypeScript definitions directly from the backend Pydantic schemas:

```bash
cd frontend

# 1. Ensure backend is running (port 5001), then fetch OpenAPI spec & generate types:
npm run generate-api-types       # openapi-typescript → src/types/api.d.ts

# 2. Validate all JSDoc types and React component props:
npm run check-types              # tsc --noEmit (0 errors required)
```

### Key Frontend Conventions:
- **Authentication**: `httpOnly` cookie (`auth_token`). `ApiService` automatically handles cookie persistence.
- **SSE Streaming**: 7 live endpoints use Server-Sent Events. Connect via `new EventSource(url)` with automatic cookie authorization.
- **Error Codes**: All API error responses return `{"error": "<message>", "code": "ERR_CODE"}`. Map `data.code` to user-facing translation strings via `t('api.' + data.code)`.
- **i18n Translation Parity**: Run `python frontend/scripts/check_translations.py` to ensure symmetry between `en` and `bg` translation files.

---

## 2. Backend Developer Guidelines

### Endpoint Implementation Pattern (spectree + Pydantic v2)

Every backend endpoint must use Pydantic v2 schemas and spectree `@api.validate` decorators for request/response validation:

```python
from spectree import Response
from spec import api
from schemas.challenge import CreateChallengeSchema
from schemas.responses.challenge import ChallengeResponse

@challenges_bp.route("", methods=["POST"])
@login_required
@role_required(["admin"])
@api.validate(
    json=CreateChallengeSchema,
    resp=Response(HTTP_201=ChallengeResponse),
    tags=["Challenges"],
    security=[{"cookieAuth": []}],
)
def create_challenge(json: CreateChallengeSchema):
    """Creates a new competition challenge."""
    # json is the pre-validated CreateChallengeSchema instance
    challenge = Challenge(title=json.title, description=json.description)
    db.session.add(challenge)
    db.session.commit()
    return challenge.to_dict(), 201
```

### Key Backend Conventions:
- **Error Code Standard**: Use `err("ERR_CODE", status_code)` from `error_utils.py`. Every `ERR_*` code must be registered in `DEFAULT_ERROR_MESSAGES` and translated in both `en` and `bg` locales.
- **Schema Errors**: Custom Pydantic field validators raise `SchemaError("ERR_CODE", "Message")` from `schemas/exceptions.py`.
- **Error Linter**: Run `python backend/scripts/check_error_codes.py` before submitting PRs.
- **Type Annotations**: All backend source code must pass `mypy . --no-incremental` with 0 errors.

---

## 3. Custom Evaluators & Templates

When creating custom evaluator scripts for tasks:
- Refer to [`custom-evaluators.md`](custom-evaluators.md) for the required 4 module variables contract (`METRIC_NAME`, `SUBMISSION_COLUMNS`, `LABELS_COLUMNS`, `EVALUATOR_OPTIONS`) and `evaluate()` signature.
- Check template examples in `docs/evaluator_templates/`:
  - [`evaluator_custom_template.py`](evaluator_templates/evaluator_custom_template.py) — Comprehensive reference template.
  - [`evaluator_ht1_audio.py`](evaluator_templates/evaluator_ht1_audio.py) — Audio classification.
  - [`evaluator_ht2_delivery.py`](evaluator_templates/evaluator_ht2_delivery.py) — Grid delivery navigation.
  - [`evaluator_ht3_animal.py`](evaluator_templates/evaluator_ht3_animal.py) — Animal deduction logic.

---

## 4. Building Sphinx Documentation

Sphinx compiles project documentation and autodoc API references into HTML:

```bash
cd docs

# 1. Install Sphinx requirements
pip install -r requirements.txt

# 2. Build HTML output
make html

# Output is generated in docs/build/html/ (open index.html in browser)
```
