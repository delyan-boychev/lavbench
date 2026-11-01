"""Stage task packages: building, uploading to nano-colab and locking task files after publish."""

import io
import json
import os
import zipfile
from typing import Any

import pytest
import requests

from config import Config
from models import StageCompute, Task
from services import stage_package
from services.nanocolab_client import NanoColabClient, NanoColabError, NanoColabUnavailableError
from tests.helpers.nanocolab_fake import NOTEBOOK, FakeNanoColab, add_task, install


@pytest.fixture
def uploads(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> str:
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path))
    return str(tmp_path)


@pytest.fixture
def nanocolab(monkeypatch: pytest.MonkeyPatch, uploads: str) -> FakeNanoColab:
    fake = FakeNanoColab()
    install(monkeypatch, fake)
    return fake


@pytest.fixture
def task(db_session: Any, sample_challenge: Any, sample_stage: Any, uploads: str) -> Task:
    created = add_task(db_session, sample_challenge, sample_stage, uploads, title="Regression")
    db_session.commit()
    return created


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


def compute_url(challenge: Any, stage: Any) -> str:
    return f"/api/challenges/{challenge.id}/stages/{stage.id}/compute"


def put_compute(
    client: Any, challenge: Any, stage: Any, headers: dict[str, str], **changes: Any
) -> Any:
    return client.put(
        compute_url(challenge, stage),
        data=json.dumps(compute_body(**changes)),
        content_type="application/json",
        headers=headers,
    )


def names_in(path: str) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        return archive.namelist()


def test_package_excludes_labels_and_keeps_baseline_name(db_session, sample_stage, task, uploads):
    entries = stage_package.package_entries(sample_stage)
    assert [entry.arcname for entry in entries] == [
        "task1/baseline_notebook.ipynb",
        "task1/train.csv",
    ]
    built = stage_package.build(entries, os.path.join(uploads, "packages"))
    assert names_in(built.path) == ["task1/baseline_notebook.ipynb", "task1/train.csv"]
    with zipfile.ZipFile(built.path) as archive:
        assert b"PAR1secret" not in b"".join(archive.read(name) for name in archive.namelist())
        assert archive.read("task1/baseline_notebook.ipynb") == NOTEBOOK
    assert built.version == f"lb-{built.sha256[:12]}-v1"


def test_package_is_deterministic(db_session, sample_stage, task, uploads):
    entries = stage_package.package_entries(sample_stage)
    first = stage_package.build(entries, os.path.join(uploads, "a"))
    second = stage_package.build(entries, os.path.join(uploads, "b"))
    assert first.sha256 == second.sha256
    with open(first.path, "rb") as one, open(second.path, "rb") as two:
        assert one.read() == two.read()
    with zipfile.ZipFile(first.path) as archive:
        for info in archive.infolist():
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert info.external_attr >> 16 == 0o100644


def test_package_changes_when_a_file_changes(db_session, sample_stage, task, uploads):
    before = stage_package.build(stage_package.package_entries(sample_stage), uploads)
    folder = os.path.join(uploads, f"task_{task.id}")
    with open(os.path.join(folder, "0_train.csv"), "wb") as handle:
        handle.write(b"id,x\n1,3\n")
    after = stage_package.build(stage_package.package_entries(sample_stage), uploads)
    assert before.version != after.version


def test_tasks_get_numbered_folders(db_session, sample_challenge, sample_stage, task, uploads):
    second = add_task(db_session, sample_challenge, sample_stage, uploads, title="Second")
    folders = stage_package.task_folders(sample_stage)
    assert folders == {str(task.id): "task1", str(second.id): "task2"}
    arcnames = [entry.arcname for entry in stage_package.package_entries(sample_stage)]
    assert "task2/train.csv" in arcnames


def test_failed_build_leaves_no_temporary_file(
    db_session, sample_stage, task, uploads, monkeypatch
):
    def broken(*args: Any, **kwargs: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(stage_package.shutil, "copyfileobj", broken)
    directory = os.path.join(uploads, "packages")
    with pytest.raises(OSError):
        stage_package.build(stage_package.package_entries(sample_stage), directory)
    assert os.listdir(directory) == []


def test_save_uploads_package_and_sends_its_version(
    client,
    db_session,
    sample_challenge,
    sample_stage,
    task,
    tokens,
    csrf_headers,
    nanocolab,
    uploads,
):
    res = put_compute(client, sample_challenge, sample_stage, csrf_headers(tokens.admin))
    assert res.status_code == 200
    body = res.get_json()
    version = body["asset_version"]
    assert version.startswith("lb-") and version.endswith("-v1")
    assert body["package_state"] == "READY"
    assert body["task_folders"] == {str(task.id): "task1"}
    assert nanocolab.events[-1]["asset_version"] == version
    assert nanocolab.package_names(version) == ["task1/baseline_notebook.ipynb", "task1/train.csv"]
    assert os.listdir(os.path.join(uploads, "stage_packages")) == []


def test_unchanged_files_are_not_uploaded_again(
    client, sample_challenge, sample_stage, task, tokens, csrf_headers, nanocolab
):
    headers = csrf_headers(tokens.admin)
    put_compute(client, sample_challenge, sample_stage, headers)
    uploaded = dict(nanocolab.uploads)
    nanocolab.uploads.clear()
    assert (
        put_compute(client, sample_challenge, sample_stage, headers, max_attendance=6).status_code
        == 200
    )
    assert nanocolab.uploads == {}
    assert nanocolab.events[-1]["asset_version"] == next(iter(uploaded))


def test_asset_version_cannot_be_typed(
    client, sample_challenge, sample_stage, task, tokens, csrf_headers, nanocolab
):
    res = put_compute(
        client, sample_challenge, sample_stage, csrf_headers(tokens.admin), asset_version="local-v1"
    )
    assert res.status_code == 422
    assert nanocolab.events == []


def test_validating_package_defers_event_until_ready(
    client, db_session, sample_challenge, sample_stage, task, tokens, csrf_headers, nanocolab
):
    nanocolab.complete_state = "QUEUED"
    headers = csrf_headers(tokens.admin)
    res = put_compute(client, sample_challenge, sample_stage, headers)
    assert res.status_code == 200
    assert res.get_json()["package_state"] == "VALIDATING"
    assert res.get_json()["sync_state"] == "PACKAGING"
    assert nanocolab.events == []
    version = res.get_json()["asset_version"]
    nanocolab.assets[version]["state"] = "READY"
    refreshed = client.get(compute_url(sample_challenge, sample_stage), headers=headers)
    assert refreshed.get_json()["package_state"] == "READY"
    assert refreshed.get_json()["sync_state"] == "SYNCED"
    assert nanocolab.events[-1]["asset_version"] == version


def test_publish_waits_for_package(
    client, db_session, sample_challenge, sample_stage, task, tokens, csrf_headers, nanocolab
):
    nanocolab.complete_state = "PROCESSING"
    res = put_compute(
        client, sample_challenge, sample_stage, csrf_headers(tokens.admin), published=True
    )
    assert res.status_code == 409
    assert res.get_json()["code"] == "ERR_STAGE_PACKAGE_NOT_READY"
    stored = db_session.get(StageCompute, sample_stage.id)
    assert stored.published is False
    assert nanocolab.events == []


def test_invalid_package_reports_validator_error(
    client, db_session, sample_challenge, sample_stage, task, tokens, csrf_headers, nanocolab
):
    nanocolab.complete_state = "FAILED"
    nanocolab.complete_error = "ZIP contains hidden, reserved or unsafe paths."
    res = put_compute(
        client, sample_challenge, sample_stage, csrf_headers(tokens.admin), published=True
    )
    assert res.status_code == 422
    assert res.get_json()["code"] == "ERR_STAGE_PACKAGE_INVALID"
    stored = db_session.get(StageCompute, sample_stage.id)
    assert stored.package_state == "FAILED"
    assert stored.package_error == "ZIP contains hidden, reserved or unsafe paths."
    assert stored.published is False
    assert nanocolab.events == []


def test_stage_without_task_files_cannot_package(
    client, db_session, sample_challenge, sample_stage, tokens, csrf_headers, nanocolab
):
    res = put_compute(client, sample_challenge, sample_stage, csrf_headers(tokens.admin))
    assert res.status_code == 422
    assert res.get_json()["code"] == "ERR_STAGE_PACKAGE_EMPTY"
    assert db_session.get(StageCompute, sample_stage.id).package_error == "ERR_STAGE_PACKAGE_EMPTY"
    assert nanocolab.uploads == {}


def test_upload_failure_fails_sync_and_cleans_up(
    client,
    db_session,
    sample_challenge,
    sample_stage,
    task,
    tokens,
    csrf_headers,
    nanocolab,
    uploads,
):
    nanocolab.upload_failure = NanoColabUnavailableError(503)
    res = put_compute(
        client, sample_challenge, sample_stage, csrf_headers(tokens.admin), published=True
    )
    assert res.status_code == 502
    assert db_session.get(StageCompute, sample_stage.id).published is False
    assert os.listdir(os.path.join(uploads, "stage_packages")) == []


def test_published_package_is_frozen(
    client,
    db_session,
    sample_challenge,
    sample_stage,
    task,
    tokens,
    csrf_headers,
    nanocolab,
    uploads,
):
    headers = csrf_headers(tokens.admin)
    version = put_compute(
        client, sample_challenge, sample_stage, headers, published=True
    ).get_json()["asset_version"]
    os.utime(os.path.join(uploads, f"task_{task.id}", "0_train.csv"), (1, 1))
    nanocolab.uploads.clear()
    res = client.post(f"{compute_url(sample_challenge, sample_stage)}/sync", headers=headers)
    assert res.status_code == 200
    assert res.get_json()["asset_version"] == version
    assert nanocolab.uploads == {}


def publish(client: Any, challenge: Any, stage: Any, headers: dict[str, str]) -> None:
    assert put_compute(client, challenge, stage, headers, published=True).status_code == 200


def test_files_of_published_stage_are_locked(
    client, sample_challenge, sample_stage, task, tokens, csrf_headers, nanocolab
):
    headers = csrf_headers(tokens.admin)
    publish(client, sample_challenge, sample_stage, headers)
    res = client.put(
        f"/api/tasks/{task.id}",
        data={"file0": (io.BytesIO(b"id\n1\n"), "extra.csv")},
        headers=headers,
        content_type="multipart/form-data",
    )
    assert res.status_code == 409
    assert res.get_json()["code"] == "ERR_TASK_FILES_LOCKED"


def test_baseline_and_deletions_are_locked_after_publish(
    client, sample_challenge, sample_stage, task, tokens, csrf_headers, nanocolab
):
    headers = csrf_headers(tokens.admin)
    publish(client, sample_challenge, sample_stage, headers)
    for data in (
        {"baseline_notebook": (io.BytesIO(NOTEBOOK), "new.ipynb")},
        {"deleted_files": json.dumps(["train.csv"])},
        {"delete_baseline": "true"},
        {"stage_id": ""},
    ):
        res = client.put(
            f"/api/tasks/{task.id}", data=data, headers=headers, content_type="multipart/form-data"
        )
        assert res.status_code == 409, data
        assert res.get_json()["code"] == "ERR_TASK_FILES_LOCKED"


def test_metadata_edits_stay_allowed_after_publish(
    client, db_session, sample_challenge, sample_stage, task, tokens, csrf_headers, nanocolab
):
    headers = csrf_headers(tokens.admin)
    publish(client, sample_challenge, sample_stage, headers)
    res = client.put(
        f"/api/tasks/{task.id}",
        data={"title": "Renamed task", "deleted_files": "[]"},
        headers=headers,
        content_type="multipart/form-data",
    )
    assert res.status_code == 200
    assert db_session.get(Task, task.id).title == "Renamed task"


def test_task_cannot_be_deleted_or_added_after_publish(
    client, sample_challenge, sample_stage, task, tokens, csrf_headers, nanocolab
):
    headers = csrf_headers(tokens.admin)
    publish(client, sample_challenge, sample_stage, headers)
    assert (
        client.delete(f"/api/tasks/{task.id}", headers=headers).get_json()["code"]
        == "ERR_TASK_FILES_LOCKED"
    )
    res = client.post(
        f"/api/challenges/{sample_challenge.id}/tasks",
        data={
            "title": "Late task",
            "stage_id": str(sample_stage.id),
            "baseline_notebook": (io.BytesIO(NOTEBOOK), "late.ipynb"),
        },
        headers=headers,
        content_type="multipart/form-data",
    )
    assert res.status_code == 409
    assert res.get_json()["code"] == "ERR_TASK_FILES_LOCKED"


def test_draft_stage_files_stay_editable(
    client, sample_challenge, sample_stage, task, tokens, csrf_headers, nanocolab
):
    headers = csrf_headers(tokens.admin)
    assert put_compute(client, sample_challenge, sample_stage, headers).status_code == 200
    res = client.put(
        f"/api/tasks/{task.id}",
        data={"deleted_files": json.dumps(["train.csv"])},
        headers=headers,
        content_type="multipart/form-data",
    )
    assert res.status_code == 200


class Reply:
    def __init__(self, status: int) -> None:
        self.status_code = status


def test_client_sends_key_only_to_its_own_host(monkeypatch, tmp_path):
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        requests, "put", lambda url, **kwargs: calls.append({"url": url, **kwargs}) or Reply(204)
    )
    path = tmp_path / "p.zip"
    path.write_bytes(b"PK")
    client = NanoColabClient("http://nanocolab.test", "ncak_test0000_" + "k" * 40, 5.0)
    client.upload_asset(
        {"url": "http://nanocolab.test/v1/assets/lb-a-v1/content", "auth": "api_key"}, str(path)
    )
    assert calls[-1]["headers"]["Authorization"].startswith("Bearer ncak_")
    assert calls[-1]["allow_redirects"] is False
    with pytest.raises(NanoColabError):
        client.upload_asset(
            {"url": "http://evil.test/v1/assets/x/content", "auth": "api_key"}, str(path)
        )
    with pytest.raises(NanoColabError):
        client.upload_asset(
            {"url": "http://nanocolab.test.evil.test/x", "auth": "api_key"}, str(path)
        )
    assert len(calls) == 1


def test_client_storage_upload_has_no_api_key(monkeypatch, tmp_path):
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        requests, "put", lambda url, **kwargs: calls.append({"url": url, **kwargs}) or Reply(200)
    )
    path = tmp_path / "p.zip"
    path.write_bytes(b"PK")
    client = NanoColabClient("http://nanocolab.test", "ncak_test0000_" + "k" * 40, 5.0)
    client.upload_asset(
        {"url": "https://storage.test/upload?session=abc", "auth": "none"}, str(path)
    )
    assert "Authorization" not in calls[-1]["headers"]
    with pytest.raises(NanoColabError):
        client.upload_asset({"url": "http://storage.test/upload", "auth": "none"}, str(path))
    assert len(calls) == 1


def test_client_upload_errors(monkeypatch, tmp_path):
    path = tmp_path / "p.zip"
    path.write_bytes(b"PK")
    client = NanoColabClient("http://nanocolab.test", "ncak_test0000_" + "k" * 40, 5.0)
    target = {"url": "http://nanocolab.test/v1/assets/lb-a-v1/content", "auth": "api_key"}
    monkeypatch.setattr(requests, "put", lambda url, **kwargs: Reply(409))
    with pytest.raises(NanoColabError) as rejected:
        client.upload_asset(target, str(path))
    assert rejected.value.status == 409

    def unreachable(url: str, **kwargs: Any) -> Reply:
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "put", unreachable)
    with pytest.raises(NanoColabUnavailableError):
        client.upload_asset(target, str(path))
