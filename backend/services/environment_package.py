"""Deterministic workspace package of an environment: one folder per task."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from typing import Any

from config import Config
from models import Task
from schemas.environment import GIB
from services import hf_zip
from utils.error_utils import format_size
from utils.files import file_sha256, task_file_visibility
from utils.json_utils import safe_json_loads
from utils.text import is_safe_path, is_valid_folder_name

BUILDER_VERSION = 1
SOLUTION_NOTEBOOK = "solution.ipynb"
SUBMISSION_PARQUET = "submission.parquet"
MAX_ENTRIES = 2000
MAX_EXPORT_PATHS = 16
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
FILE_MODE = 0o100644 << 16
CHUNK = 1024 * 1024


class PackageError(Exception):
    """The package cannot be built; ``code`` is an ``ERR_*`` code shown to admins."""

    def __init__(self, code: str, message: str, limit: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.limit = limit


@dataclass(frozen=True)
class PackageEntry:
    """A file to ship: a stored file, or ``member`` of the HF ZIP at ``source``."""

    arcname: str
    source: str
    size: int
    member: str | None = None
    digest: str | None = None


@dataclass(frozen=True)
class BuiltPackage:
    path: str
    sha256: str
    size: int
    version: str


def file_entry(arcname: str, source: str) -> PackageEntry:
    return PackageEntry(arcname, source, os.path.getsize(source))


def solution_path(task: Task) -> str:
    return f"{task.folder_name}/{SOLUTION_NOTEBOOK}"


def submission_path(task: Task) -> str:
    return f"{task.folder_name}/{SUBMISSION_PARQUET}"


def export_paths(tasks: list[Task]) -> list[str]:
    """The files LavBench reads back: every task's notebook, plus the Parquet of file tasks."""
    paths = [solution_path(task) for task in tasks]
    paths.extend(submission_path(task) for task in tasks if task.is_file_mode)
    return sorted(paths)


def check_folders(tasks: list[Task]) -> None:
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


def public_entries(task: Task) -> list[PackageEntry]:
    """The starter notebook and the public files of one task; hidden files never ship."""
    folder = task.folder_name
    entries: list[PackageEntry] = []
    names: set[str] = set()
    if task.baseline_notebook_path and os.path.isfile(task.baseline_notebook_path):
        entries.append(file_entry(solution_path(task), task.baseline_notebook_path))
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
            entries.append(file_entry(f"{folder}/{filename}", source))
            names.add(filename.casefold())
    return entries


_KEEP = object()


def hf_entries(tasks: list[Task], override: dict[str, Any] | None = None) -> list[PackageEntry]:
    """Root ``models/`` and ``datasets/`` from every task's HF ZIP; a folder in two tasks
    ships once when identical, and is a conflict otherwise.

    ``override`` maps a task id to the sha256 it would have (None for none).
    """
    override = override or {}
    owners: dict[str, tuple[Task, list[tuple[str, int, int]]]] = {}
    entries: list[PackageEntry] = []
    for task in tasks:
        sha256 = override.get(str(task.id), _KEEP)
        if sha256 is _KEEP:
            sha256 = task.hf_zip_sha256
        if not sha256:
            continue
        source = hf_zip.hf_zip_path(str(sha256))
        try:
            summary = hf_zip.inspect_zip(source)
        except (OSError, hf_zip.HfZipError) as exc:
            raise PackageError(
                "ERR_ENVIRONMENT_PACKAGE_FAILED",
                f"The Hugging Face data of the task {task.title} cannot be read: {exc}",
            ) from None
        for folder in summary.folders:
            listing = hf_zip.folder_listing(summary, folder)
            if folder in owners:
                other, other_listing = owners[folder]
                if other_listing != listing:
                    raise PackageError(
                        "ERR_HF_FOLDER_CONFLICT",
                        f"The folder {folder} differs between the tasks {other.title} "
                        f"and {task.title}.",
                    )
                continue
            owners[folder] = (task, listing)
            entries.extend(
                PackageEntry(
                    arcname=entry.path,
                    source=source,
                    size=entry.size,
                    member=entry.info.filename,
                    digest=f"hf:{sha256}:{entry.path}",
                )
                for entry in summary.entries
                if entry.path.startswith(f"{folder}/")
            )
    return entries


def check_caps(entries: list[PackageEntry]) -> None:
    """2,000 entries and ``NANOCOLAB_PACKAGE_MAX_BYTES``; the message gives the value."""
    if len(entries) > MAX_ENTRIES:
        raise PackageError(
            "ERR_ENVIRONMENT_PACKAGE_TOO_LARGE",
            f"The package would hold {len(entries)} files, more than {MAX_ENTRIES}.",
            limit=f"{MAX_ENTRIES} files",
        )
    total = sum(entry.size for entry in entries)
    if total > Config.NANOCOLAB_PACKAGE_MAX_BYTES:
        limit = format_size(Config.NANOCOLAB_PACKAGE_MAX_BYTES)
        raise PackageError(
            "ERR_ENVIRONMENT_PACKAGE_TOO_LARGE",
            f"The package would be {format_size(total)}, larger than {limit}.",
            limit=limit,
        )


def check_projected(
    tasks: list[Task],
    task: Task,
    *,
    public_file: tuple[str, str] | None = None,
    hf_sha256: Any = _KEEP,
) -> None:
    """The package caps and HF conflicts as they would be after one upload or removal.

    ``public_file`` is ``(filename, path)`` of a public file the task would hold.
    """
    entries = [entry for each in tasks for entry in public_entries(each)]
    if public_file is not None:
        arcname = f"{task.folder_name}/{public_file[0]}"
        entries = [e for e in entries if e.arcname != arcname]
        entries.append(file_entry(arcname, public_file[1]))
    override = {} if hf_sha256 is _KEEP else {str(task.id): hf_sha256}
    entries.extend(hf_entries(tasks, override))
    check_caps(entries)


def package_entries(tasks: list[Task]) -> list[PackageEntry]:
    """Every task's folder, plus the shared Hugging Face folders at the root."""
    if len(export_paths(tasks)) > MAX_EXPORT_PATHS:
        raise PackageError(
            "ERR_ENVIRONMENT_TOO_MANY_TASKS",
            f"An environment reads back at most {MAX_EXPORT_PATHS} files: one per notebook "
            "task and two per file task.",
            limit=str(MAX_EXPORT_PATHS),
        )
    check_folders(tasks)
    entries = [entry for task in tasks for entry in public_entries(task)]
    for entry in entries:
        if not is_safe_path(entry.arcname):
            raise PackageError(
                "ERR_ENVIRONMENT_PACKAGE_FAILED",
                f"The file name {entry.arcname} is not allowed in a workspace.",
            )
    entries.extend(hf_entries(tasks))
    if not entries:
        raise PackageError(
            "ERR_ENVIRONMENT_PACKAGE_EMPTY", "The environment has no task files to package."
        )
    check_caps(entries)
    return sorted(entries, key=lambda entry: entry.arcname)


def data_gib(entries: list[PackageEntry]) -> int:
    """The task data's size in whole GiB, rounded up."""
    return math.ceil(sum(entry.size for entry in entries) / GIB)


def fingerprint(entries: list[PackageEntry]) -> str:
    """Cheap change detector over names, sizes and mtimes, so unchanged files are not hashed;
    an HF entry's source names its ZIP's sha256."""
    listing = []
    for entry in entries:
        status = os.stat(entry.source)
        listing.append([entry.arcname, entry.source, entry.member, entry.size, status.st_mtime_ns])
    payload = json.dumps([BUILDER_VERSION, listing]).encode()
    return hashlib.sha256(payload).hexdigest()


def content_version(entries: list[PackageEntry]) -> str:
    """``lb-<12 hex>-v<builder>`` over the sorted ``<sha256>  <path>`` lines."""
    lines = "".join(f"{e.digest or file_sha256(e.source)}  {e.arcname}\n" for e in entries)
    digest = hashlib.sha256(lines.encode()).hexdigest()
    return f"lb-{digest[:12]}-v{BUILDER_VERSION}"


def build(entries: list[PackageEntry], version: str, directory: str) -> BuiltPackage:
    """Write a ZIP_STORED archive (ZIP64 when needed) with fixed timestamps and modes,
    streaming each entry, then hash it."""
    os.makedirs(directory, mode=0o700, exist_ok=True)
    handle, path = tempfile.mkstemp(prefix="environment-", suffix=".zip", dir=directory)
    os.close(handle)
    sources: dict[str, zipfile.ZipFile] = {}
    try:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
            for entry in entries:
                info = zipfile.ZipInfo(entry.arcname, date_time=FIXED_TIME)
                info.compress_type = zipfile.ZIP_STORED
                info.external_attr = FILE_MODE
                info.create_system = 3
                # A known size lets zipfile write the ZIP64 header up front for large files
                info.file_size = entry.size
                if entry.member is None:
                    with open(entry.source, "rb") as source, archive.open(info, "w") as target:
                        shutil.copyfileobj(source, target, CHUNK)
                    continue
                if entry.source not in sources:
                    sources[entry.source] = hf_zip.open_zip(entry.source)
                member = sources[entry.source].open(entry.member)
                with member as source, archive.open(info, "w") as target:
                    shutil.copyfileobj(source, target, CHUNK)
        size = os.path.getsize(path)
        if size > Config.NANOCOLAB_PACKAGE_MAX_BYTES:
            limit = format_size(Config.NANOCOLAB_PACKAGE_MAX_BYTES)
            raise PackageError(
                "ERR_ENVIRONMENT_PACKAGE_TOO_LARGE",
                f"The package is larger than {limit}.",
                limit=limit,
            )
        sha256 = file_sha256(path)
    except BaseException:
        os.unlink(path)
        raise
    finally:
        for opened in sources.values():
            opened.close()
    return BuiltPackage(path=path, sha256=sha256, size=size, version=version)
