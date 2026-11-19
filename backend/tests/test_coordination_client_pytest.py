"""Tests for the Redis coordination client."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.cache_utils import (
    DIRTY_LEADERBOARD_VERSIONS,
    EVALUATION_PRIORITY_STEPS,
    KOMBU_PRIORITY_SEP,
    clear_dirty_leaderboard_version,
    get_coordination_client,
    get_dirty_leaderboard_versions,
    get_queue_depth,
    get_queue_depths,
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

    def test_counts_messages_kombu_puts_on_priority_lists(self, redis_flush):
        """Messages sent with priority 1..9 land on separate lists, which count too."""
        from kombu import Connection, Exchange, Queue

        import tasks
        from config import Config

        r = _coordination()
        queue = Queue("mtest_queue", Exchange("mtest_queue", type="direct"), "mtest_queue")
        options = tasks.celery.conf.broker_transport_options
        with Connection(Config.CELERY_BROKER_URL, transport_options=options) as conn:
            producer = conn.Producer()
            for priority in (0, 1, 2, 3, 4, 9):
                producer.publish(
                    {"priority": priority},
                    exchange=queue.exchange,
                    routing_key="mtest_queue",
                    declare=[queue],
                    priority=priority,
                )
        try:
            assert len(r.keys("mtest_queue*")) > 1, "kombu used no separate priority list"
            assert get_queue_depth("mtest_queue") == 6
            assert get_queue_depths(["mtest_queue", "mtest_other"]) == {
                "mtest_queue": 6,
                "mtest_other": 0,
            }
        finally:
            for key in r.keys("mtest_queue*"):
                r.delete(key)

    def test_priority_layout_matches_kombu_and_the_celery_app(self):
        from kombu.transport.redis import Channel

        import tasks

        assert Channel.sep == KOMBU_PRIORITY_SEP
        overrides = tasks.celery.conf.broker_transport_options
        assert "sep" not in overrides
        assert tuple(overrides["priority_steps"]) == EVALUATION_PRIORITY_STEPS
        assert overrides["queue_order_strategy"] == "priority"

    def test_workers_take_staff_first_then_groups_in_order_fifo_within(self, redis_flush):
        """Kombu, with the app's options, hands out lower priorities first, FIFO inside one."""
        from kombu import Connection, Exchange, Queue

        import tasks
        from config import Config

        r = _coordination()
        queue = Queue("ptest_queue", Exchange("ptest_queue", type="direct"), "ptest_queue")
        sent = [("late-6+", 4), ("a-none", 1), ("staff", 0), ("3-5", 3), ("b-none", 1), ("1-2", 2)]
        options = tasks.celery.conf.broker_transport_options
        try:
            with Connection(Config.CELERY_BROKER_URL, transport_options=options) as conn:
                producer = conn.Producer()
                for body, priority in sent:
                    producer.publish(
                        body,
                        exchange=queue.exchange,
                        routing_key="ptest_queue",
                        declare=[queue],
                        priority=priority,
                    )
                consumer = conn.SimpleQueue(queue)
                received = []
                for _ in sent:
                    message = consumer.get(timeout=5)
                    received.append(message.payload)
                    message.ack()
                consumer.close()
            assert received == ["staff", "a-none", "b-none", "1-2", "3-5", "late-6+"]
        finally:
            for key in r.keys("ptest_queue*"):
                r.delete(key)

    def test_all_queues_are_read_in_one_round_trip_without_a_scan(self, monkeypatch):
        from unittest.mock import MagicMock

        broker = MagicMock()
        pipe = broker.pipeline.return_value
        pipe.execute.return_value = [2, 0, 1, 0, 0, 5, 1, 0, 0, 0]
        monkeypatch.setattr("utils.cache_utils.get_coordination_client", lambda: broker)

        assert get_queue_depths(["cpu_queue", "gpu_queue"]) == {"cpu_queue": 3, "gpu_queue": 6}
        pipe.execute.assert_called_once_with()
        keys = [call.args[0] for call in pipe.llen.call_args_list]
        assert keys == [
            "cpu_queue",
            "cpu_queue\x06\x161",
            "cpu_queue\x06\x162",
            "cpu_queue\x06\x163",
            "cpu_queue\x06\x164",
            "gpu_queue",
            "gpu_queue\x06\x161",
            "gpu_queue\x06\x162",
            "gpu_queue\x06\x163",
            "gpu_queue\x06\x164",
        ]
        broker.scan.assert_not_called()
        broker.scan_iter.assert_not_called()
        broker.keys.assert_not_called()

    def test_depths_fail_open(self, monkeypatch):
        from unittest.mock import MagicMock

        monkeypatch.setattr("utils.cache_utils.get_coordination_client", lambda: None)
        assert get_queue_depths(["cpu_queue"]) == {"cpu_queue": 0}

        broker = MagicMock()
        broker.pipeline.return_value.execute.side_effect = ConnectionError("down")
        monkeypatch.setattr("utils.cache_utils.get_coordination_client", lambda: broker)
        assert get_queue_depths(["cpu_queue", "gpu_queue"]) == {"cpu_queue": 0, "gpu_queue": 0}


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

    def test_delete_only_clears_dirty_and_cache_keys(self, redis_flush):
        co = _coordination()
        co.hset(DIRTY_LEADERBOARD_VERSIONS, "123", 2)
        set_cached("leaderboard:raw:123", {"x": 1})
        set_cached("leaderboard:pending:123", {"x": 1})

        invalidate_leaderboard_cache(123, delete_only=True)

        assert co.hget(DIRTY_LEADERBOARD_VERSIONS, "123") is None
        r = get_redis_client()
        if not r:
            pytest.skip("Redis unavailable")
        assert r.get("leaderboard:raw:123") is None
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

    def test_dirty_versions_constant(self):
        assert DIRTY_LEADERBOARD_VERSIONS == "leaderboard:dirty_versions"
