"""Tests for the watchdog task."""

import json
from datetime import timedelta
from unittest.mock import patch

import pytest

from models import Challenge, Submission, Task, User, db
from tasks import watchdog_stuck_submissions
from utils.dates import utcnow


class TestWatchdogStuckSubmissions:
    @pytest.fixture(autouse=True)
    def setup(self, app, db_session, app_ctx, redis_flush):
        import tasks

        tasks.app = app
        self.seed_basic_data()

    def seed_basic_data(self):
        self.challenge = Challenge(
            title="Watchdog Test",
            description="Test",
            max_eval_requests=5,
            start_time=utcnow() - timedelta(hours=2),
            end_time=utcnow() + timedelta(hours=2),
            is_frozen=False,
        )
        db.session.add(self.challenge)
        db.session.commit()

        self.task = Task(
            title="Task 1",
            challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
            metrics_config={"accuracy": {"weight": 1.0, "higher_is_better": True}},
        )
        db.session.add(self.task)

        self.competitor = User(
            username="test_comp",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Comp-001",
            challenge_id=self.challenge.id,
        )
        self.competitor.set_demographics("Jane", "Doe", "12", "School", "City")
        db.session.add(self.competitor)
        db.session.commit()

    def _create_submission(self, status, executed_at=None, created_at=None, time_limit=None):
        kwargs = {
            "challenge_id": self.challenge.id,
            "task_id": self.task.id,
            "user_id": self.competitor.id,
            "status": status,
            "code_cells": "[]",
        }
        if executed_at is not None:
            kwargs["executed_at"] = executed_at
        if created_at is not None:
            kwargs["created_at"] = created_at
        if time_limit is not None:
            self.task.time_limit_sec = time_limit
        sub = Submission(**kwargs)
        sub.celery_task_id = f"attempt-{sub.id or 'pending'}-{status}"
        db.session.add(sub)
        db.session.commit()
        return sub

    def test_no_stuck_submissions(self):
        sub = self._create_submission("completed")
        sub.executed_at = utcnow()
        db.session.commit()

        result = watchdog_stuck_submissions()
        assert result.get("timed_out", 0) == 0

    def test_times_out_stuck_queued_submission(self):
        self._create_submission("queued", created_at=utcnow() - timedelta(hours=1, minutes=5))
        with patch("utils.cache_utils.invalidate_leaderboard_cache") as invalidate:
            result = watchdog_stuck_submissions()
        assert result.get("timed_out", 0) >= 1
        invalidate.assert_called_once_with(self.challenge.id)
        sub = Submission.query.first()
        assert sub.status == "failed"
        # Never picked up is the platform's fault, so it costs no quota
        assert sub.detailed_status == "failed_infra"
        assert "WATCHDOG" in sub.logs

    def test_does_not_time_out_recent_queued_submission(self):
        self._create_submission("queued", created_at=utcnow())
        result = watchdog_stuck_submissions()
        assert result.get("timed_out", 0) == 0

    def test_times_out_running_submission_exceeded_time_limit(self):
        self._create_submission("running", executed_at=utcnow() - timedelta(seconds=1000))
        result = watchdog_stuck_submissions()
        assert result.get("timed_out", 0) >= 1
        # The runner enforces the limit itself, so this means the worker was lost
        sub = Submission.query.first()
        assert sub.detailed_status == "failed_infra"
        assert "worker lost" in sub.logs

    def test_does_not_time_out_running_within_limit(self):
        self._create_submission("running", executed_at=utcnow() - timedelta(seconds=10))
        result = watchdog_stuck_submissions()
        assert result.get("timed_out", 0) == 0

    def test_uses_dispatch_time_limit_snapshot_not_current(self):
        # Task limit shrank from 900s (dispatch time) to 60s after the run
        # started. The watchdog must keep the dispatch-time budget: 1.5 * 900
        # > 1000s elapsed, so the run must NOT be killed
        self.task.time_limit_sec = 60
        db.session.commit()
        sub = self._create_submission("running", executed_at=utcnow() - timedelta(seconds=1000))
        sub.time_limit_snapshot = 900
        db.session.commit()
        result = watchdog_stuck_submissions()
        assert result.get("timed_out", 0) == 0

    def test_respects_snapshot_when_shrunk_below_runtime(self):
        sub = self._create_submission("running", executed_at=utcnow() - timedelta(seconds=1000))
        sub.time_limit_snapshot = 60
        db.session.commit()
        result = watchdog_stuck_submissions()
        assert result.get("timed_out", 0) >= 1

    def _scoring_task(self):
        from config import Config

        self.task.custom_eval_code = "def evaluate(a, b, c):\n    return {}\n"
        self.task.metrics_config = {"custom_score": {"weight": 1.0}}
        db.session.commit()
        # Run allowance 1.5 * 300 s, plus 120 s base and one evaluator run
        return 450 + 120 + Config.CUSTOM_EVALUATOR_TIME_LIMIT_SECONDS

    def test_spares_a_notebook_submission_that_is_still_scoring(self):
        allowance = self._scoring_task()
        sub = self._create_submission(
            "running", executed_at=utcnow() - timedelta(seconds=allowance - 30)
        )
        sub.time_limit_snapshot = 300
        db.session.commit()
        assert watchdog_stuck_submissions().get("timed_out", 0) == 0

    def test_catches_a_notebook_submission_past_run_and_scoring_time(self):
        allowance = self._scoring_task()
        sub = self._create_submission(
            "running", executed_at=utcnow() - timedelta(seconds=allowance + 30)
        )
        sub.time_limit_snapshot = 300
        db.session.commit()
        assert watchdog_stuck_submissions().get("timed_out", 0) >= 1
        assert "scoring time" in Submission.query.first().logs

    def test_recovered_from_fallback(self):
        from utils.cache_utils import get_redis_client

        r = get_redis_client()
        if not r:
            pytest.skip("Redis unavailable")

        sub = self._create_submission("running")
        fallback_key = f"submission:{sub.id}:fallback"
        fallback_data = {
            "attempt_id": sub.celery_task_id,
            "worker_id": "worker-watchdog",
            "status": "completed",
            "detailed_status": "done",
            "public_score": 0.9,
            "private_score": 0.8,
            "logs": "recovered via fallback",
        }
        r.set(f"worker:attempt:{sub.celery_task_id}", "worker-watchdog", ex=3600)
        r.set(fallback_key, json.dumps(fallback_data))

        with patch("utils.cache_utils.invalidate_leaderboard_cache") as invalidate:
            result = watchdog_stuck_submissions()
        assert result.get("recovered", 0) >= 1
        invalidate.assert_called_once_with(self.challenge.id)

        db.session.expire_all()
        updated = db.session.get(Submission, sub.id)
        assert updated.status == "completed"
        assert updated.public_score == 0.9
        assert updated.private_score == 0.8

    def test_fallback_clears_redis_key(self):
        from utils.cache_utils import get_redis_client

        r = get_redis_client()
        if not r:
            pytest.skip("Redis unavailable")

        sub = self._create_submission("running")
        fallback_key = f"submission:{sub.id}:fallback"
        r.set(
            fallback_key,
            json.dumps(
                {
                    "status": "completed",
                    "attempt_id": sub.celery_task_id,
                    "worker_id": "worker-watchdog",
                }
            ),
        )
        r.set(f"worker:attempt:{sub.celery_task_id}", "worker-watchdog", ex=3600)
        watchdog_stuck_submissions()
        assert r.get(fallback_key) is None

    def test_stale_fallback_cannot_overwrite_new_attempt(self):
        from utils.cache_utils import get_redis_client

        r = get_redis_client()
        if not r:
            pytest.skip("Redis unavailable")

        sub = self._create_submission("running")
        fallback_key = f"submission:{sub.id}:fallback"
        r.set(
            fallback_key,
            json.dumps(
                {
                    "status": "completed",
                    "attempt_id": "superseded-attempt",
                    "worker_id": "old-worker",
                    "public_score": 1.0,
                }
            ),
        )
        r.set(f"worker:attempt:{sub.celery_task_id}", "new-worker", ex=3600)

        watchdog_stuck_submissions()

        db.session.expire_all()
        assert db.session.get(Submission, sub.id).status == "running"
        assert r.get(fallback_key) is None

    def _fallback(self, sub, worker_id):
        return json.dumps(
            {
                "status": "completed",
                "detailed_status": "done",
                "attempt_id": sub.celery_task_id,
                "worker_id": worker_id,
                "public_score": 0.7,
            }
        )

    def test_fallback_recovered_after_lease_expired(self):
        from utils.cache_utils import get_coordination_client

        r = get_coordination_client()
        if not r:
            pytest.skip("Redis unavailable")

        sub = self._create_submission("running")
        # The worker lost contact longer than WORKER_ATTEMPT_LEASE_TTL: no binding left
        r.delete(f"worker:attempt:{sub.celery_task_id}")
        r.set(f"submission:{sub.id}:fallback", self._fallback(sub, "worker-a"))

        result = watchdog_stuck_submissions()

        assert result["recovered"] == 1
        db.session.expire_all()
        updated = db.session.get(Submission, sub.id)
        assert updated.status == "completed"
        assert updated.public_score == 0.7

    def test_fallback_rejected_while_another_worker_holds_the_lease(self):
        from utils.cache_utils import get_coordination_client

        r = get_coordination_client()
        if not r:
            pytest.skip("Redis unavailable")

        sub = self._create_submission("running")
        r.set(f"worker:attempt:{sub.celery_task_id}", "worker-b", ex=3600)
        r.set(f"submission:{sub.id}:fallback", self._fallback(sub, "worker-a"))

        result = watchdog_stuck_submissions()

        assert result["recovered"] == 0
        db.session.expire_all()
        assert db.session.get(Submission, sub.id).status == "running"
        assert r.get(f"submission:{sub.id}:fallback") is None

    def test_fallback_without_worker_id_is_rejected(self):
        from utils.cache_utils import get_coordination_client

        r = get_coordination_client()
        if not r:
            pytest.skip("Redis unavailable")

        sub = self._create_submission("running")
        r.set(f"submission:{sub.id}:fallback", self._fallback(sub, ""))

        result = watchdog_stuck_submissions()

        assert result["recovered"] == 0
        db.session.expire_all()
        assert db.session.get(Submission, sub.id).status == "running"

    def test_times_out_building_env_status(self):
        self._create_submission(
            "building_env",
            executed_at=utcnow() - timedelta(seconds=1000),
        )
        result = watchdog_stuck_submissions()
        assert result.get("timed_out", 0) >= 1

    def test_times_out_running_inference_status(self):
        self._create_submission(
            "running_inference",
            executed_at=utcnow() - timedelta(seconds=600),
        )
        result = watchdog_stuck_submissions()
        assert result.get("timed_out", 0) >= 1

    def test_times_out_evaluating_status(self):
        self._create_submission(
            "evaluating",
            executed_at=utcnow() - timedelta(seconds=600),
        )
        result = watchdog_stuck_submissions()
        assert result.get("timed_out", 0) >= 1

    def test_multiple_stuck_submissions(self):
        self._create_submission("queued", created_at=utcnow() - timedelta(hours=1, minutes=5))
        self._create_submission("running", executed_at=utcnow() - timedelta(seconds=600))
        result = watchdog_stuck_submissions()
        assert result.get("timed_out", 0) >= 2

    def test_revokes_celery_task_for_timed_out_submission(self, mocker):
        import tasks

        sub = self._create_submission("running", executed_at=utcnow() - timedelta(seconds=1000))
        sub.celery_task_id = "celery-task-abc"
        db.session.commit()
        mock_revoke = mocker.patch.object(tasks.celery.control, "revoke")
        result = watchdog_stuck_submissions()
        assert result.get("timed_out", 0) >= 1
        mock_revoke.assert_called_once_with("celery-task-abc", terminate=True)

    def test_revoke_failure_is_swallowed(self, mocker):
        import tasks

        sub = self._create_submission("running", executed_at=utcnow() - timedelta(seconds=1000))
        sub.celery_task_id = "celery-task-def"
        db.session.commit()
        mocker.patch.object(tasks.celery.control, "revoke", side_effect=Exception("broker down"))
        result = watchdog_stuck_submissions()
        assert result.get("timed_out", 0) >= 1
