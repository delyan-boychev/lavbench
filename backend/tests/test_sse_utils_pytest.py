from unittest.mock import MagicMock, patch

from sse_utils import (
    clear_submission_logs,
    publish_leaderboard_update,
    publish_submission_log,
    publish_submissions_update,
)


class TestPublishLeaderboardUpdate:
    @patch("sse_utils.get_redis_client")
    def test_publishes_to_correct_channel(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis
        publish_leaderboard_update(task_id=42)
        mock_redis.publish.assert_called_once()
        args = mock_redis.publish.call_args[0]
        assert args[0] == "task_42_leaderboard"

    @patch("sse_utils.get_redis_client")
    def test_none_task_id_does_nothing(self, mock_get_redis):
        publish_leaderboard_update(task_id=None)
        mock_get_redis.return_value.publish.assert_not_called()

    @patch("sse_utils.get_redis_client")
    def test_empty_task_id_does_nothing(self, mock_get_redis):
        publish_leaderboard_update(task_id="")
        mock_get_redis.return_value.publish.assert_not_called()

    @patch("sse_utils.get_redis_client")
    def test_redis_none_no_error(self, mock_get_redis):
        mock_get_redis.return_value = None
        publish_leaderboard_update(task_id=1)

    @patch("sse_utils.get_redis_client")
    def test_redis_exception_caught(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_redis.publish.side_effect = Exception("Redis down")
        mock_get_redis.return_value = mock_redis
        publish_leaderboard_update(task_id=1)


class TestPublishSubmissionsUpdate:
    @patch("sse_utils.get_redis_client")
    def test_publishes_to_correct_channel(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis
        publish_submissions_update(task_id=7, user_id=3)
        mock_redis.publish.assert_called_once()
        args = mock_redis.publish.call_args[0]
        assert args[0] == "task_7_user_3_submissions"

    @patch("sse_utils.get_redis_client")
    def test_none_task_id_does_nothing(self, mock_get_redis):
        publish_submissions_update(task_id=None, user_id=1)
        mock_get_redis.return_value.publish.assert_not_called()

    @patch("sse_utils.get_redis_client")
    def test_none_user_id_does_nothing(self, mock_get_redis):
        publish_submissions_update(task_id=1, user_id=None)
        mock_get_redis.return_value.publish.assert_not_called()

    @patch("sse_utils.get_redis_client")
    def test_redis_none_no_error(self, mock_get_redis):
        mock_get_redis.return_value = None
        publish_submissions_update(task_id=1, user_id=1)


class TestPublishSubmissionLog:
    @patch("sse_utils.get_redis_client")
    def test_rpush_ltrim_expire_publish(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis
        publish_submission_log(submission_id=99, log_line="starting eval")

        mock_redis.rpush.assert_called_once()
        mock_redis.ltrim.assert_called_once()
        mock_redis.expire.assert_called_once_with("submission:99:logs", 3600)
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
