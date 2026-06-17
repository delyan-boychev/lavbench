import os
import sys
import json
import unittest
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# Use a file-based SQLite so both test and tasks module share the same DB
_db_path = tempfile.mktemp(suffix='.db')
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import db, User, Challenge, Task, Submission
from tasks import watchdog_stuck_submissions


class TestWatchdogStuckSubmissions(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        if os.path.exists(_db_path):
            os.unlink(_db_path)

    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']
        self.client = self.app.test_client()

        # Patch tasks.app so watchdog uses the test app's engine/DB
        import tasks
        tasks.app = self.app

        self.app_context = self.app.app_context()
        self.app_context.push()

        from cache_utils import get_redis_client
        r = get_redis_client()
        if r:
            try:
                r.flushdb()
            except Exception:
                pass

        db.create_all()
        self.seed_basic_data()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def seed_basic_data(self):
        self.challenge = Challenge(
            title="Watchdog Test",
            description="Test",
            max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2),
            is_frozen=False
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
            metrics_config={"accuracy": {"weight": 1.0, "higher_is_better": True}}
        )
        db.session.add(self.task)

        self.competitor = User(
            username="test_comp",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Comp-001",
            challenge_id=self.challenge.id
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
            code_cells='[]'
        )
        if executed_at is not None:
            kwargs['executed_at'] = executed_at
        if created_at is not None:
            kwargs['created_at'] = created_at
        if time_limit is not None:
            # Set per-task time limit override via task attribute
            self.task.time_limit_sec = time_limit
        sub = Submission(**kwargs)
        db.session.add(sub)
        db.session.commit()
        return sub

    def test_no_stuck_submissions(self):
        sub = self._create_submission('completed')
        sub.executed_at = datetime.utcnow()
        db.session.commit()

        result = watchdog_stuck_submissions()
        self.assertEqual(result.get("timed_out", 0), 0)

    def test_times_out_stuck_queued_submission(self):
        self._create_submission('queued', created_at=datetime.utcnow() - timedelta(minutes=15))
        result = watchdog_stuck_submissions()
        self.assertGreaterEqual(result.get("timed_out", 0), 1)
        sub = Submission.query.first()
        self.assertEqual(sub.status, 'failed')
        self.assertIn("WATCHDOG", sub.logs)

    def test_does_not_time_out_recent_queued_submission(self):
        self._create_submission('queued', created_at=datetime.utcnow())
        result = watchdog_stuck_submissions()
        self.assertEqual(result.get("timed_out", 0), 0)

    def test_times_out_running_submission_exceeded_time_limit(self):
        self._create_submission(
            'running',
            executed_at=datetime.utcnow() - timedelta(seconds=1000)
        )
        result = watchdog_stuck_submissions()
        self.assertGreaterEqual(result.get("timed_out", 0), 1)

    def test_does_not_time_out_running_within_limit(self):
        self._create_submission(
            'running',
            executed_at=datetime.utcnow() - timedelta(seconds=10)
        )
        result = watchdog_stuck_submissions()
        self.assertEqual(result.get("timed_out", 0), 0)

    def test_recovered_from_fallback(self):
        from cache_utils import get_redis_client
        r = get_redis_client()
        if not r:
            self.skipTest("Redis unavailable")

        sub = self._create_submission('running')
        fallback_key = f"submission:{sub.id}:fallback"
        fallback_data = {
            "status": "completed",
            "detailed_status": "done",
            "public_score": 0.9,
            "private_score": 0.8,
            "logs": "recovered via fallback"
        }
        r.set(fallback_key, json.dumps(fallback_data))

        result = watchdog_stuck_submissions()
        self.assertGreaterEqual(result.get("recovered", 0), 1)

        db.session.expire_all()
        updated = db.session.get(Submission, sub.id)
        self.assertEqual(updated.status, "completed")
        self.assertEqual(updated.public_score, 0.9)
        self.assertEqual(updated.private_score, 0.8)

    def test_fallback_clears_redis_key(self):
        from cache_utils import get_redis_client
        r = get_redis_client()
        if not r:
            self.skipTest("Redis unavailable")

        sub = self._create_submission('running')
        fallback_key = f"submission:{sub.id}:fallback"
        r.set(fallback_key, json.dumps({"status": "completed"}))
        watchdog_stuck_submissions()
        self.assertIsNone(r.get(fallback_key))

    def test_times_out_building_env_status(self):
        self._create_submission(
            'building_env',
            executed_at=datetime.utcnow() - timedelta(seconds=1000)
        )
        result = watchdog_stuck_submissions()
        self.assertGreaterEqual(result.get("timed_out", 0), 1)

    def test_times_out_running_inference_status(self):
        self._create_submission(
            'running_inference',
            executed_at=datetime.utcnow() - timedelta(seconds=600)
        )
        result = watchdog_stuck_submissions()
        self.assertGreaterEqual(result.get("timed_out", 0), 1)

    def test_times_out_evaluating_status(self):
        self._create_submission(
            'evaluating',
            executed_at=datetime.utcnow() - timedelta(seconds=600)
        )
        result = watchdog_stuck_submissions()
        self.assertGreaterEqual(result.get("timed_out", 0), 1)

    def test_multiple_stuck_submissions(self):
        self._create_submission('queued', created_at=datetime.utcnow() - timedelta(minutes=15))
        self._create_submission('running', executed_at=datetime.utcnow() - timedelta(seconds=600))
        result = watchdog_stuck_submissions()
        self.assertGreaterEqual(result.get("timed_out", 0), 2)
