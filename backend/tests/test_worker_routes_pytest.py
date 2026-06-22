import os
import json
from datetime import datetime, timedelta

import pytest
from models import db, User, Challenge, Task, Submission
from auth_utils import generate_token, generate_worker_token


class TestWorkerEndpoints:
    @pytest.fixture(autouse=True)
    def setup(self, client, db_session, app_ctx, redis_flush):
        self.client = client
        import shutil

        upload_folder = os.path.join(os.path.dirname(__file__), "..", "test_uploads")
        os.makedirs(upload_folder, exist_ok=True)
        from flask import current_app

        current_app.config["UPLOAD_FOLDER"] = upload_folder
        self.upload_folder = upload_folder
        self.seed_basic_data()
        yield
        shutil.rmtree(upload_folder, ignore_errors=True)

    def seed_basic_data(self):
        self.challenge = Challenge(
            title="Test Challenge",
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

        self.submission = Submission(
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            user_id=self.competitor.id,
            status="running",
            code_cells="[]",
        )
        db.session.add(self.submission)
        db.session.commit()

        self.worker_token = generate_worker_token(
            submission_id=self.submission.id, task_id=self.task.id, expires_in_sec=600
        )

        self.admin = User(
            username="test_admin",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            alias_id="Admin-001",
        )
        db.session.add(self.admin)
        db.session.commit()
        self.admin_token = generate_token(self.admin.id, role="admin")

    def _worker_headers(self):
        return {"X-Worker-Token": self.worker_token, "Content-Type": "application/json"}

    def _auth_headers(self, token=None):
        t = token or self.admin_token
        return {"Authorization": f"Bearer {t}"}

    def test_report_progress_success(self):
        resp = self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={"status": "completed", "detailed_status": "done"},
            headers=self._worker_headers(),
        )
        assert resp.status_code == 200

    def test_report_progress_updates_submission(self):
        self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={
                "status": "completed",
                "detailed_status": "done",
                "public_score": 0.95,
                "private_score": 0.85,
                "execution_time_ms": 1234,
                "logs": "eval completed",
            },
            headers=self._worker_headers(),
        )
        sub = db.session.get(Submission, self.submission.id)
        assert sub.status == "completed"
        assert sub.public_score == 0.95
        assert sub.private_score == 0.85
        assert sub.execution_time_ms == 1234
        assert "eval completed" in sub.logs

    def test_report_progress_invalid_token(self):
        resp = self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={"status": "completed", "detailed_status": "done"},
            headers={"X-Worker-Token": "invalid-token"},
        )
        assert resp.status_code == 401

    def test_report_progress_wrong_submission_id(self):
        resp = self.client.post(
            "/api/worker/report/99999",
            json={"status": "completed", "detailed_status": "done"},
            headers=self._worker_headers(),
        )
        assert resp.status_code == 404

    def test_report_progress_missing_token(self):
        resp = self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={"status": "completed", "detailed_status": "done"},
        )
        assert resp.status_code == 401

    def test_report_progress_sets_executed_at(self):
        self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={"status": "completed", "detailed_status": "done"},
            headers=self._worker_headers(),
        )
        sub = db.session.get(Submission, self.submission.id)
        assert sub.executed_at is not None

    def test_report_progress_saves_metrics_payload(self):
        self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={
                "status": "completed",
                "detailed_status": "done",
                "metrics_payload_public": json.dumps({"accuracy": 0.9}),
                "metrics_payload_private": json.dumps({"accuracy": 0.8}),
            },
            headers=self._worker_headers(),
        )
        sub = db.session.get(Submission, self.submission.id)
        assert sub.metrics_payload_public is not None
        assert sub.metrics_payload_private is not None

    def test_report_progress_with_fallback_data(self):
        from cache_utils import get_redis_client, set_cached

        r = get_redis_client()
        if r:
            r.delete(f"submission:{self.submission.id}:fallback")
        resp = self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={
                "status": "completed",
                "detailed_status": "done",
                "fallback_data": {"test": True},
            },
            headers=self._worker_headers(),
        )
        assert resp.status_code == 200

    def test_download_task_file_success(self):
        os.makedirs(os.path.join(self.upload_folder, "task_" + str(self.task.id)), exist_ok=True)
        task_dir = os.path.join(self.upload_folder, "task_" + str(self.task.id))
        with open(os.path.join(task_dir, "data.csv"), "w") as f:
            f.write("col1,col2\n1,2")
        self.task.files = json.dumps([{"filename": "data.csv", "saved_name": "data.csv"}])
        db.session.commit()

        resp = self.client.get(
            f"/api/worker/tasks/{self.task.id}/files/data.csv",
            headers={"X-Worker-Token": self.worker_token},
        )
        assert resp.status_code == 200
        assert b"col1,col2" in resp.data

    def test_download_task_file_wrong_task(self):
        resp = self.client.get(
            "/api/worker/tasks/99999/files/data.csv", headers={"X-Worker-Token": self.worker_token}
        )
        assert resp.status_code == 401

    def test_get_active_datasets(self):
        resp = self.client.get(
            "/api/worker/active-datasets", headers={"X-Worker-Token": self.worker_token}
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "datasets" in data

    def test_get_active_datasets_invalid_token(self):
        resp = self.client.get("/api/worker/active-datasets", headers={"X-Worker-Token": "bad"})
        assert resp.status_code == 401

    def test_get_task_hf_key(self):
        resp = self.client.get(
            f"/api/worker/tasks/{self.task.id}/hf-key",
            headers={"X-Worker-Token": self.worker_token},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "hf_key" in data

    def test_get_task_hf_key_invalid_token(self):
        resp = self.client.get(
            f"/api/worker/tasks/{self.task.id}/hf-key", headers={"X-Worker-Token": "bad"}
        )
        assert resp.status_code == 401

    def test_get_task_hf_key_task_not_found(self):
        resp = self.client.get(
            "/api/worker/tasks/99999/hf-key", headers={"X-Worker-Token": self.worker_token}
        )
        assert resp.status_code == 404
