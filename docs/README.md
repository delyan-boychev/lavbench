# LavBench Developer Documentation

## Quick Access

| Resource                         | URL                                  | Who                     |
| -------------------------------- | ------------------------------------ | ----------------------- |
| **Swagger UI** (REST + SSE docs) | `http://localhost:5001/apidoc/swagger/` | Backend & Frontend devs |
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

1. Create Pydantic v2 schemas in `backend/schemas/` for request validation (e.g., `schemas/admin.py`) and response serialization (e.g., `schemas/responses.py`)
2. Define the route in the appropriate `routes/*.py` file, decorating with `@api.validate(json=MyRequestSchema, resp=Response(HTTP_200=MyResponseSchema))`
3. Register the blueprint in `backend/app.py` (if new file)
4. Run `npm run generate-api-types` in `frontend/` to update TypeScript types
5. Run `npm run check-types` to verify 0 errors

For PATCH routes, use `json.model_fields_set` to detect which fields were explicitly sent by the client (not `None` defaults). For form-data endpoints, use `@api.validate(form=MyFormSchema, ...)`.

### Route template (spectree + Pydantic)

```python
from spectree import Response

@some_bp.route('/path/<uuid:id>', methods=['POST'])
@login_required
@api.validate(
    json=MyRequestSchema,
    resp=Response(HTTP_200=MyResponseSchema, HTTP_401=ErrorResponse),
    tags=["Category"],
    security=[{"cookieAuth": []}],
)
def some_action(id, json: MyRequestSchema):
    """Brief description of what this endpoint does."""
    # json is the validated MyRequestSchema instance
    ...
    return MyResponseSchema(...)
```

### SSE endpoint template

````python
@some_bp.route('/path/<uuid:id>/live', methods=['GET'])
@login_required
@api.validate(
    tags=["SSE Streaming"],
    security=[{"cookieAuth": []}],
    skip_validation=True,  # SSE responses bypass validation
)
def stream_some_event(id):
    """Brief description of the live stream."""
    def event_generator():
        ...
        yield f"data: {json.dumps(data)}\n\n"
    return sse_response(event_generator)
````
