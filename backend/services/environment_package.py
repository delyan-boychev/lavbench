"""Deterministic workspace package of an environment: one folder per task."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass

from config import Config
from models import Task
from utils.error_utils import format_size
from utils.files import task_file_visibility
from utils.json_utils import safe_json_loads
from utils.text import is_valid_folder_name

BUILDER_VERSION = 1
SOLUTION_NOTEBOOK = "solution.ipynb"
MAX_ENTRIES = 2000
MAX_EXPORT_PATHS = 16
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
FILE_MODE = 0o100644 << 16
CHUNK = 1024 * 1024
_RESERVED_PART = re.compile(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?")


class PackageError(Exception):
    """The package cannot be built; ``code`` is an ``ERR_*`` code shown to admins."""

    def __init__(self, code: str, message: str, limit: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.limit = limit


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


def is_safe_path(path: str) -> bool:
    """The path rules nanoColab applies to every package entry."""
    if (
        not path
        or len(path) > 512
        or unicodedata.normalize("NFC", path) != path
        or "\\" in path
        or ":" in path
        or any(ord(c) < 32 or ord(c) == 127 for c in path)
    ):
        return False
    return all(
        part
        and not part.startswith(".")
        and not part.endswith((".", " "))
        and not _RESERVED_PART.fullmatch(part)
        for part in path.split("/")
    )


def solution_path(task: Task) -> str:
    return f"{task.folder_name}/{SOLUTION_NOTEBOOK}"


def export_paths(tasks: list[Task]) -> list[str]:
    return sorted(solution_path(task) for task in tasks)


def package_entries(tasks: list[Task]) -> list[PackageEntry]:
    """Public files and the starter notebook of each task; hidden files never ship."""
    if len(tasks) > MAX_EXPORT_PATHS:
        raise PackageError(
            "ERR_ENVIRONMENT_TOO_MANY_TASKS",
            f"An environment holds at most {MAX_EXPORT_PATHS} tasks.",
            limit=str(MAX_EXPORT_PATHS),
        )
    entries: list[PackageEntry] = []
    folders: set[str] = set()
    for task in tasks:
        folder = task.folder_name
        if not folder or not is_valid_folder_name(folder):
            raise PackageError(
                "ERR_TASK_FOLDER_INVALID", f"The task {task.title} has no valid folder name."
            )
        if folder in folders:
            raise PackageError("ERR_TASK_FOLDER_TAKEN", f"Two tasks use the folder {folder}.")
        folders.add(folder)
        names: set[str] = set()
        if task.baseline_notebook_path and os.path.isfile(task.baseline_notebook_path):
            entries.append(PackageEntry(solution_path(task), task.baseline_notebook_path))
            names.add(SOLUTION_NOTEBOOK)
        upload_dir = os.path.join(Config.UPLOAD_FOLDER, f"task_{task.id}")
        for item in safe_json_loads(task.files, []):
            filename = str(item.get("filename") or "")
            saved_name = os.path.basename(str(item.get("saved_name") or ""))
            if task_file_visibility(item) != "public" or not saved_name:
                continue
            if filename.casefold() in names:
                continue
            source = os.path.join(upload_dir, saved_name)
            if os.path.isfile(source):
                entries.append(PackageEntry(f"{folder}/{filename}", source))
                names.add(filename.casefold())
    for entry in entries:
        if not is_safe_path(entry.arcname):
            raise PackageError(
                "ERR_ENVIRONMENT_PACKAGE_FAILED",
                f"The file name {entry.arcname} is not allowed in a workspace.",
            )
    if not entries:
        raise PackageError(
            "ERR_ENVIRONMENT_PACKAGE_EMPTY", "The environment has no task files to package."
        )
    if len(entries) > MAX_ENTRIES:
        raise PackageError(
            "ERR_ENVIRONMENT_PACKAGE_TOO_LARGE",
            f"The package would hold more than {MAX_ENTRIES} files.",
            limit=f"{MAX_ENTRIES} files",
        )
    total = sum(os.path.getsize(entry.source) for entry in entries)
    if total > Config.NANOCOLAB_PACKAGE_MAX_BYTES:
        limit = format_size(Config.NANOCOLAB_PACKAGE_MAX_BYTES)
        raise PackageError(
            "ERR_ENVIRONMENT_PACKAGE_TOO_LARGE",
            f"The package would be larger than {limit}.",
            limit=limit,
        )
    return sorted(entries, key=lambda entry: entry.arcname)


def fingerprint(entries: list[PackageEntry]) -> str:
    """Cheap change detector over names, sizes and mtimes, so unchanged files are not hashed."""
    listing = []
    for entry in entries:
        status = os.stat(entry.source)
        listing.append([entry.arcname, entry.source, status.st_size, status.st_mtime_ns])
    payload = json.dumps([BUILDER_VERSION, listing]).encode()
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def content_version(entries: list[PackageEntry]) -> str:
    """``lb-<12 hex>-v<builder>`` over the sorted ``<sha256>  <path>`` lines."""
    lines = "".join(f"{_file_sha256(e.source)}  {e.arcname}\n" for e in entries)
    digest = hashlib.sha256(lines.encode()).hexdigest()
    return f"lb-{digest[:12]}-v{BUILDER_VERSION}"


def build(entries: list[PackageEntry], version: str, directory: str) -> BuiltPackage:
    """Write a ZIP_STORED archive with fixed timestamps and modes, then hash it."""
    os.makedirs(directory, mode=0o700, exist_ok=True)
    handle, path = tempfile.mkstemp(prefix="environment-", suffix=".zip", dir=directory)
    os.close(handle)
    try:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED, allowZip64=False) as archive:
            for entry in entries:
                info = zipfile.ZipInfo(entry.arcname, date_time=FIXED_TIME)
                info.compress_type = zipfile.ZIP_STORED
                info.external_attr = FILE_MODE
                info.create_system = 3
                with open(entry.source, "rb") as source, archive.open(info, "w") as target:
                    shutil.copyfileobj(source, target, CHUNK)
        size = os.path.getsize(path)
        if size > Config.NANOCOLAB_PACKAGE_MAX_BYTES:
            limit = format_size(Config.NANOCOLAB_PACKAGE_MAX_BYTES)
            raise PackageError(
                "ERR_ENVIRONMENT_PACKAGE_TOO_LARGE",
                f"The package is larger than {limit}.",
                limit=limit,
            )
        sha256 = _file_sha256(path)
    except BaseException:
        os.unlink(path)
        raise
    return BuiltPackage(path=path, sha256=sha256, size=size, version=version)
