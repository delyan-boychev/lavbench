"""Tests for the task data fix round: baselines, the HF store, leftover files, locks, codes."""

import hashlib
import io
import json
import os
import time
import zipfile
from collections import namedtuple
from unittest.mock import patch

import pandas as pd
import pytest

from config import Config
from models import (
    AuditLog,
    Environment,
    JuryChallenge,
    Stage,
    Submission,
    Task,
    WorkspaceSetting,
    db,
)
from services import baseline_service, environment_package, environment_service, hf_zip
from services.task_data import sweep_hf_store, sweep_task_dirs
from tests.helpers.hf import CONFIG, hf_zip_bytes
from utils.auth_utils import generate_token
from utils.cache_utils import cache_lock
from utils.metadata import hf_prep_seconds
from utils.uploads import incoming_dir, sweep_incoming

IDS = [1, 2, 3]
NOTEBOOK = {
    "nbformat": 4,
    "nbformat_minor": 5,
    "metadata": {},
    "cells": [{"cell_type": "code", "metadata": {}, "source": "print(1)", "outputs": []}],
}


def parquet(frame: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False)
    return buffer.getvalue()


LABELS = parquet(pd.DataFrame({"id": IDS, "label": [0, 1, 1]}))
OTHER_LABELS = parquet(pd.DataFrame({"id": [7, 8], "label": [0, 1]}))
BASELINE = parquet(pd.DataFrame({"id": IDS, "prediction": [0, 0, 1]}))


@pytest.fixture(autouse=True)
def _isolated(redis_flush, app, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, "UPLOAD_FOLDER", str(tmp_path))
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path))
    with patch("routes.task_data.schedule_baseline") as scheduled:
        yield scheduled


@pytest.fixture
def admin(tokens, csrf_headers):
    return csrf_headers(tokens.admin)


def _raw(headers):
    return {**headers, "Content-Type": "application/octet-stream"}


def _put_zip(client, headers, task, data):
    return client.put(f"/api/tasks/{task.id}/hf-zip", data=data, headers=_raw(headers))


def _put_file(client, headers, task, name, data, visibility="public"):
    return client.put(
        f"/api/tasks/{task.id}/files/{name}",
        data=data,
        query_string={"visibility": visibility},
        headers=_raw(headers),
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


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _view(client, headers, task):
    return client.get(f"/api/tasks/{task.id}", headers=headers).get_json()


# ── Labels and baseline together ──


def test_new_labels_install_and_flag_a_baseline_that_no_longer_fits(
    client, admin, db_session, sample_challenge
):
    task = _task(db_session, sample_challenge, mode="file")
    assert _put_file(client, admin, task, "labels.parquet", LABELS, "hidden").status_code == 200
    name = "baseline_submission.parquet"
    assert _put_file(client, admin, task, name, BASELINE, "hidden").status_code == 200
    assert "ERR_BASELINE_SUBMISSION_MISMATCH" not in _view(client, admin, task)["problem_codes"]

    shifted = parquet(pd.DataFrame({"id": [1, 2, 9], "label": [0, 1, 1]}))
    replaced = _put_file(client, admin, task, "labels.parquet", shifted, "hidden")
    assert replaced.status_code == 200, replaced.get_json()
    assert "ERR_BASELINE_SUBMISSION_MISMATCH" in replaced.get_json()["problem_codes"]
    fields = replaced.get_json()["problem_fields"]["ERR_BASELINE_SUBMISSION_MISMATCH"]
    counts = {"expected_ids": 3, "missing_ids": 1, "unexpected_ids": 1}
    assert {key: fields[key] for key in counts} == counts
    assert "1 of the 3 expected ids are missing" in fields["detail"]
    assert fields["reason"] == "ids_mismatch"
    assert db.session.get(Task, task.id).problem_fields == {
        "ERR_BASELINE_SUBMISSION_MISMATCH": fields
    }

    wrong = _put_file(client, admin, task, name, BASELINE, "hidden")
    assert wrong.status_code == 422
    body = wrong.get_json()
    assert body["code"] == "ERR_BASELINE_SUBMISSION_INVALID"
    assert body["detail"]

    fitting = parquet(pd.DataFrame({"id": [1, 2, 9], "prediction": [1, 1, 0]}))
    fixed = _put_file(client, admin, task, name, fitting, "hidden")
    assert fixed.status_code == 200, fixed.get_json()
    assert "ERR_BASELINE_SUBMISSION_MISMATCH" not in fixed.get_json()["problem_codes"]
    assert fixed.get_json()["problem_fields"] == {}
    assert db.session.get(Task, task.id).problem_fields is None


def test_labels_back_to_fitting_ones_clear_the_mismatch(
    client, admin, db_session, sample_challenge
):
    task = _task(db_session, sample_challenge, mode="file")
    name = "baseline_submission.parquet"
    # Baseline first: with no labels yet there is nothing to check it against
    assert _put_file(client, admin, task, name, BASELINE, "hidden").status_code == 200
    mismatched = _put_file(client, admin, task, "labels.parquet", OTHER_LABELS, "hidden")
    assert "ERR_BASELINE_SUBMISSION_MISMATCH" in mismatched.get_json()["problem_codes"]
    fitting = _put_file(client, admin, task, "labels.parquet", LABELS, "hidden")
    assert "ERR_BASELINE_SUBMISSION_MISMATCH" not in fitting.get_json()["problem_codes"]
    _put_file(client, admin, task, "labels.parquet", OTHER_LABELS, "hidden")
    removed = client.delete(f"/api/tasks/{task.id}/files/{name}", headers=admin)
    assert "ERR_BASELINE_SUBMISSION_MISMATCH" not in removed.get_json()["problem_codes"]


# ── Debounced baseline ──


def test_several_changes_queue_one_baseline_after_the_last(db_session, sample_challenge):
    task = _task(db_session, sample_challenge)
    with (
        patch("tasks.run_due_baseline.apply_async") as delayed,
        patch("services.baseline_service.requeue_baseline") as requeued,
    ):
        for _ in range(3):
            baseline_service.schedule_baseline(task, "user")
        assert baseline_service.baseline_pending(task.id)
        assert {c.kwargs["countdown"] for c in delayed.call_args_list} == {60}
        results = [
            baseline_service.run_due_baseline(*c.kwargs["args"]) for c in delayed.call_args_list
        ]
    assert results == ["superseded", "superseded", "queued"]
    requeued.assert_called_once()
    assert not baseline_service.baseline_pending(task.id)


def test_a_pending_change_ignores_an_older_runs_outcome(db_session, sample_challenge, sample_admin):
    task = _task(db_session, sample_challenge)
    task.problem_codes = ["ERR_BASELINE_FAILED"]
    old = Submission(
        task_id=task.id,
        challenge_id=sample_challenge.id,
        user_id=sample_admin.id,
        is_baseline=True,
        status="running",
        code_cells="[]",
    )
    db_session.add(old)
    db_session.commit()
    with patch("tasks.run_due_baseline.apply_async"):
        baseline_service.schedule_baseline(task, sample_admin.id)
    # A running row stays, so its worker's report still lands
    assert db.session.get(Submission, old.id) is not None
    old.status = "completed"
    db_session.commit()
    baseline_service.apply_baseline_outcome(old)
    assert db.session.get(Task, task.id).problem_codes == ["ERR_BASELINE_FAILED"]


def test_without_the_broker_the_baseline_queues_at_once(db_session, sample_challenge):
    task = _task(db_session, sample_challenge)
    with (
        patch("tasks.run_due_baseline.apply_async", side_effect=OSError("broker down")),
        patch("services.baseline_service.requeue_baseline") as requeued,
    ):
        baseline_service.schedule_baseline(task, "user")
    requeued.assert_called_once()
    assert not baseline_service.baseline_pending(task.id)


# ── HF time budget and the ZIP recorded at dispatch ──


def test_a_notebook_run_gets_extra_time_for_its_hf_zip(
    db_session, sample_challenge, sample_admin, tmp_path
):
    notebook = tmp_path / "baseline.ipynb"
    notebook.write_text(json.dumps(NOTEBOOK))
    task = _task(db_session, sample_challenge)
    task.baseline_notebook_path = str(notebook)
    task.hf_zip_sha256 = "a" * 64
    task.hf_zip_size = 3 * 1024**3
    db_session.commit()
    with patch("tasks.evaluate_submission.apply_async") as enqueued:
        run = baseline_service.queue_baseline(task, sample_challenge, sample_admin.id)
    extra = hf_prep_seconds(task.hf_zip_size)
    # 60 s plus two passes over 3 GiB at 20 MiB/s, rounded up
    assert extra == 60 + 308
    assert (
        enqueued.call_args.kwargs["soft_time_limit"] == Config.CELERY_TASK_SOFT_TIME_LIMIT + extra
    )
    assert enqueued.call_args.kwargs["time_limit"] == Config.CELERY_TASK_TIME_LIMIT + extra
    assert db.session.get(Submission, run.id).hf_zip_sha256 == "a" * 64
    assert hf_prep_seconds(None) == 0


# ── The HF store ──


def test_a_superseded_zip_stays_while_a_run_uses_it(
    client, admin, db_session, sample_challenge, sample_admin
):
    task = _task(db_session, sample_challenge)
    old = hf_zip_bytes()
    assert _put_zip(client, admin, task, old).status_code == 200
    run = Submission(
        task_id=task.id,
        challenge_id=sample_challenge.id,
        user_id=sample_admin.id,
        status="running",
        code_cells="[]",
        hf_zip_sha256=_sha(old),
    )
    db_session.add(run)
    db_session.commit()
    new = hf_zip_bytes({"models/acme/tiny/config.json": b"{}"})
    assert _put_zip(client, admin, task, new).status_code == 200
    assert os.path.isfile(hf_zip.hf_zip_path(_sha(old)))
    assert sweep_hf_store() == 0
    run.status = "completed"
    db_session.commit()
    assert sweep_hf_store() == 1
    assert not os.path.exists(hf_zip.hf_zip_path(_sha(old)))
    assert os.path.isfile(hf_zip.hf_zip_path(_sha(new)))


def test_an_identical_upload_keeps_the_stored_file(client, admin, db_session, sample_challenge):
    _environments_on(db_session, sample_challenge)
    task = _task(db_session, sample_challenge)
    data = hf_zip_bytes()
    assert _put_zip(client, admin, task, data).status_code == 200
    path = hf_zip.hf_zip_path(_sha(data))
    os.utime(path, (1000, 1000))
    before = environment_package.fingerprint(environment_package.package_plan([task]))
    assert _put_zip(client, admin, task, data).status_code == 200
    assert os.stat(path).st_mtime == 1000
    task = db.session.get(Task, task.id)
    after = environment_package.fingerprint(environment_package.package_plan([task]))
    assert after == before
    assert not os.listdir(incoming_dir())


def test_the_real_entry_count_and_the_file_cap_are_enforced(
    client, admin, db_session, sample_challenge, monkeypatch
):
    task = _task(db_session, sample_challenge)
    monkeypatch.setattr(hf_zip, "MAX_FILES", 2)
    many = hf_zip_bytes({f"datasets/acme/d/{i}.txt": b"x" for i in range(3)})
    response = _put_zip(client, admin, task, many)
    assert response.status_code == 422
    assert "more than 2 files" in response.get_json()["detail"]

    monkeypatch.setattr(hf_zip, "MAX_MEMBERS", 2)
    original = zipfile._EndRecData  # type: ignore[attr-defined]

    def understated(handle):
        record = original(handle)
        record[zipfile._ECD_ENTRIES_TOTAL] = 1  # type: ignore[attr-defined]
        return record

    monkeypatch.setattr(zipfile, "_EndRecData", understated)
    path = os.path.join(Config.UPLOAD_FOLDER, "many.zip")
    with open(path, "wb") as handle:
        handle.write(many)
    with pytest.raises(hf_zip.HfZipError, match="more than 2 entries"):
        hf_zip.open_zip(path)


# ── Leftover files and disk ──


def test_incoming_temps_and_unlisted_files_are_swept_and_never_exported(
    client, admin, tokens, auth_headers, db_session, sample_challenge
):
    task = _task(db_session, sample_challenge)
    listed = _put_file(client, admin, task, "train.csv", b"id\n1\n").get_json()["files"][0]
    task_dir = os.path.join(Config.UPLOAD_FOLDER, f"task_{task.id}")
    old = time.time() - 7 * 3600
    for name in ("stale-crash.csv", "fresh-crash.csv"):
        with open(os.path.join(task_dir, name), "w") as handle:
            handle.write("x")
    os.utime(os.path.join(task_dir, "stale-crash.csv"), (old, old))
    os.makedirs(incoming_dir(), exist_ok=True)
    for name in (".upload-old.part", ".upload-new.part"):
        with open(os.path.join(incoming_dir(), name), "w") as handle:
            handle.write("x")
    os.utime(os.path.join(incoming_dir(), ".upload-old.part"), (old, old))

    exported = client.get(
        f"/api/challenges/{sample_challenge.id}/export", headers=auth_headers(tokens.admin)
    )
    with zipfile.ZipFile(io.BytesIO(exported.data)) as archive:
        names = [n for n in archive.namelist() if n.startswith("tasks/")]
    assert names == [f"tasks/{task.id}/{listed['saved_name']}"]

    assert sweep_incoming() == 1
    assert os.listdir(incoming_dir()) == [".upload-new.part"]
    assert sweep_task_dirs() == 1
    assert sorted(os.listdir(task_dir)) == sorted([listed["saved_name"], "fresh-crash.csv"])


def test_the_backup_leaves_uploads_in_progress_out():
    import inspect

    from tasks.task_modules import system

    assert '--exclude={uploads_name}/.incoming"' in inspect.getsource(system.run_backup)


def test_an_upload_larger_than_the_free_disk_is_refused(
    client, admin, db_session, sample_challenge, monkeypatch
):
    task = _task(db_session, sample_challenge)
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(
        "utils.uploads.shutil.disk_usage", lambda _path: usage(0, 0, 2 * 1024**3 + 10)
    )
    response = _put_file(client, admin, task, "train.csv", b"x" * 100)
    assert response.status_code == 507
    body = response.get_json()
    assert (body["code"], body["limit"]) == ("ERR_UPLOAD_NO_SPACE", "0 MB")
    assert not os.path.exists(os.path.join(Config.UPLOAD_FOLDER, f"task_{task.id}"))


# ── Locks ──


def test_a_held_owner_lock_answers_busy_with_retry_after(
    client, admin, db_session, sample_challenge, monkeypatch
):
    monkeypatch.setattr("utils.uploads.STORE_LOCK_WAIT_SECONDS", 0)
    task = _task(db_session, sample_challenge)
    with cache_lock(f"upload_store:owner:{sample_challenge.id}:-") as got:
        assert got
        for response in (
            _put_file(client, admin, task, "train.csv", b"id\n1\n"),
            _put_zip(client, admin, task, hf_zip_bytes()),
            client.delete(f"/api/tasks/{task.id}/hf-zip", headers=admin),
        ):
            assert response.status_code == 503
            assert response.get_json()["code"] == "ERR_UPLOAD_STORE_BUSY"
            assert response.headers["Retry-After"]
    assert not os.listdir(incoming_dir())


def _stages(db_session, challenge):
    stages = []
    for number in (1, 2):
        stage = Stage(
            challenge_id=challenge.id,
            title=f"Round {number}",
            stage_number=number,
            start_time=challenge.start_time,
            end_time=challenge.end_time,
        )
        db_session.add(stage)
        stages.append(stage)
    db_session.commit()
    return stages


def test_moving_a_task_checks_the_target_package(client, admin, db_session, sample_challenge):
    _environments_on(db_session, sample_challenge)
    first_stage, second_stage = _stages(db_session, sample_challenge)
    first = _task(db_session, sample_challenge, stage=first_stage)
    second = _task(db_session, sample_challenge, title="Two", folder="two", stage=second_stage)
    assert _put_zip(client, admin, first, hf_zip_bytes()).status_code == 200
    other = hf_zip_bytes({"models/acme/tiny/config.json": b"{}"})
    assert _put_zip(client, admin, second, other).status_code == 200
    moved = client.put(
        f"/api/tasks/{second.id}",
        headers=admin,
        data={"stage_id": str(first_stage.id)},
        content_type="multipart/form-data",
    )
    assert moved.status_code == 409
    body = moved.get_json()
    assert (body["code"], body["folder"], body["detail"]) == (
        "ERR_HF_FOLDER_CONFLICT",
        "models/acme/tiny",
        "BERT",
    )
    assert db.session.get(Task, second.id).stage_id == second_stage.id


def test_a_held_target_lock_refuses_a_stage_move(
    client, admin, db_session, sample_challenge, monkeypatch
):
    monkeypatch.setattr("utils.uploads.STORE_LOCK_WAIT_SECONDS", 0)
    _environments_on(db_session, sample_challenge)
    first_stage, second_stage = _stages(db_session, sample_challenge)
    task = _task(db_session, sample_challenge, stage=second_stage)
    with cache_lock(f"upload_store:owner:{sample_challenge.id}:{first_stage.id}") as got:
        assert got
        moved = client.put(
            f"/api/tasks/{task.id}",
            headers=admin,
            data={"stage_id": str(first_stage.id)},
            content_type="multipart/form-data",
        )
    assert moved.status_code == 503
    assert moved.get_json()["code"] == "ERR_UPLOAD_STORE_BUSY"
    assert db.session.get(Task, task.id).stage_id == second_stage.id


def test_a_stage_move_holds_the_target_lock_until_it_commits(
    client, admin, db_session, sample_challenge
):
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    _environments_on(db_session, sample_challenge)
    first_stage, second_stage = _stages(db_session, sample_challenge)
    task = _task(db_session, sample_challenge, stage=second_stage)
    key = f"upload_store:owner:{sample_challenge.id}:{first_stage.id}"
    held = []

    def probe(session):
        for obj in [*session.identity_map.values(), *session.dirty]:
            if isinstance(obj, Task) and obj.id == task.id and obj.stage_id == first_stage.id:
                with cache_lock(key) as got:
                    held.append(not got)
                return

    event.listen(Session, "before_commit", probe)
    try:
        moved = client.put(
            f"/api/tasks/{task.id}",
            headers=admin,
            data={"stage_id": str(first_stage.id)},
            content_type="multipart/form-data",
        )
    finally:
        event.remove(Session, "before_commit", probe)
    assert moved.status_code == 200, moved.get_json()
    # A second move into the stage waits from the projected check through this commit
    assert held[0] is True
    assert held[-1] is False


# ── Access ──


def test_a_jury_member_gets_404_for_a_missing_task_before_the_body(
    client, csrf_headers, create_user, db_session
):
    jury = create_user(username="jury_missing", role="jury")
    db_session.commit()
    headers = {**csrf_headers(generate_token(jury.id, "jury")), "Content-Type": "application/json"}
    response = client.put(
        "/api/tasks/00000000-0000-7000-8000-000000000000/hf-zip", data=b"{bad json", headers=headers
    )
    assert response.status_code == 404
    assert response.get_json()["code"] == "ERR_TASK_NOT_FOUND"


def test_an_unassigned_jury_member_cannot_change_task_data(
    client, csrf_headers, create_user, db_session, sample_challenge
):
    task = _task(db_session, sample_challenge)
    jury = create_user(username="jury_other", role="jury")
    db_session.commit()
    JuryChallenge.query.filter_by(jury_id=jury.id).delete()
    db_session.commit()
    headers = csrf_headers(generate_token(jury.id, "jury"))
    responses = [
        _put_file(client, headers, task, "train.csv", b"id\n1\n"),
        client.delete(f"/api/tasks/{task.id}/files/train.csv", headers=headers),
        _put_zip(client, headers, task, hf_zip_bytes()),
        client.delete(f"/api/tasks/{task.id}/hf-zip", headers=headers),
    ]
    assert [r.status_code for r in responses] == [403] * 4


# ── Audit, problem codes, fields ──


def test_replacing_a_file_records_its_previous_visibility_and_size(
    client, admin, db_session, sample_challenge
):
    task = _task(db_session, sample_challenge)
    assert _put_file(client, admin, task, "notes.csv", b"12345", "hidden").status_code == 200
    assert _put_file(client, admin, task, "notes.csv", b"1", "public").status_code == 200
    entry = AuditLog.query.filter_by(target_type="task").order_by(AuditLog.id.desc()).first()
    assert entry.details["replaced_visibility"] == "hidden"
    assert entry.details["replaced_size_bytes"] == 5


def test_missing_files_show_as_problem_codes_for_staff_only(
    client, admin, tokens, csrf_headers, db_session, sample_challenge
):
    notebook = _task(db_session, sample_challenge)
    file_task = _task(db_session, sample_challenge, title="File", folder="file", mode="file")
    assert _view(client, admin, notebook)["problem_codes"] == ["ERR_TASK_LABELS_MISSING"]
    assert _view(client, admin, file_task)["problem_codes"] == [
        "ERR_BASELINE_SUBMISSION_MISSING",
        "ERR_TASK_LABELS_MISSING",
    ]
    data = hf_zip_bytes()
    assert _put_zip(client, admin, notebook, data).status_code == 200
    os.remove(hf_zip.hf_zip_path(_sha(data)))
    assert "ERR_HF_ZIP_MISSING" in _view(client, admin, notebook)["problem_codes"]
    competitor = _view(client, csrf_headers(tokens.competitor), notebook)
    assert competitor.get("problem_codes") is None


def test_a_successful_build_clears_an_hf_sync_failure(client, db_session, sample_challenge):
    task = _task(db_session, sample_challenge)
    task.problem_codes = ["ERR_HF_DATA_SYNC_FAILED"]
    db_session.commit()
    with patch("routes.tasks._task_capability", return_value={"attempt_id": "a"}):
        response = client.post(
            f"/api/worker/tasks/{task.id}/report-build-error",
            json={"error": ""},
            headers={"X-Worker-Token": "valid-token"},
        )
    assert response.status_code == 200
    assert db.session.get(Task, task.id).problem_codes is None


def test_a_run_that_prepared_the_hf_data_clears_a_recorded_hf_failure(
    client, db_session, sample_challenge, sample_competitor
):
    task = _task(db_session, sample_challenge)
    task.hf_zip_sha256 = "a" * 64
    task.problem_codes = ["ERR_BASELINE_FAILED", "ERR_HF_DATA_SYNC_FAILED"]
    stale = Submission(
        user_id=sample_competitor.id,
        challenge_id=sample_challenge.id,
        task_id=task.id,
        status="queued",
        hf_zip_sha256="b" * 64,
        celery_task_id="attempt-1",
    )
    current = Submission(
        user_id=sample_competitor.id,
        challenge_id=sample_challenge.id,
        task_id=task.id,
        status="queued",
        hf_zip_sha256="a" * 64,
        celery_task_id="attempt-2",
    )
    db_session.add_all([stale, current])
    db_session.commit()

    def report(submission):
        with (
            patch("routes.tasks.check_worker_auth", return_value={"worker_id": "w"}),
            patch("routes.tasks._worker_capability", return_value=True),
        ):
            return client.post(
                f"/api/worker/report/{submission.id}",
                json={
                    "status": "running",
                    "detailed_status": "running_inference",
                    "hf_ready": True,
                },
                headers={"X-Worker-Token": "valid-token"},
            )

    # A run that prepared a superseded ZIP proves nothing about the task's current one
    assert report(stale).status_code == 200
    assert "ERR_HF_DATA_SYNC_FAILED" in db.session.get(Task, task.id).problem_codes
    assert report(current).status_code == 200
    assert db.session.get(Task, task.id).problem_codes == ["ERR_BASELINE_FAILED"]


def test_runs_past_a_sync_step_clear_its_failure_without_a_rebuild(
    client, db_session, sample_challenge, sample_competitor
):
    task = _task(db_session, sample_challenge)
    task.problem_codes = ["ERR_TASK_FILE_SYNC_FAILED", "ERR_TASK_LABELS_SYNC_FAILED"]
    run = Submission(
        user_id=sample_competitor.id,
        challenge_id=sample_challenge.id,
        task_id=task.id,
        status="queued",
        celery_task_id="attempt-1",
    )
    db_session.add(run)
    db_session.commit()

    def report(payload):
        with (
            patch("routes.tasks.check_worker_auth", return_value={"worker_id": "w"}),
            patch("routes.tasks._worker_capability", return_value=True),
        ):
            return client.post(
                f"/api/worker/report/{run.id}",
                json=payload,
                headers={"X-Worker-Token": "valid-token"},
            )

    assert report({"status": "running", "detailed_status": "running_inference"}).status_code == 200
    assert db.session.get(Task, task.id).problem_codes == ["ERR_TASK_LABELS_SYNC_FAILED"]
    done = {"status": "completed", "detailed_status": "completed", "public_score": 0.5}
    assert report(done).status_code == 200
    assert not db.session.get(Task, task.id).problem_codes


def test_refusals_send_the_fields_their_texts_use(
    client, admin, db_session, sample_challenge, monkeypatch
):
    task = _task(db_session, sample_challenge)
    invalid = _put_zip(client, admin, task, hf_zip_bytes({"weights/acme/tiny/a.bin": b"x"}))
    body = invalid.get_json()
    assert (body["file"], body["detail"]) == ("weights/acme/tiny/a.bin", body["error"])
    assert body["reason"] == "outside_folders"

    _environments_on(db_session, sample_challenge)
    monkeypatch.setattr(Config, "NANOCOLAB_PACKAGE_MAX_BYTES", 10)
    large = _put_zip(client, admin, task, hf_zip_bytes())
    body = large.get_json()
    assert body["code"] == "ERR_ENVIRONMENT_PACKAGE_TOO_LARGE"
    assert (body["detail"], body["limit"], body["reason"]) == ("0 MB", "0 MB", "package_size")


def test_a_failed_package_keeps_its_fields_for_the_status(db_session, sample_challenge):
    env = Environment(challenge_id=sample_challenge.id, enabled=True, image_id="py")
    db_session.add(env)
    db_session.commit()
    environment_service._package_failed(
        env,
        "ERR_ENVIRONMENT_PACKAGE_TOO_LARGE",
        "The package would hold 2001 files, more than 2000.",
        {"limit": "2000", "detail": "2001", "reason": "package_files"},
    )
    db_session.commit()
    status = environment_service.environment_status(env)
    assert (status["code"], status["detail"], status["limit"], status["reason"]) == (
        "ERR_ENVIRONMENT_PACKAGE_TOO_LARGE",
        "2001",
        "2000",
        "package_files",
    )
    assert status["folder"] is None


def test_hf_applies_to_notebook_runs_and_to_file_tasks_with_workspaces(
    client, admin, tokens, csrf_headers, db_session, sample_challenge
):
    notebook = _task(db_session, sample_challenge)
    file_task = _task(db_session, sample_challenge, title="File", folder="file", mode="file")
    student = csrf_headers(tokens.competitor)
    assert _view(client, student, notebook)["hf_applies"] is True
    assert _view(client, student, file_task)["hf_applies"] is False
    _environments_on(db_session, sample_challenge)
    assert _view(client, admin, file_task)["hf_applies"] is True


# ── No ZIP reads on the web host ──


def test_the_environment_view_reads_no_zip(client, admin, db_session, sample_challenge):
    _environments_on(db_session, sample_challenge)
    task = _task(db_session, sample_challenge)
    task.baseline_notebook_path = None
    assert _put_zip(client, admin, task, hf_zip_bytes()).status_code == 200
    owner = environment_service.owner_of_task(db.session.get(Task, task.id))
    with (
        patch("services.hf_zip.inspect_zip", side_effect=AssertionError("read")),
        patch("services.hf_zip.open_zip", side_effect=AssertionError("read")),
    ):
        view = environment_service.environment_dict(None, owner)
        plan = environment_package.package_plan(owner.tasks())
        environment_package.check_projected(owner.tasks(), task)
    assert view["data_gib"] == 1
    assert plan.hf_bytes == len(CONFIG)


def test_an_unchanged_package_is_not_unzipped_by_the_sync(
    db_session, sample_challenge, client, admin
):
    _environments_on(db_session, sample_challenge)
    task = _task(db_session, sample_challenge)
    assert _put_zip(client, admin, task, hf_zip_bytes()).status_code == 200
    owner = environment_service.owner_of_task(db.session.get(Task, task.id))
    env = Environment(challenge_id=sample_challenge.id, enabled=True, image_id="py")
    env.package_fingerprint = environment_package.fingerprint(
        environment_package.package_plan(owner.tasks())
    )
    env.asset_version = "lb-x-v1"
    env.package_state = "READY"
    env.workspace_gib = 4
    db_session.add(env)
    db_session.commit()
    with patch("services.hf_zip.inspect_zip", side_effect=AssertionError("read")):
        environment_service.ensure_package(env, owner, client=None)  # type: ignore[arg-type]
    assert env.package_state == "READY"


def test_a_dispatch_that_cannot_build_its_metadata_leaves_no_queued_row(
    db_session, sample_challenge, sample_admin, tmp_path, monkeypatch
):
    notebook = tmp_path / "baseline.ipynb"
    notebook.write_text(json.dumps(NOTEBOOK))
    task = _task(db_session, sample_challenge)
    task.baseline_notebook_path = str(notebook)
    db_session.commit()
    monkeypatch.setattr(Config, "EVALUATION_SPLIT_SECRET", "")
    with patch("tasks.evaluate_submission.apply_async") as enqueued:
        assert baseline_service.queue_baseline(task, sample_challenge, sample_admin.id) is None
    enqueued.assert_not_called()
    run = Submission.query.filter_by(task_id=task.id).one()
    assert (run.status, run.detailed_status, run.celery_task_id) == ("failed", "failed_infra", None)
