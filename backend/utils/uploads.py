"""Streamed raw-body uploads: one file per request, hashed on the way to a temp file."""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from flask import Response, request
from werkzeug.exceptions import ClientDisconnected

from utils.cache_utils import cache_lock
from utils.error_utils import err, format_size, with_retry_after
from utils.files import copy_with_digest, upload_root
from utils.request_helpers import end_db_transaction

ErrorResult = tuple[Response, int]
UPLOAD_TEMP_PREFIX = ".upload-"
# In-progress uploads, on the upload folder's filesystem so installing them is a rename
INCOMING_DIR = ".incoming"
# A temp file this old belongs to an upload that died with its worker
INCOMING_MAX_AGE_SECONDS = 6 * 3600
# Free space an upload must leave, so the database, logs and backups keep room
FREE_SPACE_MARGIN_BYTES = 2 * 1024**3
RAW_BODY_TYPES = ("application/octet-stream", "application/zip")
# Installing a checked file is a rename and a commit, so a short wait covers any holder
STORE_LOCK_WAIT_SECONDS = 30
STORE_LOCK_TTL = 120
BUSY_RETRY_SECONDS = 10


@dataclass(frozen=True)
class ReceivedBody:
    path: str
    size: int
    sha256: str

    def discard(self) -> None:
        with contextlib.suppress(OSError):
            os.remove(self.path)


def incoming_dir() -> str:
    return os.path.join(upload_root(), INCOMING_DIR)


def _interrupted() -> ErrorResult:
    return err("ERR_UPLOAD_INTERRUPTED", 400)


def _no_space(length: int, directory: str) -> ErrorResult | None:
    """Refuse a body that would leave less than the margin free on the upload disk."""
    try:
        free = shutil.disk_usage(directory).free - FREE_SPACE_MARGIN_BYTES
    except OSError:
        return None
    if length <= free:
        return None
    available = format_size(max(free, 0))
    return err(
        "ERR_UPLOAD_NO_SPACE",
        507,
        message=f"Not enough free disk space on the server for this file ({available} free).",
        limit=available,
    )


def receive_body(
    max_bytes: int, refuse_too_large: Callable[[], ErrorResult]
) -> ReceivedBody | ErrorResult:
    """Stream the raw request body into ``UPLOAD_FOLDER/.incoming/``; call after the auth
    and lock checks.

    Ends the DB transaction first, needs ``Content-Length`` and stops at *max_bytes*.
    """
    content_type = (request.mimetype or "").lower()
    if content_type not in RAW_BODY_TYPES:
        return err("ERR_UPLOAD_CONTENT_TYPE", 415)
    length = request.content_length
    if length is None:
        return err("ERR_UPLOAD_LENGTH_REQUIRED", 411)
    if length == 0:
        return err("ERR_NO_DATA_PROVIDED", 400)
    if length > max_bytes:
        return refuse_too_large()
    directory = incoming_dir()
    os.makedirs(directory, exist_ok=True)
    refused = _no_space(length, directory)
    if refused:
        return refused
    end_db_transaction()
    request.max_content_length = max_bytes
    fd, path = tempfile.mkstemp(prefix=UPLOAD_TEMP_PREFIX, suffix=".part", dir=directory)
    try:
        with os.fdopen(fd, "wb") as target:
            size, sha256 = copy_with_digest(request.stream, target, max_bytes)
    except ValueError:
        _remove(path)
        return refuse_too_large()
    except (ClientDisconnected, OSError):
        _remove(path)
        return _interrupted()
    except BaseException:
        _remove(path)
        raise
    if size != length:
        _remove(path)
        return _interrupted()
    return ReceivedBody(path=path, size=size, sha256=sha256)


def _remove(path: str) -> None:
    with contextlib.suppress(OSError):
        os.remove(path)


def busy() -> ErrorResult:
    return with_retry_after(err("ERR_UPLOAD_STORE_BUSY", 503), BUSY_RETRY_SECONDS)


def sweep_incoming(now: float | None = None) -> int:
    """Remove temp files of uploads that ended without cleaning up (a killed process)."""
    directory = incoming_dir()
    if not os.path.isdir(directory):
        return 0
    cutoff = (now or time.time()) - INCOMING_MAX_AGE_SECONDS
    removed = 0
    for entry in os.scandir(directory):
        with contextlib.suppress(OSError):
            if entry.is_file(follow_symlinks=False) and entry.stat().st_mtime < cutoff:
                os.remove(entry.path)
                removed += 1
    return removed


@contextlib.contextmanager
def store_lock(key: str) -> Iterator[bool]:
    """A Redis lock waited for briefly: installing files and their DB rows run under it."""
    deadline = time.monotonic() + STORE_LOCK_WAIT_SECONDS
    while True:
        with cache_lock(f"upload_store:{key}", ttl=STORE_LOCK_TTL) as got:
            if got or time.monotonic() >= deadline:
                yield got
                return
        time.sleep(0.2)
