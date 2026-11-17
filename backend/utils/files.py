"""Safe file saving and cleanup helpers."""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
from typing import IO, Any

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

_COPY_CHUNK = 1024 * 1024


def copy_with_digest(
    source: IO[bytes], target: IO[bytes], max_bytes: int | None = None
) -> tuple[int, str]:
    """Copy *source* into *target* and return its size and sha256 from the same pass."""
    digest = hashlib.sha256()
    size = 0
    while chunk := source.read(_COPY_CHUNK):
        size += len(chunk)
        if max_bytes is not None and size > max_bytes:
            raise ValueError(f"File exceeds {max_bytes} bytes")
        digest.update(chunk)
        target.write(chunk)
    return size, digest.hexdigest()


def file_sha256(path: str) -> str:
    """Hex sha256 of a file on disk, read in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_COPY_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def save_with_digest(uploaded_file: FileStorage, path: str) -> tuple[int, str]:
    """Save an upload to *path* and return its size and sha256."""
    with open(path, "wb") as target:
        return copy_with_digest(uploaded_file.stream, target)


def safe_save_file(uploaded_file: FileStorage, directory: str, filename: str | None = None) -> str:
    os.makedirs(directory, exist_ok=True)
    safe_name = (
        secure_filename(filename) if filename else secure_filename(uploaded_file.filename or "")
    )
    save_path = os.path.join(directory, safe_name)
    uploaded_file.save(save_path)
    return save_path


def cleanup_paths(paths: list[str | None]) -> None:
    for p in paths:
        if p and os.path.exists(p):
            with contextlib.suppress(OSError):
                os.remove(p)


def remove_if_exists(path: str | None) -> None:
    if path and os.path.exists(path):
        with contextlib.suppress(OSError):
            os.remove(path)


def rmtree_ignore(path: str | None) -> None:
    if path and os.path.exists(path):
        shutil.rmtree(path, ignore_errors=True)


HIDDEN_TASK_FILES = frozenset({"labels.parquet"})


def task_file_visibility(entry: dict[str, Any]) -> str:
    """Return ``public`` or ``hidden`` for one entry of ``Task.files``."""
    visibility = entry.get("visibility")
    if visibility in ("public", "hidden"):
        return str(visibility)
    return "hidden" if entry.get("filename") in HIDDEN_TASK_FILES else "public"
