"""SSE response helpers: DB session release, reconnect jitter and signal-only streams."""

from __future__ import annotations

import contextlib
import json
import logging
import random
import time
from collections.abc import Callable, Generator
from typing import Any

from flask import Response, stream_with_context

from config import Config
from models import db
from utils.cache_utils import get_sse_client
from utils.sse_utils import sse_connection_limit, sse_heartbeat

logger = logging.getLogger(__name__)

# Seconds between keep-alive comments; eviction is checked at the same pace
SSE_KEEPALIVE_SECONDS = 10.0
# Spread of the retry field and the idle timeout (+/-30%) so streams never act in sync
_JITTER_FRACTION = 0.3
# Upper bound on queued messages folded into one update signal
_MAX_DRAINED_MESSAGES = 100

SSE_UPDATE_PAYLOAD: dict[str, str] = {"event": "update"}
SSE_SOCKET_LIMIT_PAYLOAD: dict[str, str] = {
    "error": "too many connections",
    "code": "ERR_SSE_SOCKET_LIMIT",
}

_rng = random.SystemRandom()


def _jittered(value: float) -> float:
    return value * _rng.uniform(1 - _JITTER_FRACTION, 1 + _JITTER_FRACTION)


def sse_data(payload: dict[str, Any]) -> str:
    """Serialize one JSON payload as an SSE data event."""
    return f"data: {json.dumps(payload)}\n\n"


def sse_retry_field() -> str:
    """Return this stream's retry field: SSE_RETRY_MS jittered by +/-30%."""
    return f"retry: {round(_jittered(Config.SSE_RETRY_MS))}\n\n"


def jittered_idle_timeout() -> float:
    """Return this stream's idle timeout: SSE_IDLE_TIMEOUT jittered by +/-30%."""
    return _jittered(Config.SSE_IDLE_TIMEOUT)


def sse_response(
    event_generator: Callable[[], Generator[str, None, None]],
) -> tuple[Response, int, dict[str, str]]:
    """Release the request's DB session, then stream the generator.

    A stream lives for up to the idle timeout; keeping the session would pin a
    pooled connection, and its open transaction, for that whole time. Generators
    must therefore never query the database.
    """
    db.session.remove()
    headers: dict[str, str] = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
        "Content-Type": "text/event-stream",
    }
    return stream_with_context(event_generator()), 200, headers  # type: ignore[return-value]


def subscribe_channel(channel: str) -> Any | None:
    """Subscribe to a broker pub/sub channel; None when the broker is unreachable."""
    client = get_sse_client()
    if client is None:
        return None
    pubsub = client.pubsub()
    try:
        pubsub.subscribe(channel)
    except Exception as e:
        logger.warning("SSE subscribe to %s failed: %s", channel, e)
        close_pubsub(pubsub)
        return None
    return pubsub


def close_pubsub(pubsub: Any | None) -> None:
    """Unsubscribe and release a pub/sub connection, ignoring broker errors."""
    if pubsub is None:
        return
    with contextlib.suppress(Exception):
        pubsub.unsubscribe()
    with contextlib.suppress(Exception):
        pubsub.close()


def _drain(pubsub: Any) -> None:
    """Consume already-queued messages so a burst yields a single signal."""
    with contextlib.suppress(Exception):
        for _ in range(_MAX_DRAINED_MESSAGES):
            if not pubsub.get_message(ignore_subscribe_messages=True, timeout=0.0):
                return


def signal_stream(channel: str, user_id: Any) -> Callable[[], Generator[str, None, None]]:
    """Build a stream that turns every message on ``channel`` into ``{"event": "update"}``.

    Clients refetch over REST when signalled, so the stream builds no payload and
    never touches the database. Without a broker connection it degrades to one
    signal per keep-alive interval, which keeps clients polling.
    """

    def generate() -> Generator[str, None, None]:
        with sse_connection_limit(user_id=user_id) as (allowed, member):
            if not allowed:
                yield sse_data(SSE_SOCKET_LIMIT_PAYLOAD)
                return
            yield sse_retry_field()
            yield sse_data({"info": "connected"})
            pubsub = subscribe_channel(channel)
            deadline = time.monotonic() + jittered_idle_timeout()
            try:
                while True:
                    if time.monotonic() >= deadline:
                        yield sse_data({"event": "timeout"})
                        return
                    if member and not sse_heartbeat(member, user_id):
                        yield sse_data({"event": "evicted"})
                        return
                    if pubsub is None:
                        time.sleep(SSE_KEEPALIVE_SECONDS)
                        yield sse_data(SSE_UPDATE_PAYLOAD)
                        continue
                    message = pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=SSE_KEEPALIVE_SECONDS
                    )
                    if not message:
                        yield ": keep-alive\n\n"
                        continue
                    _drain(pubsub)
                    yield sse_data(SSE_UPDATE_PAYLOAD)
            except Exception as e:
                logger.warning("SSE stream on %s ended by an error: %s", channel, e)
            finally:
                close_pubsub(pubsub)

    return generate
