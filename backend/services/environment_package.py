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
from typing import IO, Any

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
    """The package cannot be built; ``code`` is an ``ERR_*`` code shown to admins.

    ``fields`` are what the error text interpolates (``limit``, ``detail``, ``folder``).
    """

    def __init__(self, code: str, message: str, limit: str | None = None, **fields: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.fields = {**fields, **({"limit": limit} if limit is not None else {})}

    @property
    def limit(self) -> str | None:
        return self.fields.get("limit")


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


_KEEP: Any = object()


@dataclass(frozen=True)
class HfSource:
    """One task's HF ZIP as its task columns (or an upload's checked summary) describe it."""

    task: Task
    sha256: str
    folders: tuple[str, ...]
    file_count: int
    unpacked_bytes: int
    summary: hf_zip.HfZipSummary | None = None


@dataclass(frozen=True)
class Duplicate:
    """A file of a shared HF folder that ships from another task's ZIP; the build hashes both."""

    arcname: str
    source: str
    member: str
    owner_title: str


@dataclass(frozen=True)
class PackagePlan:
    """What the package would hold, from the files and task columns, without reading ZIPs."""

    public: list[PackageEntry]
    hf_file_count: int
    hf_bytes: int
    hf_shas: list[tuple[str, str]]

    @property
    def file_count(self) -> int:
        return len(self.public) + self.hf_file_count

    @property
    def total_bytes(self) -> int:
        return sum(entry.size for entry in self.public) + self.hf_bytes


def hf_source(task: Task, sha256: str, summary: hf_zip.HfZipSummary) -> HfSource:
    """An upload being checked: its summary is in hand, so it is never read again."""
    return HfSource(
        task, sha256, tuple(summary.folders), summary.file_count, summary.unpacked_bytes, summary
    )


def hf_sources(tasks: list[Task], override: dict[str, HfSource | None]) -> list[HfSource]:
    """The tasks' HF ZIPs; ``override`` maps a task id to the source it would have."""
    sources = []
    for task in tasks:
        if str(task.id) in override:
            replaced = override[str(task.id)]
            if replaced is not None:
                sources.append(replaced)
            continue
        if task.hf_zip_sha256:
            sources.append(
                HfSource(
                    task,
                    str(task.hf_zip_sha256),
                    tuple(task.hf_folders or []),
                    int(task.hf_file_count or 0),
                    int(task.hf_unpacked_bytes or 0),
                )
            )
    return sources


def _summary(source: HfSource, cache: dict[str, hf_zip.HfZipSummary]) -> hf_zip.HfZipSummary:
    """The ZIP's central directory, read once per hash."""
    if source.summary is not None:
        return source.summary
    if source.sha256 not in cache:
        try:
            cache[source.sha256] = hf_zip.inspect_zip(hf_zip.hf_zip_path(source.sha256))
        except (OSError, ValueError) as exc:
            raise PackageError(
                "ERR_ENVIRONMENT_PACKAGE_FAILED",
                f"The Hugging Face data of the task {source.task.title} cannot be read: {exc}",
            ) from None
    return cache[source.sha256]


def folder_conflict(folder: str, first: Task, second: Task, subject: Task | None) -> PackageError:
    """``detail`` names the task the changed one clashes with (the first one in a sync)."""
    other = second if subject is not None and str(first.id) == str(subject.id) else first
    return PackageError(
        "ERR_HF_FOLDER_CONFLICT",
        f"The folder {folder} differs between the tasks {first.title} and {second.title}.",
        folder=folder,
        detail=other.title,
    )


def hf_plan(
    tasks: list[Task], override: dict[str, HfSource | None] | None = None, subject: Any = None
) -> tuple[int, int, list[tuple[str, str]]]:
    """Files and bytes the tasks' HF folders add, from the task columns.

    A ZIP in two tasks ships once; only a folder shared by two different ZIPs reads their
    listings, which must match (size and CRC: the build compares SHA-256).
    """
    sources = hf_sources(tasks, override or {})
    owners: dict[str, HfSource] = {}
    seen: set[str] = set()
    cache: dict[str, hf_zip.HfZipSummary] = {}
    files = size = 0
    for source in sources:
        if source.sha256 in seen:
            continue
        seen.add(source.sha256)
        files += source.file_count
        size += source.unpacked_bytes
        for folder in source.folders:
            first = owners.setdefault(folder, source)
            if first is source:
                continue
            listing = hf_zip.folder_listing(_summary(source, cache), folder)
            if listing != hf_zip.folder_listing(_summary(first, cache), folder):
                raise folder_conflict(folder, first.task, source.task, subject)
            files -= len(listing)
            size -= sum(item[1] for item in listing)
    return files, size, sorted((str(s.task.id), s.sha256) for s in sources)


def hf_entries(tasks: list[Task]) -> tuple[list[PackageEntry], list[Duplicate]]:
    """Root ``models/`` and ``datasets/`` from every task's HF ZIP (a Celery-side read).

    A folder in two ZIPs ships once when both hold the same paths; the build then checks
    each duplicate file's SHA-256 against the shipped one.
    """
    owners: dict[str, tuple[HfSource, set[str]]] = {}
    seen: set[str] = set()
    cache: dict[str, hf_zip.HfZipSummary] = {}
    entries: list[PackageEntry] = []
    duplicates: list[Duplicate] = []
    for source in hf_sources(tasks, {}):
        if source.sha256 in seen:
            continue
        seen.add(source.sha256)
        summary = _summary(source, cache)
        path = hf_zip.hf_zip_path(source.sha256)
        for folder in summary.folders:
            members = [e for e in summary.entries if e.path.startswith(f"{folder}/")]
            paths = {e.path for e in members}
            if folder in owners:
                first, first_paths = owners[folder]
                if paths != first_paths:
                    raise folder_conflict(folder, first.task, source.task, None)
                duplicates.extend(
                    Duplicate(e.path, path, e.info.filename, first.task.title) for e in members
                )
                continue
            owners[folder] = (source, paths)
            entries.extend(
                PackageEntry(
                    arcname=e.path,
                    source=path,
                    size=e.size,
                    member=e.info.filename,
                    digest=f"hf:{source.sha256}:{e.path}",
                )
                for e in members
            )
    return entries, duplicates


def check_caps(file_count: int, total_bytes: int) -> None:
    """2,000 entries and ``NANOCOLAB_PACKAGE_MAX_BYTES``; ``detail`` gives the value."""
    if file_count > MAX_ENTRIES:
        raise PackageError(
            "ERR_ENVIRONMENT_PACKAGE_TOO_LARGE",
            f"The package would hold {file_count} files, more than {MAX_ENTRIES}.",
            limit=f"{MAX_ENTRIES} files",
            detail=f"{file_count} files",
        )
    if total_bytes > Config.NANOCOLAB_PACKAGE_MAX_BYTES:
        limit = format_size(Config.NANOCOLAB_PACKAGE_MAX_BYTES)
        raise PackageError(
            "ERR_ENVIRONMENT_PACKAGE_TOO_LARGE",
            f"The package would be {format_size(total_bytes)}, larger than {limit}.",
            limit=limit,
            detail=format_size(total_bytes),
        )


def check_projected(
    tasks: list[Task],
    task: Task,
    *,
    public_file: tuple[str, str] | None = None,
    hf: Any = _KEEP,
) -> None:
    """The package caps and HF conflicts as they would be after one change.

    ``tasks`` are the owner's tasks after the change (a moved task included);
    ``public_file`` is ``(filename, path)`` of a public file the task would hold, and
    ``hf`` the task's ``HfSource`` (None to remove it).
    """
    entries = [entry for each in tasks for entry in public_entries(each)]
    if public_file is not None:
        arcname = f"{task.folder_name}/{public_file[0]}"
        entries = [e for e in entries if e.arcname != arcname]
        entries.append(file_entry(arcname, public_file[1]))
    override = {} if hf is _KEEP else {str(task.id): hf}
    files, size, _ = hf_plan(tasks, override, subject=task)
    check_caps(len(entries) + files, sum(e.size for e in entries) + size)


def package_plan(tasks: list[Task]) -> PackagePlan:
    """The structure and caps checks of a package, without reading any HF ZIP's contents."""
    if len(export_paths(tasks)) > MAX_EXPORT_PATHS:
        raise PackageError(
            "ERR_ENVIRONMENT_TOO_MANY_TASKS",
            f"An environment reads back at most {MAX_EXPORT_PATHS} files: one per notebook "
            "task and two per file task.",
            limit=str(MAX_EXPORT_PATHS),
        )
    check_folders(tasks)
    public = [entry for task in tasks for entry in public_entries(task)]
    for entry in public:
        if not is_safe_path(entry.arcname):
            raise PackageError(
                "ERR_ENVIRONMENT_PACKAGE_FAILED",
                f"The file name {entry.arcname} is not allowed in a workspace.",
            )
    files, size, shas = hf_plan(tasks)
    plan = PackagePlan(public, files, size, shas)
    if not plan.file_count:
        raise PackageError(
            "ERR_ENVIRONMENT_PACKAGE_EMPTY", "The environment has no task files to package."
        )
    check_caps(plan.file_count, plan.total_bytes)
    return plan


def package_entries(tasks: list[Task]) -> tuple[list[PackageEntry], list[Duplicate]]:
    """Every task's folder, plus the shared Hugging Face folders at the root; call after
    ``package_plan`` passed."""
    entries = [entry for task in tasks for entry in public_entries(task)]
    hf, duplicates = hf_entries(tasks)
    entries.extend(hf)
    check_caps(len(entries), sum(entry.size for entry in entries))
    return sorted(entries, key=lambda entry: entry.arcname), duplicates


def data_gib(plan: PackagePlan) -> int:
    """The task data's size in whole GiB, rounded up."""
    return math.ceil(plan.total_bytes / GIB)


def fingerprint(plan: PackagePlan) -> str:
    """Cheap change detector: public files by name, size and mtime, HF data by each task's
    ZIP sha256 (which fixes its paths and contents), so nothing is hashed or unzipped."""
    listing = []
    for entry in plan.public:
        status = os.stat(entry.source)
        listing.append([entry.arcname, entry.source, entry.size, status.st_mtime_ns])
    payload = json.dumps([BUILDER_VERSION, listing, plan.hf_shas]).encode()
    return hashlib.sha256(payload).hexdigest()


def content_version(entries: list[PackageEntry]) -> str:
    """``lb-<12 hex>-v<builder>`` over the sorted ``<sha256>  <path>`` lines."""
    lines = "".join(f"{e.digest or file_sha256(e.source)}  {e.arcname}\n" for e in entries)
    digest = hashlib.sha256(lines.encode()).hexdigest()
    return f"lb-{digest[:12]}-v{BUILDER_VERSION}"


def _member(sources: dict[str, zipfile.ZipFile], path: str, member: str) -> IO[bytes]:
    if path not in sources:
        sources[path] = hf_zip.open_zip(path)
    return sources[path].open(member)


def _copy(source: IO[bytes], target: IO[bytes], digest: Any) -> None:
    while chunk := source.read(CHUNK):
        digest.update(chunk)
        target.write(chunk)


def _check_duplicates(
    sources: dict[str, zipfile.ZipFile], duplicates: list[Duplicate], hashes: dict[str, str]
) -> None:
    """A shared HF folder is the same data only when every file has the same SHA-256."""
    for duplicate in duplicates:
        digest = hashlib.sha256()
        with _member(sources, duplicate.source, duplicate.member) as source:
            while chunk := source.read(CHUNK):
                digest.update(chunk)
        if digest.hexdigest() != hashes.get(duplicate.arcname):
            folder = hf_zip.folder_of(duplicate.arcname)
            raise PackageError(
                "ERR_HF_FOLDER_CONFLICT",
                f"The folder {folder} holds different files in two tasks ({duplicate.arcname}).",
                folder=folder,
                detail=duplicate.owner_title,
            )


def build(
    entries: list[PackageEntry],
    version: str,
    directory: str,
    duplicates: list[Duplicate] | None = None,
) -> BuiltPackage:
    """Write a ZIP_STORED archive (ZIP64 when needed) with fixed timestamps and modes,
    streaming each entry, then hash it; shared HF files are compared by SHA-256."""
    duplicates = duplicates or []
    hashes: dict[str, str] = {}
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
                digest = hashlib.sha256()
                member = _member(sources, entry.source, entry.member)
                with member as source, archive.open(info, "w") as target:
                    _copy(source, target, digest)
                hashes[entry.arcname] = digest.hexdigest()
        _check_duplicates(sources, duplicates, hashes)
        size = os.path.getsize(path)
        if size > Config.NANOCOLAB_PACKAGE_MAX_BYTES:
            limit = format_size(Config.NANOCOLAB_PACKAGE_MAX_BYTES)
            raise PackageError(
                "ERR_ENVIRONMENT_PACKAGE_TOO_LARGE",
                f"The package is {format_size(size)}, larger than {limit}.",
                limit=limit,
                detail=format_size(size),
            )
        sha256 = file_sha256(path)
    except BaseException:
        os.unlink(path)
        raise
    finally:
        for opened in sources.values():
            opened.close()
    return BuiltPackage(path=path, sha256=sha256, size=size, version=version)
