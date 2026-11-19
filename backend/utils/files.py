"""Safe file saving and cleanup helpers."""

from __future__ import annotations

import hashlib
from typing import IO, Any

from werkzeug.utils import secure_filename

_COPY_CHUNK = 1024 * 1024


def upload_root() -> str:
    """The upload folder of the running app, or the configured one outside a request."""
    from flask import current_app, has_app_context

    from config import Config

    if has_app_context():
        return str(current_app.config["UPLOAD_FOLDER"])
    return Config.UPLOAD_FOLDER


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


def unique_saved_name(original_name: str) -> str:
    """A new on-disk name per upload: workers detect a replaced file by its ``saved_name``."""
    import uuid

    return f"{uuid.uuid4().hex}-{secure_filename(original_name) or 'file'}"


def file_sha256(path: str) -> str:
    """Hex sha256 of a file on disk, read in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_COPY_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


LABELS_FILE = "labels.parquet"
BASELINE_SUBMISSION_FILE = "baseline_submission.parquet"
HIDDEN_TASK_FILES = frozenset({LABELS_FILE, BASELINE_SUBMISSION_FILE})


def task_file_visibility(entry: dict[str, Any]) -> str:
    """Return ``public`` or ``hidden`` for one entry of ``Task.files``.

    Labels and the baseline submission are always hidden; other files follow their
    recorded ``visibility`` and are public when it is absent.
    """
    if entry.get("filename") in HIDDEN_TASK_FILES or entry.get("visibility") == "hidden":
        return "hidden"
    return "public"
