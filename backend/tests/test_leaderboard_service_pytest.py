"""Tests for the leaderboard service."""

import json
import os
import sys
from datetime import timedelta

import pytest

from utils.dates import utcnow

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import Config
from models import Challenge, Stage, Submission, Task, User, db
from services.leaderboard_service import (
    build_and_cache_leaderboard,
)


class TestBuildAndCacheLeaderboard:
    @pytest.fixture(autouse=True)
    def _setup(self, db_session, redis_flush):
        self.challenge = Challenge(
            title="Leaderboard Test",
            description="Test",
            max_eval_requests=5,
            start_time=utcnow() - timedelta(hours=2),
            end_time=utcnow() + timedelta(hours=2),
            is_frozen=False,
            scores_finalized=False,
        )
        db_session.add(self.challenge)
        db_session.commit()

        self.task = Task(
            title="Task 1",
            challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
            metrics_config={"accuracy": {"weight": 1.0, "higher_is_better": True}},
        )
        db_session.add(self.task)

        self.task2 = Task(
            title="Task 2",
            challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
            metrics_config={"mse": {"weight": 1.0, "higher_is_better": False}},
        )
        db_session.add(self.task2)
        db_session.commit()

    def _create_competitor(self, username, name=None, surname=None):
        comp = User(
            username=username,
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id=f"User-{username}",
            challenge_id=self.challenge.id,
        )
        comp.set_demographics(name or username, surname or "Test", "12", "School", "City")
        db.session.add(comp)
        db.session.commit()
        return comp

    def _create_submission(
        self,
        user_id,
        task_id,
        public_score,
        private_score,
        status="completed",
        execution_time_ms=0,
    ):
        sub = Submission(
            challenge_id=self.challenge.id,
            task_id=task_id,
            user_id=user_id,
            status=status,
            public_score=public_score,
            private_score=private_score,
            execution_time_ms=execution_time_ms,
            code_cells="[]",
            created_at=utcnow(),
        )
        db.session.add(sub)
        db.session.commit()
        return sub

    def test_equal_scores_keep_the_earlier_submission(self):
        from datetime import timedelta

        from services.contest_rules import counted_run

        comp = self._create_competitor("tie")
        later = self._create_submission(comp.id, self.task.id, 0.9, 0.9)
        earlier = self._create_submission(comp.id, self.task.id, 0.9, 0.9)
        earlier.created_at = later.created_at - timedelta(minutes=5)
        db.session.commit()
        result = build_and_cache_leaderboard(self.challenge.id)
        chosen = result[0]["task_scores"][str(self.task.id)]["submission_id"]
        assert str(chosen) == str(earlier.id)
        best = counted_run(self.task, [later, earlier], self.challenge)
        assert best is not None and best.id == earlier.id

    def test_empty_challenge_returns_empty(self):
        result = build_and_cache_leaderboard(self.challenge.id)
        assert isinstance(result, list)

    def test_single_competitor_best_submission(self):
        comp = self._create_competitor("alice")
        self._create_submission(comp.id, self.task.id, 0.8, 0.7, execution_time_ms=100)
        self._create_submission(comp.id, self.task.id, 0.9, 0.8, execution_time_ms=200)
        result = build_and_cache_leaderboard(self.challenge.id)
        assert len(result) == 1
        entry = result[0]
        assert entry["user"]["username"] == "alice"
        assert entry["has_submitted"] is True
        ts = entry["task_scores"][str(self.task.id)]
        assert ts["public_score"] == 0.9

    def test_active_leaderboard_selects_public_best_without_private_leak(self):
        comp = self._create_competitor("alice")
        public_best = self._create_submission(comp.id, self.task.id, 0.9, 0.1)
        self._create_submission(comp.id, self.task.id, 0.4, 0.99)

        result = build_and_cache_leaderboard(self.challenge.id)

        task_score = result[0]["task_scores"][str(self.task.id)]
        assert task_score["submission_id"] == public_best.id
        assert task_score["public_score"] == 0.9

    def test_finalized_hidden_leaderboard_still_selects_public_best(self):
        self.challenge.scores_finalized = True
        self.challenge.reveal_results = False
        db.session.commit()
        comp = self._create_competitor("alice")
        public_best = self._create_submission(comp.id, self.task.id, 0.9, 0.1)
        self._create_submission(comp.id, self.task.id, 0.4, 0.99)

        result = build_and_cache_leaderboard(self.challenge.id)

        task_score = result[0]["task_scores"][str(self.task.id)]
        assert task_score["submission_id"] == public_best.id
        assert task_score["public_score"] == 0.9

    def test_finalized_revealed_leaderboard_keeps_the_public_best(self):
        """Private scores never pick the run; they are shown for the run that counts."""
        self.challenge.scores_finalized = True
        self.challenge.reveal_results = True
        db.session.commit()
        comp = self._create_competitor("alice")
        public_best = self._create_submission(comp.id, self.task.id, 0.9, 0.1)
        self._create_submission(comp.id, self.task.id, 0.4, 0.99)

        result = build_and_cache_leaderboard(self.challenge.id)

        task_score = result[0]["task_scores"][str(self.task.id)]
        assert task_score["submission_id"] == public_best.id
        assert task_score["private_score"] == 0.1

    def test_revealed_stage_keeps_the_public_best_before_challenge_finalization(self):
        stage = Stage(
            challenge_id=self.challenge.id,
            stage_number=1,
            title="Revealed Stage",
            start_time=utcnow() - timedelta(hours=2),
            end_time=utcnow() - timedelta(hours=1),
            is_finalized=True,
            reveal_results=True,
        )
        db.session.add(stage)
        db.session.flush()
        self.task.stage_id = stage.id
        db.session.commit()
        comp = self._create_competitor("alice")
        public_best = self._create_submission(comp.id, self.task.id, 0.9, 0.1)
        private_best = self._create_submission(comp.id, self.task.id, 0.4, 0.99)
        public_best.created_at = stage.end_time - timedelta(minutes=1)
        private_best.created_at = stage.end_time - timedelta(minutes=1)
        db.session.commit()

        result = build_and_cache_leaderboard(self.challenge.id)

        task_score = result[0]["task_scores"][str(self.task.id)]
        assert task_score["submission_id"] == public_best.id
        assert task_score["private_score"] == 0.1

    def test_multiple_competitors_sorted_by_score(self):
        alice = self._create_competitor("alice")
        bob = self._create_competitor("bob")
        self._create_submission(alice.id, self.task.id, 0.9, 0.8)
        self._create_submission(bob.id, self.task.id, 0.7, 0.6)
        result = build_and_cache_leaderboard(self.challenge.id)
        assert len(result) == 2
        assert result[0]["public_score"] > result[1]["public_score"]

    def test_non_submitting_competitors_included(self):
        self._create_competitor("nobody")
        result = build_and_cache_leaderboard(self.challenge.id)
        assert len(result) == 1
        assert result[0]["has_submitted"] is False

    def test_tie_broken_by_execution_time(self):
        alice = self._create_competitor("alice")
        bob = self._create_competitor("bob")
        self._create_submission(alice.id, self.task.id, 0.9, 0.8, execution_time_ms=100)
        self._create_submission(bob.id, self.task.id, 0.9, 0.8, execution_time_ms=200)
        result = build_and_cache_leaderboard(self.challenge.id)
        assert len(result) == 2
        assert result[0]["user"]["username"] == "alice"

    def test_finalized_leaderboard_uses_total_points(self):
        self.challenge.scores_finalized = True
        db.session.commit()

        alice = self._create_competitor("alice")
        bob = self._create_competitor("bob")
        self._create_submission(alice.id, self.task.id, 0.9, 0.8)
        self._create_submission(bob.id, self.task.id, 0.7, 0.6)

        alice.manual_points = json.dumps({str(self.task.id): 10})
        bob.manual_points = json.dumps({str(self.task.id): 5})
        db.session.commit()

        result = build_and_cache_leaderboard(self.challenge.id)
        assert result[0]["user"]["username"] == "alice"
        assert result[0]["total_points"] > result[1]["total_points"]

    def test_baseline_included_in_leaderboard(self):
        comp = self._create_competitor("alice")
        self._create_submission(comp.id, self.task.id, 0.8, 0.7)
        baseline_user = User(
            username="baseline_bot",
            password_hash="pbkdf2:sha256:...",
            role="admin",
        )
        db.session.add(baseline_user)
        db.session.commit()
        baseline = self._create_submission(baseline_user.id, self.task.id, 0.9, 0.85)
        baseline.is_baseline = True
        db.session.commit()

        result = build_and_cache_leaderboard(self.challenge.id)
        baseline_entries = [e for e in result if e.get("is_baseline_entry")]
        assert len(baseline_entries) == 1
        assert baseline_entries[0]["is_baseline_entry"] is True
        assert len(result) == 2

    def test_cache_hit_returns_cached(self):
        comp = self._create_competitor("alice")
        self._create_submission(comp.id, self.task.id, 0.8, 0.7)
        build_and_cache_leaderboard(self.challenge.id)
        result = build_and_cache_leaderboard(self.challenge.id)
        assert len(result) == 1

    def test_invalid_challenge_id_returns_none(self):
        result = build_and_cache_leaderboard(99999)
        assert result is None

    def test_submission_inside_grace_period_ranks_and_later_one_is_excluded(self):
        """Eligibility must span the grace period the UI advertises, and stop there.

        Competitors see the strict ``end_time`` as the deadline, but the submit form
        and ``validate_submission_allowed`` both stay open for
        ``DEADLINE_GRACE_PERIOD_SECONDS`` afterwards. A submission accepted in that
        window must still rank; one made after it must not.
        """
        self.challenge.start_time = utcnow() - timedelta(hours=4)
        self.challenge.end_time = utcnow() - timedelta(minutes=10)
        db.session.commit()
        comp = self._create_competitor("alice")
        grace = timedelta(seconds=Config.DEADLINE_GRACE_PERIOD_SECONDS)

        in_grace = self._create_submission(comp.id, self.task.id, 0.5, 0.5)
        too_late = self._create_submission(comp.id, self.task.id, 0.99, 0.99)
        in_grace.created_at = self.challenge.end_time + (grace / 2)
        too_late.created_at = self.challenge.end_time + grace + timedelta(seconds=1)
        db.session.commit()

        result = build_and_cache_leaderboard(self.challenge.id)

        task_score = result[0]["task_scores"][str(self.task.id)]
        assert task_score["submission_id"] == in_grace.id
        assert task_score["public_score"] == 0.5


class TestLeaderboardStampedeProtection:
    """Readers never recompute while a cached value exists; one TTL for the cache."""

    @staticmethod
    def _lock(got):
        from contextlib import contextmanager

        @contextmanager
        def fake_lock(_key, ttl=120):
            yield got

        return fake_lock

    def test_cached_value_is_served_without_computing(self, mocker):
        import services.leaderboard_service as lbs

        mocker.patch.object(lbs, "get_cached", return_value=[{"rank": 1}])
        compute = mocker.patch.object(lbs, "_compute_leaderboard_entries")
        assert lbs.build_and_cache_leaderboard("c1") == [{"rank": 1}]
        compute.assert_not_called()

    def test_lock_miss_serves_the_value_the_lock_holder_builds(self, mocker):
        import services.leaderboard_service as lbs

        mocker.patch.object(lbs, "get_cached", side_effect=[None, None, [{"rank": 1}]])
        mocker.patch.object(lbs, "cache_lock", self._lock(False))
        mocker.patch.object(lbs.time, "sleep")
        compute = mocker.patch.object(lbs, "_compute_leaderboard_entries")
        assert lbs.build_and_cache_leaderboard("c1") == [{"rank": 1}]
        compute.assert_not_called()

    def test_lock_miss_computes_only_when_no_cached_value_exists(self, mocker):
        import services.leaderboard_service as lbs

        mocker.patch.object(lbs, "get_cached", return_value=None)
        mocker.patch.object(lbs, "cache_lock", self._lock(False))
        mocker.patch.object(lbs.time, "sleep")
        compute = mocker.patch.object(
            lbs, "_compute_leaderboard_entries", return_value=[{"rank": 2}]
        )
        set_cached = mocker.patch.object(lbs, "set_cached")
        assert lbs.build_and_cache_leaderboard("c1") == [{"rank": 2}]
        compute.assert_called_once_with("c1")
        set_cached.assert_called_once_with(
            "leaderboard:raw:c1", [{"rank": 2}], timeout=lbs.LEADERBOARD_CACHE_SECONDS
        )

    def test_rebuild_skips_when_another_rebuild_holds_the_lock(self, mocker):
        import services.leaderboard_service as lbs

        mocker.patch.object(lbs, "cache_lock", self._lock(False))
        compute = mocker.patch.object(lbs, "_compute_leaderboard_entries")
        assert lbs.rebuild_leaderboard("c1") is False
        compute.assert_not_called()

    def test_rebuild_overwrites_the_cache_with_the_single_ttl(self, mocker):
        import services.leaderboard_service as lbs

        mocker.patch.object(lbs, "cache_lock", self._lock(True))
        mocker.patch.object(lbs, "_compute_leaderboard_entries", return_value=[{"rank": 3}])
        set_cached = mocker.patch.object(lbs, "set_cached")
        assert lbs.rebuild_leaderboard("c1") is True
        set_cached.assert_called_once_with(
            "leaderboard:raw:c1", [{"rank": 3}], timeout=lbs.LEADERBOARD_CACHE_SECONDS
        )

    def test_frozen_variant_is_gone(self):
        import inspect

        import services.leaderboard_service as lbs

        assert "is_frozen_view" not in inspect.signature(lbs.build_and_cache_leaderboard).parameters
