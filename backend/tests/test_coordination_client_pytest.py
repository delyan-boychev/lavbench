"""Tests for the Redis coordination client."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.cache_utils import (
    DIRTY_CHALLENGES_SET,
    DIRTY_LEADERBOARD_VERSIONS,
    clear_dirty_leaderboard_version,
    get_coordination_client,
    get_dirty_leaderboard_versions,
    get_queue_depth,
    get_redis_client,
    invalidate_leaderboard_cache,
    log_dead_letter,
    set_cached,
    submission_fallback_key,
    submission_logs_key,
    worker_spec_key,
)


def _coordination():
    r = get_coordination_client()
    if not r:
        pytest.skip("Redis unavailable")
    return r


class TestCoordinationClient:
    def test_returns_working_client(self, redis_flush):
        r = get_coordination_client()
        if not r:
            pytest.skip("Redis unavailable")
        assert r.ping() is True

    def test_set_get_round_trip(self, redis_flush):
        r = _coordination()
        r.set("coordination:test:key", "value-1", ex=60)
        val = r.get("coordination:test:key")
        decoded = val.decode() if isinstance(val, bytes) else val
        assert decoded == "value-1"


class TestQueueDepth:
    def test_returns_int(self, redis_flush):
        depth = get_queue_depth("celery")
        assert isinstance(depth, int)
        assert depth >= 0

    def test_reflects_pushes_to_celery_queue(self, redis_flush):
        r = _coordination()
        before = r.llen("celery")
        try:
            r.rpush("celery", "msg-1", "msg-2", "msg-3")
            assert get_queue_depth("celery") >= before + 3
        finally:
            r.ltrim("celery", 0, before - 1 if before > 0 else 0)
            if before == 0:
                r.delete("celery")

    def test_counts_priority_subqueues(self, redis_flush):
        """Celery stores priority>0 messages under `{queue}@N` keys."""
        r = _coordination()
        base = r.llen("mtest_queue")
        svc_keys = [k.decode() for k in r.keys("mtest_queue@*")] if r.keys("mtest_queue@*") else []
        try:
            r.rpush("mtest_queue", "base-msg")
            r.rpush("mtest_queue@8", "prio-msg-1")
            r.rpush("mtest_queue@0", "prio-msg-2")
            assert get_queue_depth("mtest_queue") == base + 3
        finally:
            r.delete("mtest_queue")
            for k in svc_keys:
                r.delete(k)


class TestInvalidateLeaderboardCache:
    def test_marks_challenge_dirty(self, redis_flush):
        invalidate_leaderboard_cache(123)
        r = _coordination()
        assert int(r.hget(DIRTY_LEADERBOARD_VERSIONS, "123")) == 1

    def test_invalidation_increments_version(self, redis_flush):
        invalidate_leaderboard_cache(123)
        invalidate_leaderboard_cache(123)
        r = _coordination()
        assert int(r.hget(DIRTY_LEADERBOARD_VERSIONS, "123")) == 2

    def test_clear_preserves_newer_invalidation(self, redis_flush):
        invalidate_leaderboard_cache(123)
        r = _coordination()
        versions = get_dirty_leaderboard_versions(r)
        invalidate_leaderboard_cache(123)

        assert clear_dirty_leaderboard_version(r, 123, versions["123"]) is False
        assert int(r.hget(DIRTY_LEADERBOARD_VERSIONS, "123")) == 2

    def test_consumes_legacy_dirty_set(self, redis_flush):
        r = _coordination()
        r.sadd(DIRTY_CHALLENGES_SET, "123")

        assert get_dirty_leaderboard_versions(r)["123"] == 1
        assert not r.exists(DIRTY_CHALLENGES_SET)

    def test_delete_only_clears_dirty_and_cache_keys(self, redis_flush):
        co = _coordination()
        co.sadd(DIRTY_CHALLENGES_SET, "123")
        co.hset(DIRTY_LEADERBOARD_VERSIONS, "123", 2)
        set_cached("leaderboard:raw:123:frozen", {"x": 1})
        set_cached("leaderboard:raw:123:unfrozen", {"x": 1})
        set_cached("leaderboard:pending:123", {"x": 1})

        invalidate_leaderboard_cache(123, delete_only=True)

        members = {
            m.decode() if isinstance(m, bytes) else m for m in co.smembers(DIRTY_CHALLENGES_SET)
        }
        assert "123" not in members
        assert co.hget(DIRTY_LEADERBOARD_VERSIONS, "123") is None
        r = get_redis_client()
        if not r:
            pytest.skip("Redis unavailable")
        assert r.get("leaderboard:raw:123:frozen") is None
        assert r.get("leaderboard:raw:123:unfrozen") is None
        assert r.get("leaderboard:pending:123") is None


class TestDeadLetterRoundTrip:
    def _unique_submission_id(self):
        import uuid

        return f"coord-{uuid.uuid4().hex}"

    def _read_entry(self, r, submission_id, timeout=2.0):
        import time

        needle = f'"submission_id": "{submission_id}"'.encode()
        deadline = time.time() + timeout
        while time.time() < deadline:
            entries = r.lrange("dead_letter_queue", 0, -1)
            matches = [e for e in entries if needle in e]
            if matches:
                return matches[0]
            time.sleep(0.05)
        return None

    def test_log_and_read_via_coordination_client(self, redis_flush):
        r = _coordination()
        submission_id = self._unique_submission_id()
        log_dead_letter(submission_id, task_id=7, challenge_id=3, error="boom")
        entry = self._read_entry(r, submission_id)
        assert entry is not None
        data = json.loads(entry)
        assert data["submission_id"] == submission_id
        assert data["task_id"] == 7
        assert data["challenge_id"] == 3
        assert data["error"] == "boom"

    def test_log_without_error(self, redis_flush):
        r = _coordination()
        submission_id = self._unique_submission_id()
        log_dead_letter(submission_id)
        entry = self._read_entry(r, submission_id)
        assert entry is not None
        data = json.loads(entry)
        assert data["submission_id"] == submission_id
        assert data["error"] is None


class TestKeyHelpers:
    def test_worker_spec_key(self):
        assert worker_spec_key("worker-01") == "worker_spec:worker-01"

    def test_submission_fallback_key(self):
        assert submission_fallback_key("sub_abc") == "submission:sub_abc:fallback"

    def test_submission_logs_key(self):
        assert submission_logs_key("sub_abc") == "submission:sub_abc:logs"

    def test_dirty_challenges_set_constant(self):
        assert DIRTY_CHALLENGES_SET == "leaderboard:dirty_challenges"

    def test_dirty_versions_constant(self):
        assert DIRTY_LEADERBOARD_VERSIONS == "leaderboard:dirty_versions"
