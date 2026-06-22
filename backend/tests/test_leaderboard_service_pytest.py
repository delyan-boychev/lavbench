import os
import sys
import json
import math
import pytest
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models import db, User, Challenge, Task, Submission, is_metric_lower_better
from services.leaderboard_service import build_and_cache_leaderboard, get_task_leaderboard_data


class TestBuildAndCacheLeaderboard:
    @pytest.fixture(autouse=True)
    def _setup(self, db_session, redis_flush):
        self.challenge = Challenge(
            title="Leaderboard Test",
            description="Test",
            max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2),
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
        self, user_id, task_id, public_score, private_score, status="completed", execution_time_ms=0
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
            created_at=datetime.utcnow(),
        )
        db.session.add(sub)
        db.session.commit()
        return sub

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

    def test_multiple_competitors_sorted_by_score(self):
        alice = self._create_competitor("alice")
        bob = self._create_competitor("bob")
        self._create_submission(alice.id, self.task.id, 0.9, 0.8)
        self._create_submission(bob.id, self.task.id, 0.7, 0.6)
        result = build_and_cache_leaderboard(self.challenge.id)
        assert len(result) == 2
        assert result[0]["public_score"] > result[1]["public_score"]

    def test_non_submitting_competitors_included(self):
        comp = self._create_competitor("nobody")
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

    def test_baseline_entry_included(self):
        comp = self._create_competitor("alice")
        self._create_submission(comp.id, self.task.id, 0.8, 0.7)
        baseline = self._create_submission(0, self.task.id, 0.9, 0.85)
        baseline.is_baseline = True
        baseline.user_id = 0
        db.session.commit()

        result = build_and_cache_leaderboard(self.challenge.id)
        usernames = [e["user"]["username"] for e in result]
        assert "baseline" in usernames

    def test_cache_hit_returns_cached(self):
        comp = self._create_competitor("alice")
        self._create_submission(comp.id, self.task.id, 0.8, 0.7)
        build_and_cache_leaderboard(self.challenge.id)
        result = build_and_cache_leaderboard(self.challenge.id)
        assert len(result) == 1

    def test_invalid_challenge_id_returns_none(self):
        result = build_and_cache_leaderboard(99999)
        assert result is None


class TestGetTaskLeaderboardData:
    @pytest.fixture(autouse=True)
    def _setup(self, db_session, redis_flush):
        self.challenge = Challenge(
            title="Task LB Test",
            description="Test",
            max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2),
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
        db_session.commit()

    def test_task_not_found(self):
        result = get_task_leaderboard_data(99999, "admin", None)
        assert "error" in result

    def test_competitor_access_denied_not_started(self, db_session):
        self.challenge.start_time = datetime.utcnow() + timedelta(hours=24)
        self.challenge.end_time = datetime.utcnow() + timedelta(hours=48)
        db_session.commit()
        comp = User(
            username="test_comp",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Comp-001",
            challenge_id=self.challenge.id,
        )
        db_session.add(comp)
        db_session.commit()
        result = get_task_leaderboard_data(self.task.id, "competitor", comp.id)
        assert "error" in result

    def test_admin_can_access_anytime(self):
        result = get_task_leaderboard_data(self.task.id, "admin", None)
        assert "error" not in result
        assert "leaderboard" in result

    def test_baseline_in_entries(self):
        baseline = Submission(
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            user_id=0,
            status="completed",
            is_baseline=True,
            public_score=0.95,
            private_score=0.90,
            code_cells="[]",
            created_at=datetime.utcnow(),
        )
        db.session.add(baseline)
        db.session.commit()

        result = get_task_leaderboard_data(self.task.id, "admin", None)
        entries = result["leaderboard"]
        baseline_entries = [e for e in entries if e.get("is_baseline_entry")]
        assert len(baseline_entries) == 1
