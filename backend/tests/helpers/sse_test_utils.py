"""FakeRedis mock for SSE unit tests — simulates Redis sorted sets, pub/sub, and pipelines."""

from __future__ import annotations

from typing import Any


class _FakeRedis:
    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._sorted_sets: dict[str, dict[str, float]] = {}
        self._lists: dict[str, list[Any]] = {}

    # ── Generic key-value ─────────────────────────────────────────────

    def get(self, key: str) -> str | None:
        val = self._data.get(key)
        if val is not None and isinstance(val, str):
            return val
        return None

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

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

    # ── Pub/Sub ───────────────────────────────────────────────────────

    def publish(self, channel: str, message: str) -> int:
        return 1

    # ── Pipeline ──────────────────────────────────────────────────────

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self)


class _FakePipeline:
    def __init__(self, redis: _FakeRedis) -> None:
        self._redis = redis
        self._commands: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def incr(self, key: str) -> _FakePipeline:
        self._commands.append(("incr", (key,), {}))
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
