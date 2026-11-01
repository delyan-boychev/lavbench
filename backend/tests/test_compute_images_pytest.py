"""Workspace image catalogue: listing, choosing and locking a stage's notebook environment."""

import json
from typing import Any, ClassVar

import pytest
import requests

from config import Config
from models import StageCompute
from services.nanocolab_client import NanoColabClient, NanoColabError, NanoColabUnavailableError
from tests.helpers.nanocolab_fake import CATALOGUE, DIGEST, FakeNanoColab, add_task, install


@pytest.fixture
def nanocolab(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    db_session: Any,
    sample_challenge: Any,
    sample_stage: Any,
) -> FakeNanoColab:
    fake = FakeNanoColab()
    install(monkeypatch, fake)
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path))
    add_task(db_session, sample_challenge, sample_stage, str(tmp_path))
    db_session.commit()
    return fake


def compute_body(**changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "enabled": True,
        "published": False,
        "compute_kind": "CPU",
        "cpu_cores": 1,
        "memory_gib": 2,
        "disk_gib": 10,
        "gpu_type": None,
        "image_id": "python-ml",
        "max_attendance": 5,
        "retention_days": 1,
    }
    body.update(changes)
    return body


def put_compute(
    client: Any, challenge: Any, stage: Any, headers: dict[str, str], **changes: Any
) -> Any:
    return client.put(
        f"/api/challenges/{challenge.id}/stages/{stage.id}/compute",
        data=json.dumps(compute_body(**changes)),
        content_type="application/json",
        headers=headers,
    )


def images_url(challenge: Any) -> str:
    return f"/api/challenges/{challenge.id}/compute/images"


def test_admin_lists_catalogue(client, sample_challenge, tokens, auth_headers, nanocolab):
    res = client.get(images_url(sample_challenge), headers=auth_headers(tokens.admin))
    assert res.status_code == 200
    images = res.get_json()["images"]
    assert [image["image_id"] for image in images] == ["python-ml", "python-base"]
    assert images[0]["packages"] == [{"name": "pandas", "version": "2.2.3"}]
    assert images[0]["default"] is True


def test_competitor_cannot_list_catalogue(
    client, sample_challenge, tokens, auth_headers, nanocolab
):
    res = client.get(images_url(sample_challenge), headers=auth_headers(tokens.competitor))
    assert res.status_code == 403
    assert nanocolab.catalogue_calls == 0


def test_catalogue_requires_login(client, sample_challenge, nanocolab):
    assert client.get(images_url(sample_challenge)).status_code == 401
    assert nanocolab.catalogue_calls == 0


def test_catalogue_unavailable_when_not_configured(
    client, sample_challenge, tokens, auth_headers, monkeypatch
):
    monkeypatch.setattr(Config, "NANOCOLAB_API_URL", "")
    res = client.get(images_url(sample_challenge), headers=auth_headers(tokens.admin))
    assert res.status_code == 503
    assert res.get_json()["code"] == "ERR_COMPUTE_UNAVAILABLE"


@pytest.mark.parametrize("failure", [NanoColabUnavailableError(503), NanoColabError(401)])
def test_catalogue_unavailable_when_nanocolab_fails(
    client, sample_challenge, tokens, auth_headers, nanocolab, failure
):
    nanocolab.catalogue = failure
    res = client.get(images_url(sample_challenge), headers=auth_headers(tokens.admin))
    assert res.status_code == 503
    assert res.get_json()["code"] == "ERR_COMPUTE_UNAVAILABLE"


def test_save_sends_image_id_and_records_pinned_digest(
    client, db_session, sample_challenge, sample_stage, tokens, csrf_headers, nanocolab
):
    res = put_compute(client, sample_challenge, sample_stage, csrf_headers(tokens.admin))
    assert res.status_code == 200
    assert res.get_json()["image_id"] == "python-ml"
    assert res.get_json()["image_digest"] == DIGEST
    assert nanocolab.events[-1]["image_id"] == "python-ml"
    assert "environment_digest" not in nanocolab.events[-1]
    stored = db_session.get(StageCompute, sample_stage.id)
    assert stored.image_id == "python-ml"
    assert stored.image_digest == DIGEST


def test_save_refuses_image_missing_from_catalogue(
    client, db_session, sample_challenge, sample_stage, tokens, csrf_headers, nanocolab
):
    res = put_compute(
        client, sample_challenge, sample_stage, csrf_headers(tokens.admin), image_id="gpu-torch"
    )
    assert res.status_code == 400
    assert res.get_json()["code"] == "ERR_INVALID_WORKSPACE_IMAGE"
    assert db_session.get(StageCompute, sample_stage.id) is None
    assert nanocolab.events == []


@pytest.mark.parametrize(
    "image_id", ["", "Python-ML", DIGEST, "python ml", "python-ml\n", "x" * 64]
)
def test_save_refuses_missing_or_malformed_image(
    client, db_session, sample_challenge, sample_stage, tokens, csrf_headers, nanocolab, image_id
):
    res = put_compute(
        client, sample_challenge, sample_stage, csrf_headers(tokens.admin), image_id=image_id
    )
    assert res.status_code == 422
    assert res.get_json()["code"] == "ERR_INVALID_WORKSPACE_IMAGE"
    assert db_session.get(StageCompute, sample_stage.id) is None
    assert nanocolab.events == []


def test_save_refuses_raw_image_digest_field(
    client, sample_challenge, sample_stage, tokens, csrf_headers, nanocolab
):
    res = put_compute(
        client, sample_challenge, sample_stage, csrf_headers(tokens.admin), image_digest=DIGEST
    )
    assert res.status_code == 422
    assert nanocolab.events == []


def test_save_fails_closed_when_catalogue_unreachable(
    client, db_session, sample_challenge, sample_stage, tokens, csrf_headers, nanocolab
):
    nanocolab.catalogue = NanoColabUnavailableError(503)
    res = put_compute(client, sample_challenge, sample_stage, csrf_headers(tokens.admin))
    assert res.status_code == 503
    assert db_session.get(StageCompute, sample_stage.id) is None
    assert nanocolab.events == []


def test_disabled_compute_needs_no_image(
    client, sample_challenge, sample_stage, tokens, csrf_headers, nanocolab
):
    res = put_compute(
        client,
        sample_challenge,
        sample_stage,
        csrf_headers(tokens.admin),
        enabled=False,
        image_id="",
    )
    assert res.status_code == 200
    assert nanocolab.catalogue_calls == 0


def test_published_stage_cannot_change_image(
    client, sample_challenge, sample_stage, tokens, csrf_headers, nanocolab
):
    headers = csrf_headers(tokens.admin)
    assert (
        put_compute(client, sample_challenge, sample_stage, headers, published=True).status_code
        == 200
    )
    calls = nanocolab.catalogue_calls
    res = put_compute(
        client, sample_challenge, sample_stage, headers, published=True, image_id="python-base"
    )
    assert res.status_code == 409
    assert res.get_json()["code"] == "ERR_STAGE_COMPUTE_LOCKED"
    assert nanocolab.catalogue_calls == calls
    assert nanocolab.events[-1]["image_id"] == "python-ml"


def test_published_stage_resyncs_after_image_is_retired(
    client, sample_challenge, sample_stage, tokens, csrf_headers, nanocolab
):
    headers = csrf_headers(tokens.admin)
    assert (
        put_compute(client, sample_challenge, sample_stage, headers, published=True).status_code
        == 200
    )
    nanocolab.catalogue = {"images": []}
    res = client.post(
        f"/api/challenges/{sample_challenge.id}/stages/{sample_stage.id}/compute/sync",
        headers=headers,
    )
    assert res.status_code == 200
    assert nanocolab.events[-1]["image_id"] == "python-ml"


def test_client_lists_images_with_bearer_key(monkeypatch):
    calls: list[dict[str, Any]] = []

    class Reply:
        status_code = 200
        headers: ClassVar[dict[str, str]] = {}

        def json(self) -> dict[str, Any]:
            return CATALOGUE

    def fake_request(method: str, url: str, **kwargs: Any) -> Reply:
        calls.append({"method": method, "url": url, **kwargs})
        return Reply()

    monkeypatch.setattr(requests, "request", fake_request)
    client = NanoColabClient("http://nanocolab.test", "ncak_test0000_" + "k" * 40, 5.0)
    assert client.list_images() == CATALOGUE
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == "http://nanocolab.test/v1/images"
    assert calls[0]["headers"]["Authorization"].startswith("Bearer ncak_")
    assert calls[0]["allow_redirects"] is False


def test_client_retries_catalogue_on_gateway_errors(monkeypatch):
    statuses = [503, 200]

    class Reply:
        def __init__(self, status: int) -> None:
            self.status_code = status
            self.headers: dict[str, str] = {}

        def json(self) -> dict[str, Any]:
            return CATALOGUE if self.status_code == 200 else {"detail": "down"}

    monkeypatch.setattr(requests, "request", lambda method, url, **kwargs: Reply(statuses.pop(0)))
    monkeypatch.setattr("services.nanocolab_client.time.sleep", lambda seconds: None)
    client = NanoColabClient("http://nanocolab.test", "ncak_test0000_" + "k" * 40, 5.0)
    assert client.list_images() == CATALOGUE
    assert statuses == []
