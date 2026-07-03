import os
import sys
from datetime import timedelta
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from utils.dates import utcnow

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from auth_utils import generate_token
from models import Challenge, Submission, Task, User, db


class TestBackendExceptionAndErrorCases:
    @pytest.fixture(autouse=True)
    def setup(self, app, db_session):
        self.app = app
        self.client = app.test_client()
        self.seed_basic_data()

    def seed_basic_data(self):
        self.admin = User(
            username="admin_user",
            password_hash="pbkdf2:sha256:260000$mockpbkdf2hash",
            role="admin",
            alias_id="Admin-999",
        )
        self.challenge_a = Challenge(
            title="Challenge Alpha",
            description="Competitor challenge A",
            max_eval_requests=3,
            start_time=utcnow() - timedelta(hours=1),
            end_time=utcnow() + timedelta(hours=1),
        )
        self.challenge_b = Challenge(
            title="Challenge Beta",
            description="Competitor challenge B",
            max_eval_requests=5,
            start_time=utcnow() - timedelta(hours=1),
            end_time=utcnow() + timedelta(hours=1),
        )
        db.session.add(self.admin)
        db.session.add(self.challenge_a)
        db.session.add(self.challenge_b)
        db.session.commit()

        self.competitor = User(
            username="competitor_user",
            password_hash="pbkdf2:sha256:260000$mockpbkdf2hash",
            role="competitor",
            alias_id="Competitor-101",
            challenge_id=self.challenge_a.id,
        )
        self.unregistered_competitor = User(
            username="unregistered_user",
            password_hash="pbkdf2:sha256:260000$mockpbkdf2hash",
            role="competitor",
            alias_id="Competitor-102",
            challenge_id=None,
        )
        db.session.add(self.competitor)
        db.session.add(self.unregistered_competitor)
        db.session.commit()

        self.task_a = Task(
            challenge_id=self.challenge_a.id,
            title="Task A",
            description="Task A description",
        )
        db.session.add(self.task_a)
        db.session.commit()

    def _auth(self, user):
        return {"Authorization": f"Bearer {generate_token(user.id, user.role)}"}

    def test_login_missing_parameters(self):
        res = self.client.post("/api/auth/login", json={})
        assert res.status_code == 400
        assert "Missing username or password" in res.json["error"]

        res = self.client.post("/api/auth/login", json={"username": "admin_user"})
        assert res.status_code == 400
        assert "Missing username or password" in res.json["error"]

    def test_login_invalid_credentials(self):
        res = self.client.post("/api/auth/login", json={"username": "ghost", "password": "pwd"})
        assert res.status_code == 401
        assert "Invalid credentials" in res.json["error"]

        res = self.client.post(
            "/api/auth/login",
            json={"username": "admin_user", "password": "wrong_password"},
        )
        assert res.status_code == 401
        assert "Invalid credentials" in res.json["error"]

    def test_me_unauthorized_missing_token(self):
        res = self.client.get("/api/auth/me")
        assert res.status_code == 401
        assert "Unauthorized access" in res.json["error"]

    def test_me_unauthorized_invalid_token(self):
        headers = {"Authorization": "Bearer malformed.token.signature"}
        res = self.client.get("/api/auth/me", headers=headers)
        assert res.status_code == 401
        assert "Unauthorized access" in res.json["error"]

    def test_me_user_not_found(self):
        token = generate_token(99999, "competitor")
        res = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 404
        assert "User not found" in res.json["error"]

    def test_get_challenge_not_registered_competitor(self):
        headers = self._auth(self.competitor)
        res = self.client.get(f"/api/challenges/{self.challenge_b.id}", headers=headers)
        assert res.status_code == 403
        assert "Access denied. You are not registered for this competition" in res.json["error"]

    def test_get_challenge_not_found(self):
        headers = self._auth(self.admin)
        res = self.client.get("/api/challenges/9999", headers=headers)
        assert res.status_code == 404

    def test_create_challenge_unauthorized_role(self):
        headers = self._auth(self.competitor)
        res = self.client.post("/api/challenges", json={"title": "Unauthorized"}, headers=headers)
        assert res.status_code == 403
        assert "Requires role: ['admin', 'jury']" in res.json["error"]

    def test_create_challenge_missing_title(self):
        headers = self._auth(self.admin)
        res = self.client.post("/api/challenges", json={"description": "No Title"}, headers=headers)
        assert res.status_code == 400
        assert "Competition title is required" in res.json["error"]

    def test_update_challenge_not_found(self):
        headers = self._auth(self.admin)
        res = self.client.put("/api/challenges/9999", json={"title": "Updated"}, headers=headers)
        assert res.status_code == 404

    def test_delete_challenge_not_found(self):
        headers = self._auth(self.admin)
        res = self.client.delete("/api/challenges/9999", headers=headers)
        assert res.status_code == 404

    def test_parse_notebook_denied_access_competitor(self):
        headers = self._auth(self.competitor)
        res = self.client.post(
            f"/api/challenges/{self.challenge_b.id}/parse-notebook", headers=headers
        )
        assert res.status_code == 403
        assert "Access denied" in res.json["error"]

    def test_parse_notebook_missing_file(self):
        headers = self._auth(self.competitor)
        res = self.client.post(
            f"/api/challenges/{self.challenge_a.id}/parse-notebook", headers=headers
        )
        assert res.status_code == 400
        assert "No file uploaded" in res.json["error"]

    def test_parse_notebook_invalid_extension(self):
        headers = self._auth(self.competitor)
        file_content = BytesIO(b"print('not a notebook')")
        data = {"file": (file_content, "submission.py")}
        res = self.client.post(
            f"/api/challenges/{self.challenge_a.id}/parse-notebook",
            data=data,
            headers=headers,
        )
        assert res.status_code == 400
        assert "not allowed" in res.json["error"]

    def test_parse_notebook_malformed_json(self):
        headers = self._auth(self.competitor)
        file_content = BytesIO(b"this is not a valid JSON notebook")
        data = {"file": (file_content, "submission.ipynb")}
        res = self.client.post(
            f"/api/challenges/{self.challenge_a.id}/parse-notebook",
            data=data,
            headers=headers,
        )
        assert res.status_code == 400
        assert "Invalid notebook file" in res.json["error"]

    def test_submit_code_denied_access_competitor(self):
        headers = self._auth(self.competitor)
        res = self.client.post(
            f"/api/challenges/{self.challenge_b.id}/submit", json={}, headers=headers
        )
        assert res.status_code == 403
        assert "Access denied" in res.json["error"]

    def test_submit_code_challenge_inactive_or_archived(self):
        headers = self._auth(self.competitor)

        inactive_challenge = Challenge(
            title="Inactive",
            is_active=False,
            max_eval_requests=5,
            start_time=utcnow() - timedelta(hours=1),
            end_time=utcnow() + timedelta(hours=1),
        )
        db.session.add(inactive_challenge)
        db.session.commit()

        self.competitor.challenge_id = inactive_challenge.id
        db.session.commit()

        res = self.client.post(
            f"/api/challenges/{inactive_challenge.id}/submit", json={}, headers=headers
        )
        assert res.status_code == 400
        assert "This challenge is currently inactive" in res.json["error"]

        archived_challenge = Challenge(
            title="Archived",
            is_active=True,
            is_archived=True,
            max_eval_requests=5,
            start_time=utcnow() - timedelta(hours=1),
            end_time=utcnow() + timedelta(hours=1),
        )
        db.session.add(archived_challenge)
        db.session.commit()

        self.competitor.challenge_id = archived_challenge.id
        db.session.commit()

        res = self.client.post(
            f"/api/challenges/{archived_challenge.id}/submit", json={}, headers=headers
        )
        assert res.status_code == 400
        assert "This competition has been archived" in res.json["error"]

    def test_submit_code_timeline_violations(self):
        headers = self._auth(self.competitor)
        self.competitor.challenge_id = self.challenge_a.id
        db.session.commit()

        self.challenge_a.start_time = utcnow() + timedelta(hours=1)
        self.challenge_a.end_time = utcnow() + timedelta(hours=2)
        db.session.commit()

        res = self.client.post(
            f"/api/challenges/{self.challenge_a.id}/submit", json={}, headers=headers
        )
        assert res.status_code == 400
        assert "This competition has not started yet" in res.json["error"]

        self.challenge_a.start_time = utcnow() - timedelta(hours=2)
        self.challenge_a.end_time = utcnow() - timedelta(hours=1)
        db.session.commit()

        res = self.client.post(
            f"/api/challenges/{self.challenge_a.id}/submit", json={}, headers=headers
        )
        assert res.status_code == 400
        assert "This competition has ended" in res.json["error"]

    @patch("tasks.evaluate_submission.delay")
    def test_submit_code_missing_cells_and_rate_limits(self, mock_celery):
        headers = self._auth(self.competitor)

        self.challenge_a.start_time = utcnow() - timedelta(hours=1)
        self.challenge_a.end_time = utcnow() + timedelta(hours=1)
        db.session.commit()

        res = self.client.post(
            f"/api/challenges/{self.challenge_a.id}/submit", json={}, headers=headers
        )
        assert res.status_code == 400
        assert "selected_cells list is required" in res.json["error"]

        for _i in range(3):
            sub = Submission(
                user_id=self.competitor.id,
                challenge_id=self.challenge_a.id,
                task_id=self.task_a.id,
                status="completed",
                code_cells="[]",
                created_at=utcnow(),
            )
            db.session.add(sub)
        db.session.commit()

        res = self.client.post(
            f"/api/challenges/{self.challenge_a.id}/submit",
            json={"selected_cells": ["cell_content"], "task_id": self.task_a.id},
            headers=headers,
        )
        assert res.status_code == 429
        assert "Daily limit reached" in res.json["error"]

    def test_select_final_submission_denied_competitor(self):
        headers = self._auth(self.competitor)
        sub = Submission(
            user_id=self.admin.id,
            challenge_id=self.challenge_a.id,
            status="completed",
            code_cells="[]",
        )
        db.session.add(sub)
        db.session.commit()

        res = self.client.post(f"/api/submissions/{sub.id}/select-final", headers=headers)
        assert res.status_code == 404

    def test_get_leaderboard_denied_access_competitor(self):
        headers = self._auth(self.competitor)
        res = self.client.get(f"/api/challenges/{self.challenge_b.id}/leaderboard", headers=headers)
        assert res.status_code == 403
        assert "Access denied" in res.json["error"]

    def test_get_leaderboard_not_found(self):
        headers = self._auth(self.admin)
        res = self.client.get("/api/challenges/9999/leaderboard", headers=headers)
        assert res.status_code == 404

    @patch("requests.post")
    def test_report_status_success_on_first_try(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        from worker_utils import report_status_to_server

        metadata = {
            "main_server_url": "http://localhost:5001",
            "worker_secret_key": "secret",
            "submission_id": 1,
        }
        success = report_status_to_server(metadata, "completed", "done")
        assert success
        mock_post.assert_called_once()

    @patch("time.sleep")
    @patch("requests.post")
    def test_report_status_retry_on_failure_then_succeed(self, mock_post, mock_sleep):
        mock_post.side_effect = [
            Exception("Connection timeout"),
            MagicMock(status_code=500),
            MagicMock(status_code=200),
        ]
        from worker_utils import report_status_to_server

        metadata = {
            "main_server_url": "http://localhost:5001",
            "worker_secret_key": "secret",
            "submission_id": 1,
        }
        success = report_status_to_server(
            metadata, "completed", "done", max_retries=3, backoff_factor=1
        )
        assert success
        assert mock_post.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("time.sleep")
    @patch("requests.post")
    def test_report_status_fails_completely(self, mock_post, mock_sleep):
        mock_post.side_effect = Exception("Permanent failure")
        from worker_utils import report_status_to_server

        metadata = {
            "main_server_url": "http://localhost:5001",
            "worker_secret_key": "secret",
            "submission_id": 1,
        }
        success = report_status_to_server(
            metadata, "completed", "done", max_retries=3, backoff_factor=1
        )
        assert not success
        assert mock_post.call_count == 3

    @patch("requests.post")
    @patch("worker_utils.download_task_files_to_dir")
    @patch("task_modules.submission_runner.run_command_streaming")
    @patch("task_modules.submission_runner._get_client")
    @patch("task_modules.submission_runner.check_docker_available")
    def test_evaluate_submission_callback_failure_raises_runtime_error(
        self, mock_post, mock_dl, mock_stream, mock_get_client, mock_docker_check
    ):
        mock_docker_check.return_value = True
        mock_get_client.return_value = MagicMock()
        mock_post.return_value = MagicMock(status_code=500)
        mock_stream.return_value = (0, "", "", False)

        from tasks import evaluate_submission

        metadata = {
            "main_server_url": "http://localhost:5001",
            "worker_secret_key": "secret",
            "submission_id": 1,
            "task_id": 2,
            "user_code": "def predict(x): return 1",
            "is_custom_eval": True,
            "custom_eval_code": (
                'print(\'{"status": "success", "public_score": '
                '0.85, "private_score": 0.85, "execution_time_ms": 5}\')'
            ),
        }

        result = evaluate_submission(submission_id=1, metadata=metadata)
        assert "evaluated with status failed" in result
