# LavBench Developer Documentation

## Quick Access

| Resource                         | URL                                  | Who                     |
| -------------------------------- | ------------------------------------ | ----------------------- |
| **Swagger UI** (REST + SSE docs) | `http://localhost:5001/apidocs`      | Backend & Frontend devs |
| **Health check**                 | `http://localhost:5001/api/health`   | DevOps, monitoring      |
| **Architecture overview**        | [`ARCHITECTURE.md`](ARCHITECTURE.md) | New contributors        |

## For Frontend Developers

### Generate TypeScript types from the API spec

```bash
cd frontend
# Start the backend first (port 5001), then:
npm run generate-api-types       # openapi-typescript → src/types/api.d.ts
npm run check-types              # tsc --noEmit — verify 0 errors
```

This pipeline generates `src/types/api.d.ts` (full type definitions for all ~72 endpoints), with JSDoc `@type` annotations verified by TypeScript's `checkJs` mode.

### Key things to know

- **Auth**: httpOnly cookie (`auth_token`). The `ApiService` wrapper sends cookies automatically. No manual token management needed.
- **SSE endpoints**: 7 streaming endpoints use Server-Sent Events. Connect with `new EventSource(url)`. Cookie auth is automatic.
- **Rate limiting**: Per-user, per-endpoint. Backend returns 429 with `ERR_RATE_LIMITED` code. Frontend should show a toast and throttle retries.
- **Error format**: All errors return `{"error": "message", "code": "ERR_CODE"}`. Map `code` values to user-facing translations where needed.
- **Type system**: JSDoc `@type` annotations reference `import('./types/api').paths['/api/...']['method']['responses']['200']['content']['application/json']`. Never use `@ts-ignore` or `@type {any}` — use specific assertions instead.
- **Translation check**: `python3 scripts/check_translations.py` validates i18n keys across en/bg locales, finds missing/orphaned keys.

### Example: calling the login endpoint

```javascript
import api from "./services/ApiService";

/** @type {{ ok: boolean, data: import('./types/api').paths['/api/auth/login']['post']['responses']['200']['content']['application/json'] }} */
const { ok, data } = await api.post("/auth/login", {
  username: "admin_1c15d4d7",
  password: hashedPassword,
});
if (ok) {
  // data.user contains the typed User object
  // cookie is set automatically by the browser
}
```

## For Backend Developers

### Adding a new endpoint

1. Create a Pydantic v2 schema in `backend/schemas/` (e.g., `schemas/admin.py`) with `BaseModel` and `Field()` definitions
2. Define the route in the appropriate `routes/*.py` file, decorating with `@validate_json(MySchema)` or `@validate_form(MyFormSchema)` for request validation
3. Add a flasgger YAML docstring with request/response schemas
4. The Swagger UI at `/apidocs` auto-updates on next server restart
5. Run `npm run generate-api-types` in `frontend/` to update TypeScript types
6. Run `npm run check-types` to verify 0 errors

For PATCH routes, use `data.model_fields_set` to detect which fields were explicitly sent by the client (not `None` defaults). For form-data endpoints, use `@validate_form` which coerces form strings to bools/ints before validation.

### flasgger docstring template (OpenAPI 3.0)

```python
@some_bp.route('/path/<uuid:id>', methods=['POST'])
@login_required
def some_action(id):
    """
    Brief description of what this endpoint does.
    ---
    tags:
      - Category
    parameters:
      - in: path
        name: id
        type: string
        required: true
        description: Resource UUID
      - in: body
        name: body
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [field1]
              properties:
                field1:
                  type: string
                  example: "value"
    responses:
      200:
        description: Success
        content:
          application/json:
            schema:
              type: object
              properties:
                result:
                  type: string
      401:
        description: Unauthorized
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/Error'
    """
```

**Key difference**: Use OpenAPI 3.0 `content: application/json: schema:` (not Swagger 2.0 bare `schema:`). The `$ref` path is `#/components/schemas/Error` (not `#/definitions/Error`). This ensures `openapi-typescript` generates proper response body types instead of `content?: never`.

### SSE endpoint template

````python
"""
Brief description of the live stream.
---
tags:
  - SSE Streaming
parameters:
  - in: path
    name: id
    type: string
    required: true
produces:
  - text/event-stream
responses:
  200:
    description: |
      ## SSE Event Stream
      **Protocol:** Server-Sent Events, automatic browser reconnection
      **Event data format (JSON):**
      ```json
      {"key": "value"}
      ```
    content:
      text/event-stream:
        schema:
          type: string
          format: binary
  401:
    description: Unauthorized
"""
````
