"""OpenAPI spec consistency — guards contracts the frontend api.d.ts depends on.

The generated `frontend/src/types/api.d.ts` is derived from this spec. If a
path or a nullable field regresses, `tsc --noEmit` against the committed file
would still pass, so these tests pin the contracts the type pipeline relies on.
"""

from __future__ import annotations

from typing import Any

SSE_PATHS = (
    "/api/admin/backups/live",
    "/api/admin/workers/stats/live",
    "/api/admin/submissions/queue/live",
    "/api/challenges/{challenge_id}/leaderboard/live",
    "/api/submissions/{submission_id}/logs/live",
    "/api/tasks/{task_id}/submissions/live",
    "/api/worker-status/live",
)

QUEUE_KILL_PATHS = (
    "/api/admin/submissions/queue",
    "/api/admin/submissions/queue/clear",
    "/api/admin/submissions/queue/live",
    "/api/submissions/{submission_id}/kill",
)


def _get_spec(client: Any) -> dict[str, Any]:
    resp = client.get("/apidoc/openapi.json")
    assert resp.status_code == 200
    return resp.get_json()


def test_spec_contains_credentials_route(client: Any) -> None:
    spec = _get_spec(client)
    methods = spec["paths"]["/api/admin/challenges/{challenge_id}/credentials"]
    assert "get" in methods


def test_spec_contains_queue_and_kill_paths(client: Any) -> None:
    spec = _get_spec(client)
    for path in QUEUE_KILL_PATHS:
        assert path in spec["paths"], f"missing path {path}"


def test_import_competitors_csv_has_multipart_request_body(client: Any) -> None:
    spec = _get_spec(client)
    op = spec["paths"]["/api/admin/import-competitors-csv"]["post"]
    content = op["requestBody"]["content"]
    assert "multipart/form-data" in content, "CSV import must be documented as multipart"
    schema = content["multipart/form-data"]["schema"]
    assert "$ref" in schema, "challenge_id form schema must be resolvable"
    ref_name = schema["$ref"].split("/")[-1]
    props = spec["components"]["schemas"][ref_name]["properties"]
    assert "challenge_id" in props, "challenge_id form field must be in the request schema"


def test_validation_error_model_is_error_response(client: Any) -> None:
    spec = _get_spec(client)
    op = spec["paths"]["/api/admin/backups"]["get"]
    schema = op["responses"]["422"]["content"]["application/json"]["schema"]
    assert schema.get("type") != "array", (
        "implicit 422 must use ErrorResponse, not spectree's default ValidationError array"
    )
    if "properties" in schema:
        assert {"code", "error"}.issubset(schema["properties"]), (
            "implicit 422 must follow the ErrorResponse shape (code, error)"
        )


def test_spec_contains_all_sse_live_endpoints(client: Any) -> None:
    spec = _get_spec(client)
    for path in SSE_PATHS:
        assert path in spec["paths"], f"missing SSE path {path}"


def test_audit_log_response_nullable_fields(client: Any) -> None:
    spec = _get_spec(client)
    schemas = spec["components"]["schemas"]
    audit = next((name for name in schemas if name.endswith(".AuditLogResponse")), None)
    assert audit is not None, "AuditLogResponse schema missing from spec"
    props = schemas[audit]["properties"]
    for field in ("admin_id", "action_type", "target_type"):
        any_of = props[field].get("anyOf", [])
        assert any(entry.get("type") == "null" for entry in any_of), (
            f"AuditLogResponse.{field} must be nullable"
        )
