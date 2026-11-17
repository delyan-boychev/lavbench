"""Contract tests: the client and the fake both follow the pinned nanoColab /v1 OpenAPI."""

import hashlib

import pytest
import requests

from config import Config
from services import nanocolab_client
from services.nanocolab_client import (
    NanoColabClient,
    NanoColabError,
    NanoColabUnavailableError,
    detail_message,
    url_allowed,
)
from tests.helpers.nanocolab_fake import (
    ROUTES,
    SPEC,
    SPEC_PATH,
    STORAGE_URL,
    install,
    schema_validator,
    validate_response,
)

# The spec is docs/api/nanocolab-v1.openapi.json of nano-colab fix/lavbench-integration
PINNED_COMMIT = "5cb1e0f5d16d937566c846474ebf9b4a39137f0b"
PINNED_SHA256 = "3da05e3dd1ab41a35acb32f4a0a7ff9826f653cd56e38a9b5e0db047a0f372bd"


@pytest.fixture
def fake(monkeypatch, tmp_path):
    return install(monkeypatch, tmp_path)


@pytest.fixture
def client(fake):
    built = NanoColabClient.from_config()
    assert built is not None
    return built


def test_vendored_spec_is_the_pinned_file():
    assert hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest() == PINNED_SHA256
    assert SPEC["info"]["version"] == "1.0.0"


def test_every_route_the_fake_serves_is_in_the_spec():
    for method, template in ROUTES:
        assert method.lower() in SPEC["paths"][template]


def test_full_client_flow_matches_the_spec(fake, client, tmp_path):
    catalog = client.catalog()
    assert catalog["images"][0]["image_id"] == "python-ml"
    assert catalog["profiles"] is None

    package = tmp_path / "package.zip"
    package.write_bytes(b"PK" + b"\0" * 64)
    sha = hashlib.sha256(package.read_bytes()).hexdigest()
    sent = []
    started = client.start_asset_upload("lb-abc-v1", package.stat().st_size, sha)
    client.upload_asset(started["upload"], str(package), sent.append)
    assert sent[-1] == package.stat().st_size
    asset = client.complete_asset_upload("lb-abc-v1")
    assert asset["state"] == "READY"
    assert client.get_asset("lb-abc-v1")["state"] == "READY"

    payload = {
        "name": "Olympiad - Round 1",
        "starts_at": "2026-11-16T08:00:00+00:00",
        "ends_at": "2099-11-16T12:03:00+00:00",
        "profile": {
            "compute_kind": "CPU",
            "cpu_cores": 2,
            "memory_gib": 8,
            "disk_gib": 10,
            "gpu_type": None,
        },
        "image_id": "python-ml",
        "asset_version": "lb-abc-v1",
        "max_attendance": 3,
        "retention_days": 30,
        "published": True,
        "export_paths": ["image-classification/solution.ipynb"],
        "actor": "lavbench-sync",
    }
    event = client.put_event("stage-1", payload)
    assert event["environment_digest"].endswith("a" * 64)
    assert client.get_readiness("stage-1")["status"] == "READY"
    workspace = client.ensure_workspace("stage-1", "0192aaaa-bbbb-7ccc-8ddd-eeeeffff0000")
    launch = client.launch(workspace["workspace_id"], "0192aaaa-bbbb-7ccc-8ddd-eeeeffff0000")
    assert launch["launch_token"]
    assert {call[1] for call in fake.calls} == {template for _, template in ROUTES}


@pytest.mark.parametrize(
    ("detail", "message"),
    [
        ("Unknown workspace image", "Unknown workspace image"),
        (
            {"message": "These fields cannot change after the event is published", "fields": ["x"]},
            "These fields cannot change after the event is published (x)",
        ),
        (
            [{"loc": ["body", "max_attendance"], "msg": "too small", "type": "x"}],
            "max_attendance: too small",
        ),
    ],
)
def test_the_three_error_shapes_map_to_one_message(fake, client, detail, message):
    template = "/v1/events/{external_id}"
    status = 422 if isinstance(detail, list) else 409
    validate_response(template, "PUT", status, {"detail": detail})
    fake.fail("PUT", template, status, detail)
    with pytest.raises(NanoColabError) as raised:
        client.put_event("stage-1", _minimal_event())
    assert raised.value.status == status
    assert raised.value.message == message
    assert detail_message(detail) == message


def test_retry_after_is_kept_and_not_slept_on(fake, client, monkeypatch):
    monkeypatch.setattr(nanocolab_client.time, "sleep", lambda _s: pytest.fail("slept"))
    fake.fail(
        "PUT",
        "/v1/events/{external_id}/workspaces/{external_user_id}",
        503,
        "Preparing",
        {"Retry-After": "30"},
    )
    with pytest.raises(NanoColabUnavailableError) as raised:
        client.ensure_workspace("stage-1", "user-1")
    assert raised.value.retry_after == 30


def test_5xx_without_retry_after_is_retried(fake, client, monkeypatch):
    sleeps = []
    monkeypatch.setattr(nanocolab_client.time, "sleep", sleeps.append)
    fake.fail("GET", "/v1/events/{external_id}/readiness", 503, "busy")
    with pytest.raises(NanoColabUnavailableError):
        client.get_readiness("stage-1")
    assert sleeps == list(nanocolab_client.RETRY_DELAYS)


def test_launch_is_never_retried(fake, client, monkeypatch):
    monkeypatch.setattr(nanocolab_client.time, "sleep", lambda _s: pytest.fail("slept"))
    fake.fail("POST", "/v1/workspaces/{workspace_id}/launch", 503, "busy")
    with pytest.raises(NanoColabUnavailableError):
        client.launch("a" * 64, "user-1")
    assert len(fake.calls) == 1


def test_redirects_are_errors(fake, client):
    fake.fail("GET", "/v1/images", 302, "moved")
    with pytest.raises(NanoColabError):
        client.catalog()


@pytest.mark.parametrize(
    ("url", "insecure", "allowed"),
    [
        ("https://storage.example/upload?sig=1", False, True),
        ("http://storage.example/upload", False, False),
        ("http://storage.example/upload", True, False),
        ("http://localhost:8090/v1/objects/x", False, False),
        ("http://localhost:8090/v1/objects/x", True, True),
        ("http://127.0.0.1:8090/v1/objects/x", True, True),
        ("https://user:pw@storage.example/x", False, False),
        ("ftp://storage.example/x", True, False),
    ],
)
def test_url_rules(url, insecure, allowed):
    assert url_allowed(url, insecure) is allowed


def test_upload_refuses_plain_http_and_credentials(client, tmp_path):
    package = tmp_path / "p.zip"
    package.write_bytes(b"x" * 30)
    with pytest.raises(NanoColabError):
        client.upload_asset({"url": "http://evil.example/x", "method": "PUT"}, str(package), print)
    with pytest.raises(NanoColabError):
        client.upload_asset(
            {"url": f"{STORAGE_URL}/x", "method": "PUT", "headers": {"Authorization": "x"}},
            str(package),
            print,
        )


def test_client_is_off_without_url_key_or_https(monkeypatch, tmp_path):
    install(monkeypatch, tmp_path)
    assert NanoColabClient.from_config() is not None
    monkeypatch.setattr(Config, "NANOCOLAB_API_KEY_FILE", str(tmp_path / "missing"))
    assert NanoColabClient.from_config() is None
    install(monkeypatch, tmp_path)
    monkeypatch.setattr(Config, "NANOCOLAB_API_URL", "http://nanocolab.example")
    assert NanoColabClient.from_config() is None
    monkeypatch.setattr(Config, "NANOCOLAB_API_URL", "")
    assert NanoColabClient.from_config() is None


def test_transport_errors_become_unavailable(monkeypatch, tmp_path):
    install(monkeypatch, tmp_path)

    class Broken(requests.adapters.BaseAdapter):
        def send(self, request, **kwargs):
            raise requests.ConnectionError("down")

        def close(self):
            return None

    def session():
        new = requests.Session()
        new.mount("https://", Broken())
        return new

    monkeypatch.setattr(nanocolab_client, "_new_session", session)
    monkeypatch.setattr(nanocolab_client.time, "sleep", lambda _s: None)
    built = NanoColabClient.from_config()
    with pytest.raises(NanoColabUnavailableError):
        built.catalog()


def test_error_schema_accepts_every_detail_shape():
    validator = schema_validator("/components/schemas/ErrorResponse")
    for detail in ("text", {"message": "m"}, [{"loc": [], "msg": "m"}]):
        validator.validate({"detail": detail})


def test_fake_storage_checks_hash(fake, client, tmp_path):
    package = tmp_path / "p.zip"
    package.write_bytes(b"y" * 40)
    started = client.start_asset_upload("lb-def-v1", 40, "0" * 64)
    with pytest.raises(AssertionError):
        client.upload_asset(started["upload"], str(package), lambda _n: None)
    assert "lb-def-v1" not in fake.uploads


def _minimal_event():
    return {
        "name": "Round",
        "starts_at": "2026-11-16T08:00:00+00:00",
        "ends_at": "2026-11-16T12:00:00+00:00",
        "profile": {"compute_kind": "CPU", "cpu_cores": 2, "memory_gib": 8, "disk_gib": 10},
        "image_id": "python-ml",
        "asset_version": "lb-abc-v1",
        "max_attendance": 3,
        "actor": "lavbench-sync",
    }
