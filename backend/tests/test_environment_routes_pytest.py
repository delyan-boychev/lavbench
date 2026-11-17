"""Tests for nanoColab environments: settings, sync, publish, locks, extension and launch."""

import io
import json
import os
import zipfile
from datetime import UTC, datetime, timedelta

import pytest

from config import Config
from models import AuditLog, Challenge, Environment, Stage, Submission, Task, User, Workspace
from services import environment_package, environment_service
from tests.helpers.nanocolab_fake import install
from utils.auth_utils import generate_token
from utils.dates import utcnow

NOTEBOOK = json.dumps({"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": []}).encode()


@pytest.fixture
def fake(monkeypatch, tmp_path):
    return install(monkeypatch, tmp_path)


@pytest.fixture
def queued(monkeypatch):
    calls = []
    monkeypatch.setattr(environment_service, "enqueue_sync", calls.append)
    return calls


@pytest.fixture
def stage(db_session, sample_challenge):
    stage = Stage(
        title="Round 1",
        challenge_id=sample_challenge.id,
        stage_number=1,
        start_time=utcnow() - timedelta(minutes=30),
        end_time=utcnow() + timedelta(minutes=60),
    )
    db_session.add(stage)
    db_session.commit()
    return stage


def _task(db_session, challenge, stage, title="Image Classification"):
    task = Task(challenge_id=challenge.id, stage_id=stage.id if stage else None, title=title)
    db_session.add(task)
    db_session.flush()
    folder = f"{Config.UPLOAD_FOLDER}/task_{task.id}"
    os.makedirs(folder, exist_ok=True)
    with open(f"{folder}/0_train.csv", "wb") as handle:
        handle.write(b"id,x\n1,2\n")
    with open(f"{folder}/1_labels.parquet", "wb") as handle:
        handle.write(b"PAR1secret")
    with open(f"{folder}/baseline_starter.ipynb", "wb") as handle:
        handle.write(NOTEBOOK)
    task.files = json.dumps(
        [
            {"filename": "train.csv", "saved_name": "0_train.csv", "size_bytes": 9},
            {"filename": "labels.parquet", "saved_name": "1_labels.parquet", "size_bytes": 10},
        ]
    )
    task.baseline_notebook_path = f"{folder}/baseline_starter.ipynb"
    db_session.commit()
    return task


@pytest.fixture
def task(db_session, sample_challenge, stage, fake):
    return _task(db_session, sample_challenge, stage)


@pytest.fixture
def jury_token(create_user, db_session):
    jury = create_user(username="jury_env", role="jury")
    db_session.commit()
    return generate_token(jury.id, "jury")


WORKSPACE = {
    "enabled": True,
    "image_id": "python-ml",
    "profile_id": "cpu-compact",
    "workspace_gib": 10,
}


class _Found:
    """One environment from the list, shaped like a response."""

    status_code = 200

    def __init__(self, body):
        self._body = body

    def get_json(self):
        return self._body


def _environments(client, headers, challenge):
    return client.get(f"/api/challenges/{challenge.id}/environments", headers=headers)


def _get(client, headers, challenge, stage):
    rows = _environments(client, headers, challenge).get_json()["environments"]
    stage_id = str(stage.id) if stage else None
    return _Found(next(row for row in rows if row["stage_id"] == stage_id))


def _set_workspace(client, headers, challenge, **changes):
    body = {"workspace": {**WORKSPACE, **changes}}
    return client.put(f"/api/challenges/{challenge.id}", json=body, headers=headers)


def _save(client, headers, challenge, stage, **changes):
    response = _set_workspace(client, headers, challenge, **changes)
    if response.status_code != 200:
        return response
    return _get(client, headers, challenge, stage)


def _ready_environment(client, admin, challenge, stage):
    response = _save(client, admin, challenge, stage)
    assert response.status_code == 200, response.get_json()
    env_id = response.get_json()["id"]
    assert environment_service.sync_environment(env_id) == "ok"
    return env_id


def _publish(client, admin, challenge, env_id):
    return client.post(
        f"/api/challenges/{challenge.id}/environments/{env_id}/publish", headers=admin
    )


# ── Disabled integration ──


def test_routes_answer_disabled_without_url(client, sample_challenge, tokens, auth_headers):
    response = _environments(client, auth_headers(tokens.admin), sample_challenge)
    assert response.status_code == 404
    assert response.get_json()["code"] == "ERR_NANOCOLAB_DISABLED"


def test_enabling_workspaces_without_nanocolab_is_a_field_error(
    client, sample_challenge, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    response = _set_workspace(client, admin, sample_challenge)
    assert response.status_code == 422
    assert response.get_json()["field"] == "workspace.enabled"
    assert _set_workspace(client, admin, sample_challenge, enabled=False).status_code == 200


# ── Competition setting ──


def test_list_shows_defaults_and_never_calls_nanocolab(
    client, fake, sample_challenge, stage, tokens, auth_headers
):
    body = _get(client, auth_headers(tokens.admin), sample_challenge, stage).get_json()
    assert body["id"] is None
    assert body["stage_title"] == "Round 1"
    assert (body["cpu_cores"], body["memory_gib"], body["workspace_gib"]) == (2, 8, 10)
    assert body["status"]["state"] == "off"
    assert fake.calls == []


def test_setting_derives_each_stage_environment_and_queues_a_sync(
    client, fake, queued, db_session, sample_challenge, stage, task, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    response = _set_workspace(client, admin, sample_challenge, profile_id="cpu-standard")
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["workspace"]["profile_id"] == "cpu-standard"
    env = Environment.query.one()
    assert env.stage_id == stage.id
    assert (env.enabled, env.image_id, env.cpu_cores, env.memory_gib) == (True, "python-ml", 2, 12)
    assert queued == [env.id]
    body = _get(client, admin, sample_challenge, stage).get_json()
    assert body["folders"] == ["image-classification"]
    entry = AuditLog.query.filter_by(target_type="challenge", action_type="update").one()
    assert entry.details["workspace"]["profile_id"] == "cpu-standard"


def test_new_stages_inherit_the_setting_and_follow_its_edits(
    client, fake, queued, db_session, sample_challenge, stage, task, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    assert _set_workspace(client, admin, sample_challenge).status_code == 200
    created = client.post(
        f"/api/challenges/{sample_challenge.id}/stages",
        json={
            "title": "Round 2",
            "start_time": (stage.end_time + timedelta(minutes=10)).isoformat(),
            "end_time": (stage.end_time + timedelta(minutes=50)).isoformat(),
        },
        headers=admin,
    )
    assert created.status_code == 201, created.get_json()
    second = db_session.get(Stage, created.get_json()["id"])
    assert second.environment.enabled and second.environment.image_id == "python-ml"
    edited = _set_workspace(client, admin, sample_challenge, workspace_gib=20, auto_publish=True)
    assert edited.status_code == 200
    for env in Environment.query.all():
        assert (env.workspace_gib, env.auto_publish) == (20, True)
    assert _set_workspace(client, admin, sample_challenge, enabled=False).status_code == 200
    assert not any(env.enabled for env in Environment.query.all())


def test_published_stages_keep_their_settings_while_others_follow(
    client, fake, queued, db_session, sample_challenge, stage, task, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    later = Stage(
        title="Round 2",
        challenge_id=sample_challenge.id,
        stage_number=2,
        start_time=stage.end_time + timedelta(minutes=10),
        end_time=stage.end_time + timedelta(minutes=50),
    )
    db_session.add(later)
    db_session.commit()
    env_id = _ready_environment(client, admin, sample_challenge, stage)
    assert _publish(client, admin, sample_challenge, env_id).status_code == 200
    edited = _set_workspace(client, admin, sample_challenge, workspace_gib=40)
    assert edited.status_code == 200, edited.get_json()
    published = db_session.get(Environment, env_id)
    assert published.workspace_gib == 10
    assert Environment.query.filter_by(stage_id=later.id).one().workspace_gib == 40


def test_nanocolab_is_asked_only_when_the_image_or_profile_changes(
    client, fake, queued, sample_challenge, stage, task, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    assert _set_workspace(client, admin, sample_challenge).status_code == 200
    fake.calls.clear()
    fake.fail("GET", "/v1/images", 503, "down")
    resized = _set_workspace(client, admin, sample_challenge, workspace_gib=30)
    assert resized.status_code == 200
    assert ("GET", "/v1/images") not in fake.calls
    changed = _set_workspace(client, admin, sample_challenge, profile_id="cpu-standard")
    assert changed.status_code == 503
    assert changed.get_json()["code"] == "ERR_NANOCOLAB_UNAVAILABLE"


def test_field_errors_name_the_field_and_the_allowed_values(
    client, fake, queued, sample_challenge, stage, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    cases = [
        ({"image_id": "nope"}, "ERR_INVALID_WORKSPACE_IMAGE", "workspace.image_id"),
        ({"image_id": ""}, "ERR_INVALID_WORKSPACE_IMAGE", "workspace.image_id"),
        ({"image_id": "Bad Image"}, "ERR_INVALID_WORKSPACE_IMAGE", "workspace.image_id"),
        ({"profile_id": "gpu-huge"}, "ERR_INVALID_WORKSPACE_PROFILE", "workspace.profile_id"),
        ({"workspace_gib": 5}, "ERR_INVALID_WORKSPACE_SIZE", "workspace.workspace_gib"),
        ({"workspace_gib": 500}, "ERR_INVALID_WORKSPACE_SIZE", "workspace.workspace_gib"),
        ({"workspace_gib": "ten"}, "ERR_INVALID_WORKSPACE_SIZE", "workspace.workspace_gib"),
        (
            {"archive_until": "2000-01-01T00:00"},
            "ERR_INVALID_ARCHIVE_DATE",
            "workspace.archive_until",
        ),
        ({"archive_until": "soon"}, "ERR_INVALID_DATE_FORMAT", "workspace.archive_until"),
    ]
    for changes, code, field in cases:
        body = _set_workspace(client, admin, sample_challenge, **changes).get_json()
        assert (body["code"], body["field"]) == (code, field), changes
    profile = _set_workspace(client, admin, sample_challenge, profile_id="gpu-huge").get_json()
    assert profile["allowed"] == "CPU Compact, CPU Standard"
    assert profile["error"] == "Profile must be one of: CPU Compact, CPU Standard."
    size = _set_workspace(client, admin, sample_challenge, workspace_gib=5).get_json()
    assert (size["min"], size["max"]) == (10, 98)
    assert "between 10 and 98 GiB" in size["error"]
    assert Environment.query.count() == 0


def test_profiles_come_from_nanocolab_with_a_built_in_fallback(
    client, fake, queued, sample_challenge, stage, task, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    listing = client.get("/api/environment/images", headers=admin).get_json()
    assert [p["id"] for p in listing["profiles"]] == ["cpu-compact", "cpu-standard"]
    assert listing["workspace_gib"] == {"min": 10, "max": 98, "default": 10}
    fake.profiles = [
        {"id": "cpu-large", "name": "CPU Large", "cpu_cores": 2, "memory_gib": 12},
        {"id": "broken", "name": "", "cpu_cores": 2, "memory_gib": 8},
    ]
    listing = client.get("/api/environment/images", headers=admin).get_json()
    assert [p["id"] for p in listing["profiles"]] == ["cpu-large"]
    refused = _set_workspace(client, admin, sample_challenge).get_json()
    assert refused["code"] == "ERR_INVALID_WORKSPACE_PROFILE"
    assert refused["allowed"] == "CPU Large"
    saved = _set_workspace(client, admin, sample_challenge, profile_id="cpu-large")
    assert saved.status_code == 200
    assert Environment.query.one().memory_gib == 12


def test_created_competition_takes_the_setting(client, fake, queued, tokens, auth_headers):
    response = client.post(
        "/api/challenges",
        json={
            "title": "With workspaces",
            "start_time": (utcnow() + timedelta(days=1)).isoformat(),
            "end_time": (utcnow() + timedelta(days=2)).isoformat(),
            "workspace": {**WORKSPACE, "workspace_gib": 15},
        },
        headers=auth_headers(tokens.admin),
    )
    assert response.status_code == 201, response.get_json()
    assert response.get_json()["workspace"]["workspace_gib"] == 15
    env = Environment.query.one()
    assert str(env.challenge_id) == response.get_json()["id"]
    assert env.workspace_gib == 15
    invalid = client.post(
        "/api/challenges",
        json={
            "title": "Refused",
            "start_time": (utcnow() + timedelta(days=1)).isoformat(),
            "end_time": (utcnow() + timedelta(days=2)).isoformat(),
            "workspace": {**WORKSPACE, "image_id": "nope"},
        },
        headers=auth_headers(tokens.admin),
    )
    assert invalid.get_json()["code"] == "ERR_INVALID_WORKSPACE_IMAGE"
    assert Challenge.query.filter_by(title="Refused").count() == 0


def test_disk_is_the_work_space_plus_the_task_data(
    client,
    fake,
    queued,
    monkeypatch,
    db_session,
    sample_challenge,
    stage,
    task,
    tokens,
    auth_headers,
):
    admin = auth_headers(tokens.admin)
    monkeypatch.setattr(environment_package, "GIB", 4)
    assert _set_workspace(client, admin, sample_challenge, workspace_gib=12).status_code == 200
    env = Environment.query.one()
    data = environment_package.data_gib(environment_package.package_entries([task]))
    assert data > 1
    assert env.disk_gib == 12 + data
    body = _get(client, admin, sample_challenge, stage).get_json()
    assert (body["workspace_gib"], body["data_gib"], body["disk_gib"]) == (12, data, 12 + data)
    with open(f"{Config.UPLOAD_FOLDER}/task_{task.id}/2_extra.csv", "wb") as handle:
        handle.write(b"x" * 64)
    files = json.loads(task.files)
    files.append({"filename": "extra.csv", "saved_name": "2_extra.csv", "size_bytes": 64})
    task.files = json.dumps(files)
    db_session.commit()
    body = _get(client, admin, sample_challenge, stage).get_json()
    assert body["data_gib"] == data + 16
    assert body["disk_gib"] == 12 + data + 16
    assert environment_service.sync_environment(env.id) == "ok"
    assert Environment.query.one().disk_gib == 12 + data + 16
    assert fake.events[f"stage-{stage.id}"]["profile"]["disk_gib"] == 12 + data + 16


def test_jury_reads_but_cannot_write(
    client, fake, queued, sample_challenge, stage, task, tokens, auth_headers, jury_token
):
    jury = auth_headers(jury_token)
    assert _environments(client, jury, sample_challenge).status_code == 200
    assert _set_workspace(client, jury, sample_challenge).status_code == 403
    assert client.get("/api/environment/images", headers=jury).status_code == 403
    env_id = _ready_environment(client, auth_headers(tokens.admin), sample_challenge, stage)
    assert _publish(client, jury, sample_challenge, env_id).status_code == 403
    extension = client.post(
        f"/api/challenges/{sample_challenge.id}/environments/{env_id}/extension",
        json={"end_time": "2099-01-01T00:00:00", "reason": "network outage at venue"},
        headers=jury,
    )
    assert extension.status_code == 403
    listing = client.get(
        f"/api/challenges/{sample_challenge.id}/environments/{env_id}/workspaces", headers=jury
    )
    assert listing.status_code == 200


def test_competition_with_stages_has_no_environment_of_its_own(
    client, fake, queued, sample_challenge, stage, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    assert _set_workspace(client, admin, sample_challenge).status_code == 200
    rows = _environments(client, admin, sample_challenge).get_json()["environments"]
    assert [row["stage_id"] for row in rows] == [str(stage.id)]
    assert Environment.query.filter_by(challenge_id=sample_challenge.id).count() == 0


def test_overlapping_stages_are_refused_while_workspaces_are_on(
    client, fake, queued, db_session, sample_challenge, stage, task, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    assert _set_workspace(client, admin, sample_challenge).status_code == 200
    created = client.post(
        f"/api/challenges/{sample_challenge.id}/stages",
        json={
            "title": "Round 2",
            "start_time": stage.end_time.isoformat(),
            "end_time": (stage.end_time + timedelta(minutes=50)).isoformat(),
        },
        headers=admin,
    )
    assert created.status_code == 409
    assert created.get_json()["code"] == "ERR_ENVIRONMENT_OVERLAP"
    assert created.get_json()["stages"] == "Round 2, Round 1"
    assert _set_workspace(client, admin, sample_challenge, enabled=False).status_code == 200
    second = Stage(
        title="Round 2",
        challenge_id=sample_challenge.id,
        stage_number=2,
        start_time=stage.end_time,
        end_time=stage.end_time + timedelta(minutes=50),
    )
    db_session.add(second)
    db_session.commit()
    response = _set_workspace(client, admin, sample_challenge)
    assert response.status_code == 409
    assert response.get_json()["code"] == "ERR_ENVIRONMENT_OVERLAP"


# ── Sync and status ──


def test_sync_uploads_the_package_and_puts_the_event_with_grace(
    client,
    fake,
    queued,
    db_session,
    sample_challenge,
    stage,
    task,
    sample_competitor,
    tokens,
    auth_headers,
):
    env_id = _ready_environment(client, auth_headers(tokens.admin), sample_challenge, stage)
    env = db_session.get(Environment, env_id)
    assert env.package_state == "READY"
    payload = fake.events[f"stage-{stage.id}"]
    ends_at = datetime.fromisoformat(payload["ends_at"]).replace(tzinfo=None)
    assert ends_at == stage.end_time + timedelta(seconds=Config.DEADLINE_GRACE_PERIOD_SECONDS)
    assert payload["published"] is False
    assert payload["max_attendance"] == 2 + 2
    assert payload["export_paths"] == ["image-classification/solution.ipynb"]
    assert payload["actor"] == "lavbench-sync"
    names = sorted(_zip_names(fake.uploads[env.asset_version]))
    assert names == ["image-classification/solution.ipynb", "image-classification/train.csv"]
    status = _get(client, auth_headers(tokens.admin), sample_challenge, stage)
    assert status.get_json()["status"]["state"] == "ready"
    assert environment_service.sync_environment(env_id) == "ok"
    assert len(fake.uploads) == 1


def test_upload_progress_signals_each_ten_percent_step(
    monkeypatch, db_session, sample_challenge, stage
):
    env = Environment(stage_id=stage.id, enabled=True)
    db_session.add(env)
    db_session.commit()
    signals = []
    monkeypatch.setattr(environment_service, "publish_environment_update", signals.append)
    report = environment_service._upload_progress(env, 1000, sample_challenge.id)
    for sent in (50, 100, 150, 250, 300, 1000):
        report(sent)
    assert signals == [sample_challenge.id] * 3
    assert db_session.get(Environment, env.id).package_progress == 99


def test_package_problem_is_shown_with_its_code(
    client, fake, queued, db_session, sample_challenge, stage, tokens, auth_headers
):
    empty = Task(challenge_id=sample_challenge.id, stage_id=stage.id, title="Empty", files="[]")
    db_session.add(empty)
    db_session.commit()
    response = _save(client, auth_headers(tokens.admin), sample_challenge, stage)
    env_id = response.get_json()["id"]
    assert environment_service.sync_environment(env_id) == "problem"
    status = _get(client, auth_headers(tokens.admin), sample_challenge, stage)
    assert status.get_json()["status"]["code"] == "ERR_ENVIRONMENT_PACKAGE_EMPTY"
    published = _publish(client, auth_headers(tokens.admin), sample_challenge, env_id)
    assert published.status_code == 422
    assert published.get_json()["code"] == "ERR_ENVIRONMENT_PACKAGE_EMPTY"
    sync_audit = AuditLog.query.filter_by(action_type="sync").one()
    assert sync_audit.details["code"] == "ERR_ENVIRONMENT_PACKAGE_EMPTY"


def test_rejected_package_shows_nanocolab_message(
    client, fake, queued, sample_challenge, stage, task, tokens, auth_headers
):
    fake.complete_state = "FAILED"
    fake.complete_error = "ZIP contains hidden, reserved or unsafe paths."
    response = _save(client, auth_headers(tokens.admin), sample_challenge, stage)
    environment_service.sync_environment(response.get_json()["id"])
    status = _get(client, auth_headers(tokens.admin), sample_challenge, stage)
    body = status.get_json()["status"]
    assert body["code"] == "ERR_ENVIRONMENT_PACKAGE_FAILED"
    assert body["message"] == "ZIP contains hidden, reserved or unsafe paths."


def test_preparing_alerts_after_the_threshold(
    client, fake, queued, monkeypatch, sample_challenge, stage, task, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    env_id = _ready_environment(client, admin, sample_challenge, stage)
    fake.readiness = {"status": "PREPARING", "message": "Pulling", "retry_after_seconds": 10}
    assert _publish(client, admin, sample_challenge, env_id).status_code == 200
    environment_service.sync_environment(env_id)
    status = _get(client, admin, sample_challenge, stage).get_json()["status"]
    assert status["state"] == "preparing"
    assert status["alert"] is False
    monkeypatch.setattr(Config, "NANOCOLAB_PREPARING_ALERT_MINUTES", -1)
    status = _get(client, admin, sample_challenge, stage).get_json()["status"]
    assert status["alert"] is True
    monkeypatch.setattr(Config, "NANOCOLAB_STATUS_STALE_SECONDS", -1)
    status = _get(client, admin, sample_challenge, stage).get_json()["status"]
    assert status["state"] == "unknown"


def test_sync_failure_carries_nanocolab_message(
    client, fake, queued, sample_challenge, stage, task, tokens, auth_headers, jury_token
):
    fake.fail("PUT", "/v1/events/{external_id}", 409, "This task package belongs to another owner")
    response = _save(client, auth_headers(tokens.admin), sample_challenge, stage)
    assert environment_service.sync_environment(response.get_json()["id"]) == "problem"
    status = _get(client, auth_headers(tokens.admin), sample_challenge, stage)
    body = status.get_json()["status"]
    assert body["code"] == "ERR_ENVIRONMENT_SYNC_FAILED"
    assert body["message"] == "This task package belongs to another owner"
    jury = _get(client, auth_headers(jury_token), sample_challenge, stage)
    assert jury.get_json()["status"]["code"] == "ERR_ENVIRONMENT_SYNC_FAILED"
    assert jury.get_json()["status"]["message"] is None


def test_sync_task_has_room_for_a_large_upload():
    from tasks import sync_environment

    assert sync_environment.soft_time_limit > Config.CELERY_TASK_SOFT_TIME_LIMIT
    assert sync_environment.time_limit < environment_service.SYNC_LOCK_TTL


def test_beat_skips_environments_past_their_end_and_grace(
    db_session, sample_challenge, stage, sample_future_challenge, archived_challenge
):
    grace = timedelta(seconds=Config.DEADLINE_GRACE_PERIOD_SECONDS)
    in_grace, ended = (
        Stage(
            title=title,
            challenge_id=sample_challenge.id,
            stage_number=number,
            start_time=utcnow() - timedelta(hours=1),
            end_time=utcnow() - age,
        )
        for title, number, age in (("In grace", 2, grace / 2), ("Ended", 3, grace * 2))
    )
    db_session.add_all([in_grace, ended])
    db_session.flush()
    envs = {
        "current": Environment(stage_id=stage.id, enabled=True),
        "in_grace": Environment(stage_id=in_grace.id, enabled=True),
        "ended": Environment(stage_id=ended.id, enabled=True),
        "future_competition": Environment(challenge_id=sample_future_challenge.id, enabled=True),
        "ended_competition": Environment(challenge_id=archived_challenge.id, enabled=True),
    }
    db_session.add_all(envs.values())
    db_session.commit()
    expected = {str(envs[key].id) for key in ("current", "in_grace", "future_competition")}
    assert set(environment_service.enabled_environment_ids()) == expected


# ── Publish ──


def test_publish_sends_published_and_freezes_attendance(
    client,
    fake,
    queued,
    db_session,
    create_user,
    sample_challenge,
    stage,
    task,
    sample_competitor,
    tokens,
    auth_headers,
):
    admin = auth_headers(tokens.admin)
    env_id = _ready_environment(client, admin, sample_challenge, stage)
    response = _publish(client, admin, sample_challenge, env_id)
    assert response.status_code == 200
    assert response.get_json()["published_at"]
    assert fake.events[f"stage-{stage.id}"]["published"] is True
    assert AuditLog.query.filter_by(action_type="publish").count() == 1
    create_user(username="late_comer", challenge_id=sample_challenge.id)
    db_session.commit()
    assert environment_service.sync_environment(env_id) == "ok"
    assert fake.events[f"stage-{stage.id}"]["max_attendance"] == 2 + 2


def test_publish_waits_for_the_package(
    client, fake, queued, sample_challenge, stage, task, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    env_id = _save(client, admin, sample_challenge, stage).get_json()["id"]
    response = _publish(client, admin, sample_challenge, env_id)
    assert response.status_code == 503
    assert response.get_json()["code"] == "ERR_ENVIRONMENT_PREPARING"
    assert response.headers["Retry-After"]


def test_publish_waits_when_a_public_file_changed_since_the_sync(
    client, fake, queued, sample_challenge, stage, task, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    env_id = _ready_environment(client, admin, sample_challenge, stage)
    old_asset = Environment.query.one().asset_version
    with open(f"{Config.UPLOAD_FOLDER}/task_{task.id}/0_train.csv", "wb") as handle:
        handle.write(b"id,x\n1,2\n3,4\n")
    event_puts = fake.calls.count(("PUT", "/v1/events/{external_id}"))
    queued.clear()
    response = _publish(client, admin, sample_challenge, env_id)
    assert response.status_code == 503
    assert response.get_json()["code"] == "ERR_ENVIRONMENT_PREPARING"
    assert queued == [Environment.query.one().id]
    assert fake.calls.count(("PUT", "/v1/events/{external_id}")) == event_puts
    assert fake.events[f"stage-{stage.id}"]["published"] is False
    assert environment_service.sync_environment(env_id) == "ok"
    assert _publish(client, admin, sample_challenge, env_id).status_code == 200
    event = fake.events[f"stage-{stage.id}"]
    assert event["published"] is True
    assert event["asset_version"] not in (None, old_asset)


def test_more_than_sixteen_tasks_cannot_be_published(
    client, fake, queued, db_session, sample_challenge, stage, task, tokens, auth_headers
):
    for index in range(16):
        _task(db_session, sample_challenge, stage, title=f"Extra {index}")
    admin = auth_headers(tokens.admin)
    env_id = _save(client, admin, sample_challenge, stage).get_json()["id"]
    assert environment_service.sync_environment(env_id) == "problem"
    response = _publish(client, admin, sample_challenge, env_id)
    body = response.get_json()
    assert response.status_code == 409
    assert body["code"] == "ERR_ENVIRONMENT_TOO_MANY_TASKS"
    assert body["limit"] == "16"
    assert "16" in body["error"]
    status = _get(client, admin, sample_challenge, stage).get_json()["status"]
    assert status["code"] == "ERR_ENVIRONMENT_TOO_MANY_TASKS"
    assert status["limit"] == "16"


def test_publish_reports_an_unbuildable_package_at_once(
    client, fake, queued, db_session, sample_challenge, stage, task, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    env_id = _ready_environment(client, admin, sample_challenge, stage)
    for index in range(16):
        _task(db_session, sample_challenge, stage, title=f"Extra {index}")
    response = _publish(client, admin, sample_challenge, env_id)
    assert response.status_code == 409
    assert response.get_json()["code"] == "ERR_ENVIRONMENT_TOO_MANY_TASKS"
    assert fake.events[f"stage-{stage.id}"]["published"] is False


def test_auto_publish_inside_the_lead_time(
    client, fake, queued, sample_challenge, stage, task, tokens, auth_headers
):
    response = _save(client, auth_headers(tokens.admin), sample_challenge, stage, auto_publish=True)
    environment_service.sync_environment(response.get_json()["id"])
    env = Environment.query.one()
    assert env.published_at is not None
    assert fake.events[f"stage-{stage.id}"]["published"] is True
    entry = AuditLog.query.filter_by(action_type="publish").one()
    assert entry.admin_id is None


def test_published_environment_locks_settings_stage_times_and_files(
    client, fake, queued, sample_challenge, stage, task, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    env_id = _ready_environment(client, admin, sample_challenge, stage)
    _publish(client, admin, sample_challenge, env_id)

    changed = _set_workspace(client, admin, sample_challenge, profile_id="cpu-standard")
    assert changed.status_code == 409
    assert changed.get_json()["code"] == "ERR_ENVIRONMENT_LOCKED"
    assert _set_workspace(client, admin, sample_challenge).status_code == 200
    moved = client.put(
        f"/api/challenges/{sample_challenge.id}/stages/{stage.id}",
        json={"end_time": (stage.end_time + timedelta(minutes=5)).isoformat()},
        headers=admin,
    )
    assert moved.status_code == 409
    assert moved.get_json()["code"] == "ERR_ENVIRONMENT_LOCKED"
    # A form that rounds the stored times to minutes would move the window
    rounded = client.put(
        f"/api/challenges/{sample_challenge.id}/stages/{stage.id}",
        json={"title": "Round 1", "end_time": stage.end_time.strftime("%Y-%m-%dT%H:%M")},
        headers=admin,
    )
    assert stage.end_time.second or stage.end_time.microsecond
    assert rounded.get_json()["code"] == "ERR_ENVIRONMENT_LOCKED"
    retitled = client.put(
        f"/api/challenges/{sample_challenge.id}/stages/{stage.id}",
        json={"title": "Round 1 (final)"},
        headers=admin,
    )
    assert retitled.status_code == 200
    labels = client.put(
        f"/api/tasks/{task.id}",
        data={"file0": (io.BytesIO(b"PAR1"), "labels.parquet")},
        headers=admin,
        content_type="multipart/form-data",
    )
    assert labels.get_json().get("code") != "ERR_TASK_FILES_LOCKED"
    deleted = client.delete(
        f"/api/challenges/{sample_challenge.id}/stages/{stage.id}", headers=admin
    )
    assert deleted.get_json()["code"] == "ERR_ENVIRONMENT_LOCKED"
    upload = client.put(
        f"/api/tasks/{task.id}",
        data={"file0": (io.BytesIO(b"x"), "extra.csv")},
        headers=admin,
        content_type="multipart/form-data",
    )
    assert upload.status_code == 409
    assert upload.get_json()["code"] == "ERR_TASK_FILES_LOCKED"
    rename = client.put(
        f"/api/tasks/{task.id}",
        data={"folder_name": "other-name"},
        headers=admin,
        content_type="multipart/form-data",
    )
    assert rename.get_json()["code"] == "ERR_ENVIRONMENT_LOCKED"
    assert client.delete(f"/api/tasks/{task.id}", headers=admin).status_code == 409
    created = client.post(
        f"/api/challenges/{sample_challenge.id}/tasks",
        data={
            "title": "New",
            "stage_id": str(stage.id),
            "baseline_notebook": (io.BytesIO(NOTEBOOK), "b.ipynb"),
        },
        headers=admin,
        content_type="multipart/form-data",
    )
    assert created.get_json()["code"] == "ERR_TASK_FILES_LOCKED"
    deleted_challenge = client.delete(f"/api/challenges/{sample_challenge.id}", headers=admin)
    assert deleted_challenge.status_code == 409


# ── Extension ──


def test_extension_needs_a_reason_and_sends_it(
    client, fake, queued, db_session, sample_challenge, stage, task, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    env_id = _ready_environment(client, admin, sample_challenge, stage)
    _publish(client, admin, sample_challenge, env_id)
    url = f"/api/challenges/{sample_challenge.id}/environments/{env_id}/extension"
    new_end = (stage.end_time + timedelta(minutes=15)).isoformat()
    short = client.post(url, json={"end_time": new_end, "reason": "x"}, headers=admin)
    assert short.status_code == 422
    assert short.get_json()["code"] == "ERR_REASON_REQUIRED"
    earlier = (stage.end_time - timedelta(minutes=5)).isoformat()
    refused = client.post(url, json={"end_time": earlier, "reason": "power cut"}, headers=admin)
    assert refused.get_json()["code"] == "ERR_INVALID_DATE_RANGE"
    response = client.post(
        url, json={"end_time": new_end, "reason": "power cut in room 2"}, headers=admin
    )
    assert response.status_code == 200, response.get_json()
    event = fake.events[f"stage-{stage.id}"]
    assert event["extension_reason"] == "power cut in room 2"
    assert db_session.get(Stage, stage.id).end_time == datetime.fromisoformat(new_end)
    entry = AuditLog.query.filter_by(action_type="extend").one()
    assert entry.reason == "power cut in room 2"


def test_extension_after_the_end_is_too_late(
    client, fake, queued, db_session, sample_challenge, stage, task, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    env_id = _ready_environment(client, admin, sample_challenge, stage)
    stage.end_time = utcnow() - timedelta(hours=1)
    db_session.commit()
    response = client.post(
        f"/api/challenges/{sample_challenge.id}/environments/{env_id}/extension",
        json={"end_time": utcnow().isoformat(), "reason": "too late anyway"},
        headers=admin,
    )
    assert response.get_json()["code"] == "ERR_EXTENSION_TOO_LATE"


def _naive_utc(value):
    return datetime.fromisoformat(value).astimezone(UTC).replace(tzinfo=None)


def test_archive_date_defaults_per_stage_until_chosen(
    client, fake, queued, db_session, sample_challenge, stage, task, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    shown = _save(client, admin, sample_challenge, stage).get_json()["archive_until"]
    assert Environment.query.one().archive_until is None
    default = stage.end_time + timedelta(days=30, seconds=Config.DEADLINE_GRACE_PERIOD_SECONDS)
    assert _naive_utc(shown) == default
    chosen = sample_challenge.end_time + timedelta(days=5)
    response = _save(client, admin, sample_challenge, stage, archive_until=chosen.isoformat())
    assert response.status_code == 200
    assert Environment.query.one().archive_until == chosen
    assert _set_workspace(client, admin, sample_challenge).status_code == 200
    assert Environment.query.one().archive_until is None


@pytest.mark.parametrize("chosen_minutes", [None, 10])
def test_extension_moves_the_archive_date_and_saving_still_works(
    chosen_minutes, client, fake, queued, sample_challenge, stage, task, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    ends_at = sample_challenge.end_time + timedelta(seconds=Config.DEADLINE_GRACE_PERIOD_SECONDS)
    chosen = ends_at + timedelta(minutes=chosen_minutes) if chosen_minutes else None
    extra = {"archive_until": chosen.isoformat()} if chosen else {}
    env_id = _save(client, admin, sample_challenge, stage, **extra).get_json()["id"]
    assert environment_service.sync_environment(env_id) == "ok"
    assert _publish(client, admin, sample_challenge, env_id).status_code == 200
    extended = client.post(
        f"/api/challenges/{sample_challenge.id}/environments/{env_id}/extension",
        json={
            "end_time": (stage.end_time + timedelta(minutes=30)).isoformat(),
            "reason": "power cut in room 2",
        },
        headers=admin,
    )
    assert extended.status_code == 200, extended.get_json()
    stored = Environment.query.one().archive_until
    assert stored == (chosen + timedelta(minutes=30) if chosen else None)
    resaved = _set_workspace(client, admin, sample_challenge, **extra)
    assert resaved.status_code == 200, resaved.get_json()
    assert Environment.query.one().archive_until == stored


# ── Students ──


def test_student_launch_creates_the_workspace_once(
    client, fake, queued, sample_challenge, stage, task, sample_competitor, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    student = auth_headers(tokens.competitor)
    env_id = _ready_environment(client, admin, sample_challenge, stage)
    status = client.get(f"/api/tasks/{task.id}/environment", headers=student)
    assert status.get_json()["status"] == "not_open"
    _publish(client, admin, sample_challenge, env_id)
    environment_service.sync_environment(env_id)
    status = client.get(f"/api/tasks/{task.id}/environment", headers=student).get_json()
    assert status["status"] == "ready"
    assert status["open_path"] == "image-classification/solution.ipynb"

    first = client.post(f"/api/tasks/{task.id}/environment/launch", headers=student)
    assert first.status_code == 200, first.get_json()
    assert first.headers["Cache-Control"] == "no-store"
    assert first.get_json()["launch_token"]
    second = client.post(f"/api/tasks/{task.id}/environment/launch", headers=student)
    assert second.status_code == 200
    assert Workspace.query.count() == 1
    assert len(fake.workspaces) == 1
    assert AuditLog.query.filter_by(action_type="launch").count() == 2

    rows = client.get(
        f"/api/challenges/{sample_challenge.id}/environments/{env_id}/workspaces", headers=admin
    ).get_json()["workspaces"]
    opened = [row for row in rows if row["opened"]]
    assert [row["username"] for row in opened] == [sample_competitor.username]


def test_student_cannot_reach_the_environment_of_a_stage_not_started(
    client,
    fake,
    queued,
    db_session,
    sample_challenge,
    stage,
    sample_competitor,
    tokens,
    auth_headers,
):
    later = Stage(
        title="Round 2",
        challenge_id=sample_challenge.id,
        stage_number=2,
        start_time=utcnow() + timedelta(minutes=70),
        end_time=utcnow() + timedelta(minutes=110),
    )
    db_session.add(later)
    db_session.commit()
    task = _task(db_session, sample_challenge, later)
    student = auth_headers(tokens.competitor)
    responses = [
        client.get(f"/api/tasks/{task.id}", headers=student),
        client.get(f"/api/tasks/{task.id}/environment", headers=student),
        client.post(f"/api/tasks/{task.id}/environment/launch", headers=student),
    ]
    for response in responses:
        assert response.status_code == 403
        assert response.get_json()["code"] == "ERR_NOT_AVAILABLE"


def _open_environment(client, admin, challenge, stage):
    env_id = _ready_environment(client, admin, challenge, stage)
    assert _publish(client, admin, challenge, env_id).status_code == 200
    environment_service.sync_environment(env_id)
    return env_id


def test_launch_follows_the_workspace_id_nanocolab_returns(
    client,
    fake,
    queued,
    db_session,
    sample_challenge,
    stage,
    task,
    sample_competitor,
    tokens,
    auth_headers,
):
    env_id = _open_environment(client, auth_headers(tokens.admin), sample_challenge, stage)
    db_session.add(
        Workspace(environment_id=env_id, user_id=sample_competitor.id, workspace_id="stale")
    )
    db_session.commit()
    response = client.post(
        f"/api/tasks/{task.id}/environment/launch", headers=auth_headers(tokens.competitor)
    )
    assert response.status_code == 200, response.get_json()
    workspace_id = Workspace.query.one().workspace_id
    assert workspace_id != "stale"
    assert workspace_id in fake.workspaces


def test_launch_audit_names_the_student_as_target(
    client, fake, queued, sample_challenge, stage, task, sample_competitor, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    _open_environment(client, admin, sample_challenge, stage)
    launched = client.post(
        f"/api/tasks/{task.id}/environment/launch", headers=auth_headers(tokens.competitor)
    )
    assert launched.status_code == 200
    entry = AuditLog.query.filter_by(action_type="launch").one()
    assert entry.admin_id is None
    assert str(entry.target_user_id) == str(sample_competitor.id)
    logs = client.get(f"/api/admin/audit-logs?challenge_id={sample_challenge.id}", headers=admin)
    assert logs.status_code == 200
    row = next(log for log in logs.get_json()["logs"] if log["action_type"] == "launch")
    assert row["admin_id"] is None
    assert row["target_user_username"] == sample_competitor.username


def test_workspace_list_shows_each_students_latest_submission(
    client,
    fake,
    queued,
    db_session,
    sample_challenge,
    stage,
    task,
    sample_competitor,
    tokens,
    auth_headers,
):
    admin = auth_headers(tokens.admin)
    env_id = _save(client, admin, sample_challenge, stage).get_json()["id"]
    elsewhere = Task(challenge_id=sample_challenge.id, title="Outside the stage")
    db_session.add(elsewhere)
    db_session.flush()
    now = utcnow()
    for task_id, status, minutes in (
        (task.id, "completed", 30),
        (task.id, "failed", 10),
        (elsewhere.id, "running", 1),
    ):
        db_session.add(
            Submission(
                user_id=sample_competitor.id,
                challenge_id=sample_challenge.id,
                task_id=task_id,
                status=status,
                created_at=now - timedelta(minutes=minutes),
            )
        )
    db_session.commit()
    rows = client.get(
        f"/api/challenges/{sample_challenge.id}/environments/{env_id}/workspaces", headers=admin
    ).get_json()["workspaces"]
    by_user = {row["user_id"]: row for row in rows}
    row = by_user[str(sample_competitor.id)]
    assert row["last_submission_status"] == "failed"
    assert _naive_utc(row["last_submission_at"]) == now - timedelta(minutes=10)
    assert all(
        other["last_submission_at"] is None
        for user_id, other in by_user.items()
        if user_id != str(sample_competitor.id)
    )


def test_jury_sees_aliases_while_double_blind(
    client,
    fake,
    queued,
    sample_challenge,
    stage,
    task,
    sample_competitor,
    tokens,
    auth_headers,
    jury_token,
):
    env_id = _ready_environment(client, auth_headers(tokens.admin), sample_challenge, stage)
    rows = client.get(
        f"/api/challenges/{sample_challenge.id}/environments/{env_id}/workspaces",
        headers=auth_headers(jury_token),
    ).get_json()["workspaces"]
    assert rows and all(row["username"] is None for row in rows)
    assert sample_competitor.alias_id in {row["alias"] for row in rows}


def test_launch_errors(
    client,
    fake,
    queued,
    db_session,
    sample_challenge,
    stage,
    task,
    sample_competitor,
    tokens,
    auth_headers,
):
    admin = auth_headers(tokens.admin)
    student = auth_headers(tokens.competitor)
    url = f"/api/tasks/{task.id}/environment/launch"
    assert client.post(url, headers=student).get_json()["code"] == "ERR_ENVIRONMENT_NOT_ENABLED"
    env_id = _ready_environment(client, admin, sample_challenge, stage)
    assert client.post(url, headers=student).get_json()["code"] == "ERR_ENVIRONMENT_NOT_OPEN"
    _publish(client, admin, sample_challenge, env_id)
    fake.readiness = {"status": "PREPARING", "message": "Pulling", "retry_after_seconds": 15}
    environment_service.sync_environment(env_id)
    preparing = client.post(url, headers=student)
    assert preparing.status_code == 503
    assert preparing.headers["Retry-After"] == "15"
    fake.readiness = {"status": "READY", "message": "ok", "retry_after_seconds": 10}
    environment_service.sync_environment(env_id)
    fake.fail(
        "PUT",
        "/v1/events/{external_id}/workspaces/{external_user_id}",
        409,
        "The event has reached its maximum attendance",
    )
    assert client.post(url, headers=student).get_json()["code"] == "ERR_ENVIRONMENT_FULL"
    fake.fail(
        "PUT",
        "/v1/events/{external_id}/workspaces/{external_user_id}",
        403,
        "Missing scope workspaces:launch",
    )
    hidden = client.post(url, headers=student).get_json()
    assert hidden["code"] == "ERR_NANOCOLAB_UNAVAILABLE"
    assert "scope" not in hidden["error"]


def test_unregistered_student_cannot_launch(
    client, fake, queued, db_session, sample_future_challenge, stage, task, tokens, auth_headers
):
    other = User(username="elsewhere", password_hash="x", role="competitor", alias_id="E-1")
    other.challenge_id = sample_future_challenge.id
    db_session.add(other)
    db_session.commit()
    headers = auth_headers(generate_token(other.id, "competitor"))
    response = client.post(f"/api/tasks/{task.id}/environment/launch", headers=headers)
    assert response.status_code == 403


# ── Task folder names ──


def test_task_folder_names_are_generated_and_unique(
    client, fake, queued, sample_challenge, stage, task, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)

    def create(title, **extra):
        return client.post(
            f"/api/challenges/{sample_challenge.id}/tasks",
            data={
                "title": title,
                "stage_id": str(stage.id),
                "baseline_notebook": (io.BytesIO(NOTEBOOK), "b.ipynb"),
                **extra,
            },
            headers=admin,
            content_type="multipart/form-data",
        )

    numbered = create("Image classification!")
    assert numbered.status_code == 201
    assert numbered.get_json()["folder_name"] == "image-classification-2"
    clash = create("Other", folder_name="image-classification")
    assert clash.status_code == 409
    assert clash.get_json()["code"] == "ERR_TASK_FOLDER_TAKEN"
    created = create("Класификация")
    assert created.status_code == 201
    assert created.get_json()["folder_name"] == "klasifikatsiya"
    invalid = create("Other", folder_name="models")
    assert invalid.status_code == 422
    assert invalid.get_json()["code"] == "ERR_TASK_FOLDER_INVALID"
    renamed = client.put(
        f"/api/tasks/{task.id}",
        data={"folder_name": "klasifikatsiya"},
        headers=admin,
        content_type="multipart/form-data",
    )
    assert renamed.get_json()["code"] == "ERR_TASK_FOLDER_TAKEN"


def test_audit_filter_includes_environment_rows(
    client, fake, queued, sample_challenge, stage, task, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    env_id = _ready_environment(client, admin, sample_challenge, stage)
    assert _publish(client, admin, sample_challenge, env_id).status_code == 200
    logs = client.get(
        f"/api/admin/audit-logs?challenge_id={sample_challenge.id}", headers=admin
    ).get_json()["logs"]
    assert any(log["target_type"] == "environment" for log in logs)


def _zip_names(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.namelist()


def test_competition_without_stages_owns_its_environment(
    client, fake, queued, db_session, sample_challenge, sample_competitor, tokens, auth_headers
):
    _task(db_session, sample_challenge, None, title="Spam Filter")
    admin = auth_headers(tokens.admin)
    body = _save(client, admin, sample_challenge, None).get_json()
    assert body["stage_id"] is None
    assert environment_service.sync_environment(body["id"]) == "ok"
    event = fake.events[f"challenge-{sample_challenge.id}"]
    assert event["export_paths"] == ["spam-filter/solution.ipynb"]
    assert _publish(client, admin, sample_challenge, body["id"]).status_code == 200
    stage = client.post(
        f"/api/challenges/{sample_challenge.id}/stages",
        json={
            "title": "Late stage",
            "start_time": sample_challenge.start_time.isoformat(),
            "end_time": sample_challenge.end_time.isoformat(),
        },
        headers=admin,
    )
    assert stage.status_code == 409
    assert stage.get_json()["code"] == "ERR_ENVIRONMENT_LOCKED"


def test_first_stage_takes_over_from_an_unpublished_competition_environment(
    client, fake, queued, db_session, sample_challenge, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    own_id = _save(client, admin, sample_challenge, None).get_json()["id"]
    created = client.post(
        f"/api/challenges/{sample_challenge.id}/stages",
        json={
            "title": "Round 1",
            "start_time": sample_challenge.start_time.isoformat(),
            "end_time": sample_challenge.end_time.isoformat(),
        },
        headers=admin,
    )
    assert created.status_code == 201, created.get_json()
    assert db_session.get(Environment, own_id).enabled is False
    stage_env = Environment.query.filter_by(stage_id=created.get_json()["id"]).one()
    assert stage_env.enabled
    deleted = client.delete(
        f"/api/challenges/{sample_challenge.id}/stages/{created.get_json()['id']}", headers=admin
    )
    assert deleted.status_code == 200
    assert db_session.get(Environment, own_id).enabled is True


def _edit_task(client, admin, task, **fields):
    return client.put(
        f"/api/tasks/{task.id}", data=fields, headers=admin, content_type="multipart/form-data"
    )


def test_folder_follows_the_title_until_set_by_hand(
    client, fake, queued, sample_challenge, stage, task, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    assert _edit_task(client, admin, task, title="Spam Filter").get_json()["folder_name"] == (
        "spam-filter"
    )
    assert _edit_task(client, admin, task, folder_name="my-folder").status_code == 200
    renamed = _edit_task(client, admin, task, title="Other Title").get_json()
    assert renamed["folder_name"] == "my-folder"
    reset = _edit_task(client, admin, task, folder_name="").get_json()
    assert reset["folder_name"] == "other-title"
    assert _edit_task(client, admin, task, title="Third").get_json()["folder_name"] == "third"


def _create_task(client, admin, challenge, title, stage=None, **extra):
    data = {"title": title, "baseline_notebook": (io.BytesIO(NOTEBOOK), "b.ipynb"), **extra}
    if stage is not None:
        data["stage_id"] = str(stage.id)
    return client.post(
        f"/api/challenges/{challenge.id}/tasks",
        data=data,
        headers=admin,
        content_type="multipart/form-data",
    )


def test_duplicate_titles_get_numbered_folders_without_nanocolab(
    client, sample_challenge, tokens, auth_headers
):
    assert not environment_service.nanocolab_enabled()
    admin = auth_headers(tokens.admin)
    first = _create_task(client, admin, sample_challenge, "Spam Filter")
    second = _create_task(client, admin, sample_challenge, "Spam filter!")
    assert (first.status_code, second.status_code) == (201, 201)
    assert first.get_json()["folder_name"] == "spam-filter"
    assert second.get_json()["folder_name"] == "spam-filter-2"
    long_names = [
        _create_task(client, admin, sample_challenge, "a" * 50).get_json()["folder_name"]
        for _ in range(2)
    ]
    assert long_names == ["a" * 40, "a" * 38 + "-2"]
    clash = _create_task(client, admin, sample_challenge, "Other", folder_name="spam-filter-2")
    assert clash.status_code == 409
    assert clash.get_json()["code"] == "ERR_TASK_FOLDER_TAKEN"


def test_title_edits_and_stage_moves_number_generated_folders(
    client, fake, queued, db_session, sample_challenge, stage, task, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    _create_task(client, admin, sample_challenge, "Spam Filter", stage=stage)
    renamed = _edit_task(client, admin, task, title="Spam filter")
    assert renamed.get_json()["folder_name"] == "spam-filter-2"
    second = Stage(
        title="Round 2",
        challenge_id=sample_challenge.id,
        stage_number=2,
        start_time=stage.end_time,
        end_time=stage.end_time + timedelta(minutes=30),
    )
    db_session.add(second)
    db_session.commit()
    _task(db_session, sample_challenge, second, title="Spam Filter")
    moved = _edit_task(client, admin, task, stage_id=str(second.id))
    assert moved.status_code == 200, moved.get_json()
    assert moved.get_json()["folder_name"] == "spam-filter-2"
    _create_task(client, admin, sample_challenge, "Kept", stage=second, folder_name="my-folder")
    by_hand = _create_task(
        client, admin, sample_challenge, "By hand", stage=stage, folder_name="my-folder"
    ).get_json()
    refused = client.put(
        f"/api/tasks/{by_hand['id']}",
        data={"stage_id": str(second.id)},
        headers=admin,
        content_type="multipart/form-data",
    )
    assert refused.status_code == 409
    assert refused.get_json()["code"] == "ERR_TASK_FOLDER_TAKEN"


def test_folder_is_frozen_after_publish(
    client, fake, queued, sample_challenge, stage, task, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    env_id = _ready_environment(client, admin, sample_challenge, stage)
    _publish(client, admin, sample_challenge, env_id)
    edited = _edit_task(client, admin, task, title="Renamed After Publish")
    assert edited.status_code == 200
    assert edited.get_json()["folder_name"] == "image-classification"


def test_student_sees_unknown_when_the_status_is_stale(
    client, fake, queued, monkeypatch, sample_challenge, stage, task, tokens, auth_headers
):
    admin = auth_headers(tokens.admin)
    env_id = _ready_environment(client, admin, sample_challenge, stage)
    _publish(client, admin, sample_challenge, env_id)
    environment_service.sync_environment(env_id)
    monkeypatch.setattr(Config, "NANOCOLAB_STATUS_STALE_SECONDS", -1)
    status = client.get(
        f"/api/tasks/{task.id}/environment", headers=auth_headers(tokens.competitor)
    )
    assert status.get_json()["status"] == "unknown"
