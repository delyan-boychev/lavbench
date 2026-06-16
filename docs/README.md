# LavBench Developer Documentation

## Quick Access

| Resource | URL | Who |
|----------|-----|-----|
| **Swagger UI** (REST + SSE docs) | `http://localhost:5001/apidocs` | Backend & Frontend devs |
| **Health check** | `http://localhost:5001/api/health` | DevOps, monitoring |
| **Architecture overview** | [`ARCHITECTURE.md`](ARCHITECTURE.md) | New contributors |

## For Frontend Developers

### Generate TypeScript types from the API spec

```bash
cd frontend
npm run generate-api-types
```

This runs `openapi-typescript` against the live OpenAPI spec served by the backend, producing `src/types/api.d.ts` with full type definitions for all endpoints.

### Key things to know

- **Auth**: httpOnly cookie (`auth_token`). The `ApiService` wrapper sends cookies automatically. No manual token management needed.
- **SSE endpoints**: 6 streaming endpoints use Server-Sent Events. Connect with `new EventSource(url)`. Cookie auth is automatic.
- **Rate limiting**: Per-user, per-endpoint. Backend returns 429 with `ERR_RATE_LIMITED` code. Frontend should show a toast and throttle retries.
- **Error format**: All errors return `{"error": "message", "code": "ERR_CODE"}`. Map `code` values to user-facing translations where needed.

### Example: calling the login endpoint

```javascript
import api from './services/ApiService';

const { ok, data } = await api.post('/auth/login', {
  username: 'admin_1c15d4d7',
  password: hashedPassword
});
if (ok) {
  // data.user contains the user object
  // cookie is set automatically by the browser
}
```

## For Backend Developers

### Adding a new endpoint

1. Define the route in the appropriate `routes/*.py` file
2. Add a flasgger YAML docstring with request/response schemas
3. The Swagger UI at `/apidocs` auto-updates on next server restart
4. Run `npm run generate-api-types` in `frontend/` to update TypeScript types

### flasgger docstring template

```python
@some_bp.route('/path/<int:id>', methods=['POST'])
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
        type: integer
        required: true
        description: Resource ID
      - in: body
        name: body
        required: true
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
        schema:
          type: object
          properties:
            result:
              type: string
      401:
        description: Unauthorized
        schema:
          $ref: '#/definitions/Error'
    """
```

### SSE endpoint template

```python
"""
Brief description of the live stream.
---
tags:
  - SSE Streaming
parameters:
  - in: path
    name: id
    type: integer
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
    schema:
      type: string
      format: binary
  401:
    description: Unauthorized
"""
```
