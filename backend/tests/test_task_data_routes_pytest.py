"""Tests for the streamed task data routes: data files and the Hugging Face ZIP."""

import hashlib
import io
import json
import os
import zipfile
from datetime import timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from config import Config
from models import AuditLog, Environment, Stage, Task, WorkspaceSetting
from services import hf_zip
from tests.helpers.hf import CONFIG, hf_zip_bytes
from utils.auth_utils import generate_token
from utils.dates import utcnow
from utils.uploads import incoming_dir


@pytest.fixture(autouse=True)
def _isolated(redis_flush, app, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, "UPLOAD_FOLDER", str(tmp_path))
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path))
    with patch("routes.task_data.schedule_baseline") as requeued:
        yield requeued


@pytest.fixture
def admin(tokens, csrf_headers):
    return csrf_headers(tokens.admin)


def _raw(headers, content_type="application/octet-stream"):
    return {**headers, "Content-Type": content_type}


def _put_zip(client, headers, task, data, content_type="application/zip"):
    return client.put(
        f"/api/tasks/{task.id}/hf-zip", data=data, headers=_raw(headers, content_type)
    )


def _task(db_session, challenge, title="BERT", folder="bert", mode="notebook", stage=None):
    task = Task(
        challenge_id=challenge.id,
        title=title,
        folder_name=folder,
        evaluation_mode=mode,
        stage_id=stage.id if stage else None,
    )
    db_session.add(task)
    db_session.commit()
    return task


def _environments_on(db_session, challenge):
    db_session.add(WorkspaceSetting(challenge_id=challenge.id, enabled=True, image_id="py"))
    db_session.commit()


def _publish(db_session, challenge):
    env = Environment(
        challenge_id=challenge.id,
        enabled=True,
        image_id="py",
        event_id="e1",
        published_at=utcnow() - timedelta(minutes=1),
    )
    db_session.add(env)
    db_session.commit()


# ── Hugging Face ZIP ──


def test_an_upload_records_the_zip_and_skips_hidden_entries(
    client, admin, db_session, sample_challenge, _isolated
):
    task = _task(db_session, sample_challenge)
    data = hf_zip_bytes()
    response = _put_zip(client, admin, task, data)
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    sha256 = hashlib.sha256(data).hexdigest()
    assert body["hf_zip_sha256"] == sha256
    assert body["hf_zip_size"] == len(data)
    assert body["hf_folders"] == ["models/acme/tiny"]
    assert (body["hf_file_count"], body["hf_unpacked_bytes"]) == (1, len(CONFIG))
    assert body["hf_skipped_count"] == 2
    assert body["hf_zip_not_imported"] is False
    assert os.path.isfile(hf_zip.hf_zip_path(sha256))
    assert not os.listdir(incoming_dir())
    entry = AuditLog.query.filter_by(target_type="task").one()
    assert entry.details["hf_zip"] == {"old_sha256": None, "new_sha256": sha256}
    _isolated.assert_called_once()


def test_competitors_see_the_folders_but_not_the_admin_fields(
    client, admin, tokens, csrf_headers, db_session, sample_challenge, sample_competitor
):
    task = _task(db_session, sample_challenge)
    assert _put_zip(client, admin, task, hf_zip_bytes()).status_code == 200
    view = client.get(f"/api/tasks/{task.id}", headers=csrf_headers(tokens.competitor))
    body = view.get_json()
    assert body["hf_folders"] == ["models/acme/tiny"]
    assert body["hf_zip_sha256"] is None
    assert body["hf_skipped_count"] is None


def test_a_replaced_zip_is_deleted_unless_another_task_uses_it(
    client, admin, db_session, sample_challenge
):
    first = _task(db_session, sample_challenge)
    second = _task(db_session, sample_challenge, title="Other", folder="other")
    old = hf_zip_bytes()
    old_sha = hashlib.sha256(old).hexdigest()
    assert _put_zip(client, admin, first, old).status_code == 200
    assert _put_zip(client, admin, second, old).status_code == 200
    new = hf_zip_bytes({"models/acme/tiny/config.json": b"{}"})
    assert _put_zip(client, admin, first, new).status_code == 200
    assert os.path.isfile(hf_zip.hf_zip_path(old_sha))
    removed = client.delete(f"/api/tasks/{second.id}/hf-zip", headers=admin)
    assert removed.status_code == 200
    assert removed.get_json()["hf_folders"] == []
    assert not os.path.exists(hf_zip.hf_zip_path(old_sha))


@pytest.mark.parametrize(
    ("data", "named"),
    [
        (hf_zip_bytes({"models/acme/config.json": b"x"}), "models/acme/config.json"),
        (hf_zip_bytes({"weights/acme/tiny/a.bin": b"x"}), "weights/acme/tiny/a.bin"),
        (hf_zip_bytes({"models/acme/tiny/con.txt": b"x"}), "models/acme/tiny/con.txt"),
        (hf_zip_bytes({"models/acme/tiny/a:b": b"x"}), "models/acme/tiny/a:b"),
        (hf_zip_bytes({"../evil": b"x"}), "../evil"),
        (hf_zip_bytes({"/abs/x": b"x"}), "/abs/x"),
        (
            hf_zip_bytes({"models/acme/tiny/a.json": b"x"}, symlinks={"models/acme/tiny/l": "/x"}),
            "models/acme/tiny/l",
        ),
        (
            hf_zip_bytes({"models/acme/tiny/a.json": b"x"}, symlinks={"models/acme/.l": "/x"}),
            "models/acme/.l",
        ),
        (
            hf_zip_bytes({"models/acme/tiny/a.json": b"x"}, encrypted=("models/acme/tiny/a.json",)),
            "models/acme/tiny/a.json",
        ),
        (
            hf_zip_bytes({"models/acme/tiny/a.json": b"x"}, compression=zipfile.ZIP_BZIP2),
            "models/acme/tiny/a.json",
        ),
        (
            hf_zip_bytes({"models/acme/tiny/A.json": b"x", "models/acme/tiny/a.json": b"y"}),
            "models/acme/tiny/a.json",
        ),
        (hf_zip_bytes({"models/acme/tiny/.cache/x": b"x"}), "no files"),
        (b"not a zip at all", "not a ZIP"),
    ],
    ids=[
        "no-name-folder",
        "wrong-root",
        "reserved-name",
        "colon",
        "traversal",
        "absolute",
        "symlink",
        "hidden-symlink",
        "encrypted",
        "bzip2",
        "case-conflict",
        "only-hidden",
        "not-zip",
    ],
)
def test_a_bad_zip_is_refused_naming_the_path(
    client, admin, db_session, sample_challenge, data, named
):
    task = _task(db_session, sample_challenge)
    response = _put_zip(client, admin, task, data)
    assert response.status_code == 422
    body = response.get_json()
    assert body["code"] == "ERR_HF_ZIP_INVALID"
    assert named in body["error"]
    assert body["detail"] == body["error"]
    assert not os.path.exists(hf_zip.hf_store_dir())
    assert not os.listdir(incoming_dir())


def test_a_zip_bomb_is_refused_from_the_declared_sizes(client, admin, db_session, sample_challenge):
    task = _task(db_session, sample_challenge)
    bomb = hf_zip_bytes({"models/acme/tiny/zeros.bin": b"\0" * 1_000_000})
    response = _put_zip(client, admin, task, bomb)
    assert response.get_json()["code"] == "ERR_HF_ZIP_INVALID"
    assert "compression-ratio" in response.get_json()["error"]


def test_size_limits_answer_413_with_the_limit(
    client, admin, db_session, sample_challenge, monkeypatch
):
    task = _task(db_session, sample_challenge)
    data = hf_zip_bytes({"models/acme/tiny/w.bin": os.urandom(4000)}, compression=0)
    monkeypatch.setattr(Config, "HF_ZIP_MAX_BYTES", 1000)
    too_big = _put_zip(client, admin, task, data)
    assert too_big.status_code == 413
    assert too_big.get_json()["code"] == "ERR_HF_ZIP_TOO_LARGE"
    assert too_big.get_json()["limit"]
    # Hex text compresses about twice, so the ZIP fits and the unpacked files do not
    unpacked = hf_zip_bytes({"models/acme/tiny/w.txt": os.urandom(3000).hex().encode()})
    monkeypatch.setattr(Config, "HF_ZIP_MAX_BYTES", 5000)
    assert len(unpacked) < 5000
    response = _put_zip(client, admin, task, unpacked)
    assert response.status_code == 413
    assert "unpacked" in response.get_json()["error"]


def test_the_body_must_be_raw_with_a_length(client, admin, db_session, sample_challenge):
    task = _task(db_session, sample_challenge)
    multipart = client.put(
        f"/api/tasks/{task.id}/hf-zip",
        data={"file": (io.BytesIO(hf_zip_bytes()), "hf.zip")},
        headers=admin,
        content_type="multipart/form-data",
    )
    assert multipart.status_code == 415
    assert multipart.get_json()["code"] == "ERR_UPLOAD_CONTENT_TYPE"
    empty = client.put(
        f"/api/tasks/{task.id}/hf-zip",
        data=b"",
        headers=_raw(admin, "application/zip"),
        environ_overrides={"CONTENT_LENGTH": "0"},
    )
    assert empty.get_json()["code"] == "ERR_NO_DATA_PROVIDED"
    chunked = client.put(
        f"/api/tasks/{task.id}/hf-zip",
        input_stream=io.BytesIO(hf_zip_bytes()),
        headers={**_raw(admin, "application/zip"), "Transfer-Encoding": "chunked"},
    )
    assert chunked.status_code == 411
    assert chunked.get_json()["code"] == "ERR_UPLOAD_LENGTH_REQUIRED"


def test_admin_and_jury_upload_but_competitors_do_not(
    client, tokens, csrf_headers, db_session, sample_challenge, create_user
):
    task = _task(db_session, sample_challenge)
    student = _put_zip(client, csrf_headers(tokens.competitor), task, hf_zip_bytes())
    assert student.status_code == 403
    jury = create_user(username="jury_hf", role="jury")
    db_session.commit()
    allowed = _put_zip(client, csrf_headers(generate_token(jury.id, "jury")), task, hf_zip_bytes())
    assert allowed.status_code == 200, allowed.get_json()


def test_hf_data_locks_with_the_published_environment(client, admin, db_session, sample_challenge):
    task = _task(db_session, sample_challenge)
    assert _put_zip(client, admin, task, hf_zip_bytes()).status_code == 200
    _publish(db_session, sample_challenge)
    replaced = _put_zip(client, admin, task, hf_zip_bytes({"models/a/b/c.json": b"1"}))
    assert (replaced.status_code, replaced.get_json()["code"]) == (409, "ERR_TASK_FILES_LOCKED")
    removed = client.delete(f"/api/tasks/{task.id}/hf-zip", headers=admin)
    assert removed.get_json()["code"] == "ERR_TASK_FILES_LOCKED"


def test_the_same_folder_with_other_files_conflicts_in_one_environment(
    client, admin, db_session, sample_challenge
):
    _environments_on(db_session, sample_challenge)
    first = _task(db_session, sample_challenge)
    second = _task(db_session, sample_challenge, title="Second", folder="second")
    assert _put_zip(client, admin, first, hf_zip_bytes()).status_code == 200
    # Identical folders are shared
    assert _put_zip(client, admin, second, hf_zip_bytes()).status_code == 200
    other = hf_zip_bytes({"models/acme/tiny/config.json": b'{"model_type": "gpt"}'})
    response = _put_zip(client, admin, second, other)
    assert response.status_code == 409
    body = response.get_json()
    assert body["code"] == "ERR_HF_FOLDER_CONFLICT"
    assert "models/acme/tiny" in body["error"] and "BERT" in body["error"]
    assert not os.path.exists(hf_zip.hf_zip_path(hashlib.sha256(other).hexdigest()))


def test_conflicts_only_count_within_the_same_environment_owner(
    client, admin, db_session, sample_challenge
):
    _environments_on(db_session, sample_challenge)
    stages = []
    for number in (1, 2):
        stage = Stage(
            challenge_id=sample_challenge.id,
            title=f"Round {number}",
            stage_number=number,
            start_time=sample_challenge.start_time,
            end_time=sample_challenge.end_time,
        )
        db_session.add(stage)
        stages.append(stage)
    db_session.commit()
    first = _task(db_session, sample_challenge, stage=stages[0])
    second = _task(db_session, sample_challenge, title="S2", folder="s2", stage=stages[1])
    assert _put_zip(client, admin, first, hf_zip_bytes()).status_code == 200
    other = hf_zip_bytes({"models/acme/tiny/config.json": b"{}"})
    assert _put_zip(client, admin, second, other).status_code == 200


def test_the_projected_package_must_fit_the_caps(
    client, admin, db_session, sample_challenge, monkeypatch
):
    _environments_on(db_session, sample_challenge)
    task = _task(db_session, sample_challenge)
    monkeypatch.setattr(Config, "NANOCOLAB_PACKAGE_MAX_BYTES", 100)
    data = hf_zip_bytes({"models/acme/tiny/w.bin": os.urandom(500)}, compression=0)
    response = _put_zip(client, admin, task, data)
    assert response.status_code == 413
    body = response.get_json()
    assert body["code"] == "ERR_ENVIRONMENT_PACKAGE_TOO_LARGE"
    assert "larger than" in body["error"]
    assert body["limit"]
    monkeypatch.setattr(Config, "NANOCOLAB_PACKAGE_MAX_BYTES", 10**9)
    monkeypatch.setattr("services.environment_package.MAX_ENTRIES", 2)
    many = hf_zip_bytes({f"datasets/acme/d/{i}.txt": b"x" for i in range(3)})
    response = _put_zip(client, admin, task, many)
    assert response.status_code == 413
    assert "3 files" in response.get_json()["error"]


def test_without_environments_the_package_caps_do_not_apply(
    client, admin, db_session, sample_challenge, monkeypatch
):
    task = _task(db_session, sample_challenge)
    monkeypatch.setattr(Config, "NANOCOLAB_PACKAGE_MAX_BYTES", 1)
    assert _put_zip(client, admin, task, hf_zip_bytes()).status_code == 200


def test_removal_clears_the_columns_and_the_import_flag(
    client, admin, db_session, sample_challenge
):
    task = _task(db_session, sample_challenge)
    task.hf_zip_not_imported = True
    db_session.commit()
    response = client.delete(f"/api/tasks/{task.id}/hf-zip", headers=admin)
    assert response.status_code == 200
    assert response.get_json()["hf_zip_not_imported"] is False


def test_deleting_a_task_deletes_its_unshared_zip(client, admin, db_session, sample_challenge):
    first = _task(db_session, sample_challenge)
    second = _task(db_session, sample_challenge, title="Two", folder="two")
    shared = hf_zip_bytes()
    sha256 = hashlib.sha256(shared).hexdigest()
    for task in (first, second):
        assert _put_zip(client, admin, task, shared).status_code == 200
    assert client.delete(f"/api/tasks/{first.id}", headers=admin).status_code == 200
    assert os.path.isfile(hf_zip.hf_zip_path(sha256))
    assert client.delete(f"/api/tasks/{second.id}", headers=admin).status_code == 200
    assert not os.path.exists(hf_zip.hf_zip_path(sha256))


def test_export_records_the_zip_and_import_flags_the_task(
    client, admin, tokens, auth_headers, db_session, sample_challenge
):
    task = _task(db_session, sample_challenge)
    data = hf_zip_bytes()
    assert _put_zip(client, admin, task, data).status_code == 200
    exported = client.get(
        f"/api/challenges/{sample_challenge.id}/export", headers=auth_headers(tokens.admin)
    )
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.data)) as archive:
        names = archive.namelist()
        challenge = json.loads(archive.read("challenge.json"))
    assert not any(name.endswith(".zip") for name in names)
    task_data = challenge["tasks"][0]
    assert task_data["hf_zip_sha256"] == hashlib.sha256(data).hexdigest()
    assert task_data["hf_zip_size"] == len(data)
    assert task_data["hf_folders"] == ["models/acme/tiny"]
    imported = client.post(
        "/api/challenges/import",
        data={"file": (io.BytesIO(exported.data), "challenge.zip")},
        headers=auth_headers(tokens.admin),
        content_type="multipart/form-data",
    )
    assert imported.status_code == 201, imported.get_json()
    copy = Task.query.filter(Task.challenge_id == imported.get_json()["id"]).one()
    assert copy.hf_zip_not_imported is True
    assert copy.hf_zip_sha256 is None
    view = client.get(f"/api/tasks/{copy.id}", headers=admin).get_json()
    assert view["hf_zip_not_imported"] is True
    uploaded = _put_zip(client, admin, copy, data)
    assert uploaded.get_json()["hf_zip_not_imported"] is False


# ── Task data files ──


def _put_file(client, headers, task, name, data, visibility="public", reason=None):
    query = {"visibility": visibility, **({"reason": reason} if reason else {})}
    return client.put(
        f"/api/tasks/{task.id}/files/{name}",
        data=data,
        query_string=query,
        headers=_raw(headers),
    )


def test_a_streamed_file_is_stored_hashed_and_replaced_only_when_checked(
    client, admin, db_session, sample_challenge
):
    task = _task(db_session, sample_challenge)
    first = _put_file(client, admin, task, "train.csv", b"id\n1\n")
    assert first.status_code == 200, first.get_json()
    entry = first.get_json()["files"][0]
    assert entry["sha256"] == hashlib.sha256(b"id\n1\n").hexdigest()
    assert entry["size_bytes"] == 5
    folder = os.path.join(Config.UPLOAD_FOLDER, f"task_{task.id}")
    assert os.listdir(folder) == [entry["saved_name"]]
    second = _put_file(client, admin, task, "train.csv", b"id\n2\n")
    saved = second.get_json()["files"][0]["saved_name"]
    assert saved != entry["saved_name"]
    assert os.listdir(folder) == [saved]


def test_a_refused_labels_file_keeps_the_old_one(client, admin, db_session, sample_challenge):
    task = _task(db_session, sample_challenge)
    good = io.BytesIO()
    pd.DataFrame({"id": [1, 2], "label": [0, 1]}).to_parquet(good, index=False)
    stored = _put_file(client, admin, task, "labels.parquet", good.getvalue(), "hidden")
    assert stored.status_code == 200, stored.get_json()
    before = stored.get_json()["files"]
    bad = io.BytesIO()
    pd.DataFrame({"row": [1]}).to_parquet(bad, index=False)
    refused = _put_file(client, admin, task, "labels.parquet", bad.getvalue(), "hidden")
    assert refused.get_json()["code"] == "ERR_INVALID_LABELS_SCHEMA"
    db_session.expire_all()
    assert json.loads(db_session.get(Task, task.id).files) == before
    folder = os.path.join(Config.UPLOAD_FOLDER, f"task_{task.id}")
    assert os.listdir(folder) == [before[0]["saved_name"]]


def test_file_limits_names_and_count(client, admin, db_session, sample_challenge, monkeypatch):
    task = _task(db_session, sample_challenge)
    monkeypatch.setattr(Config, "TASK_FILE_MAX_BYTES", 3)
    too_big = _put_file(client, admin, task, "a.csv", b"1234")
    assert (too_big.status_code, too_big.get_json()["code"]) == (413, "ERR_FILE_TOO_LARGE")
    assert too_big.get_json()["limit"]
    monkeypatch.setattr(Config, "TASK_FILE_MAX_BYTES", 100)
    assert _put_file(client, admin, task, "run.exe", b"x").get_json()["code"] == (
        "ERR_INVALID_FILE_TYPE"
    )
    assert _put_file(client, admin, task, "con.txt", b"x").get_json()["code"] == (
        "ERR_INVALID_FILENAME"
    )
    # Hidden files never ship, so only the basic name rules apply
    assert _put_file(client, admin, task, "con.txt", b"x", "hidden").status_code == 200
    for index in range(4):
        assert _put_file(client, admin, task, f"f{index}.csv", b"x").status_code == 200
    sixth = _put_file(client, admin, task, "f9.csv", b"x")
    assert sixth.get_json()["code"] == "ERR_TOO_MANY_FILES"
    assert _put_file(client, admin, task, "f0.csv", b"y").status_code == 200


def test_public_files_count_in_the_projected_package(
    client, admin, db_session, sample_challenge, monkeypatch
):
    _environments_on(db_session, sample_challenge)
    task = _task(db_session, sample_challenge)
    monkeypatch.setattr(Config, "NANOCOLAB_PACKAGE_MAX_BYTES", 10)
    public = _put_file(client, admin, task, "big.csv", b"x" * 20)
    assert public.get_json()["code"] == "ERR_ENVIRONMENT_PACKAGE_TOO_LARGE"
    assert _put_file(client, admin, task, "big.csv", b"x" * 20, "hidden").status_code == 200


def test_a_file_is_removed_with_its_own_route(client, admin, db_session, sample_challenge):
    task = _task(db_session, sample_challenge)
    stored = _put_file(client, admin, task, "train.csv", b"id\n1\n").get_json()["files"][0]
    missing = client.delete(f"/api/tasks/{task.id}/files/other.csv", headers=admin)
    assert missing.status_code == 404
    removed = client.delete(f"/api/tasks/{task.id}/files/train.csv", headers=admin)
    assert removed.status_code == 200
    assert removed.get_json()["files"] == []
    folder = os.path.join(Config.UPLOAD_FOLDER, f"task_{task.id}")
    assert stored["saved_name"] not in os.listdir(folder)


def test_the_form_refuses_large_notebooks(client, admin, sample_challenge, monkeypatch):
    monkeypatch.setattr(Config, "MAX_NOTEBOOK_BYTES", 10)
    response = client.post(
        f"/api/challenges/{sample_challenge.id}/tasks",
        data={"title": "T", "baseline_notebook": (io.BytesIO(b"x" * 11), "b.ipynb")},
        headers=admin,
        content_type="multipart/form-data",
    )
    assert (response.status_code, response.get_json()["code"]) == (413, "ERR_FILE_TOO_LARGE")
    assert response.get_json()["field"] == "baseline_notebook"
