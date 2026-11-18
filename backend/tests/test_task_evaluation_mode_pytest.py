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


def _put(client, headers, task_id, name, data, visibility="public", reason=None):
    query = {"visibility": visibility, **({"reason": reason} if reason else {})}
    return client.put(
        f"/api/tasks/{task_id}/files/{name}",
        headers={**headers, "Content-Type": "application/octet-stream"},
        query_string=query,
        data=data,
    )


def _file_task(client, headers, challenge, baseline=BASELINE):
    """Create a file task, then stream its data files one by one like the upload list."""
    created = _create(client, headers, challenge, evaluation_mode="file")
    assert created.status_code == 201, created.get_json()
    task_id = created.get_json()["id"]
    uploads = [("train.csv", b"id,x\n1,2\n", "public"), ("labels.parquet", LABELS, "hidden")]
    if baseline is not None:
        uploads.append(("baseline_submission.parquet", baseline, "hidden"))
    response = created
    for name, data, visibility in uploads:
        response = _put(client, headers, task_id, name, data, visibility)
        if response.status_code != 200:
            break
    return response


def test_a_file_task_scores_its_hidden_baseline(
    client, tokens, csrf_headers, sample_challenge, enqueued
):
    response = _file_task(client, csrf_headers(tokens.admin), sample_challenge)
    assert response.status_code == 200, response.get_json()
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


def test_a_baseline_submission_must_match_the_labels(
    client, tokens, csrf_headers, sample_challenge, enqueued
):
    wrong_ids = parquet(pd.DataFrame({"id": [1, 2], "prediction": [0, 1]}))
    response = _file_task(client, csrf_headers(tokens.admin), sample_challenge, wrong_ids)
    assert response.status_code == 422
    assert response.get_json()["code"] == "ERR_BASELINE_SUBMISSION_INVALID"
    task = Task.query.one()
    assert "baseline_submission.parquet" not in task.files


def test_a_file_task_without_its_baseline_queues_no_run(
    client, tokens, csrf_headers, sample_challenge, enqueued
):
    response = _file_task(client, csrf_headers(tokens.admin), sample_challenge, baseline=None)
    assert response.status_code == 200
    assert Submission.query.filter_by(is_baseline=True).count() == 0


def test_the_form_no_longer_takes_data_files(client, tokens, csrf_headers, sample_challenge):
    response = _create(
        client,
        csrf_headers(tokens.admin),
        sample_challenge,
        baseline_notebook=_file(NOTEBOOK, "baseline.ipynb"),
        hidden_file0=_file(LABELS, "labels.parquet"),
    )
    assert response.status_code == 400
    assert response.get_json()["code"] == "ERR_INVALID_UPLOAD_FORMAT"
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
    admin = csrf_headers(tokens.admin)
    created = _create(
        client, admin, sample_challenge, baseline_notebook=_file(NOTEBOOK, "baseline.ipynb")
    )
    response = _put(client, admin, created.get_json()["id"], name, b"x")
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
    labels = labels[0].getvalue()
    name = "labels.parquet"
    by_jury = _put(client, jury_headers, task.id, name, labels, "hidden", "Typo in labels")
    assert by_jury.status_code == 403
    admin = csrf_headers(tokens.admin)
    no_reason = _put(client, admin, task.id, name, labels, "hidden")
    assert no_reason.get_json()["code"] == "ERR_REASON_REQUIRED"
    fixed = _put(client, admin, task.id, name, labels, "hidden", "Typo in labels")
    assert fixed.status_code == 200, fixed.get_json()
    entry = AuditLog.query.filter_by(action_type="update", target_type="task").one()
    assert entry.reason == "Typo in labels"
    assert entry.details["hidden_files_after_publish"] is True
    assert Submission.query.filter_by(task_id=task.id, is_baseline=True).count() == 1
    enqueued.assert_called_once()

    public = _put(client, admin, task.id, "train.csv", b"id\n2\n", reason="x")
    assert public.get_json()["code"] == "ERR_TASK_FILES_LOCKED"
    removed = client.delete(f"/api/tasks/{task.id}/files/train.csv", headers=admin)
    assert removed.get_json()["code"] == "ERR_TASK_FILES_LOCKED"
    folder = _update(client, admin, task, folder_name="other-folder")
    assert folder.get_json()["code"] == "ERR_ENVIRONMENT_LOCKED"


def test_a_hidden_upload_keeps_its_visibility(
    client, tokens, csrf_headers, sample_challenge, db_session, uploads_in_config, enqueued
):
    task = _task_with_files(db_session, sample_challenge, mode="notebook")
    response = _put(client, csrf_headers(tokens.admin), task.id, "answers.csv", b"secret", "hidden")
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
    original = file_submission._run_child

    def watched(*args):
        seen.append(db_session().in_transaction())
        return original(*args)

    monkeypatch.setattr(file_submission, "_run_child", watched)
    bad = parquet(pd.DataFrame({"id": [7, 8], "prediction": [0, 1]}))
    name = "baseline_submission.parquet"
    response = _put(client, csrf_headers(tokens.admin), task.id, name, bad, "hidden")
    assert response.status_code == 422
    assert response.get_json()["code"] == "ERR_BASELINE_SUBMISSION_INVALID"
    assert seen and not any(seen)
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
    public = _put(client, admin, task.id, "train.csv", b"id\n2\n")
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


def _labels_upload(client, headers, challenge, labels):
    created = _create(client, headers, challenge, baseline_notebook=_file(NOTEBOOK, "x.ipynb"))
    assert created.status_code == 201
    return _put(client, headers, created.get_json()["id"], "labels.parquet", labels, "hidden")


def test_labels_too_large_to_check_are_refused_at_upload(
    client, tokens, csrf_headers, sample_challenge, monkeypatch
):
    from services import file_submission

    # Every id now needs far more memory than the ceiling allows
    monkeypatch.setattr(file_submission, "_ID_MEMORY_FACTOR", 10**9)
    response = _labels_upload(client, csrf_headers(tokens.admin), sample_challenge, LABELS)
    assert response.status_code == 413
    body = response.get_json()
    assert (body["code"], body["field"]) == ("ERR_LABELS_TOO_LARGE", "labels.parquet")
    assert body["limit"]
    assert Task.query.one().files == "[]"


def test_invalid_labels_are_refused_from_the_child(client, tokens, csrf_headers, sample_challenge):
    no_ids = parquet(pd.DataFrame({"row": [1, 2], "label": [0, 1]}))
    response = _labels_upload(client, csrf_headers(tokens.admin), sample_challenge, no_ids)
    assert response.status_code == 400
    assert response.get_json()["code"] == "ERR_INVALID_LABELS_SCHEMA"


def test_a_crashing_baseline_check_refuses_and_reverts(
    client,
    tokens,
    csrf_headers,
    sample_challenge,
    db_session,
    uploads_in_config,
    enqueued,
    monkeypatch,
):
    import routes.task_data
    import routes.tasks

    def crash(*_args):
        raise RuntimeError("child exploded")

    monkeypatch.setattr(routes.task_data, "check_baseline_file", crash)
    monkeypatch.setattr(routes.tasks, "check_baseline_parquet", crash)
    task = _task_with_files(db_session, sample_challenge)
    files_before = task.files
    admin = csrf_headers(tokens.admin)
    name = "baseline_submission.parquet"
    uploaded = _put(client, admin, task.id, name, BASELINE, "hidden")
    assert uploaded.status_code == 422
    assert uploaded.get_json()["code"] == "ERR_BASELINE_SUBMISSION_INVALID"
    metrics = json.dumps({"accuracy": {"weight": 2.0}})
    updated = _update(client, admin, task, title="Renamed", metrics_config=metrics)
    assert updated.status_code == 422
    db_session.expire_all()
    task = db_session.get(Task, task.id)
    assert (task.title, task.files) == ("Mode Task", files_before)


def test_owner_keys_ignore_how_the_stage_id_is_written():
    import uuid

    from services.environment_service import owner_published

    stage_id = uuid.uuid4()
    published = {str(stage_id)}
    assert owner_published(published, stage_id)
    assert owner_published(published, str(stage_id).upper())
    assert not owner_published(published, None)


def test_the_first_competitor_submission_refreshes_cached_task_views(
    client, tokens, csrf_headers, sample_challenge, db_session, enqueued
):
    task = Task(challenge_id=sample_challenge.id, title="Cells", folder_name="cells")
    db_session.add(task)
    db_session.commit()
    body = {"selected_cells": [{"source": "print(1)"}]}
    with patch("utils.cache_utils.invalidate_challenge_cache") as invalidated:
        first = client.post(
            f"/api/tasks/{task.id}/submit", headers=csrf_headers(tokens.competitor), json=body
        )
        assert first.status_code == 202
        assert invalidated.call_count == 1
        client.post(
            f"/api/tasks/{task.id}/submit", headers=csrf_headers(tokens.competitor), json=body
        )
        assert invalidated.call_count == 1


def test_an_internal_labels_check_failure_is_a_platform_error(
    client, tokens, csrf_headers, sample_challenge, monkeypatch
):
    from services import file_submission

    original = file_submission.run_limited

    def broken(_script, *args, **kwargs):
        return original("raise RuntimeError('bug')\n", *args, **kwargs)

    monkeypatch.setattr(file_submission, "run_limited", broken)
    response = _labels_upload(client, csrf_headers(tokens.admin), sample_challenge, LABELS)
    assert response.status_code == 503
    assert response.get_json()["code"] == "ERR_SUBMISSION_CHECK_FAILED"
    assert Task.query.one().files == "[]"
