import json
from datetime import datetime, timedelta

import pytest
from models import Challenge, Submission, Task, User, db
from tasks import watchdog_stuck_submissions


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
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2),
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
        kwargs = dict(
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            user_id=self.competitor.id,
            status=status,
            code_cells="[]",
        )
        if executed_at is not None:
            kwargs["executed_at"] = executed_at
        if created_at is not None:
            kwargs["created_at"] = created_at
        if time_limit is not None:
            self.task.time_limit_sec = time_limit
        sub = Submission(**kwargs)
        db.session.add(sub)
        db.session.commit()
        return sub

    def test_no_stuck_submissions(self):
        sub = self._create_submission("completed")
        sub.executed_at = datetime.utcnow()
        db.session.commit()

        result = watchdog_stuck_submissions()
        assert result.get("timed_out", 0) == 0

    def test_times_out_stuck_queued_submission(self):
        self._create_submission("queued", created_at=datetime.utcnow() - timedelta(minutes=15))
        result = watchdog_stuck_submissions()
        assert result.get("timed_out", 0) >= 1
        sub = Submission.query.first()
        assert sub.status == "failed"
        assert "WATCHDOG" in sub.logs

    def test_does_not_time_out_recent_queued_submission(self):
        self._create_submission("queued", created_at=datetime.utcnow())
        result = watchdog_stuck_submissions()
        assert result.get("timed_out", 0) == 0

    def test_times_out_running_submission_exceeded_time_limit(self):
        self._create_submission("running", executed_at=datetime.utcnow() - timedelta(seconds=1000))
        result = watchdog_stuck_submissions()
        assert result.get("timed_out", 0) >= 1

    def test_does_not_time_out_running_within_limit(self):
        self._create_submission("running", executed_at=datetime.utcnow() - timedelta(seconds=10))
        result = watchdog_stuck_submissions()
        assert result.get("timed_out", 0) == 0

    def test_recovered_from_fallback(self):
        from cache_utils import get_redis_client

        r = get_redis_client()
        if not r:
            pytest.skip("Redis unavailable")

        sub = self._create_submission("running")
        fallback_key = f"submission:{sub.id}:fallback"
        fallback_data = {
            "status": "completed",
            "detailed_status": "done",
            "public_score": 0.9,
            "private_score": 0.8,
            "logs": "recovered via fallback",
        }
        r.set(fallback_key, json.dumps(fallback_data))

        result = watchdog_stuck_submissions()
        assert result.get("recovered", 0) >= 1

        db.session.expire_all()
        updated = db.session.get(Submission, sub.id)
        assert updated.status == "completed"
        assert updated.public_score == 0.9
        assert updated.private_score == 0.8

    def test_fallback_clears_redis_key(self):
        from cache_utils import get_redis_client

        r = get_redis_client()
        if not r:
            pytest.skip("Redis unavailable")

        sub = self._create_submission("running")
        fallback_key = f"submission:{sub.id}:fallback"
        r.set(fallback_key, json.dumps({"status": "completed"}))
        watchdog_stuck_submissions()
        assert r.get(fallback_key) is None

    def test_times_out_building_env_status(self):
        self._create_submission(
            "building_env", executed_at=datetime.utcnow() - timedelta(seconds=1000)
        )
        result = watchdog_stuck_submissions()
        assert result.get("timed_out", 0) >= 1

    def test_times_out_running_inference_status(self):
        self._create_submission(
            "running_inference", executed_at=datetime.utcnow() - timedelta(seconds=600)
        )
        result = watchdog_stuck_submissions()
        assert result.get("timed_out", 0) >= 1

    def test_times_out_evaluating_status(self):
        self._create_submission(
            "evaluating", executed_at=datetime.utcnow() - timedelta(seconds=600)
        )
        result = watchdog_stuck_submissions()
        assert result.get("timed_out", 0) >= 1

    def test_multiple_stuck_submissions(self):
        self._create_submission("queued", created_at=datetime.utcnow() - timedelta(minutes=15))
        self._create_submission("running", executed_at=datetime.utcnow() - timedelta(seconds=600))
        result = watchdog_stuck_submissions()
        assert result.get("timed_out", 0) >= 2
