"""FakeRedis mock for SSE unit tests — simulates Redis sorted sets, pub/sub, and pipelines."""

from __future__ import annotations

from typing import Any


class _FakeRedis:
    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._sorted_sets: dict[str, dict[str, float]] = {}
        self._lists: dict[str, list[Any]] = {}
        self.published_messages: list[tuple[str, str | bytes]] = []
        # Messages handed out, in order, by get_message() on any pubsub of this client
        self.pending_messages: list[dict[str, Any]] = []
        self.subscriptions: list[str] = []
        self.pubsubs: list[_FakePubSub] = []

    # ── Generic key-value ─────────────────────────────────────────────

    def get(self, key: str) -> str | None:
        val = self._data.get(key)
        if val is not None and isinstance(val, str):
            return val
        return None

    def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool:
        if nx and key in self._data:
            return False
        self._data[key] = value
        return True

    def delete(self, *keys: str) -> int:
        n = 0
        for k in keys:
            self._data.pop(k, None)
            self._sorted_sets.pop(k, None)
            self._lists.pop(k, None)
            n += 1
        return n

    def expire(self, key: str, _seconds: int) -> None:
        pass  # no-op in tests

    def exists(self, key: str) -> int:
        return 1 if (key in self._data or key in self._sorted_sets or key in self._lists) else 0

    def incr(self, key: str) -> int:
        val = int(self._data.get(key, 0))
        val += 1
        self._data[key] = str(val)
        return val

    def decr(self, key: str) -> int:
        val = int(self._data.get(key, 0))
        val -= 1
        self._data[key] = str(val)
        return val

    # ── Sorted sets ───────────────────────────────────────────────────

    def zadd(self, key: str, mapping: dict[str, float]) -> int:
        if key not in self._sorted_sets:
            self._sorted_sets[key] = {}
        ss = self._sorted_sets[key]
        n = 0
        for member, score in mapping.items():
            if member not in ss:
                n += 1
            ss[member] = score
        return n

    def zcard(self, key: str) -> int:
        return len(self._sorted_sets.get(key, {}))

    def zcount(self, key: str, _min: float | str, _max: float | str) -> int:
        ss = self._sorted_sets.get(key, {})
        lo = float(_min) if not isinstance(_min, (int, float)) else _min
        hi = float(_max) if not isinstance(_max, (int, float)) else _max
        return sum(1 for s in ss.values() if lo <= s <= hi)

    def zrem(self, key: str, *members: str) -> int:
        ss = self._sorted_sets.get(key)
        if not ss:
            return 0
        n = 0
        for m in members:
            if m in ss:
                del ss[m]
                n += 1
        return n

    def zpopmin(self, key: str, count: int = 1) -> list[tuple[str, float]]:
        ss = self._sorted_sets.get(key)
        if not ss:
            return []
        sorted_members = sorted(ss.items(), key=lambda x: x[1])
        popped = sorted_members[:count]
        for m, _ in popped:
            del ss[m]
        return [(m, s) for m, s in popped]

    def zrange(self, key: str, start: int, end: int, withscores: bool = False) -> list[Any]:
        ss = self._sorted_sets.get(key, {})
        sorted_members = sorted(ss.items(), key=lambda x: x[1])
        chunk = sorted_members[start : end + 1 if end >= 0 else None]
        if withscores:
            return [(m, s) for m, s in chunk]
        return [m for m, _ in chunk]

    def zscore(self, key: str, member: str) -> float | None:
        return self._sorted_sets.get(key, {}).get(member)

    def zremrangebyscore(self, key: str, _min: float | str, _max: float | str) -> int:
        ss = self._sorted_sets.get(key)
        if not ss:
            return 0
        lo = float(_min) if not isinstance(_min, (int, float)) else _min
        hi = float(_max) if not isinstance(_max, (int, float)) else _max
        to_remove = [m for m, s in ss.items() if lo <= s <= hi]
        for m in to_remove:
            del ss[m]
        return len(to_remove)

    # ── Lists ─────────────────────────────────────────────────────────

    def rpush(self, key: str, *values: Any) -> int:
        if key not in self._lists:
            self._lists[key] = []
        self._lists[key].extend(values)
        return len(self._lists[key])

    def ltrim(self, key: str, start: int, end: int) -> None:
        lst = self._lists.get(key)
        if lst is not None:
            self._lists[key] = lst[start : end + 1 if end >= 0 else None]

    def lrange(self, key: str, start: int, end: int) -> list[Any]:
        lst = self._lists.get(key, [])
        return lst[start : end + 1 if end >= 0 else None]

    # ── Pub/Sub ───────────────────────────────────────────────────────

    def publish(self, channel: str, message: str | bytes) -> int:
        """Record the message and deliver it to the pub/subs subscribed right now."""
        self.published_messages.append((channel, message))
        data = message.encode() if isinstance(message, str) else message
        receivers = [p for p in self.pubsubs if channel in p.channels]
        for p in receivers:
            p.inbox.append({"type": "message", "channel": channel.encode(), "data": data})
        return len(receivers)

    def pubsub(self) -> _FakePubSub:
        pubsub = _FakePubSub(self)
        self.pubsubs.append(pubsub)
        return pubsub

    # ── Pipeline ──────────────────────────────────────────────────────

    def pipeline(self, transaction: bool = True) -> _FakePipeline:
        return _FakePipeline(self)


class _FakePubSub:
    """Receives only what is published while subscribed, after one confirmation per channel."""

    def __init__(self, redis: _FakeRedis | None = None) -> None:
        self.channels: list[str] = []
        self.inbox: list[dict[str, Any]] = []
        self.closed = False
        self._redis = redis

    def subscribe(self, *channels: str) -> None:
        self.channels.extend(channels)
        for channel in channels:
            self.inbox.append({"type": "subscribe", "channel": channel.encode(), "data": 1})
        if self._redis is not None:
            self._redis.subscriptions.extend(channels)

    def get_message(
        self, ignore_subscribe_messages: bool = True, timeout: float | None = None
    ) -> dict[str, Any] | None:
        while self.inbox:
            message = self.inbox.pop(0)
            if message["type"] == "subscribe" and ignore_subscribe_messages:
                continue
            return message
        if self._redis is not None and self._redis.pending_messages:
            return self._redis.pending_messages.pop(0)
        return None

    def unsubscribe(self) -> None:
        self.channels = []

    def close(self) -> None:
        self.channels = []
        self.closed = True


class _FakePipeline:
    def __init__(self, redis: _FakeRedis) -> None:
        self._redis = redis
        self._commands: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def incr(self, key: str) -> _FakePipeline:
        self._commands.append(("incr", (key,), {}))
        return self

    def rpush(self, key: str, *values: Any) -> _FakePipeline:
        self._commands.append(("rpush", (key, *values), {}))
        return self

    def ltrim(self, key: str, start: int, end: int) -> _FakePipeline:
        self._commands.append(("ltrim", (key, start, end), {}))
        return self

    def expire(self, key: str, seconds: int) -> _FakePipeline:
        self._commands.append(("expire", (key, seconds), {}))
        return self

    def execute(self) -> list[Any]:
        results = []
        for cmd, args, _kwargs in self._commands:
            method = getattr(self._redis, cmd)
            results.append(method(*args))
        return results


def fake_redis() -> _FakeRedis:
    """Create a fresh FakeRedis instance for use in tests."""
    return _FakeRedis()
