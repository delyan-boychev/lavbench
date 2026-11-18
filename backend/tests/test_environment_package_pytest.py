"""Tests for the deterministic environment package."""

import json
import os
import zipfile

import pytest

from config import Config
from models import Task
from services.environment_package import (
    PackageError,
    build,
    content_version,
    export_paths,
    package_entries,
    package_plan,
)

NOTEBOOK = json.dumps({"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": []}).encode()


@pytest.fixture
def uploads(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path))
    return tmp_path


def make_task(db_session, challenge, uploads, title, files=None, baseline=True, stage=None):
    task = Task(challenge_id=challenge.id, stage_id=stage.id if stage else None, title=title)
    db_session.add(task)
    db_session.flush()
    folder = uploads / f"task_{task.id}"
    folder.mkdir()
    meta = []
    for index, (name, data, visibility) in enumerate(files or []):
        saved = f"{index}_{name}"
        (folder / saved).write_bytes(data)
        entry = {"filename": name, "saved_name": saved, "size_bytes": len(data)}
        if visibility:
            entry["visibility"] = visibility
        meta.append(entry)
    task.files = json.dumps(meta)
    if baseline:
        path = folder / "baseline_starter.ipynb"
        path.write_bytes(NOTEBOOK)
        task.baseline_notebook_path = str(path)
    db_session.flush()
    return task


def test_layout_folder_per_task_without_hidden_files(db_session, sample_challenge, uploads):
    task = make_task(
        db_session,
        sample_challenge,
        uploads,
        "Image Classification",
        files=[
            ("train.csv", b"id,x\n1,2\n", None),
            ("labels.parquet", b"PAR1secret", None),
            ("answers.csv", b"secret", "hidden"),
        ],
    )
    names = [entry.arcname for entry in package_entries([task])[0]]
    assert names == ["image-classification/solution.ipynb", "image-classification/train.csv"]
    assert export_paths([task]) == ["image-classification/solution.ipynb"]


def test_zip_is_stored_with_fixed_times_and_modes(db_session, sample_challenge, uploads):
    task = make_task(db_session, sample_challenge, uploads, "Spam", files=[("b.csv", b"b", None)])
    entries, _ = package_entries([task])
    built = build(entries, content_version(entries), str(uploads / "out"))
    with zipfile.ZipFile(built.path) as archive:
        infos = archive.infolist()
    assert [info.filename for info in infos] == ["spam/b.csv", "spam/solution.ipynb"]
    for info in infos:
        assert info.compress_type == zipfile.ZIP_STORED
        assert info.date_time == (1980, 1, 1, 0, 0, 0)
        assert (info.external_attr >> 16) & 0o777 == 0o644
    assert built.version.startswith("lb-") and built.version.endswith("-v1")
    again = build(entries, built.version, str(uploads / "out"))
    assert again.sha256 == built.sha256
    os.unlink(built.path)
    os.unlink(again.path)


def test_version_follows_content_only(db_session, sample_challenge, uploads):
    task = make_task(db_session, sample_challenge, uploads, "Spam", files=[("a.csv", b"1", None)])
    first = content_version(package_entries([task])[0])
    path = uploads / f"task_{task.id}" / "0_a.csv"
    path.write_bytes(b"1")
    assert content_version(package_entries([task])[0]) == first
    path.write_bytes(b"2")
    assert content_version(package_entries([task])[0]) != first


def test_empty_package_is_refused(db_session, sample_challenge, uploads):
    task = make_task(db_session, sample_challenge, uploads, "Empty", baseline=False)
    with pytest.raises(PackageError) as raised:
        package_plan([task])
    assert raised.value.code == "ERR_ENVIRONMENT_PACKAGE_EMPTY"


def test_too_large_package_names_the_limit(db_session, sample_challenge, uploads, monkeypatch):
    monkeypatch.setattr(Config, "NANOCOLAB_PACKAGE_MAX_BYTES", 10)
    task = make_task(
        db_session, sample_challenge, uploads, "Big", files=[("a.csv", b"x" * 64, None)]
    )
    with pytest.raises(PackageError) as raised:
        package_plan([task])
    assert raised.value.code == "ERR_ENVIRONMENT_PACKAGE_TOO_LARGE"
    assert raised.value.limit
    assert raised.value.fields["detail"]


def test_unsafe_public_name_is_refused(db_session, sample_challenge, uploads):
    task = make_task(db_session, sample_challenge, uploads, "Bad", files=[(".env", b"x", None)])
    with pytest.raises(PackageError) as raised:
        package_plan([task])
    assert raised.value.code == "ERR_ENVIRONMENT_PACKAGE_FAILED"


def test_duplicate_folders_are_refused(db_session, sample_challenge, uploads):
    first = make_task(db_session, sample_challenge, uploads, "Same")
    second = make_task(db_session, sample_challenge, uploads, "Same")
    with pytest.raises(PackageError) as raised:
        package_plan([first, second])
    assert raised.value.code == "ERR_TASK_FOLDER_TAKEN"


def test_more_than_sixteen_tasks_is_refused(db_session, sample_challenge, uploads):
    tasks = [make_task(db_session, sample_challenge, uploads, f"T{i}") for i in range(17)]
    with pytest.raises(PackageError) as raised:
        package_plan(tasks)
    assert raised.value.code == "ERR_ENVIRONMENT_TOO_MANY_TASKS"
    assert raised.value.limit == "16"
