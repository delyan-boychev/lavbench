"""Tests for task evaluation modes: file visibility, per-mode baselines and the publish locks."""

import io
import json
from datetime import timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from config import Config
from models import AuditLog, Environment, Submission, Task
from utils.auth_utils import generate_token
from utils.dates import utcnow

IDS = [1, 2, 3]
NOTEBOOK = json.dumps({"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": []}).encode()


def parquet(frame: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False)
    return buffer.getvalue()


LABELS = parquet(pd.DataFrame({"id": IDS, "label": [0, 1, 1]}))
BASELINE = parquet(pd.DataFrame({"id": IDS, "prediction": [0, 0, 1]}))


@pytest.fixture(autouse=True)
def _clean_redis(redis_flush):
    return None


@pytest.fixture
def enqueued():
    with patch("tasks.evaluate_submission.apply_async") as mocked:
        yield mocked


def _create(client, headers, challenge, **fields):
    data = {"title": "Image Classification", **fields}
    return client.post(
        f"/api/challenges/{challenge.id}/tasks",
        headers=headers,
        data=data,
        content_type="multipart/form-data",
    )


def _file(data, name):
    return (io.BytesIO(data), name)


def _file_task(client, headers, challenge, baseline=BASELINE):
    return _create(
        client,
        headers,
        challenge,
        evaluation_mode="file",
        file0=_file(b"id,x\n1,2\n", "train.csv"),
        hidden_file0=_file(LABELS, "labels.parquet"),
        hidden_file1=_file(baseline, "baseline_submission.parquet"),
    )


def test_a_file_task_scores_its_hidden_baseline(
    client, tokens, csrf_headers, sample_challenge, enqueued
):
    response = _file_task(client, csrf_headers(tokens.admin), sample_challenge)
    assert response.status_code == 201, response.get_json()
    body = response.get_json()
    assert body["evaluation_mode"] == "file"
    visibility = {entry["filename"]: entry["visibility"] for entry in body["files"]}
    assert visibility == {
        "train.csv": "public",
        "labels.parquet": "hidden",
        "baseline_submission.parquet": "hidden",
    }
    baseline = Submission.query.filter_by(is_baseline=True).one()
    assert baseline.artifact_sha256
    assert enqueued.call_args.kwargs["queue"] == "cpu_queue"


@pytest.mark.parametrize(
    "baseline",
    [None, parquet(pd.DataFrame({"id": [1, 2], "prediction": [0, 1]}))],
    ids=["missing", "wrong_ids"],
)
def test_a_file_task_needs_a_matching_baseline_submission(
    client, tokens, csrf_headers, sample_challenge, enqueued, baseline
):
    files = {
        "file0": _file(b"id,x\n1,2\n", "train.csv"),
        "hidden_file0": _file(LABELS, "labels.parquet"),
    }
    if baseline is not None:
        files["hidden_file1"] = _file(baseline, "baseline_submission.parquet")
    response = _create(
        client, csrf_headers(tokens.admin), sample_challenge, evaluation_mode="file", **files
    )
    assert response.status_code == 422
    assert response.get_json()["code"] == "ERR_BASELINE_SUBMISSION_INVALID"
    assert Task.query.count() == 0


def test_a_notebook_task_still_needs_its_baseline_notebook(
    client, tokens, csrf_headers, sample_challenge
):
    response = _create(client, csrf_headers(tokens.admin), sample_challenge)
    assert response.get_json()["code"] == "ERR_BASELINE_REQUIRED"


@pytest.mark.parametrize("name", [".env", "con.txt", "notes.", "cafe\u0301.csv", "a:b.csv"])
def test_public_file_names_follow_the_workspace_path_rules(
    client, tokens, csrf_headers, sample_challenge, name
):
    response = _create(
        client,
        csrf_headers(tokens.admin),
        sample_challenge,
        baseline_notebook=_file(NOTEBOOK, "baseline.ipynb"),
        file0=_file(b"x", name),
    )
    assert response.status_code == 400
    assert response.get_json()["code"] == "ERR_INVALID_FILENAME"


def _task_with_files(db_session, challenge, mode="file"):
    task = Task(
        challenge_id=challenge.id,
        title="Mode Task",
        folder_name="mode-task",
        evaluation_mode=mode,
        metrics_config={"accuracy": {"weight": 1.0}},
    )
    db_session.add(task)
    db_session.flush()
    import os

    folder = os.path.join(Config.UPLOAD_FOLDER, f"task_{task.id}")
    os.makedirs(folder, exist_ok=True)
    entries = []
    for index, (name, data, visibility) in enumerate(
        [
            ("train.csv", b"id\n1\n", "public"),
            ("labels.parquet", LABELS, "hidden"),
            ("baseline_submission.parquet", BASELINE, "hidden"),
        ]
    ):
        saved = f"{index}_{name}"
        with open(os.path.join(folder, saved), "wb") as handle:
            handle.write(data)
        entries.append({"filename": name, "saved_name": saved, "visibility": visibility})
    task.files = json.dumps(entries)
    db_session.commit()
    return task


@pytest.fixture
def uploads_in_config(app, monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path))
    monkeypatch.setitem(app.config, "UPLOAD_FOLDER", str(tmp_path))


def _update(client, headers, task, **fields):
    return client.put(
        f"/api/tasks/{task.id}",
        headers=headers,
        data=fields,
        content_type="multipart/form-data",
    )


def test_the_mode_locks_after_a_competitor_submission_but_not_a_baseline(
    client,
    tokens,
    csrf_headers,
    sample_challenge,
    sample_competitor,
    sample_admin,
    db_session,
    uploads_in_config,
    enqueued,
):
    task = _task_with_files(db_session, sample_challenge)
    db_session.add(
        Submission(
            user_id=sample_admin.id,
            challenge_id=sample_challenge.id,
            task_id=task.id,
            is_baseline=True,
            status="completed",
        )
    )
    db_session.commit()
    admin = csrf_headers(tokens.admin)
    switched = _update(client, admin, task, evaluation_mode="notebook")
    assert switched.status_code == 200, switched.get_json()
    db_session.add(
        Submission(
            user_id=sample_competitor.id,
            challenge_id=sample_challenge.id,
            task_id=task.id,
            status="completed",
        )
    )
    db_session.commit()
    locked = _update(client, admin, task, evaluation_mode="file")
    assert locked.status_code == 409
    assert locked.get_json()["code"] == "ERR_TASK_MODE_LOCKED"


@pytest.fixture
def published(db_session, sample_challenge):
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


def test_hidden_files_can_be_fixed_after_publish_with_a_reason(
    client,
    tokens,
    csrf_headers,
    sample_challenge,
    db_session,
    uploads_in_config,
    published,
    create_user,
    enqueued,
):
    task = _task_with_files(db_session, sample_challenge)
    labels = _file(parquet(pd.DataFrame({"id": IDS, "label": [1, 1, 1]})), "labels.parquet")
    jury = create_user(username="jury_fix", role="jury")
    db_session.commit()
    jury_headers = csrf_headers(generate_token(jury.id, "jury"))
    by_jury = _update(client, jury_headers, task, hidden_file0=labels, reason="Typo in labels")
    assert by_jury.status_code == 403
    admin = csrf_headers(tokens.admin)
    labels = _file(parquet(pd.DataFrame({"id": IDS, "label": [1, 1, 1]})), "labels.parquet")
    no_reason = _update(client, admin, task, hidden_file0=labels)
    assert no_reason.get_json()["code"] == "ERR_REASON_REQUIRED"
    labels = _file(parquet(pd.DataFrame({"id": IDS, "label": [1, 1, 1]})), "labels.parquet")
    fixed = _update(client, admin, task, hidden_file0=labels, reason="Typo in labels")
    assert fixed.status_code == 200, fixed.get_json()
    entry = AuditLog.query.filter_by(action_type="update", target_type="task").one()
    assert entry.reason == "Typo in labels"
    assert entry.details["hidden_files_after_publish"] is True
    assert Submission.query.filter_by(task_id=task.id, is_baseline=True).count() == 1
    enqueued.assert_called_once()

    public = _update(client, admin, task, file0=_file(b"id\n2\n", "train.csv"), reason="x")
    assert public.get_json()["code"] == "ERR_TASK_FILES_LOCKED"
    folder = _update(client, admin, task, folder_name="other-folder")
    assert folder.get_json()["code"] == "ERR_ENVIRONMENT_LOCKED"


def test_a_hidden_upload_keeps_its_visibility(
    client, tokens, csrf_headers, sample_challenge, db_session, uploads_in_config, enqueued
):
    task = _task_with_files(db_session, sample_challenge, mode="notebook")
    response = _update(
        client, csrf_headers(tokens.admin), task, hidden_file0=_file(b"secret", "answers.csv")
    )
    assert response.status_code == 200, response.get_json()
    files = {entry["filename"]: entry["visibility"] for entry in response.get_json()["files"]}
    assert files["answers.csv"] == "hidden"
    student = client.get(
        f"/api/tasks/{task.id}/download/answers.csv", headers=csrf_headers(tokens.competitor)
    )
    assert student.status_code == 403


def test_a_bad_baseline_on_update_leaves_the_task_as_it_was(
    client,
    tokens,
    csrf_headers,
    sample_challenge,
    db_session,
    uploads_in_config,
    enqueued,
    monkeypatch,
):
    from services import file_submission

    task = _task_with_files(db_session, sample_challenge)
    files_before = task.files
    seen = []
    original = file_submission.sniff_parquet

    def watched(*args):
        seen.append(db_session().in_transaction())
        return original(*args)

    monkeypatch.setattr(file_submission, "sniff_parquet", watched)
    bad = _file(parquet(pd.DataFrame({"id": [7, 8], "prediction": [0, 1]})), "x.parquet")
    response = _update(
        client,
        csrf_headers(tokens.admin),
        task,
        title="Renamed",
        hidden_file0=(bad[0], "baseline_submission.parquet"),
    )
    assert response.status_code == 422
    assert response.get_json()["code"] == "ERR_BASELINE_SUBMISSION_INVALID"
    assert seen == [False]
    db_session.expire_all()
    task = db_session.get(Task, task.id)
    assert (task.title, task.files) == ("Mode Task", files_before)
    saved = {entry["saved_name"] for entry in json.loads(task.files)}
    folder = f"{Config.UPLOAD_FOLDER}/task_{task.id}"
    import os

    assert set(os.listdir(folder)) == saved


def _task_view(client, headers, task):
    return client.get(f"/api/tasks/{task.id}", headers=headers).get_json()


def test_mode_locked_flag_matches_the_refusal(
    client,
    tokens,
    csrf_headers,
    sample_challenge,
    sample_competitor,
    db_session,
    uploads_in_config,
    enqueued,
):
    task = _task_with_files(db_session, sample_challenge)
    admin = csrf_headers(tokens.admin)
    assert _task_view(client, admin, task)["mode_locked"] is False
    db_session.add(
        Submission(
            user_id=sample_competitor.id,
            challenge_id=sample_challenge.id,
            task_id=task.id,
            status="completed",
        )
    )
    db_session.commit()
    assert _task_view(client, admin, task)["mode_locked"] is True
    refused = _update(client, admin, task, evaluation_mode="notebook")
    assert refused.get_json()["code"] == "ERR_TASK_MODE_LOCKED"


def test_files_locked_flag_matches_the_refusals(
    client, tokens, csrf_headers, sample_challenge, db_session, uploads_in_config, enqueued
):
    task = _task_with_files(db_session, sample_challenge)
    admin = csrf_headers(tokens.admin)
    assert _task_view(client, admin, task)["files_locked"] is False
    env = Environment(
        challenge_id=sample_challenge.id, enabled=True, image_id="python-ml", event_id="e"
    )
    db_session.add(env)
    db_session.commit()
    assert _task_view(client, admin, task)["files_locked"] is False
    env.published_at = utcnow()
    db_session.commit()
    view = _task_view(client, admin, task)
    assert view["files_locked"] is True
    assert _task_view(client, csrf_headers(tokens.competitor), task)["files_locked"] is True
    public = _update(client, admin, task, file0=_file(b"id\n2\n", "train.csv"))
    assert public.get_json()["code"] == "ERR_TASK_FILES_LOCKED"
    folder = _update(client, admin, task, folder_name="another-folder")
    assert folder.get_json()["code"] == "ERR_ENVIRONMENT_LOCKED"


def test_task_lists_load_the_flags_in_a_fixed_number_of_queries(
    client, tokens, csrf_headers, sample_challenge, db_session, uploads_in_config
):
    from sqlalchemy import event

    from models import db

    for index in range(5):
        db_session.add(
            Task(challenge_id=sample_challenge.id, title=f"T{index}", folder_name=f"t-{index}")
        )
    db_session.commit()
    counted = []

    def count(*_args, **_kwargs):
        counted.append(1)

    from services.task_locks import task_locks

    tasks = Task.query.filter_by(challenge_id=sample_challenge.id).all()
    event.listen(db.engine, "before_cursor_execute", count)
    try:
        locks = task_locks(tasks)
    finally:
        event.remove(db.engine, "before_cursor_execute", count)
    assert len(locks) == 5
    assert len(counted) == 2
