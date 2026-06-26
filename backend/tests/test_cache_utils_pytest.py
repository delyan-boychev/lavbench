import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from cache_utils import (
    cache_lock,
    delete_cached,
    get_cached,
    get_redis_client,
    log_dead_letter,
    set_cached,
)


class TestCacheLock:
    def test_acquires_lock(self, redis_flush):
        with cache_lock("lock:test:unit", ttl=10) as got:
            assert got

    def test_lock_releases_after_context(self, redis_flush):
        with cache_lock("lock:test:unit", ttl=10) as got:
            assert got
        with cache_lock("lock:test:unit", ttl=10) as got2:
            assert got2

    def test_concurrent_lock_rejected(self, redis_flush):
        with cache_lock("lock:test:unit", ttl=10) as got1:
            assert got1
            r = get_redis_client()
            if r:
                got2 = r.set("lock:test:unit", "test", nx=True, ex=10)
                assert not got2

    def test_uuid_ownership_prevents_cross_deletion(self, redis_flush):
        r = get_redis_client()
        if not r:
            pytest.skip("Redis unavailable")
        with cache_lock("lock:test:unit", ttl=10):
            r.set("lock:test:unit", "evil-owner", ex=10)
        val = r.get("lock:test:unit")
        assert val is not None
        decoded = val.decode() if isinstance(val, bytes) else val
        assert decoded == "evil-owner"
        r.delete("lock:test:unit")


class TestDeadLetterQueue:
    @pytest.fixture(autouse=True)
    def clear_queue(self):
        try:
            r = get_redis_client()
            if r:
                r.delete("dead_letter_queue")
        except Exception:  # noqa: S110
            pass

    def test_logs_entry(self, redis_flush):
        log_dead_letter(42, task_id=7, challenge_id=3, error="test error")
        r = get_redis_client()
        if not r:
            pytest.skip("Redis unavailable")
        entries = r.lrange("dead_letter_queue", 0, -1)
        matches = [e for e in entries if b'"submission_id": 42' in e]
        assert len(matches) >= 1, f"Entry for submission 42 not found in {entries}"
        data = json.loads(matches[0])
        assert data["submission_id"] == 42
        assert data["task_id"] == 7
        assert data["challenge_id"] == 3
        assert "test error" in data["error"]

    def test_logs_without_error(self, redis_flush):
        log_dead_letter(1)
        r = get_redis_client()
        if not r:
            pytest.skip("Redis unavailable")
        entries = r.lrange("dead_letter_queue", 0, -1)
        matches = [e for e in entries if b'"submission_id": 1' in e]
        assert len(matches) >= 1, f"Entry for submission 1 not found in {entries}"

    def test_trims_to_1000(self, redis_flush):
        r = get_redis_client()
        if not r:
            pytest.skip("Redis unavailable")
        # Clear any entries left by other workers
        r.delete("dead_letter_queue")
        for i in range(1100):
            log_dead_letter(i)
        count = r.llen("dead_letter_queue")
        # Allow a small fudge for concurrent workers pushing during the loop
        assert count <= 1050
        r.delete("dead_letter_queue")


class TestCacheOperations:
    def test_set_and_get_cache(self, redis_flush):
        set_cached("test:cache:key", {"foo": "bar"}, timeout=30)
        result = get_cached("test:cache:key")
        assert result is not None
        assert result["foo"] == "bar"

    def test_get_returns_none_for_missing(self, redis_flush):
        result = get_cached("test:cache:nonexistent_key_xyz")
        assert result is None

    def test_delete_cache(self, redis_flush):
        set_cached("test:cache:key", {"x": 1}, timeout=30)
        assert get_cached("test:cache:key") is not None
        delete_cached("test:cache:key")
        assert get_cached("test:cache:key") is None
