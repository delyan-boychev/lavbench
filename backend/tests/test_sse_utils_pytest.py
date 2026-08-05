"""Tests for sse_utils.py — publish helpers and Sorted Set connection limiter."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from tests.helpers.sse_test_utils import _FakeRedis, fake_redis
from utils.sse_utils import (
    CHANNEL_BACKUPS,
    CHANNEL_QUEUE,
    CHANNEL_TASK_REBUILD,
    CHANNEL_WORKER_STATS,
    CHANNEL_WORKER_STATUS,
    clear_submission_logs,
    leaderboard_channel,
    publish_leaderboard_update,
    publish_queue_update,
    publish_submission_log,
    publish_submission_log_batch,
    publish_submission_status,
    publish_submissions_update,
    sse_connection_limit,
    sse_heartbeat,
    submission_logs_channel,
    submissions_channel,
)

# ── Fixtures ──


@pytest.fixture
def fredis() -> _FakeRedis:
    return fake_redis()


# ── Channel helpers & constants ──


class TestChannelHelpers:
    def test_leaderboard_channel(self):
        assert leaderboard_channel(42) == "leaderboard_42"
        assert leaderboard_channel("abc") == "leaderboard_abc"

    def test_submissions_channel(self):
        assert submissions_channel(7, 3) == "task_7_challenge_3_submissions"

    def test_submission_logs_channel(self):
        assert submission_logs_channel(99) == "submission_99_logs"


class TestChannelConstants:
    def test_documented_constants(self):
        assert CHANNEL_TASK_REBUILD == "task_rebuild"
        assert CHANNEL_BACKUPS == "backup_status"
        assert CHANNEL_WORKER_STATS == "worker_stats_update"
        assert CHANNEL_QUEUE == "queue_updates"
        assert CHANNEL_WORKER_STATUS == "worker_status_live"


# ── publish_leaderboard_update ──


class TestPublishLeaderboardUpdate:
    @patch("utils.sse_utils.get_coordination_client")
    def test_publishes_to_correct_channel(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis
        publish_leaderboard_update(challenge_id=42)
        mock_redis.publish.assert_called_once()
        args = mock_redis.publish.call_args[0]
        assert args[0] == "leaderboard_42"

    @patch("utils.sse_utils.get_coordination_client")
    def test_publishes_with_challenge_id(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis
        publish_leaderboard_update(challenge_id=7)
        mock_redis.publish.assert_called_once()
        args = mock_redis.publish.call_args[0]
        assert args[0] == "leaderboard_7"

    @patch("utils.sse_utils.get_coordination_client")
    def test_none_challenge_id_does_nothing(self, mock_get_redis):
        publish_leaderboard_update(challenge_id=None)
        mock_get_redis.return_value.publish.assert_not_called()

    @patch("utils.sse_utils.get_coordination_client")
    def test_empty_challenge_id_does_nothing(self, mock_get_redis):
        publish_leaderboard_update(challenge_id="")
        mock_get_redis.return_value.publish.assert_not_called()

    @patch("utils.sse_utils.get_coordination_client")
    def test_redis_none_no_error(self, mock_get_redis):
        mock_get_redis.return_value = None
        publish_leaderboard_update(challenge_id=1)

    @patch("utils.sse_utils.get_coordination_client")
    def test_redis_exception_caught(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_redis.publish.side_effect = Exception("Redis down")
        mock_get_redis.return_value = mock_redis
        publish_leaderboard_update(challenge_id=1)

    def test_publishes_to_fakeredis_channel(self, fredis):
        with patch("utils.sse_utils.get_coordination_client", return_value=fredis):
            publish_leaderboard_update(challenge_id=42)
        assert fredis.published_messages == [("leaderboard_42", '{"event": "update"}')]


# ── publish_submissions_update ──


class TestPublishSubmissionsUpdate:
    @patch("utils.sse_utils.get_coordination_client")
    def test_publishes_to_correct_channel(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis
        publish_submissions_update(task_id=7, challenge_id=3)
        mock_redis.publish.assert_called_once()
        args = mock_redis.publish.call_args[0]
        assert args[0] == "task_7_challenge_3_submissions"

    @patch("utils.sse_utils.get_coordination_client")
    def test_none_task_id_does_nothing(self, mock_get_redis):
        publish_submissions_update(task_id=None, challenge_id=1)
        mock_get_redis.return_value.publish.assert_not_called()

    @patch("utils.sse_utils.get_coordination_client")
    def test_none_challenge_id_does_nothing(self, mock_get_redis):
        publish_submissions_update(task_id=1, challenge_id=None)
        mock_get_redis.return_value.publish.assert_not_called()

    @patch("utils.sse_utils.get_coordination_client")
    def test_redis_none_no_error(self, mock_get_redis):
        mock_get_redis.return_value = None
        publish_submissions_update(task_id=1, challenge_id=1)

    def test_publishes_to_fakeredis_channel(self, fredis):
        with patch("utils.sse_utils.get_coordination_client", return_value=fredis):
            publish_submissions_update(task_id=7, challenge_id=3)
        assert fredis.published_messages == [
            ("task_7_challenge_3_submissions", '{"event": "update"}')
        ]


# ── publish_submission_log ──


class TestPublishSubmissionLog:
    @patch("utils.sse_utils.get_coordination_client")
    @patch("utils.sse_utils.get_redis_client")
    def test_storage_on_cache_publish_on_coordination(self, mock_cache, mock_coord):
        cache_redis = MagicMock()
        mock_cache.return_value = cache_redis
        coord_redis = MagicMock()
        mock_coord.return_value = coord_redis
        publish_submission_log(submission_id=99, log_line="starting eval")

        cache_redis.rpush.assert_called_once()
        cache_redis.ltrim.assert_called_once()
        cache_redis.expire.assert_called_once_with("submission:99:logs", 86400)
        cache_redis.publish.assert_not_called()

        rpush_args = cache_redis.rpush.call_args[0]
        assert rpush_args[0] == "submission:99:logs"
        assert rpush_args[1] == "starting eval"

        coord_redis.publish.assert_called_once()
        publish_args = coord_redis.publish.call_args[0]
        assert publish_args[0] == "submission_99_logs"

    @patch("utils.sse_utils.get_redis_client")
    def test_none_submission_id_does_nothing(self, mock_cache):
        publish_submission_log(submission_id=None, log_line="test")
        mock_cache.return_value.rpush.assert_not_called()

    @patch("utils.sse_utils.get_coordination_client")
    @patch("utils.sse_utils.get_redis_client")
    def test_redis_none_no_error(self, mock_cache, mock_coord):
        mock_cache.return_value = None
        mock_coord.return_value = None
        publish_submission_log(submission_id=1, log_line="test")

    def test_publishes_to_fakeredis_channel(self, fredis):
        with (
            patch("utils.sse_utils.get_coordination_client", return_value=fredis),
            patch("utils.sse_utils.get_redis_client", return_value=fredis),
        ):
            publish_submission_log(submission_id=99, log_line="starting eval")
        assert fredis.published_messages == [("submission_99_logs", '{"log": "starting eval"}')]


class TestPublishSubmissionLogBatch:
    @patch("utils.sse_utils.get_coordination_client")
    @patch("utils.sse_utils.get_redis_client")
    def test_pipelines_storage_and_single_publish(self, mock_cache, mock_coord):
        pipeline = MagicMock()
        mock_cache.return_value.pipeline.return_value = pipeline
        coord_redis = MagicMock()
        mock_coord.return_value = coord_redis

        publish_submission_log_batch(submission_id=99, log_lines=["a", "b", "c"])

        assert pipeline.rpush.call_count == 3
        pipeline.ltrim.assert_called_once_with("submission:99:logs", -10000, -1)
        dispatch = mock_cache.return_value.pipeline.call_args[1]["transaction"]
        assert dispatch is False
        coord_redis.publish.assert_called_once()
        publish_args = coord_redis.publish.call_args[0]
        assert publish_args[0] == "submission_99_logs"
        assert json.loads(publish_args[1]) == {"logs": ["a", "b", "c"]}

    @patch("utils.sse_utils.get_redis_client")
    def test_no_lines_does_nothing(self, mock_cache):
        publish_submission_log_batch(submission_id=99, log_lines=[])
        mock_cache.return_value.rpush.assert_not_called()
        mock_cache.return_value.pipeline.assert_not_called()

    def test_publishes_batch_to_fakeredis_channel(self, fredis):
        with (
            patch("utils.sse_utils.get_coordination_client", return_value=fredis),
            patch("utils.sse_utils.get_redis_client", return_value=fredis),
        ):
            publish_submission_log_batch(submission_id=99, log_lines=["a", "b"])
        assert fredis.published_messages == [("submission_99_logs", '{"logs": ["a", "b"]}')]
        assert fredis.lrange("submission:99:logs", 0, -1) == ["a", "b"]


# ── clear_submission_logs ──


class TestClearSubmissionLogs:
    @patch("utils.sse_utils.get_redis_client")
    def test_deletes_correct_key(self, mock_cache):
        mock_redis = MagicMock()
        mock_cache.return_value = mock_redis
        clear_submission_logs(submission_id=55)
        mock_redis.delete.assert_called_once_with("submission:55:logs")

    @patch("utils.sse_utils.get_redis_client")
    def test_none_submission_id_does_nothing(self, mock_cache):
        clear_submission_logs(submission_id=None)
        mock_cache.return_value.delete.assert_not_called()

    @patch("utils.sse_utils.get_redis_client")
    def test_redis_none_no_error(self, mock_cache):
        mock_cache.return_value = None
        clear_submission_logs(submission_id=1)


# ── publish_submission_status ──


class TestPublishSubmissionStatus:
    @patch("utils.sse_utils.get_coordination_client")
    def test_publishes_status(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis
        publish_submission_status(submission_id=42, status="completed")
        mock_redis.publish.assert_called_once()
        args = mock_redis.publish.call_args[0]
        assert args[0] == "submission_42_logs"
        assert '"status": "completed"' in args[1]

    @patch("utils.sse_utils.get_coordination_client")
    def test_none_submission_id_does_nothing(self, mock_get_redis):
        publish_submission_status(submission_id=None, status="completed")
        mock_get_redis.return_value.publish.assert_not_called()

    @patch("utils.sse_utils.get_coordination_client")
    def test_empty_status_does_nothing(self, mock_get_redis):
        publish_submission_status(submission_id=1, status="")
        mock_get_redis.return_value.publish.assert_not_called()

    @patch("utils.sse_utils.get_coordination_client")
    def test_redis_none_no_error(self, mock_get_redis):
        mock_get_redis.return_value = None
        publish_submission_status(submission_id=1, status="completed")

    @patch("utils.sse_utils.get_coordination_client")
    def test_redis_exception_caught(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_redis.publish.side_effect = Exception("Redis down")
        mock_get_redis.return_value = mock_redis
        publish_submission_status(submission_id=1, status="completed")


# ── publish_queue_update ──


class TestPublishQueueUpdate:
    @patch("utils.sse_utils.get_coordination_client")
    def test_publishes_to_queue_channel(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis
        publish_queue_update()
        mock_redis.publish.assert_called_once()
        args = mock_redis.publish.call_args[0]
        assert args[0] == "queue_updates"
        assert args[1] == '{"event": "update"}'

    @patch("utils.sse_utils.get_coordination_client")
    def test_redis_none_no_error(self, mock_get_redis):
        mock_get_redis.return_value = None
        publish_queue_update()

    @patch("utils.sse_utils.get_coordination_client")
    def test_redis_exception_caught(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_redis.publish.side_effect = Exception("Redis down")
        mock_get_redis.return_value = mock_redis
        publish_queue_update()

    def test_publishes_to_fakeredis_channel(self, fredis):
        with patch("utils.sse_utils.get_coordination_client", return_value=fredis):
            publish_queue_update()
        assert fredis.published_messages == [("queue_updates", '{"event": "update"}')]


# ── sse_connection_limit — Sorted Set connection limiter ──


class TestSseConnectionLimit:
    """Tests use FakeRedis so no real Redis connection is needed."""

    @patch("utils.sse_utils.get_coordination_client")
    def test_allows_under_limit(self, mock_get_redis, fredis):
        mock_get_redis.return_value = fredis
        with sse_connection_limit(user_id=1) as (allowed, member):
            assert allowed is True
            assert member is not None
            assert fredis.zcard("sse:connections") == 1
            assert fredis.zcard("sse:user:1") == 1

    @patch("utils.sse_utils.get_coordination_client")
    def test_allows_without_user_id(self, mock_get_redis, fredis):
        mock_get_redis.return_value = fredis
        with sse_connection_limit() as (allowed, member):
            assert allowed is True
            assert member is not None
            assert fredis.zcard("sse:connections") == 1
            assert fredis.zcard("sse:user:1") == 0  # No user key created

    @patch("utils.sse_utils.get_coordination_client")
    def test_trim_oldest_when_over_global_limit(self, mock_get_redis, fredis):
        mock_get_redis.return_value = fredis
        max_global = 2
        ctxs = [sse_connection_limit(max_global=max_global) for _ in range(3)]
        for ctx in ctxs:
            ctx.__enter__()
        assert fredis.zcard("sse:connections") == max_global  # Oldest trimmed
        for ctx in ctxs:
            ctx.__exit__(None, None, None)

    @patch("utils.sse_utils.get_coordination_client")
    def test_trim_oldest_when_over_user_limit(self, mock_get_redis, fredis):
        mock_get_redis.return_value = fredis
        max_per_user = 2
        ctxs = [sse_connection_limit(user_id=1, max_per_user=max_per_user) for _ in range(3)]
        for ctx in ctxs:
            ctx.__enter__()
        assert fredis.zcard("sse:user:1") == max_per_user  # Oldest trimmed
        for ctx in ctxs:
            ctx.__exit__(None, None, None)

    @patch("utils.sse_utils.get_coordination_client")
    def test_cleanup_removes_member_on_exit(self, mock_get_redis, fredis):
        mock_get_redis.return_value = fredis
        with sse_connection_limit(user_id=1):
            assert fredis.zcard("sse:connections") == 1
            assert fredis.zcard("sse:user:1") == 1
        assert fredis.zcard("sse:connections") == 0
        assert fredis.zcard("sse:user:1") == 0

    @patch("utils.sse_utils.get_coordination_client")
    def test_handles_multiple_concurrent(self, mock_get_redis, fredis):
        mock_get_redis.return_value = fredis
        n = 5
        contexts = []
        for _ in range(n):
            ctx = sse_connection_limit(user_id=1)
            ctx.__enter__()
            contexts.append(ctx)
        assert fredis.zcard("sse:connections") == n
        assert fredis.zcard("sse:user:1") == n
        for ctx in contexts:
            ctx.__exit__(None, None, None)
        assert fredis.zcard("sse:connections") == 0
        assert fredis.zcard("sse:user:1") == 0

    @patch("utils.sse_utils.get_coordination_client")
    def test_redis_none_falls_open(self, mock_get_redis):
        mock_get_redis.return_value = None
        with sse_connection_limit(user_id=1) as (allowed, member):
            assert allowed is True
            assert member == ""

    @patch("utils.sse_utils.get_coordination_client")
    def test_redis_exception_falls_open(self, mock_get_redis):
        bad_redis = MagicMock()
        bad_redis.zadd.side_effect = Exception("Redis down")
        mock_get_redis.return_value = bad_redis
        with sse_connection_limit(user_id=1) as (allowed, member):
            assert allowed is True
            assert member == ""

    @patch("utils.sse_utils.get_coordination_client")
    def test_cleanup_stale_connections(self, mock_get_redis, fredis):
        mock_get_redis.return_value = fredis
        with sse_connection_limit(user_id=1):
            pass
        assert fredis.zcard("sse:connections") == 0  # Cleaned on exit


# ── sse_heartbeat — keeps live SSE members from being pruned as stale ──


class TestSseHeartbeat:
    @patch("utils.sse_utils.get_coordination_client")
    def test_refreshes_global_and_user_sets(self, mock_get_redis, fredis):
        mock_get_redis.return_value = fredis
        with sse_connection_limit(user_id=7) as (allowed, member):
            assert allowed is True
            old_global = fredis.zscore("sse:connections", member)
            old_user = fredis.zscore("sse:user:7", member)

            import time

            time.sleep(0.01)
            assert sse_heartbeat(member, user_id=7) is True

            assert fredis.zscore("sse:connections", member) > old_global
            assert fredis.zscore("sse:user:7", member) > old_user

    @patch("utils.sse_utils.get_coordination_client")
    def test_returns_false_for_evicted_member(self, mock_get_redis, fredis):
        mock_get_redis.return_value = fredis
        with sse_connection_limit(user_id=1) as (allowed, member):
            assert allowed is True
            fredis.zrem("sse:connections", member)
            assert sse_heartbeat(member, user_id=1) is False

    @patch("utils.sse_utils.get_coordination_client")
    def test_empty_member_is_ok(self, mock_get_redis):
        mock_get_redis.return_value = MagicMock()
        assert sse_heartbeat("") is True

    @patch("utils.sse_utils.get_coordination_client")
    def test_redis_none_is_ok(self, mock_get_redis):
        mock_get_redis.return_value = None
        assert sse_heartbeat("member-1") is True

    @patch("utils.sse_utils.get_coordination_client")
    def test_redis_exception_is_ok(self, mock_get_redis):
        bad_redis = MagicMock()
        bad_redis.zscore.side_effect = Exception("Redis down")
        mock_get_redis.return_value = bad_redis
        assert sse_heartbeat("member-1") is True
