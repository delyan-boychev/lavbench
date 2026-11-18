"""Tests for the cache helpers."""

import json
import os
import sys
import warnings

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.cache_utils import (
    cache_lock,
    delete_cached,
    get_cached,
    get_coordination_client,
    get_redis_client,
    log_dead_letter,
    redis_time,
    set_cached,
)


class TestRedisTime:
    def test_reads_the_server_clock(self):
        import time

        r = get_coordination_client()
        if r is None:
            pytest.skip("Redis unavailable")
        assert abs(redis_time(r) - time.time()) < 5

    def test_combines_seconds_and_microseconds(self):
        from unittest.mock import MagicMock

        r = MagicMock()
        r.time.return_value = (1700000000, 250000)
        assert redis_time(r) == 1700000000.25

    def test_falls_back_to_the_local_clock(self):
        from unittest.mock import MagicMock, patch

        r = MagicMock()
        r.time.side_effect = ConnectionError("broker down")
        with patch("utils.cache_utils.time.time", return_value=42.0):
            assert redis_time(r) == 42.0


class TestCacheLock:
    @pytest.fixture
    def lock_key(self):
        import uuid

        return f"lock:test:unit:{uuid.uuid4().hex}"

    def test_acquires_lock(self, redis_flush, lock_key):
        with cache_lock(lock_key, ttl=10) as got:
            assert got

    def test_lock_releases_after_context(self, redis_flush, lock_key):
        with cache_lock(lock_key, ttl=10) as got:
            assert got
        with cache_lock(lock_key, ttl=10) as got2:
            assert got2

    def test_concurrent_lock_rejected(self, redis_flush, lock_key):
        with cache_lock(lock_key, ttl=10) as got1:
            assert got1
            r = get_redis_client()
            if r:
                got2 = r.set(lock_key, "test", nx=True, ex=10)
                assert not got2

    def test_uuid_ownership_prevents_cross_deletion(self, redis_flush, lock_key):
        r = get_redis_client()
        if not r:
            pytest.skip("Redis unavailable")
        with cache_lock(lock_key, ttl=10):
            r.set(lock_key, "evil-owner", ex=10)
        val = r.get(lock_key)
        assert val is not None
        decoded = val.decode() if isinstance(val, bytes) else val
        assert decoded == "evil-owner"
        r.delete(lock_key)


class TestDeadLetterQueue:
    @pytest.fixture(autouse=True)
    def clear_queue(self):
        try:
            r = get_coordination_client()
            if r:
                r.delete("dead_letter_queue")
        except Exception as e:
            warnings.warn(f"Failed to clear queue: {e}", stacklevel=2)

    def _unique_submission_id(self):
        import uuid

        return f"dl-{uuid.uuid4().hex}"

    def test_logs_entry(self, redis_flush):
        import time

        r = get_coordination_client()
        if not r:
            pytest.skip("Redis unavailable")
        submission_id = self._unique_submission_id()
        needle = f'"submission_id": "{submission_id}"'.encode()
        deadline = time.time() + 2.0
        matches = []
        while time.time() < deadline:
            log_dead_letter(submission_id, task_id=7, challenge_id=3, error="test error")
            entries = r.lrange("dead_letter_queue", 0, -1)
            matches = [e for e in entries if needle in e]
            if matches:
                break
            time.sleep(0.05)
        assert len(matches) >= 1, f"Entry for submission {submission_id} not found"
        data = json.loads(matches[0])
        assert data["submission_id"] == submission_id
        assert data["task_id"] == 7
        assert data["challenge_id"] == 3
        assert "test error" in data["error"]

    def test_logs_without_error(self, redis_flush):
        import time

        r = get_coordination_client()
        if not r:
            pytest.skip("Redis unavailable")
        submission_id = self._unique_submission_id()
        needle = f'"submission_id": "{submission_id}"'.encode()
        deadline = time.time() + 2.0
        matches = []
        while time.time() < deadline:
            log_dead_letter(submission_id)
            entries = r.lrange("dead_letter_queue", 0, -1)
            matches = [e for e in entries if needle in e]
            if matches:
                break
            time.sleep(0.05)
        assert len(matches) >= 1, f"Entry for submission {submission_id} not found"

    def test_trims_to_1000(self, redis_flush):
        r = get_coordination_client()
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


class TestCacheLockStore:
    def test_locks_live_on_the_broker_redis(self):
        from unittest.mock import MagicMock, patch

        broker, cache = MagicMock(), MagicMock()
        broker.set.return_value = True
        with (
            patch("utils.cache_utils.get_coordination_client", return_value=broker),
            patch("utils.cache_utils.get_redis_client", return_value=cache),
            cache_lock("submit_lock:user_1:challenge_1", ttl=10) as got,
        ):
            assert got is True
        assert broker.set.call_args.args[0] == "submit_lock:user_1:challenge_1"
        assert broker.set.call_args.kwargs == {"nx": True, "ex": 10}
        cache.set.assert_not_called()

    def test_submit_route_takes_its_lock_on_the_broker(
        self, client, tokens, auth_headers, sample_task, monkeypatch
    ):
        from unittest.mock import MagicMock

        broker = MagicMock()
        broker.exists.return_value = 0
        broker.eval.return_value = [1, 60]
        broker.set.return_value = False  # Another request holds the submit lock
        cache = MagicMock()
        cache.get.return_value = None
        monkeypatch.setattr("utils.cache_utils.get_coordination_client", lambda: broker)
        monkeypatch.setattr("utils.cache_utils.get_redis_client", lambda: cache)

        res = client.post(
            f"/api/tasks/{sample_task.id}/submit",
            json={"selected_cells": [{"source": "print(1)"}]},
            headers=auth_headers(tokens.competitor),
        )

        assert res.status_code == 429
        assert res.get_json()["code"] == "ERR_SUBMIT_LOCKED"
        assert any(
            str(call.args[0]).startswith("submit_lock:") for call in broker.set.call_args_list
        )
        assert not any(
            str(call.args[0]).startswith("submit_lock:") for call in cache.set.call_args_list
        )


class TestRenewingLock:
    def test_the_holder_keeps_the_lock_past_its_ttl(self, redis_flush):
        import time

        from utils.cache_utils import get_coordination_client, renewing_lock

        r = get_coordination_client()
        with renewing_lock("test:renewing", ttl=1) as got:
            assert got
            time.sleep(2.5)
            assert r.get("test:renewing") is not None
            with renewing_lock("test:renewing", ttl=1) as second:
                assert not second
        assert r.get("test:renewing") is None

    def test_a_crashed_holder_frees_the_lock_within_the_ttl(self, redis_flush):
        import time

        from utils.cache_utils import get_coordination_client, renewing_lock

        r = get_coordination_client()
        # A holder that died: its token stays, but nothing renews it
        r.set("test:crashed", "dead-owner", ex=1)
        with renewing_lock("test:crashed", ttl=1) as got:
            assert not got
        time.sleep(1.5)
        with renewing_lock("test:crashed", ttl=1) as got:
            assert got
