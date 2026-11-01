"""Deterministic task package for a stage's notebook workspaces."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from typing import Any

from config import Config
from models import Stage, Task
from utils.json_utils import safe_json_loads

PRIVATE_FILES = frozenset({"labels.parquet"})
BASELINE_NAME = "baseline.ipynb"
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
FILE_MODE = 0o100644 << 16
CHUNK = 1024 * 1024


@dataclass(frozen=True)
class PackageEntry:
    arcname: str
    source: str


@dataclass(frozen=True)
class BuiltPackage:
    path: str
    sha256: str
    size: int
    version: str


def stage_tasks(stage: Stage) -> list[Task]:
    tasks: list[Task] = Task.query.filter_by(stage_id=stage.id).order_by(Task.id).all()
    return tasks


def task_folders(stage: Stage) -> dict[str, str]:
    return {str(task.id): f"task{index}" for index, task in enumerate(stage_tasks(stage), start=1)}


def package_entries(stage: Stage) -> list[PackageEntry]:
    entries: list[PackageEntry] = []
    for index, task in enumerate(stage_tasks(stage), start=1):
        folder = f"task{index}"
        upload_dir = os.path.join(Config.UPLOAD_FOLDER, f"task_{task.id}")
        names: set[str] = set()
        if task.baseline_notebook_path and os.path.isfile(task.baseline_notebook_path):
            baseline = os.path.basename(task.baseline_notebook_path) or BASELINE_NAME
            entries.append(PackageEntry(f"{folder}/{baseline}", task.baseline_notebook_path))
            names.add(baseline.casefold())
        for item in safe_json_loads(task.files, []):
            filename = str(item.get("filename") or "")
            saved_name = os.path.basename(str(item.get("saved_name") or ""))
            if (
                not filename
                or not saved_name
                or filename in PRIVATE_FILES
                or filename.casefold() in names
            ):
                continue
            source = os.path.join(upload_dir, saved_name)
            if os.path.isfile(source):
                entries.append(PackageEntry(f"{folder}/{filename}", source))
                names.add(filename.casefold())
    return sorted(entries, key=lambda entry: entry.arcname)


def fingerprint(entries: list[PackageEntry]) -> str:
    listing: list[dict[str, Any]] = []
    for entry in entries:
        status = os.stat(entry.source)
        listing.append(
            {
                "arcname": entry.arcname,
                "source": entry.source,
                "size": status.st_size,
                "mtime_ns": status.st_mtime_ns,
            }
        )
    return hashlib.sha256(json.dumps(listing, sort_keys=True).encode()).hexdigest()


def version_for(sha256: str) -> str:
    return f"lb-{sha256[:12]}-v1"


def build(entries: list[PackageEntry], directory: str) -> BuiltPackage:
    os.makedirs(directory, mode=0o700, exist_ok=True)
    handle, path = tempfile.mkstemp(prefix="stage-", suffix=".zip", dir=directory)
    os.close(handle)
    try:
        with zipfile.ZipFile(path, "w") as archive:
            for entry in entries:
                info = zipfile.ZipInfo(entry.arcname, date_time=FIXED_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = FILE_MODE
                info.create_system = 3
                with (
                    open(entry.source, "rb") as source,
                    archive.open(info, "w", force_zip64=False) as target,
                ):
                    shutil.copyfileobj(source, target, CHUNK)
        digest = hashlib.sha256()
        with open(path, "rb") as built:
            while chunk := built.read(CHUNK):
                digest.update(chunk)
    except BaseException:
        os.unlink(path)
        raise
    sha256 = digest.hexdigest()
    return BuiltPackage(
        path=path, sha256=sha256, size=os.path.getsize(path), version=version_for(sha256)
    )
