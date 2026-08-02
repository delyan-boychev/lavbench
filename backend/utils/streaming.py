"""Streaming download helpers.

Flask's send_file produces direct-passthrough responses that spectree's
response validation cannot read (raises RuntimeError), while returning a
generator in a (generator, 200, headers) tuple leaves the stream untouched
and lets the WSGI server stream the body without buffering it in RAM.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import closing
from typing import BinaryIO

_CHUNK_SIZE = 1024 * 1024


def _file_chunks(handle: BinaryIO, chunk_size: int = _CHUNK_SIZE) -> Generator[bytes, None, None]:
    while True:
        chunk = handle.read(chunk_size)
        if not chunk:
            break
        yield chunk


def stream_file_response(
    file_path: str, mimetype: str, download_name: str
) -> tuple[Generator[bytes, None, None], int, dict[str, str]]:
    """Stream a file from disk as an attachment (never buffered in RAM)."""

    def generate() -> Generator[bytes, None, None]:
        with open(file_path, "rb") as fh:
            yield from _file_chunks(fh)

    return (
        generate(),
        200,
        {
            "Content-Type": mimetype,
            "Content-Disposition": f'attachment; filename="{download_name}"',
        },
    )


def stream_open_handle_response(
    handle: BinaryIO, mimetype: str, download_name: str
) -> tuple[Generator[bytes, None, None], int, dict[str, str]]:
    """Stream from an already-open binary handle (closed by the generator).

    Used for temp files that are unlinked after the response is built: the
    open handle keeps the inode alive while the body is streamed.
    """

    def generate() -> Generator[bytes, None, None]:
        with closing(handle):
            yield from _file_chunks(handle)

    return (
        generate(),
        200,
        {
            "Content-Type": mimetype,
            "Content-Disposition": f'attachment; filename="{download_name}"',
        },
    )
