"""Tests for race-safe periodic leaderboard rebuilding."""

from unittest.mock import MagicMock, patch

import tasks
from models import Challenge, db
from tasks import recalculate_dirty_leaderboards
from utils.dates import utcnow


def _challenge() -> Challenge:
    challenge = Challenge(
        title="Dirty leaderboard",
        description="Test",
        max_eval_requests=5,
        start_time=utcnow(),
        end_time=utcnow(),
        is_frozen=False,
    )
    db.session.add(challenge)
    db.session.commit()
    return challenge


def test_success_clears_only_rebuilt_version(app, db_session):
    tasks.app = app
    challenge = _challenge()
    redis_client = MagicMock()

    with (
        patch("utils.cache_utils.get_coordination_client", return_value=redis_client),
        patch(
            "utils.cache_utils.get_dirty_leaderboard_versions",
            return_value={str(challenge.id): 7},
        ),
        patch("utils.cache_utils.clear_dirty_leaderboard_version") as clear_version,
        patch("services.leaderboard_service.rebuild_leaderboard", return_value=True) as rebuild,
        patch("utils.sse_utils.publish_leaderboard_update") as publish,
    ):
        result = recalculate_dirty_leaderboards()

    assert result == {"recalculated": 1}
    rebuild.assert_called_once_with(str(challenge.id))
    publish.assert_called_once_with(str(challenge.id))
    clear_version.assert_called_once_with(redis_client, str(challenge.id), 7)


def test_rebuild_failure_preserves_dirty_version(app, db_session):
    tasks.app = app
    challenge = _challenge()
    redis_client = MagicMock()

    with (
        patch("utils.cache_utils.get_coordination_client", return_value=redis_client),
        patch(
            "utils.cache_utils.get_dirty_leaderboard_versions",
            return_value={str(challenge.id): 4},
        ),
        patch("utils.cache_utils.clear_dirty_leaderboard_version") as clear_version,
        patch(
            "services.leaderboard_service.rebuild_leaderboard",
            side_effect=RuntimeError("temporary failure"),
        ),
    ):
        result = recalculate_dirty_leaderboards()

    assert result == {"recalculated": 0}
    clear_version.assert_not_called()


def test_lock_miss_keeps_dirty_version_and_does_not_publish(app, db_session):
    tasks.app = app
    challenge = _challenge()
    redis_client = MagicMock()

    with (
        patch("utils.cache_utils.get_coordination_client", return_value=redis_client),
        patch(
            "utils.cache_utils.get_dirty_leaderboard_versions",
            return_value={str(challenge.id): 3},
        ),
        patch("utils.cache_utils.clear_dirty_leaderboard_version") as clear_version,
        patch("services.leaderboard_service.rebuild_leaderboard", return_value=False),
        patch("utils.sse_utils.publish_leaderboard_update") as publish,
    ):
        result = recalculate_dirty_leaderboards()

    assert result == {"recalculated": 0}
    clear_version.assert_not_called()
    publish.assert_not_called()


def test_deleted_challenge_clears_terminal_dirty_version(app, db_session):
    tasks.app = app
    redis_client = MagicMock()

    with (
        patch("utils.cache_utils.get_coordination_client", return_value=redis_client),
        patch(
            "utils.cache_utils.get_dirty_leaderboard_versions",
            return_value={"00000000-0000-0000-0000-000000000000": 2},
        ),
        patch("utils.cache_utils.clear_dirty_leaderboard_version") as clear_version,
        patch("services.leaderboard_service.rebuild_leaderboard", return_value=True) as rebuild,
    ):
        result = recalculate_dirty_leaderboards()

    assert result == {"recalculated": 0}
    rebuild.assert_not_called()
    clear_version.assert_called_once_with(
        redis_client,
        "00000000-0000-0000-0000-000000000000",
        2,
    )
