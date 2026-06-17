import os
import sys
import json
import unittest
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import db, User, Challenge, Task, Submission
from auth_utils import generate_token, generate_worker_token


class TestWorkerEndpoints(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), '..', 'test_uploads')
        os.makedirs(self.app.config['UPLOAD_FOLDER'], exist_ok=True)
        self.client = self.app.test_client()

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
        import shutil
        shutil.rmtree(self.app.config['UPLOAD_FOLDER'], ignore_errors=True)

    def seed_basic_data(self):
        self.challenge = Challenge(
            title="Test Challenge",
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

        self.submission = Submission(
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            user_id=self.competitor.id,
            status='running',
            code_cells='[]'
        )
        db.session.add(self.submission)
        db.session.commit()

        self.worker_token = generate_worker_token(
            submission_id=self.submission.id, task_id=self.task.id,
            expires_in_sec=600
        )

        self.admin = User(
            username="test_admin",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            alias_id="Admin-001"
        )
        db.session.add(self.admin)
        db.session.commit()
        self.admin_token = generate_token(self.admin.id, role="admin")

    def _worker_headers(self):
        return {
            "X-Worker-Token": self.worker_token,
            "Content-Type": "application/json"
        }

    def _auth_headers(self, token=None):
        t = token or self.admin_token
        return {"Authorization": f"Bearer {t}"}

    # --- report_worker_progress ---

    def test_report_progress_success(self):
        resp = self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={"status": "completed", "detailed_status": "done"},
            headers=self._worker_headers()
        )
        self.assertEqual(resp.status_code, 200)

    def test_report_progress_updates_submission(self):
        self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={
                "status": "completed", "detailed_status": "done",
                "public_score": 0.95, "private_score": 0.85,
                "execution_time_ms": 1234,
                "logs": "eval completed"
            },
            headers=self._worker_headers()
        )
        sub = db.session.get(Submission, self.submission.id)
        self.assertEqual(sub.status, "completed")
        self.assertEqual(sub.public_score, 0.95)
        self.assertEqual(sub.private_score, 0.85)
        self.assertEqual(sub.execution_time_ms, 1234)
        self.assertIn("eval completed", sub.logs)

    def test_report_progress_invalid_token(self):
        resp = self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={"status": "completed", "detailed_status": "done"},
            headers={"X-Worker-Token": "invalid-token"}
        )
        self.assertEqual(resp.status_code, 401)

    def test_report_progress_wrong_submission_id(self):
        resp = self.client.post(
            "/api/worker/report/99999",
            json={"status": "completed", "detailed_status": "done"},
            headers=self._worker_headers()
        )
        self.assertEqual(resp.status_code, 401)

    def test_report_progress_missing_token(self):
        resp = self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={"status": "completed", "detailed_status": "done"}
        )
        self.assertEqual(resp.status_code, 401)

    def test_report_progress_sets_executed_at(self):
        self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={"status": "completed", "detailed_status": "done"},
            headers=self._worker_headers()
        )
        sub = db.session.get(Submission, self.submission.id)
        self.assertIsNotNone(sub.executed_at)

    def test_report_progress_saves_metrics_payload(self):
        self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={
                "status": "completed", "detailed_status": "done",
                "metrics_payload_public": json.dumps({"accuracy": 0.9}),
                "metrics_payload_private": json.dumps({"accuracy": 0.8})
            },
            headers=self._worker_headers()
        )
        sub = db.session.get(Submission, self.submission.id)
        self.assertIsNotNone(sub.metrics_payload_public)
        self.assertIsNotNone(sub.metrics_payload_private)

    def test_report_progress_with_fallback_data(self):
        from cache_utils import get_redis_client, set_cached
        r = get_redis_client()
        if r:
            r.delete(f"submission:{self.submission.id}:fallback")
        resp = self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={
                "status": "completed", "detailed_status": "done",
                "fallback_data": {"test": True}
            },
            headers=self._worker_headers()
        )
        self.assertEqual(resp.status_code, 200)

    # --- worker_download_task_file ---

    def test_download_task_file_success(self):
        os.makedirs(os.path.join(self.app.config['UPLOAD_FOLDER'], 'task_' + str(self.task.id)), exist_ok=True)
        task_dir = os.path.join(self.app.config['UPLOAD_FOLDER'], 'task_' + str(self.task.id))
        # Write file at the saved_name location
        with open(os.path.join(task_dir, "data.csv"), "w") as f:
            f.write("col1,col2\n1,2")
        # Set the task's files metadata to map filename -> saved_name
        self.task.files = json.dumps([{"filename": "data.csv", "saved_name": "data.csv"}])
        db.session.commit()

        resp = self.client.get(
            f"/api/worker/tasks/{self.task.id}/files/data.csv",
            headers={"X-Worker-Token": self.worker_token}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"col1,col2", resp.data)

    def test_download_task_file_wrong_task(self):
        resp = self.client.get(
            "/api/worker/tasks/99999/files/data.csv",
            headers={"X-Worker-Token": self.worker_token}
        )
        self.assertEqual(resp.status_code, 401)

    # --- get_active_datasets ---

    def test_get_active_datasets(self):
        resp = self.client.get(
            "/api/worker/active-datasets",
            headers={"X-Worker-Token": self.worker_token}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("datasets", data)

    def test_get_active_datasets_invalid_token(self):
        resp = self.client.get(
            "/api/worker/active-datasets",
            headers={"X-Worker-Token": "bad"}
        )
        self.assertEqual(resp.status_code, 401)

    # --- get_task_hf_key ---

    def test_get_task_hf_key(self):
        resp = self.client.get(
            f"/api/worker/tasks/{self.task.id}/hf-key",
            headers={"X-Worker-Token": self.worker_token}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("hf_key", data)

    def test_get_task_hf_key_invalid_token(self):
        resp = self.client.get(
            f"/api/worker/tasks/{self.task.id}/hf-key",
            headers={"X-Worker-Token": "bad"}
        )
        self.assertEqual(resp.status_code, 401)

    def test_get_task_hf_key_task_not_found(self):
        resp = self.client.get(
            "/api/worker/tasks/99999/hf-key",
            headers={"X-Worker-Token": self.worker_token}
        )
        self.assertEqual(resp.status_code, 404)
