"""HTTP-level fake of nanoColab /v1 that checks every exchange against the pinned OpenAPI."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from config import Config
from services import nanocolab_client

SPEC_PATH = Path(__file__).resolve().parent.parent / "contracts" / "nanocolab-v1.openapi.json"
SPEC: dict[str, Any] = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
_REGISTRY = Registry().with_resource("urn:nanocolab", Resource(SPEC, DRAFT202012))

API_URL = "https://nanocolab.test"
STORAGE_URL = "https://storage.nanocolab.test"
API_KEY = "ncak_testkey0_" + "s" * 40
IMMUTABLE_AFTER_PUBLISH = (
    "starts_at",
    "profile",
    "image_id",
    "asset_version",
    "max_attendance",
    "retention_days",
)
IMAGES = [
    {
        "image_id": "python-ml",
        "name": "Python ML (CPU)",
        "description": "pandas, scikit-learn and pyarrow",
        "digest": "registry.test/workspace-python-ml@sha256:" + "a" * 64,
        "packages": [{"name": "pandas", "version": "2.2.3"}],
        "default": True,
    },
    {
        "image_id": "python-base",
        "name": "Python",
        "description": "",
        "digest": "registry.test/workspace-python-base@sha256:" + "b" * 64,
        "packages": [],
        "default": False,
    },
]
PROFILES = [
    {"id": "cpu-compact", "name": "CPU Compact", "cpu_cores": 2, "memory_gib": 8},
    {"id": "cpu-standard", "name": "CPU Standard", "cpu_cores": 2, "memory_gib": 12},
]


def schema_validator(pointer: str) -> Draft202012Validator:
    return Draft202012Validator({"$ref": f"urn:nanocolab#{pointer}"}, registry=_REGISTRY)


def _operation(template: str, method: str) -> dict[str, Any]:
    operation: dict[str, Any] = SPEC["paths"][template][method.lower()]
    return operation


def _json_schema_pointer(template: str, method: str, where: str) -> str:
    escaped = template.replace("~", "~0").replace("/", "~1")
    return f"/paths/{escaped}/{method.lower()}/{where}/content/application~1json/schema"


def validate_request(template: str, method: str, body: Any) -> None:
    if "requestBody" not in _operation(template, method):
        assert body is None, f"{method} {template} takes no body"
        return
    pointer = _json_schema_pointer(template, method, "requestBody")
    schema_validator(pointer).validate(body)


def validate_response(template: str, method: str, status: int, body: Any) -> None:
    responses = _operation(template, method)["responses"]
    assert str(status) in responses, f"{method} {template} never answers {status}"
    if "application/json" not in responses[str(status)].get("content", {}):
        return
    pointer = _json_schema_pointer(template, method, f"responses/{status}")
    schema_validator(pointer).validate(body)


ROUTES = [
    ("GET", "/v1/images"),
    ("POST", "/v1/assets/{version}/uploads"),
    ("POST", "/v1/assets/{version}/complete"),
    ("GET", "/v1/assets/{version}"),
    ("PUT", "/v1/events/{external_id}"),
    ("GET", "/v1/events/{external_id}/readiness"),
    ("PUT", "/v1/events/{external_id}/workspaces/{external_user_id}"),
    ("POST", "/v1/workspaces/{workspace_id}/launch"),
    ("GET", "/v1/events"),
    ("POST", "/v1/events/{external_id}/cancel"),
    ("POST", "/v1/workspaces/{workspace_id}/export/metadata"),
    ("POST", "/v1/workspaces/{workspace_id}/export/raw"),
]


def _match(method: str, path: str) -> tuple[str, dict[str, str]] | None:
    for route_method, template in ROUTES:
        if route_method != method:
            continue
        pattern = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", template)
        found = re.fullmatch(pattern, path)
        if found:
            return template, found.groupdict()
    return None


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


class FakeNanoColab(requests.adapters.BaseAdapter):
    """Answers the client like nanoColab /v1 would, keeping state in memory."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, str]] = []
        self.assets: dict[str, dict[str, Any]] = {}
        self.events: dict[str, dict[str, Any]] = {}
        self.workspaces: dict[str, dict[str, Any]] = {}
        self.uploads: dict[str, bytes] = {}
        self.complete_state = "READY"
        self.complete_error: str | None = None
        self.readiness: dict[str, Any] = {
            "status": "READY",
            "message": "Workspaces are ready.",
            "retry_after_seconds": 10,
        }
        self.failures: dict[tuple[str, str], tuple[int, Any, dict[str, str]]] = {}
        # Workspace files by (workspace_id, path); ``raw_body`` overrides what export/raw sends
        self.files: dict[tuple[str, str], bytes] = {}
        self.raw_body: bytes | None = None
        # Every export request as (workspace_id, body), to check what LavBench asked for
        self.export_requests: list[tuple[str, dict[str, Any]]] = []
        self.profiles: list[dict[str, Any]] = [dict(p) for p in PROFILES]

    def fail(
        self,
        method: str,
        template: str,
        status: int,
        detail: Any,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Make the next calls to one route fail with this status and detail."""
        self.failures[(method, template)] = (status, detail, headers or {})

    def close(self) -> None:
        return None

    def send(self, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        parts = urlsplit(request.url or "")
        if f"{parts.scheme}://{parts.netloc}" == STORAGE_URL:
            return self._storage_put(request, parts.path.rsplit("/", 1)[-1])
        assert request.headers.get("Authorization") == f"Bearer {API_KEY}"
        method = request.method or ""
        matched = _match(method, parts.path)
        assert matched, f"the client called an unknown route: {method} {parts.path}"
        template, params = matched
        body = json.loads(request.body) if request.body else None
        validate_request(template, method, body)
        self.calls.append((method, template))
        if "/export" in template:
            self.export_requests.append((params["workspace_id"], body))
        if template == "/v1/workspaces/{workspace_id}/export/raw" and (
            (method, template) not in self.failures
        ):
            return self._raw_export(request, params["workspace_id"], body)
        if (method, template) in self.failures:
            status, detail, headers = self.failures[(method, template)]
            payload: Any = {"detail": detail}
            # Tests may inject statuses the spec does not list, such as a proxy's 502
            if str(status) in _operation(template, method)["responses"]:
                validate_response(template, method, status, payload)
        else:
            status, payload = self._handle(method, template, params, body)
            headers = {}
            validate_response(template, method, status, payload)
        return self._response(request, status, payload, headers)

    def _response(
        self,
        request: requests.PreparedRequest,
        status: int,
        payload: Any,
        headers: dict[str, str],
    ) -> requests.Response:
        response = requests.Response()
        response.status_code = status
        response.request = request
        response.url = request.url or ""
        response.headers.update({"Content-Type": "application/json", **headers})
        response._content = json.dumps(payload).encode() if payload is not None else b""
        return response

    def _storage_put(self, request: requests.PreparedRequest, version: str) -> requests.Response:
        assert "Authorization" not in request.headers
        body = request.body
        if hasattr(body, "read"):
            data = b"".join(iter(lambda: body.read(1024 * 1024), b""))
        else:
            data = body
        assert isinstance(data, bytes)
        asset = self.assets[version]
        assert hashlib.sha256(data).hexdigest() == asset["sha256"]
        assert len(data) == asset["size_bytes"]
        self.uploads[version] = data
        asset["uploaded"] = True
        return self._response(request, 204, None, {})

    def _asset(self, version: str) -> dict[str, Any]:
        asset = self.assets[version]
        result: dict[str, Any] = {
            "version": version,
            "state": asset["state"],
            "error": asset.get("error"),
            "size_bytes": asset["size_bytes"],
            "file_count": None,
            "upload": None,
        }
        if asset["state"] == "UPLOADING":
            result["upload"] = {
                "url": f"{STORAGE_URL}/{version}",
                "method": "PUT",
                "auth": "none",
                "headers": {"Content-Type": "application/zip"},
                "resumable": False,
            }
        return result

    def _event_response(self, external_id: str) -> dict[str, Any]:
        event = self.events[external_id]
        return {
            "event_id": str(uuid.uuid5(uuid.NAMESPACE_URL, external_id)),
            "external_id": external_id,
            "name": event["name"],
            "state": "SCHEDULED" if event.get("published_at") else "DRAFT",
            "starts_at": event["starts_at"],
            "planned_ends_at": event["planned_ends_at"],
            "effective_ends_at": event["ends_at"],
            "published_at": event.get("published_at"),
            "max_attendance": event["max_attendance"],
            "export_paths": event.get("export_paths", []),
            "image_id": event["image_id"],
            "environment_digest": next(
                i["digest"] for i in IMAGES if i["image_id"] == event["image_id"]
            ),
            "cancelled_at": event.get("cancelled_at"),
        }

    def _handle(
        self, method: str, template: str, params: dict[str, str], body: Any
    ) -> tuple[int, Any]:
        if template == "/v1/images":
            return 200, {"images": IMAGES, "profiles": self.profiles}
        if template == "/v1/assets/{version}/uploads":
            version = params["version"]
            if version in self.assets and self.assets[version]["state"] != "UPLOADING":
                return 200, self._asset(version)
            self.assets[version] = {
                "state": "UPLOADING",
                "sha256": body["sha256"],
                "size_bytes": body["size_bytes"],
            }
            return 200, self._asset(version)
        if template == "/v1/assets/{version}/complete":
            asset = self.assets.get(params["version"])
            if asset is None:
                return 404, {"detail": "Asset not found"}
            if not asset.get("uploaded"):
                return 409, {"detail": "The ZIP has not been uploaded"}
            asset.update(state=self.complete_state, error=self.complete_error)
            return 202, self._asset(params["version"])
        if template == "/v1/assets/{version}":
            if params["version"] not in self.assets:
                return 404, {"detail": "Asset not found"}
            return 200, self._asset(params["version"])
        if template == "/v1/events/{external_id}":
            return self._put_event(params["external_id"], body)
        if template == "/v1/events/{external_id}/readiness":
            event = self.events.get(params["external_id"])
            if event is None:
                return 404, {"detail": "Event not found"}
            if not event.get("published_at"):
                return 200, {
                    "status": "PREPARING",
                    "message": "The event is not published.",
                    "retry_after_seconds": 10,
                    "capacity": None,
                }
            return 200, {**self.readiness, "capacity": None}
        if template == "/v1/events/{external_id}/workspaces/{external_user_id}":
            return self._ensure_workspace(params["external_id"], params["external_user_id"])
        if template == "/v1/events" and method == "GET":
            return 200, {"events": [self._event_response(e) for e in sorted(self.events)]}
        if template == "/v1/events/{external_id}/cancel":
            event = self.events.get(params["external_id"])
            if event is None:
                return 404, {"detail": "Event not found"}
            event.setdefault("cancelled_at", _iso(datetime.now(UTC)))
            return 200, self._event_response(params["external_id"])
        if template == "/v1/workspaces/{workspace_id}/export/metadata":
            workspace = self._export_workspace(params["workspace_id"], body)
            if workspace is None:
                return 404, {"detail": "Workspace not found"}
            result: dict[str, Any] = {
                "workspace_id": params["workspace_id"],
                "source": "LIVE",
                "path": body["path"],
            }
            data = self.files.get((params["workspace_id"], body["path"]))
            if data is None:
                return 200, {**result, "status": "MISSING"}
            return 200, {
                **result,
                "status": "OK",
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "modified_at": _iso(datetime.now(UTC)),
            }
        if template == "/v1/workspaces/{workspace_id}/launch":
            workspace = self.workspaces.get(params["workspace_id"])
            if workspace is None or workspace["external_user_id"] != body["external_user_id"]:
                return 404, {"detail": "Workspace not found"}
            expires = datetime.now(UTC) + timedelta(seconds=60)
            return 200, {
                "launch_url": "https://hub.nanocolab.test/hub/launch",
                "launch_token": uuid.uuid4().hex,
                "expires_at": _iso(expires),
            }
        raise AssertionError(f"unhandled {method} {template}")

    def _export_workspace(self, workspace_id: str, body: dict[str, Any]) -> dict[str, Any] | None:
        workspace = self.workspaces.get(workspace_id)
        if workspace is None or workspace["external_user_id"] != body["external_user_id"]:
            return None
        return workspace

    def _raw_export(
        self, request: requests.PreparedRequest, workspace_id: str, body: dict[str, Any]
    ) -> requests.Response:
        template = "/v1/workspaces/{workspace_id}/export/raw"
        if self._export_workspace(workspace_id, body) is None:
            return self._response(request, 404, {"detail": "Workspace not found"}, {})
        data = self.files.get((workspace_id, body["path"]))
        if data is None:
            detail = {"detail": "The file does not exist in the workspace"}
            validate_response(template, "POST", 404, detail)
            return self._response(request, 404, detail, {})
        digest = base64.b64encode(hashlib.sha256(data).digest()).decode()
        response = requests.Response()
        response.status_code = 200
        response.request = request
        response.url = request.url or ""
        response.headers.update(
            {
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(data)),
                "Repr-Digest": f"sha-256=:{digest}:",
                "X-Export-Source": "LIVE",
            }
        )
        response._content = data if self.raw_body is None else self.raw_body
        response._content_consumed = True
        return response

    def put_file(self, workspace_id: str, path: str, data: bytes) -> None:
        self.files[(workspace_id, path)] = data

    def _put_event(self, external_id: str, body: dict[str, Any]) -> tuple[int, Any]:
        if body["image_id"] not in {i["image_id"] for i in IMAGES}:
            return 422, {"detail": "Unknown workspace image"}
        current = self.events.get(external_id)
        if current and current.get("cancelled_at"):
            return 409, {"detail": "The event was cancelled"}
        if current and current.get("published_at"):
            if not body.get("published"):
                return 409, {"detail": "A published event cannot be unpublished"}
            conflicts = [k for k in IMMUTABLE_AFTER_PUBLISH if body.get(k) != current.get(k)]
            if _parse(body["ends_at"]) < _parse(current["ends_at"]):
                conflicts.append("ends_at")
            if conflicts:
                return 409, {
                    "detail": {
                        "message": "These fields cannot change after the event is published",
                        "fields": conflicts,
                    }
                }
            current.update(
                name=body["name"],
                export_paths=body.get("export_paths", []),
                ends_at=body["ends_at"],
                extension_reason=body.get("extension_reason"),
            )
            return 200, self._event_response(external_id)
        event = {**body, "planned_ends_at": body["ends_at"]}
        if body.get("published"):
            event["published_at"] = _iso(datetime.now(UTC))
        self.events[external_id] = event
        return (200 if current else 201), self._event_response(external_id)

    def _ensure_workspace(self, external_id: str, external_user_id: str) -> tuple[int, Any]:
        event = self.events.get(external_id)
        if event is None:
            return 404, {"detail": "Event not found"}
        workspace_id = hashlib.sha256(f"{external_id}\n{external_user_id}".encode()).hexdigest()
        existing = self.workspaces.get(workspace_id)
        if existing is None:
            now = datetime.now(UTC)
            if not _parse(event["starts_at"]) <= now < _parse(event["ends_at"]):
                return 409, {"detail": "Official workspace is outside the competition window"}
            count = sum(1 for w in self.workspaces.values() if w["external_id"] == external_id)
            if count >= event["max_attendance"]:
                return 409, {"detail": "The event has reached its maximum attendance"}
            existing = {
                "external_id": external_id,
                "external_user_id": external_user_id,
                "requested_at": _iso(now),
            }
            self.workspaces[workspace_id] = existing
            status = 201
        else:
            status = 200
        return status, {
            "workspace_id": workspace_id,
            "event_id": str(uuid.uuid5(uuid.NAMESPACE_URL, external_id)),
            "external_user_id": external_user_id,
            "kind": "OFFICIAL",
            "state": "REQUESTED",
            "requested_at": existing["requested_at"],
            "stopped_at": None,
            "archive_id": None,
        }


def install(monkeypatch: Any, tmp_path: Path) -> FakeNanoColab:
    """Point the client at a fresh fake, with a key file and a temporary upload folder."""
    fake = FakeNanoColab()
    key_file = tmp_path / "nanocolab.key"
    key_file.write_text(API_KEY + "\n", encoding="utf-8")
    monkeypatch.setattr(Config, "NANOCOLAB_API_URL", API_URL)
    monkeypatch.setattr(Config, "NANOCOLAB_API_KEY_FILE", str(key_file))
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))

    def session() -> requests.Session:
        new = requests.Session()
        new.mount("https://", fake)
        new.mount("http://", fake)
        return new

    monkeypatch.setattr(nanocolab_client, "_new_session", session)
    return fake
