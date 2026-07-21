"""Tests for sse_utils.py — publish helpers and Sorted Set connection limiter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sse_utils import (
    clear_submission_logs,
    publish_leaderboard_update,
    publish_submission_log,
    publish_submission_status,
    publish_submissions_update,
    sse_connection_limit,
)
from tests.helpers.sse_test_utils import _FakeRedis, fake_redis

# ═══════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def fredis() -> _FakeRedis:
    return fake_redis()


# ═══════════════════════════════════════════════════════════════════════
# publish_leaderboard_update
# ═══════════════════════════════════════════════════════════════════════


class TestPublishLeaderboardUpdate:
    @patch("sse_utils.get_redis_client")
    def test_publishes_to_correct_channel(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis
        publish_leaderboard_update(challenge_id=42)
        mock_redis.publish.assert_called_once()
        args = mock_redis.publish.call_args[0]
        assert args[0] == "challenge_42_leaderboard"

    @patch("sse_utils.get_redis_client")
    def test_publishes_with_challenge_id(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis
        publish_leaderboard_update(challenge_id=7)
        mock_redis.publish.assert_called_once()
        args = mock_redis.publish.call_args[0]
        assert args[0] == "challenge_7_leaderboard"

    @patch("sse_utils.get_redis_client")
    def test_none_challenge_id_does_nothing(self, mock_get_redis):
        publish_leaderboard_update(challenge_id=None)
        mock_get_redis.return_value.publish.assert_not_called()

    @patch("sse_utils.get_redis_client")
    def test_empty_challenge_id_does_nothing(self, mock_get_redis):
        publish_leaderboard_update(challenge_id="")
        mock_get_redis.return_value.publish.assert_not_called()

    @patch("sse_utils.get_redis_client")
    def test_redis_none_no_error(self, mock_get_redis):
        mock_get_redis.return_value = None
        publish_leaderboard_update(challenge_id=1)

    @patch("sse_utils.get_redis_client")
    def test_redis_exception_caught(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_redis.publish.side_effect = Exception("Redis down")
        mock_get_redis.return_value = mock_redis
        publish_leaderboard_update(challenge_id=1)


# ═══════════════════════════════════════════════════════════════════════
# publish_submissions_update
# ═══════════════════════════════════════════════════════════════════════


class TestPublishSubmissionsUpdate:
    @patch("sse_utils.get_redis_client")
    def test_publishes_to_correct_channel(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis
        publish_submissions_update(task_id=7, challenge_id=3)
        mock_redis.publish.assert_called_once()
        args = mock_redis.publish.call_args[0]
        assert args[0] == "challenge_3_submissions"

    @patch("sse_utils.get_redis_client")
    def test_none_task_id_does_nothing(self, mock_get_redis):
        publish_submissions_update(task_id=None, challenge_id=1)
        mock_get_redis.return_value.publish.assert_not_called()

    @patch("sse_utils.get_redis_client")
    def test_none_challenge_id_does_nothing(self, mock_get_redis):
        publish_submissions_update(task_id=1, challenge_id=None)
        mock_get_redis.return_value.publish.assert_not_called()

    @patch("sse_utils.get_redis_client")
    def test_redis_none_no_error(self, mock_get_redis):
        mock_get_redis.return_value = None
        publish_submissions_update(task_id=1, challenge_id=1)


# ═══════════════════════════════════════════════════════════════════════
# publish_submission_log
# ═══════════════════════════════════════════════════════════════════════


class TestPublishSubmissionLog:
    @patch("sse_utils.get_redis_client")
    def test_rpush_ltrim_expire_publish(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis
        publish_submission_log(submission_id=99, log_line="starting eval")

        mock_redis.rpush.assert_called_once()
        mock_redis.ltrim.assert_called_once()
        mock_redis.expire.assert_called_once_with("submission:99:logs", 86400)
        mock_redis.publish.assert_called_once()

        rpush_args = mock_redis.rpush.call_args[0]
        assert rpush_args[0] == "submission:99:logs"
        assert rpush_args[1] == "starting eval"

        publish_args = mock_redis.publish.call_args[0]
        assert publish_args[0] == "submission_99_logs"

    @patch("sse_utils.get_redis_client")
    def test_none_submission_id_does_nothing(self, mock_get_redis):
        publish_submission_log(submission_id=None, log_line="test")
        mock_get_redis.return_value.rpush.assert_not_called()

    @patch("sse_utils.get_redis_client")
    def test_redis_none_no_error(self, mock_get_redis):
        mock_get_redis.return_value = None
        publish_submission_log(submission_id=1, log_line="test")


# ═══════════════════════════════════════════════════════════════════════
# clear_submission_logs
# ═══════════════════════════════════════════════════════════════════════


class TestClearSubmissionLogs:
    @patch("sse_utils.get_redis_client")
    def test_deletes_correct_key(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis
        clear_submission_logs(submission_id=55)
        mock_redis.delete.assert_called_once_with("submission:55:logs")

    @patch("sse_utils.get_redis_client")
    def test_none_submission_id_does_nothing(self, mock_get_redis):
        clear_submission_logs(submission_id=None)
        mock_get_redis.return_value.delete.assert_not_called()

    @patch("sse_utils.get_redis_client")
    def test_redis_none_no_error(self, mock_get_redis):
        mock_get_redis.return_value = None
        clear_submission_logs(submission_id=1)


# ═══════════════════════════════════════════════════════════════════════
# publish_submission_status
# ═══════════════════════════════════════════════════════════════════════


class TestPublishSubmissionStatus:
    @patch("sse_utils.get_redis_client")
    def test_publishes_status(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis
        publish_submission_status(submission_id=42, status="completed")
        mock_redis.publish.assert_called_once()
        args = mock_redis.publish.call_args[0]
        assert args[0] == "submission_42_logs"
        assert '"status": "completed"' in args[1]

    @patch("sse_utils.get_redis_client")
    def test_none_submission_id_does_nothing(self, mock_get_redis):
        publish_submission_status(submission_id=None, status="completed")
        mock_get_redis.return_value.publish.assert_not_called()

    @patch("sse_utils.get_redis_client")
    def test_empty_status_does_nothing(self, mock_get_redis):
        publish_submission_status(submission_id=1, status="")
        mock_get_redis.return_value.publish.assert_not_called()

    @patch("sse_utils.get_redis_client")
    def test_redis_none_no_error(self, mock_get_redis):
        mock_get_redis.return_value = None
        publish_submission_status(submission_id=1, status="completed")

    @patch("sse_utils.get_redis_client")
    def test_redis_exception_caught(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_redis.publish.side_effect = Exception("Redis down")
        mock_get_redis.return_value = mock_redis
        publish_submission_status(submission_id=1, status="completed")


# ═══════════════════════════════════════════════════════════════════════
# sse_connection_limit — Sorted Set connection limiter
# ═══════════════════════════════════════════════════════════════════════


class TestSseConnectionLimit:
    """Tests use FakeRedis so no real Redis connection is needed."""

    @patch("sse_utils.get_redis_client")
    def test_allows_under_limit(self, mock_get_redis, fredis):
        mock_get_redis.return_value = fredis
        with sse_connection_limit(user_id=1) as (allowed, member):
            assert allowed is True
            assert member is not None
            assert fredis.zcard("sse:connections") == 1
            assert fredis.zcard("sse:user:1") == 1

    @patch("sse_utils.get_redis_client")
    def test_allows_without_user_id(self, mock_get_redis, fredis):
        mock_get_redis.return_value = fredis
        with sse_connection_limit() as (allowed, member):
            assert allowed is True
            assert member is not None
            assert fredis.zcard("sse:connections") == 1
            assert fredis.zcard("sse:user:1") == 0  # no user key created

    @patch("sse_utils.get_redis_client")
    def test_trim_oldest_when_over_global_limit(self, mock_get_redis, fredis):
        mock_get_redis.return_value = fredis
        max_global = 2
        ctxs = [sse_connection_limit(max_global=max_global) for _ in range(3)]
        for ctx in ctxs:
            ctx.__enter__()
        assert fredis.zcard("sse:connections") == max_global  # oldest trimmed
        for ctx in ctxs:
            ctx.__exit__(None, None, None)

    @patch("sse_utils.get_redis_client")
    def test_trim_oldest_when_over_user_limit(self, mock_get_redis, fredis):
        mock_get_redis.return_value = fredis
        max_per_user = 2
        ctxs = [sse_connection_limit(user_id=1, max_per_user=max_per_user) for _ in range(3)]
        for ctx in ctxs:
            ctx.__enter__()
        assert fredis.zcard("sse:user:1") == max_per_user  # oldest trimmed
        for ctx in ctxs:
            ctx.__exit__(None, None, None)

    @patch("sse_utils.get_redis_client")
    def test_cleanup_removes_member_on_exit(self, mock_get_redis, fredis):
        mock_get_redis.return_value = fredis
        with sse_connection_limit(user_id=1):
            assert fredis.zcard("sse:connections") == 1
            assert fredis.zcard("sse:user:1") == 1
        assert fredis.zcard("sse:connections") == 0
        assert fredis.zcard("sse:user:1") == 0

    @patch("sse_utils.get_redis_client")
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

    @patch("sse_utils.get_redis_client")
    def test_redis_none_falls_open(self, mock_get_redis):
        mock_get_redis.return_value = None
        with sse_connection_limit(user_id=1) as (allowed, member):
            assert allowed is True
            assert member == ""

    @patch("sse_utils.get_redis_client")
    def test_redis_exception_falls_open(self, mock_get_redis):
        bad_redis = MagicMock()
        bad_redis.zadd.side_effect = Exception("Redis down")
        mock_get_redis.return_value = bad_redis
        with sse_connection_limit(user_id=1) as (allowed, member):
            assert allowed is True
            assert member == ""

    @patch("sse_utils.get_redis_client")
    def test_cleanup_stale_connections(self, mock_get_redis, fredis):
        mock_get_redis.return_value = fredis
        with sse_connection_limit(user_id=1):
            pass
        assert fredis.zcard("sse:connections") == 0  # cleaned on exit
