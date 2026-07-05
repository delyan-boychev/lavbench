from __future__ import annotations

from collections.abc import Callable, Generator

from flask import Response, stream_with_context


def sse_response(
    event_generator: Callable[[], Generator[str, None, None]],
) -> tuple[Response, int, dict[str, str]]:
    headers: dict[str, str] = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
        "Content-Type": "text/event-stream",
    }
    return stream_with_context(event_generator()), 200, headers  # type: ignore[return-value]
