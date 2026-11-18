"""Streamed raw-body uploads: one file per request, hashed on the way to a temp file."""

from __future__ import annotations

import contextlib
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from flask import Response, request
from werkzeug.exceptions import ClientDisconnected

from utils.cache_utils import cache_lock
from utils.error_utils import err, with_retry_after
from utils.files import copy_with_digest
from utils.request_helpers import end_db_transaction

ErrorResult = tuple[Response, int]
UPLOAD_TEMP_PREFIX = ".upload-"
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


def receive_body(
    directory: str, max_bytes: int, refuse_too_large: Callable[[], ErrorResult]
) -> ReceivedBody | ErrorResult:
    """Stream the raw request body into *directory*; call after the auth and lock checks.

    Ends the DB transaction first, needs ``Content-Length`` and stops at *max_bytes*.
    """
    content_type = (request.mimetype or "").lower()
    if content_type not in RAW_BODY_TYPES:
        return err(
            "ERR_INVALID_UPLOAD_FORMAT",
            400,
            message="Send the file itself as the request body (application/octet-stream).",
        )
    length = request.content_length
    if length is None:
        return err(
            "ERR_INVALID_REQUEST_BODY", 411, message="The upload needs a Content-Length header."
        )
    if length == 0:
        return err("ERR_NO_DATA_PROVIDED", 400)
    if length > max_bytes:
        return refuse_too_large()
    end_db_transaction()
    request.max_content_length = max_bytes
    os.makedirs(directory, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix=UPLOAD_TEMP_PREFIX, suffix=".part", dir=directory)
    try:
        with os.fdopen(fd, "wb") as target:
            size, sha256 = copy_with_digest(request.stream, target, max_bytes)
    except ValueError:
        _remove(path)
        return refuse_too_large()
    except (ClientDisconnected, OSError):
        _remove(path)
        return err("ERR_INVALID_REQUEST_BODY", 400, message="The upload was interrupted.")
    except BaseException:
        _remove(path)
        raise
    if size != length:
        _remove(path)
        return err("ERR_INVALID_REQUEST_BODY", 400, message="The upload was interrupted.")
    return ReceivedBody(path=path, size=size, sha256=sha256)


def _remove(path: str) -> None:
    with contextlib.suppress(OSError):
        os.remove(path)


def busy() -> ErrorResult:
    return with_retry_after(err("ERR_SUBMISSION_CHECK_BUSY", 503), BUSY_RETRY_SECONDS)


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
