import json
import os
import time
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from werkzeug.security import generate_password_hash

from models import db, User, Challenge, Task

# =============================================================================
# Area 1: Worker Bootstrap Token
# =============================================================================


class TestWorkerBootstrapToken:
    """POST /api/worker/bootstrap-token"""

    def test_valid_secret_via_header(self, client, monkeypatch):
        monkeypatch.setenv("WORKER_SECRET_KEY", "supersecret")
        resp = client.post(
            "/api/worker/bootstrap-token",
            headers={"X-Worker-Secret": "supersecret"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "token" in data
        assert data["expires_in"] == 3600

    def test_valid_secret_via_json_body(self, client, monkeypatch):
        monkeypatch.setenv("WORKER_SECRET_KEY", "supersecret")
        resp = client.post(
            "/api/worker/bootstrap-token",
            json={"secret": "supersecret"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "token" in data

    def test_invalid_secret(self, client, monkeypatch):
        monkeypatch.setenv("WORKER_SECRET_KEY", "supersecret")
        resp = client.post(
            "/api/worker/bootstrap-token",
            headers={"X-Worker-Secret": "wrong"},
        )
        assert resp.status_code == 401
        assert "Unauthorized" in resp.get_json()["error"]

    def test_missing_secret(self, client, monkeypatch):
        monkeypatch.setenv("WORKER_SECRET_KEY", "supersecret")
        resp = client.post("/api/worker/bootstrap-token", json={})
        assert resp.status_code == 401

    def test_no_env_var_set(self, client, monkeypatch):
        monkeypatch.delenv("WORKER_SECRET_KEY", raising=False)
        resp = client.post(
            "/api/worker/bootstrap-token",
            headers={"X-Worker-Secret": "anything"},
        )
        assert resp.status_code == 401


# =============================================================================
# Area 2: Task File Download
# =============================================================================

from flask import Response

MOCK_FILE_RESPONSE = Response("test file content", 200)


class TestTaskFileDownload:
    """GET /api/tasks/<task_id>/download/<filename>"""

    @pytest.fixture
    def task_with_files(self, db_session, sample_challenge):
        task = Task(
            title="Download Test Task",
            challenge_id=sample_challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
            files=json.dumps(
                [
                    {"filename": "data.csv", "saved_name": "abc_data.csv"},
                    {"filename": "labels.parquet", "saved_name": "xyz_labels.parquet"},
                ]
            ),
        )
        db_session.add(task)
        db_session.flush()
        return task

    @pytest.fixture
    def task_no_files(self, db_session, sample_challenge):
        task = Task(
            title="No Files Task",
            challenge_id=sample_challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
            files="[]",
        )
        db_session.add(task)
        db_session.flush()
        return task

    # --- unauthenticated ---

    def test_unauthenticated_returns_401(self, client, task_with_files):
        resp = client.get(f"/api/tasks/{task_with_files.id}/download/data.csv")
        assert resp.status_code == 401

    # --- admin downloads ---

    @patch("routes.tasks.send_from_directory")
    def test_admin_downloads_regular_file(
        self, mock_send, client, task_with_files, tokens, auth_headers
    ):
        mock_send.return_value = MOCK_FILE_RESPONSE
        resp = client.get(
            f"/api/tasks/{task_with_files.id}/download/data.csv",
            headers=auth_headers(tokens.admin),
        )
        assert resp.status_code == 200
        mock_send.assert_called_once()

    @patch("routes.tasks.send_from_directory")
    def test_admin_downloads_labels_parquet(
        self, mock_send, client, task_with_files, tokens, auth_headers
    ):
        mock_send.return_value = MOCK_FILE_RESPONSE
        resp = client.get(
            f"/api/tasks/{task_with_files.id}/download/labels.parquet",
            headers=auth_headers(tokens.admin),
        )
        assert resp.status_code == 200
        mock_send.assert_called_once()

    # --- competitor downloads ---

    @patch("routes.tasks.send_from_directory")
    def test_competitor_downloads_regular_file(
        self, mock_send, client, task_with_files, tokens, auth_headers
    ):
        mock_send.return_value = MOCK_FILE_RESPONSE
        resp = client.get(
            f"/api/tasks/{task_with_files.id}/download/data.csv",
            headers=auth_headers(tokens.competitor),
        )
        assert resp.status_code == 200
        mock_send.assert_called_once()

    def test_competitor_blocked_from_labels_parquet(
        self, client, task_with_files, tokens, auth_headers
    ):
        resp = client.get(
            f"/api/tasks/{task_with_files.id}/download/labels.parquet",
            headers=auth_headers(tokens.competitor),
        )
        assert resp.status_code == 403
        data = resp.get_json()
        assert data.get("code") == "ERR_ACCESS_DENIED"

    # --- task not started ---

    def test_competitor_blocked_when_task_not_started(
        self, client, db_session, sample_future_challenge, tokens, auth_headers, create_user
    ):
        future_task = Task(
            title="Future Task",
            challenge_id=sample_future_challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
            files=json.dumps([{"filename": "data.csv", "saved_name": "abc.csv"}]),
        )
        db_session.add(future_task)
        db_session.flush()

        comp = create_user(
            username="future_comp",
            role="competitor",
            alias_id="FutureComp",
            challenge_id=sample_future_challenge.id,
        )
        from auth_utils import generate_token

        comp_token = generate_token(comp.id, "competitor")

        resp = client.get(
            f"/api/tasks/{future_task.id}/download/data.csv",
            headers=auth_headers(comp_token),
        )
        assert resp.status_code == 403
        data = resp.get_json()
        assert data.get("code") == "ERR_NOT_AVAILABLE"

    # --- file not found in metadata ---

    def test_file_not_found_in_metadata(self, client, task_with_files, tokens, auth_headers):
        resp = client.get(
            f"/api/tasks/{task_with_files.id}/download/nonexistent.ipynb",
            headers=auth_headers(tokens.competitor),
        )
        assert resp.status_code == 404
        data = resp.get_json()
        assert data.get("code") == "ERR_FILE_NOT_FOUND"

    # --- non-existent task ---

    def test_non_existent_task(self, client, tokens, auth_headers):
        resp = client.get(
            "/api/tasks/999999/download/data.csv",
            headers=auth_headers(tokens.admin),
        )
        assert resp.status_code == 404


# =============================================================================
# Area 3: Login Rate Limiting
# =============================================================================


class TestLoginRateLimiting:
    """Rate-limiting helpers in routes/auth.py + login endpoint 429."""

    def test_no_failures_not_exceeded(self, redis_flush):
        from routes.auth import _login_rate_limit_exceeded

        assert _login_rate_limit_exceeded("nonexistent_user", "1.2.3.4") is False

    def test_five_failures_exceeds_user_limit(self, redis_flush):
        from routes.auth import _record_login_failure, _login_rate_limit_exceeded

        username = "rate_test_user"
        ip = "10.0.0.1"
        for _ in range(5):
            _record_login_failure(username, ip)
        assert _login_rate_limit_exceeded(username, ip) is True

    def test_clear_failures_resets_limit(self, redis_flush):
        from routes.auth import (
            _record_login_failure,
            _login_rate_limit_exceeded,
            _clear_login_failures,
        )

        username = "clear_test_user"
        ip = "10.0.0.2"
        for _ in range(5):
            _record_login_failure(username, ip)
        assert _login_rate_limit_exceeded(username, ip) is True
        _clear_login_failures(username, ip)
        assert _login_rate_limit_exceeded(username, ip) is False

    def test_thirty_ip_failures_exceeds_ip_limit(self, redis_flush):
        from routes.auth import _record_login_failure, _login_rate_limit_exceeded

        ip = "10.0.0.100"
        for i in range(30):
            _record_login_failure(f"user_{i}", ip)
        assert _login_rate_limit_exceeded("some_other_user", ip) is True

    def test_login_endpoint_returns_429(self, redis_flush, client, db_session, app_ctx):
        user = User(
            username="ratelimitme",
            password_hash=generate_password_hash("correctpass", method="pbkdf2:sha256"),
            role="competitor",
        )
        db_session.add(user)
        db_session.flush()

        headers = {"X-Forwarded-For": "198.51.100.1"}
        for _ in range(5):
            resp = client.post(
                "/api/auth/login",
                json={"username": "ratelimitme", "password": "wrongpass"},
                headers=headers,
            )
            assert resp.status_code == 401

        resp = client.post(
            "/api/auth/login",
            json={"username": "ratelimitme", "password": "wrongpass"},
            headers=headers,
        )
        assert resp.status_code == 429
        data = resp.get_json()
        assert data.get("code") == "ERR_RATE_LIMIT_EXCEEDED"


# =============================================================================
# Area 4: Register Competitor
# =============================================================================


class TestRegisterCompetitor:
    """POST /api/admin/register-competitor"""

    COMP_PAYLOAD = {
        "name": "Ivan",
        "surname": "Petrov",
        "grade": "10",
        "school": "Sofia High",
        "city": "Sofia",
    }

    def test_admin_registers_competitor_success(
        self, client, sample_challenge, tokens, auth_headers
    ):
        payload = {**self.COMP_PAYLOAD, "challenge_id": sample_challenge.id}
        resp = client.post(
            "/api/admin/register-competitor",
            headers=auth_headers(tokens.admin),
            json=payload,
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["message"] == "Competitor registered successfully."
        assert "generated_username" in data
        assert "generated_password" in data
        assert "user" in data

    def test_missing_challenge_id_returns_400(self, client, tokens, auth_headers):
        resp = client.post(
            "/api/admin/register-competitor",
            headers=auth_headers(tokens.admin),
            json={**self.COMP_PAYLOAD},
        )
        assert resp.status_code == 400
        assert "challenge_id is required" in resp.get_json()["error"]

    def test_invalid_challenge_id_returns_400(self, client, tokens, auth_headers):
        payload = {**self.COMP_PAYLOAD, "challenge_id": 99999}
        resp = client.post(
            "/api/admin/register-competitor",
            headers=auth_headers(tokens.admin),
            json=payload,
        )
        assert resp.status_code == 400
        assert "Invalid challenge_id" in resp.get_json()["error"]

    def test_missing_name_and_surname_returns_400(
        self, client, sample_challenge, tokens, auth_headers
    ):
        payload = {"challenge_id": sample_challenge.id}
        resp = client.post(
            "/api/admin/register-competitor",
            headers=auth_headers(tokens.admin),
            json=payload,
        )
        assert resp.status_code == 400
        assert "Name and Surname" in resp.get_json()["error"]

    def test_jury_registers_competitor_before_start(
        self, client, db_session, sample_future_challenge, auth_headers
    ):
        from auth_utils import generate_token

        jury = User(
            username="jury_before",
            password_hash="x",
            role="jury",
            alias_id="JuryBefore",
        )
        db_session.add(jury)
        db_session.flush()
        jury_token = generate_token(jury.id, "jury")
        payload = {**self.COMP_PAYLOAD, "challenge_id": sample_future_challenge.id}
        resp = client.post(
            "/api/admin/register-competitor",
            headers=auth_headers(jury_token),
            json=payload,
        )
        assert resp.status_code == 201

    def test_jury_blocked_after_competition_started(
        self, client, db_session, sample_challenge, auth_headers
    ):
        from auth_utils import generate_token

        jury = User(
            username="jury_after",
            password_hash="x",
            role="jury",
            alias_id="JuryAfter",
        )
        db_session.add(jury)
        db_session.flush()
        jury_token = generate_token(jury.id, "jury")
        payload = {**self.COMP_PAYLOAD, "challenge_id": sample_challenge.id}
        resp = client.post(
            "/api/admin/register-competitor",
            headers=auth_headers(jury_token),
            json=payload,
        )
        assert resp.status_code == 403
        assert "Jury members cannot register" in resp.get_json()["error"]

    def test_unauthenticated_returns_403(self, client, sample_challenge):
        payload = {**self.COMP_PAYLOAD, "challenge_id": sample_challenge.id}
        resp = client.post(
            "/api/admin/register-competitor",
            json=payload,
        )
        assert resp.status_code == 403
