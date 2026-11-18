"""Hugging Face ZIPs: one per task, checked on upload, packaged and extracted by workers."""

from __future__ import annotations

import os
import re
import stat
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import PurePosixPath

from utils.text import is_safe_path

HF_ROOTS = ("models", "datasets")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
# Bounds read from the end record before zipfile loads the central directory
MAX_MEMBERS = 50_000
MAX_DIRECTORY_BYTES = 64 * 1024 * 1024
# The ratio nanoColab allows per entry; Hugging Face weights barely compress
MAX_COMPRESSION_RATIO = 200
CHUNK = 1024 * 1024


class HfZipError(ValueError):
    """The ZIP breaks a rule; ``too_large`` marks a size limit, which answers 413."""

    def __init__(self, message: str, *, too_large: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.too_large = too_large


@dataclass(frozen=True)
class HfEntry:
    path: str
    size: int
    crc: int
    info: zipfile.ZipInfo


@dataclass(frozen=True)
class HfZipSummary:
    entries: list[HfEntry]
    folders: list[str]
    unpacked_bytes: int
    skipped_count: int

    @property
    def file_count(self) -> int:
        return len(self.entries)


def hf_store_dir() -> str:
    from utils.files import upload_root

    return os.path.join(upload_root(), "hf")


def hf_zip_path(sha256: str) -> str:
    """Where the web host keeps a ZIP: ``UPLOAD_FOLDER/hf/<sha256>.zip``, shared by hash."""
    if not SHA256_RE.fullmatch(sha256):
        raise ValueError("Invalid sha256")
    return os.path.join(hf_store_dir(), f"{sha256}.zip")


def is_hidden(name: str) -> bool:
    """Hidden entries (a segment starting with ``.``) are skipped, never refused."""
    return any(part.startswith(".") for part in name.split("/") if part)


def folder_of(path: str) -> str:
    return "/".join(path.split("/")[:3])


def _check_member(info: zipfile.ZipInfo, names: set[str]) -> str:
    """The zip-safety rules every entry passes, hidden or not; returns the entry name."""
    name = info.filename
    if name in names:
        raise HfZipError(f"The ZIP holds {name} twice.")
    names.add(name)
    if info.flag_bits & 0x1:
        raise HfZipError(f"{name} is encrypted; use an unencrypted ZIP.")
    path = PurePosixPath(name)
    if "\\" in name or path.is_absolute() or ".." in path.parts or not path.parts:
        raise HfZipError(f"{name} is not a safe path inside the ZIP.")
    file_type = stat.S_IFMT(info.external_attr >> 16)
    if file_type not in (0, stat.S_IFREG, stat.S_IFDIR) or (
        file_type == stat.S_IFDIR and not info.is_dir()
    ):
        raise HfZipError(f"{name} is a link or a special file; include only regular files.")
    return name


def _check_visible(info: zipfile.ZipInfo, name: str) -> str:
    """nanoColab's path rules and the folder structure, for entries that ship."""
    path = name.rstrip("/")
    if not is_safe_path(path):
        raise HfZipError(f"{path} is not allowed in a workspace: rename it.")
    parts = path.split("/")
    if parts[0] not in HF_ROOTS:
        raise HfZipError(f"{path} is outside models/ and datasets/.")
    if info.is_dir():
        return path
    if len(parts) < 4:
        raise HfZipError(f"{path} must be inside models/<org>/<name>/ or datasets/<org>/<name>/.")
    if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        raise HfZipError(f"{path} uses an unsupported compression; use stored or deflated.")
    if info.file_size > max(info.compress_size, 1) * MAX_COMPRESSION_RATIO:
        raise HfZipError(f"{path} exceeds the compression-ratio limit.")
    return path


def open_zip(path: str) -> zipfile.ZipFile:
    """Open a ZIP after bounding its central directory from the end record."""
    with open(path, "rb") as probe:
        end_record = zipfile._EndRecData(probe)  # type: ignore[attr-defined]
    if end_record is None:
        raise HfZipError("The file is not a ZIP archive.")
    if end_record[zipfile._ECD_ENTRIES_TOTAL] > MAX_MEMBERS:  # type: ignore[attr-defined]
        raise HfZipError(f"The ZIP holds more than {MAX_MEMBERS} entries.")
    if end_record[zipfile._ECD_SIZE] > MAX_DIRECTORY_BYTES:  # type: ignore[attr-defined]
        raise HfZipError("The ZIP directory is too large.")
    try:
        return zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise HfZipError(f"The ZIP could not be read: {exc}") from None


def summarize(archive: zipfile.ZipFile, max_unpacked: int | None = None) -> HfZipSummary:
    """Check the central directory only; nothing is extracted."""
    names: set[str] = set()
    folded: dict[str, str] = {}
    entries: list[HfEntry] = []
    directories: set[str] = set()
    skipped = 0
    total = 0
    for info in archive.infolist():
        name = _check_member(info, names)
        if is_hidden(name):
            skipped += 0 if info.is_dir() else 1
            continue
        path = _check_visible(info, name)
        key = path.casefold()
        if key in folded and folded[key] != path:
            raise HfZipError(f"{path} differs from {folded[key]} only in letter case.")
        folded[key] = path
        if info.is_dir():
            directories.add(key)
            continue
        total += info.file_size
        if max_unpacked is not None and total > max_unpacked:
            raise HfZipError("The unpacked files are too large.", too_large=True)
        entries.append(HfEntry(path=path, size=info.file_size, crc=info.CRC, info=info))
    files = {entry.path.casefold() for entry in entries}
    for entry in entries:
        for parent in PurePosixPath(entry.path).parents:
            if str(parent).casefold() in files:
                raise HfZipError(f"{parent} is both a file and a folder.")
    if not entries:
        raise HfZipError(
            "The ZIP has no files under models/<org>/<name>/ or datasets/<org>/<name>/."
        )
    return HfZipSummary(
        entries=sorted(entries, key=lambda entry: entry.path),
        folders=sorted({folder_of(entry.path) for entry in entries}),
        unpacked_bytes=total,
        skipped_count=skipped,
    )


def inspect_zip(path: str, max_unpacked: int | None = None) -> HfZipSummary:
    """Open and check a stored ZIP; raises ``HfZipError`` naming the offending path."""
    with open_zip(path) as archive:
        return summarize(archive, max_unpacked)


def folder_listing(summary: HfZipSummary, folder: str) -> list[tuple[str, int, int]]:
    """``(path, size, crc)`` of every file in one folder: equal listings are the same data."""
    prefix = f"{folder}/"
    return [(e.path, e.size, e.crc) for e in summary.entries if e.path.startswith(prefix)]


def extract(path: str, destination: str, max_unpacked: int) -> int:
    """Extract the visible files into an empty *destination*; real sizes may not pass the
    declared ones, and zipfile checks every CRC. Returns the bytes written."""
    written_total = 0
    with open_zip(path) as archive:
        summary = summarize(archive, max_unpacked)
        for entry in summary.entries:
            target = os.path.join(destination, *entry.path.split("/"))
            os.makedirs(os.path.dirname(target), mode=0o755, exist_ok=True)
            written = 0
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            try:
                with archive.open(entry.info) as source, os.fdopen(fd, "wb") as out:
                    while chunk := source.read(CHUNK):
                        written += len(chunk)
                        if written > entry.size:
                            raise HfZipError(f"{entry.path} is larger than its declared size.")
                        out.write(chunk)
            except (zipfile.BadZipFile, zlib.error, EOFError) as exc:
                raise HfZipError(f"{entry.path} is corrupt: {exc}") from None
            if written != entry.size:
                raise HfZipError(f"{entry.path} is shorter than its declared size.")
            written_total += written
            if written_total > max_unpacked:
                raise HfZipError("The unpacked files are too large.", too_large=True)
    return written_total
