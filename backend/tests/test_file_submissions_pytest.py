"""Tests for file-mode tasks: workspace and emergency submissions, checks, quotas and downloads."""

import io
import json
import os
from datetime import timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from config import Config
from models import (
    AuditLog,
    Environment,
    JuryChallenge,
    Submission,
    Task,
    Workspace,
)
from services import environment_package, file_submission, nanocolab_client
from services.submission_service import resolve_gpu_required
from tests.helpers.nanocolab_fake import install
from utils.auth_utils import generate_token
from utils.cache_utils import cache_lock
from utils.dates import utcnow
from utils.submission_status import INFRA_FAILURE

FOLDER = "image-classification"
NOTEBOOK = json.dumps({"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": []}).encode()
IDS = [1, 2, 3, 4]


def parquet(frame: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False)
    return buffer.getvalue()


GOOD = parquet(pd.DataFrame({"id": IDS, "prediction": [0, 1, 0, 1]}))
LABELS = parquet(pd.DataFrame({"id": IDS, "label": [0, 1, 1, 1]}))


@pytest.fixture(autouse=True)
def _clean_redis(redis_flush):
    return None


@pytest.fixture
def fake(monkeypatch, tmp_path, app):
    installed = install(monkeypatch, tmp_path)
    monkeypatch.setitem(app.config, "UPLOAD_FOLDER", Config.UPLOAD_FOLDER)
    monkeypatch.setattr(nanocolab_client.time, "sleep", lambda _s: None)
    return installed


@pytest.fixture
def enqueued():
    with patch("tasks.evaluate_submission.apply_async") as mocked:
        yield mocked


def _write_task_files(task, files):
    folder = os.path.join(Config.UPLOAD_FOLDER, f"task_{task.id}")
    os.makedirs(folder, exist_ok=True)
    entries = []
    for index, (name, data, visibility) in enumerate(files):
        saved = f"{index}_{name}"
        with open(os.path.join(folder, saved), "wb") as handle:
            handle.write(data)
        entries.append(
            {
                "filename": name,
                "saved_name": saved,
                "size_bytes": len(data),
                "visibility": visibility,
            }
        )
    task.files = json.dumps(entries)


@pytest.fixture
def file_task(db_session, sample_challenge, fake):
    task = Task(
        challenge_id=sample_challenge.id,
        title="Image Classification",
        folder_name=FOLDER,
        evaluation_mode="file",
        metrics_config={"accuracy": {"weight": 1.0, "higher_is_better": True}},
    )
    db_session.add(task)
    db_session.flush()
    _write_task_files(
        task,
        [
            ("train.csv", b"id,x\n1,2\n", "public"),
            ("labels.parquet", LABELS, "hidden"),
            ("baseline_submission.parquet", GOOD, "hidden"),
        ],
    )
    db_session.commit()
    return task


@pytest.fixture
def environment(db_session, sample_challenge, fake):
    env = Environment(
        challenge_id=sample_challenge.id,
        enabled=True,
        image_id="python-ml",
        event_id="event-1",
        published_at=utcnow() - timedelta(minutes=5),
    )
    db_session.add(env)
    db_session.commit()
    return env


def _open_workspace(db_session, fake, env, user, workspace_id):
    db_session.add(Workspace(environment_id=env.id, user_id=user.id, workspace_id=workspace_id))
    db_session.commit()
    fake.workspaces[workspace_id] = {
        "external_id": f"challenge-{env.challenge_id}",
        "external_user_id": str(user.id).lower(),
        "requested_at": utcnow().isoformat(),
    }


@pytest.fixture
def workspace(db_session, fake, environment, sample_competitor):
    _open_workspace(db_session, fake, environment, sample_competitor, "ws-competitor")
    fake.put_file("ws-competitor", f"{FOLDER}/submission.parquet", GOOD)
    fake.put_file("ws-competitor", f"{FOLDER}/solution.ipynb", NOTEBOOK)
    return "ws-competitor"


def _submit(client, headers, task, body=None):
    return client.post(f"/api/tasks/{task.id}/submit-workspace", headers=headers, json=body)


def _student(tokens, csrf_headers):
    return csrf_headers(tokens.competitor)


def _incoming_files():
    root = os.path.join(Config.UPLOAD_FOLDER, "submission_files", ".incoming")
    return [name for _dirs, _sub, names in os.walk(root) for name in names]


# ── Workspace submit ──


def test_submit_workspace_uses_only_the_students_own_workspace(
    client,
    tokens,
    csrf_headers,
    file_task,
    workspace,
    fake,
    enqueued,
    db_session,
    sample_other_competitor,
    environment,
):
    _open_workspace(db_session, fake, environment, sample_other_competitor, "ws-other")
    other = parquet(pd.DataFrame({"id": IDS, "prediction": [1, 1, 1, 1]}))
    fake.put_file("ws-other", f"{FOLDER}/submission.parquet", other)
    # Paths and workspace ids from the client are ignored: both come from the server
    hostile = {"workspace_id": "ws-other", "path": "../../etc/passwd", "folder": ".."}
    response = _submit(client, _student(tokens, csrf_headers), file_task, hostile)
    assert response.status_code == 202, response.get_json()
    submission = db_session.get(Submission, response.get_json()["submission_id"])
    assert submission.origin == "workspace"
    assert submission.artifact_size == len(GOOD)
    with open(submission.artifact_path, "rb") as handle:
        assert handle.read() == GOOD
    assert submission.notebook_path.endswith("solution.ipynb")
    assert {workspace_id for workspace_id, _body in fake.export_requests} == {"ws-competitor"}
    assert {body["path"] for _id, body in fake.export_requests} == {
        f"{FOLDER}/submission.parquet",
        f"{FOLDER}/solution.ipynb",
    }
    assert submission.workspace_meta["source"] == "LIVE"
    assert enqueued.call_args.kwargs["queue"] == "cpu_queue"
    assert AuditLog.query.filter_by(action_type="export").count() == 2
    assert _incoming_files() == []


def test_a_student_without_a_workspace_never_reads_anothers(
    client, tokens, csrf_headers, file_task, workspace, fake, enqueued
):
    response = _submit(client, csrf_headers(tokens.other), file_task)
    assert response.status_code == 409
    assert response.get_json()["code"] == "ERR_WORKSPACE_EXPORT_UNAVAILABLE"
    assert response.headers["Retry-After"]
    assert fake.export_requests == []
    assert Submission.query.count() == 0


def test_export_digest_mismatch_stores_nothing(
    client, tokens, csrf_headers, file_task, workspace, fake, enqueued
):
    fake.raw_body = b"x" * len(GOOD)
    response = _submit(client, _student(tokens, csrf_headers), file_task)
    assert response.status_code == 502
    assert response.get_json()["code"] == "ERR_WORKSPACE_EXPORT_INTEGRITY"
    assert Submission.query.count() == 0
    assert _incoming_files() == []


def test_export_size_cap_answers_413_with_limit(
    client, tokens, csrf_headers, file_task, workspace, monkeypatch, enqueued
):
    monkeypatch.setattr(Config, "NANOCOLAB_EXPORT_MAX_BYTES", 100)
    response = _submit(client, _student(tokens, csrf_headers), file_task)
    assert response.status_code == 413
    body = response.get_json()
    assert body["code"] == "ERR_WORKSPACE_FILE_TOO_LARGE"
    assert body["limit"]
    assert Submission.query.count() == 0


@pytest.mark.parametrize(
    ("status", "headers", "code"),
    [
        (409, {"Retry-After": "30"}, "ERR_WORKSPACE_EXPORT_UNAVAILABLE"),
        (503, {"Retry-After": "30"}, "ERR_WORKSPACE_EXPORT_UNAVAILABLE"),
        (503, {}, "ERR_NANOCOLAB_UNAVAILABLE"),
        (410, {}, "ERR_WORKSPACE_ARCHIVE_PURGED"),
    ],
)
def test_export_failures_map_to_codes(
    client, tokens, csrf_headers, file_task, workspace, fake, enqueued, status, headers, code
):
    template = "/v1/workspaces/{workspace_id}/export/metadata"
    fake.fail("POST", template, status, "Not now", headers)
    response = _submit(client, _student(tokens, csrf_headers), file_task)
    assert response.get_json()["code"] == code
    assert response.status_code == (503 if status == 503 else status)
    if status != 410:
        assert response.headers["Retry-After"]
    assert Submission.query.count() == 0


def test_nanocolab_unreachable_answers_unavailable_with_retry_after(
    client, tokens, csrf_headers, file_task, workspace, fake, enqueued, monkeypatch
):
    def unreachable(*_args, **_kwargs):
        raise nanocolab_client.NanoColabUnavailableError(503, "nanoColab is unreachable")

    monkeypatch.setattr(nanocolab_client.NanoColabClient, "export_metadata", unreachable)
    response = _submit(client, _student(tokens, csrf_headers), file_task)
    assert response.status_code == 503
    assert response.get_json()["code"] == "ERR_NANOCOLAB_UNAVAILABLE"
    assert response.headers["Retry-After"]
    assert Submission.query.count() == 0


def test_a_file_task_without_a_published_environment_is_refused(
    client, tokens, csrf_headers, file_task, environment, db_session, enqueued
):
    environment.published_at = None
    db_session.commit()
    response = _submit(client, _student(tokens, csrf_headers), file_task)
    assert response.status_code == 409
    assert response.get_json()["code"] == "ERR_TASK_NOT_WORKSPACE_BACKED"


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("submission.parquet", "ERR_WORKSPACE_FILE_MISSING"),
        ("solution.ipynb", "ERR_WORKSPACE_NOTEBOOK_MISSING"),
    ],
)
def test_missing_workspace_files_name_the_file_and_folder(
    client, tokens, csrf_headers, file_task, workspace, fake, enqueued, name, code
):
    del fake.files[(workspace, f"{FOLDER}/{name}")]
    response = _submit(client, _student(tokens, csrf_headers), file_task)
    body = response.get_json()
    assert (response.status_code, body["code"], body["folder"]) == (404, code, FOLDER)
    assert name in body["error"] and FOLDER in body["error"]


def test_an_invalid_notebook_is_refused(
    client, tokens, csrf_headers, file_task, workspace, fake, enqueued
):
    fake.put_file(workspace, f"{FOLDER}/solution.ipynb", b"not json")
    response = _submit(client, _student(tokens, csrf_headers), file_task)
    assert response.status_code == 400
    assert response.get_json()["code"] == "ERR_PARSING_FAILED"
    assert Submission.query.count() == 0


def _nested() -> bytes:
    return parquet(pd.DataFrame({"id": [[1], [2], [3], [4]], "prediction": [0, 1, 0, 1]}))


HOSTILE = {
    "not_parquet": b"id,prediction\n1,0\n",
    "truncated": GOOD[: len(GOOD) // 2],
    "empty": parquet(pd.DataFrame({"id": pd.Series([], dtype="int64"), "prediction": []})),
    "missing_ids": parquet(pd.DataFrame({"id": [1, 2], "prediction": [0, 1]})),
    "extra_ids": parquet(pd.DataFrame({"id": [*IDS, 99], "prediction": [0, 1, 0, 1, 1]})),
    "duplicate_ids": parquet(pd.DataFrame({"id": [1, 1, 2, 3], "prediction": [0, 1, 0, 1]})),
    "nan_id": parquet(pd.DataFrame({"id": [1.0, 2.0, float("nan"), 4.0], "prediction": [0] * 4})),
    "wrong_type": parquet(pd.DataFrame({"id": ["1", "2", "3", "4"], "prediction": [0] * 4})),
    "nested": _nested(),
    "no_id_column": parquet(pd.DataFrame({"row": IDS, "prediction": [0] * 4})),
    "no_prediction": parquet(pd.DataFrame({"id": IDS})),
}


@pytest.mark.parametrize("case", sorted(HOSTILE))
def test_hostile_parquet_is_refused_before_any_row(
    client, tokens, csrf_headers, file_task, workspace, fake, enqueued, case
):
    fake.put_file(workspace, f"{FOLDER}/submission.parquet", HOSTILE[case])
    response = _submit(client, _student(tokens, csrf_headers), file_task)
    assert response.status_code == 422, response.get_json()
    assert response.get_json()["code"] == "ERR_SUBMISSION_FILE_INVALID"
    assert Submission.query.count() == 0
    enqueued.assert_not_called()


def test_id_mismatch_reports_counts_only(
    client, tokens, csrf_headers, file_task, workspace, fake, enqueued
):
    fake.put_file(workspace, f"{FOLDER}/submission.parquet", HOSTILE["extra_ids"])
    body = _submit(client, _student(tokens, csrf_headers), file_task).get_json()
    assert (body["missing_ids"], body["unexpected_ids"], body["expected_ids"]) == (0, 1, 4)
    assert "99" not in body["error"]


@pytest.mark.parametrize(
    ("limit", "value"),
    [("MAX_PARQUET_ROWS", 2), ("MAX_PARQUET_UNCOMPRESSED_BYTES", 10)],
)
def test_oversized_parquet_is_refused_from_its_footer(
    client, tokens, csrf_headers, file_task, workspace, monkeypatch, enqueued, limit, value
):
    monkeypatch.setattr(Config, limit, value)
    response = _submit(client, _student(tokens, csrf_headers), file_task)
    assert response.status_code == 422
    assert "size limits" in response.get_json()["detail"]


@pytest.mark.parametrize(
    ("status", "detailed", "accepted"),
    [
        ("queued", "queued", False),
        ("running", "running_inference", False),
        ("completed", "completed", False),
        ("failed", INFRA_FAILURE, True),
        ("failed", "failed", False),
    ],
)
def test_a_duplicate_parquet_is_refused_unless_the_first_failed_on_the_platform(
    client,
    tokens,
    csrf_headers,
    file_task,
    workspace,
    enqueued,
    db_session,
    status,
    detailed,
    accepted,
):
    headers = _student(tokens, csrf_headers)
    first = _submit(client, headers, file_task)
    assert first.status_code == 202
    row = db_session.get(Submission, first.get_json()["submission_id"])
    row.status, row.detailed_status = status, detailed
    db_session.commit()
    second = _submit(client, headers, file_task)
    if accepted:
        assert second.status_code == 202, second.get_json()
        assert Submission.query.count() == 2
    else:
        assert second.status_code == 409
        assert second.get_json()["code"] == "ERR_SUBMISSION_DUPLICATE"
        assert Submission.query.count() == 1


def test_a_held_submit_lock_creates_no_second_row(
    client,
    tokens,
    csrf_headers,
    file_task,
    workspace,
    enqueued,
    sample_competitor,
    sample_challenge,
):
    key = f"submit_lock:user_{sample_competitor.id}:challenge_{sample_challenge.id}"
    with cache_lock(key, ttl=10) as got:
        assert got
        response = _submit(client, _student(tokens, csrf_headers), file_task)
    assert response.status_code == 429
    assert response.get_json()["code"] == "ERR_SUBMIT_LOCKED"
    assert Submission.query.count() == 0


def test_the_window_gate_applies_before_any_export(
    client, tokens, csrf_headers, file_task, workspace, fake, sample_challenge, db_session
):
    sample_challenge.end_time = utcnow() - timedelta(hours=1)
    db_session.commit()
    response = _submit(client, _student(tokens, csrf_headers), file_task)
    assert response.status_code == 400
    assert response.get_json()["code"] == "ERR_COMPETITION_ENDED"
    assert fake.export_requests == []


def test_cells_to_a_file_task_are_refused(client, tokens, csrf_headers, file_task, enqueued):
    response = client.post(
        f"/api/tasks/{file_task.id}/submit",
        headers=_student(tokens, csrf_headers),
        json={"selected_cells": [{"source": "print(1)"}]},
    )
    assert response.status_code == 409
    assert response.get_json()["code"] == "ERR_TASK_MODE_MISMATCH"


def test_export_routes_are_rate_limited(
    client, tokens, csrf_headers, file_task, environment, enqueued
):
    headers = _student(tokens, csrf_headers)
    codes = [_submit(client, headers, file_task).status_code for _ in range(11)]
    assert codes[-1] == 429
    assert 429 not in codes[:10]


# ── Quotas and routing ──


def test_quota_is_shared_across_routes_and_skips_baselines_and_platform_failures(
    client,
    tokens,
    csrf_headers,
    file_task,
    workspace,
    fake,
    enqueued,
    db_session,
    sample_challenge,
    sample_competitor,
):
    sample_challenge.max_eval_requests = 2
    file_task.emergency_upload_enabled = True
    notebook_task = Task(challenge_id=sample_challenge.id, title="Notebook", folder_name="nb")
    db_session.add(notebook_task)
    yesterday = utcnow() - timedelta(days=1, hours=1)
    db_session.add_all(
        [
            Submission(
                user_id=sample_competitor.id,
                challenge_id=sample_challenge.id,
                task_id=file_task.id,
                status="completed",
                created_at=yesterday,
            ),
            Submission(
                user_id=sample_competitor.id,
                challenge_id=sample_challenge.id,
                task_id=file_task.id,
                status="failed",
                detailed_status=INFRA_FAILURE,
            ),
            Submission(
                user_id=sample_competitor.id,
                challenge_id=sample_challenge.id,
                task_id=file_task.id,
                status="completed",
                is_baseline=True,
            ),
        ]
    )
    db_session.commit()
    headers = _student(tokens, csrf_headers)
    cells = client.post(
        f"/api/tasks/{notebook_task.id}/submit",
        headers=headers,
        json={"selected_cells": [{"source": "print(1)"}]},
    )
    assert cells.status_code == 202, cells.get_json()
    assert _submit(client, headers, file_task).status_code == 202
    other = parquet(pd.DataFrame({"id": IDS, "prediction": [1, 1, 1, 1]}))
    upload = client.post(
        f"/api/tasks/{file_task.id}/submit-file",
        headers=headers,
        data={
            "submission": (io.BytesIO(other), "submission.parquet"),
            "notebook": (io.BytesIO(NOTEBOOK), "solution.ipynb"),
        },
        content_type="multipart/form-data",
    )
    assert upload.status_code == 429
    assert upload.get_json()["code"] == "ERR_DAILY_LIMIT_REACHED"


def test_file_tasks_always_use_the_cpu_queue(file_task, sample_challenge, db_session):
    file_task.gpu_required = True
    sample_challenge.gpu_required = True
    db_session.commit()
    assert resolve_gpu_required(file_task, sample_challenge) is False


# ── Emergency upload ──


def _upload(client, headers, task, data=GOOD):
    return client.post(
        f"/api/tasks/{task.id}/submit-file",
        headers=headers,
        data={
            "submission": (io.BytesIO(data), "submission.parquet"),
            "notebook": (io.BytesIO(NOTEBOOK), "solution.ipynb"),
        },
        content_type="multipart/form-data",
    )


def _switch(client, headers, task, **body):
    return client.put(f"/api/tasks/{task.id}/emergency-upload", headers=headers, json=body)


def test_emergency_upload_is_off_by_default_and_admin_only(
    client, tokens, csrf_headers, file_task, create_user, sample_challenge, db_session, enqueued
):
    student = _student(tokens, csrf_headers)
    refused = _upload(client, student, file_task)
    assert (refused.status_code, refused.get_json()["code"]) == (
        403,
        "ERR_EMERGENCY_UPLOAD_DISABLED",
    )
    # Tests assign every jury member to every competition
    jury = create_user(username="jury_switch", role="jury")
    db_session.commit()
    jury_headers = csrf_headers(generate_token(jury.id, "jury"))
    assert (
        _switch(client, jury_headers, file_task, enabled=True, reason="Outage").status_code == 403
    )
    admin = csrf_headers(tokens.admin)
    no_reason = _switch(client, admin, file_task, enabled=True)
    assert no_reason.get_json()["code"] == "ERR_REASON_REQUIRED"
    switched = _switch(client, admin, file_task, enabled=True, reason="nanoColab is down")
    assert switched.status_code == 200
    assert switched.get_json()["emergency_upload_enabled"] is True
    entry = AuditLog.query.filter_by(action_type="emergency_upload").one()
    assert entry.reason == "nanoColab is down"
    accepted = _upload(client, student, file_task)
    assert accepted.status_code == 202, accepted.get_json()
    row = db_session.get(Submission, accepted.get_json()["submission_id"])
    assert row.origin == "emergency_upload"


def test_emergency_upload_is_capped(
    client, tokens, csrf_headers, file_task, db_session, monkeypatch, enqueued
):
    file_task.emergency_upload_enabled = True
    db_session.commit()
    monkeypatch.setattr(Config, "NANOCOLAB_EXPORT_MAX_BYTES", 100)
    response = _upload(client, _student(tokens, csrf_headers), file_task)
    assert response.status_code == 413
    assert response.get_json()["limit"]


# ── Notebook mode: load from the workspace ──


def test_workspace_notebook_fills_the_cell_picker(
    client, tokens, csrf_headers, file_task, workspace, fake, db_session
):
    file_task.evaluation_mode = "notebook"
    db_session.commit()
    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": [{"cell_type": "code", "source": ["print(1)"], "metadata": {}, "outputs": []}],
    }
    fake.put_file(workspace, f"{FOLDER}/solution.ipynb", json.dumps(notebook).encode())
    url = f"/api/tasks/{file_task.id}/workspace-notebook"
    response = client.post(url, headers=_student(tokens, csrf_headers))
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["cells"][0]["source"] == "print(1)"
    del fake.files[(workspace, f"{FOLDER}/solution.ipynb")]
    missing = client.post(url, headers=_student(tokens, csrf_headers))
    assert missing.get_json()["code"] == "ERR_WORKSPACE_NOTEBOOK_MISSING"
    assert Submission.query.count() == 0


# ── Jury downloads ──


def test_jury_downloads_by_alias_while_double_blind(
    client,
    tokens,
    csrf_headers,
    file_task,
    workspace,
    enqueued,
    create_user,
    sample_challenge,
    db_session,
    sample_competitor,
):
    sample_competitor.set_demographics("Jane", "Doe", "12", "School", "City")
    db_session.commit()
    created = _submit(client, _student(tokens, csrf_headers), file_task)
    submission_id = created.get_json()["submission_id"]
    jury = create_user(username="jury_dl", role="jury")
    outsider = create_user(username="jury_out", role="jury")
    JuryChallenge.query.filter_by(jury_id=outsider.id).delete()
    db_session.commit()
    jury_headers = csrf_headers(generate_token(jury.id, "jury"))
    parquet_file = client.get(
        f"/api/submissions/{submission_id}/files/parquet", headers=jury_headers
    )
    assert parquet_file.status_code == 200
    assert parquet_file.data == GOOD
    disposition = parquet_file.headers["Content-Disposition"]
    assert sample_competitor.alias_id in disposition
    assert "Jane" not in disposition and "Doe" not in disposition
    notebook = client.get(f"/api/submissions/{submission_id}/files/notebook", headers=jury_headers)
    assert notebook.data == NOTEBOOK
    admin = client.get(
        f"/api/submissions/{submission_id}/files/parquet", headers=csrf_headers(tokens.admin)
    )
    assert "Jane" in admin.headers["Content-Disposition"]
    stranger = client.get(
        f"/api/submissions/{submission_id}/files/parquet",
        headers=csrf_headers(generate_token(outsider.id, "jury")),
    )
    assert stranger.status_code == 403
    competitor = client.get(
        f"/api/submissions/{submission_id}/files/parquet", headers=csrf_headers(tokens.other)
    )
    assert competitor.status_code == 403
    own = client.get(
        f"/api/challenges/{sample_challenge.id}/tasks/{file_task.id}/users/"
        f"{sample_competitor.id}/download",
        headers=jury_headers,
    )
    assert own.status_code == 404
    db_session.get(Submission, submission_id).status = "completed"
    db_session.commit()
    best = client.get(
        f"/api/challenges/{sample_challenge.id}/tasks/{file_task.id}/users/"
        f"{sample_competitor.id}/download",
        headers=jury_headers,
    )
    assert best.status_code == 200
    assert best.data == NOTEBOOK
    assert "Jane" not in best.headers["Content-Disposition"]


# ── Hidden files ──


def test_hidden_files_never_ship_or_reach_competitors(
    client, tokens, csrf_headers, file_task, db_session
):
    for mode in ("file", "notebook"):
        file_task.evaluation_mode = mode
        db_session.commit()
        entries = environment_package.package_entries([file_task])
        names = {entry.arcname for entry in entries}
        assert names == {f"{FOLDER}/train.csv"}
        assert f"{FOLDER}/submission.parquet" in environment_package.export_paths([file_task]) or (
            mode == "notebook"
        )
    student = _student(tokens, csrf_headers)
    for hidden in ("labels.parquet", "baseline_submission.parquet"):
        response = client.get(f"/api/tasks/{file_task.id}/download/{hidden}", headers=student)
        assert response.status_code == 403
    listed = client.get(f"/api/tasks/{file_task.id}", headers=student).get_json()["files"]
    assert [entry["filename"] for entry in listed] == ["train.csv"]


def test_export_paths_follow_the_mode(file_task, db_session):
    assert environment_package.export_paths([file_task]) == [
        f"{FOLDER}/solution.ipynb",
        f"{FOLDER}/submission.parquet",
    ]
    file_task.evaluation_mode = "notebook"
    assert environment_package.export_paths([file_task]) == [f"{FOLDER}/solution.ipynb"]


def test_baseline_of_a_file_task_scores_its_hidden_parquet(file_task, sample_admin, enqueued):
    from services.baseline_service import queue_baseline

    baseline = queue_baseline(file_task, file_task.challenge, sample_admin.id)
    assert baseline is not None and baseline.is_baseline
    assert baseline.artifact_path == file_submission.task_file_path(
        file_task, "baseline_submission.parquet"
    )
    assert baseline.origin is None
    assert enqueued.call_args.kwargs["queue"] == "cpu_queue"
    metadata = enqueued.call_args.kwargs["args"][1]
    assert metadata["evaluation_mode"] == "file"
    assert metadata["artifact_sha256"] == baseline.artifact_sha256
