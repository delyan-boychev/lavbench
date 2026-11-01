"""In-process stand-in for the nano-colab /v1 API used by compute tests."""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from typing import Any

import pytest

from config import Config
from models import Task
from services.nanocolab_client import NanoColabClient

DIGEST = "localhost:5050/nanocolab/workspace-python-ml@sha256:" + "a" * 64
CATALOGUE: dict[str, Any] = {
    "images": [
        {
            "image_id": "python-ml",
            "name": "Python ML (CPU)",
            "description": "pandas and scikit-learn",
            "digest": DIGEST,
            "packages": [{"name": "pandas", "version": "2.2.3"}],
            "default": True,
        },
        {
            "image_id": "python-base",
            "name": "Python",
            "description": "",
            "digest": "localhost:5050/nanocolab/workspace-python-base@sha256:" + "b" * 64,
            "packages": [],
            "default": False,
        },
    ]
}
NOTEBOOK = json.dumps({"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": []}).encode()


class FakeNanoColab:
    def __init__(self) -> None:
        self.catalogue: dict[str, Any] | Exception = CATALOGUE
        self.catalogue_calls = 0
        self.events: list[dict[str, Any]] = []
        self.assets: dict[str, dict[str, Any]] = {}
        self.uploads: dict[str, bytes] = {}
        self.complete_state = "READY"
        self.complete_error: str | None = None
        self.upload_failure: Exception | None = None

    def list_images(self) -> dict[str, Any]:
        self.catalogue_calls += 1
        if isinstance(self.catalogue, Exception):
            raise self.catalogue
        return self.catalogue

    def start_asset_upload(self, version: str, size_bytes: int, sha256: str) -> dict[str, Any]:
        asset = self.assets.get(version)
        if asset and asset["state"] != "UPLOADING":
            return {
                "version": version,
                "state": asset["state"],
                "error": asset.get("error"),
                "upload": None,
            }
        self.assets[version] = {"state": "UPLOADING", "sha256": sha256, "size": size_bytes}
        url = f"{Config.NANOCOLAB_API_URL}/v1/assets/{version}/content"
        return {
            "version": version,
            "state": "UPLOADING",
            "upload": {"url": url, "method": "PUT", "auth": "api_key"},
        }

    def upload_asset(self, target: dict[str, Any], path: str) -> None:
        if self.upload_failure:
            raise self.upload_failure
        version = target["url"].split("/v1/assets/")[1].split("/")[0]
        with open(path, "rb") as handle:
            data = handle.read()
        assert hashlib.sha256(data).hexdigest() == self.assets[version]["sha256"]
        self.uploads[version] = data

    def complete_asset_upload(self, version: str) -> dict[str, Any]:
        self.assets[version].update(state=self.complete_state, error=self.complete_error)
        return {"version": version, "state": self.complete_state, "error": self.complete_error}

    def get_asset(self, version: str) -> dict[str, Any]:
        asset = self.assets[version]
        return {"version": version, "state": asset["state"], "error": asset.get("error")}

    def put_event(self, external_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.events.append(payload)
        digest = next(
            (
                image["digest"]
                for image in CATALOGUE["images"]
                if image["image_id"] == payload["image_id"]
            ),
            DIGEST,
        )
        return {"event_id": "6768db74-8b73-5ab6-a520-475de0393028", "environment_digest": digest}

    def get_readiness(self, external_id: str) -> dict[str, Any]:
        return {"status": "READY", "message": "ok", "retry_after_seconds": 10}

    def package_names(self, version: str) -> list[str]:
        path = os.path.join(Config.UPLOAD_FOLDER, "inspect.zip")
        with open(path, "wb") as handle:
            handle.write(self.uploads[version])
        with zipfile.ZipFile(path) as archive:
            return archive.namelist()


def install(monkeypatch: pytest.MonkeyPatch, fake: FakeNanoColab) -> None:
    monkeypatch.setattr(Config, "NANOCOLAB_API_URL", "http://nanocolab.test")
    monkeypatch.setattr(Config, "NANOCOLAB_API_KEY", "ncak_test0000_" + "k" * 40)
    for name in (
        "list_images",
        "start_asset_upload",
        "upload_asset",
        "complete_asset_upload",
        "get_asset",
        "put_event",
        "get_readiness",
    ):
        method = getattr(fake, name)
        monkeypatch.setattr(NanoColabClient, name, lambda self, *args, _m=method: _m(*args))


def add_task(
    db_session: Any, challenge: Any, stage: Any, upload_root: str, title: str = "Task"
) -> Task:
    task = Task(challenge_id=challenge.id, stage_id=stage.id, title=title, files="[]")
    db_session.add(task)
    db_session.flush()
    folder = os.path.join(upload_root, f"task_{task.id}")
    os.makedirs(folder, exist_ok=True)
    files = {"train.csv": b"id,x\n1,2\n", "labels.parquet": b"PAR1secret"}
    meta = []
    for index, (name, data) in enumerate(files.items()):
        saved = f"{index}_{name}"
        with open(os.path.join(folder, saved), "wb") as handle:
            handle.write(data)
        meta.append({"filename": name, "saved_name": saved, "size": len(data)})
    baseline = os.path.join(folder, "baseline_notebook.ipynb")
    with open(baseline, "wb") as handle:
        handle.write(NOTEBOOK)
    task.files = json.dumps(meta)
    task.baseline_notebook_path = baseline
    db_session.flush()
    return task
