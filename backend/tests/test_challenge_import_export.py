"""Tests for challenge import/export routes.

Covers:
  - GET  /api/challenges/<id>/export          JSON export (admin/jury)
  - POST /api/challenges/import               JSON import (admin only)
  - GET  /api/challenges/<id>/export-results   CSV export (admin/jury)
  - POST /api/admin/import-competitors-csv     CSV competitor import
"""

import io
import json
from datetime import datetime, timedelta

import pytest

from models import db, User, Challenge, Task, Stage


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def challenge_with_stages_and_tasks(db_session, sample_challenge):
    ch = sample_challenge
    stage1 = Stage(
        challenge_id=ch.id,
        stage_number=1,
        title="Stage 1",
        start_time=datetime.utcnow() - timedelta(days=1),
        end_time=datetime.utcnow() + timedelta(days=1),
    )
    stage2 = Stage(
        challenge_id=ch.id,
        stage_number=2,
        title="Stage 2",
        start_time=datetime.utcnow() + timedelta(days=2),
        end_time=datetime.utcnow() + timedelta(days=5),
    )
    db_session.add_all([stage1, stage2])
    db_session.flush()

    task1 = Task(
        challenge_id=ch.id,
        stage_id=stage1.id,
        title="Task A",
        base_docker_image="python:3.10-slim",
        time_limit_sec=300,
        ram_limit_mb=512,
    )
    task2 = Task(
        challenge_id=ch.id,
        title="Task B (no stage)",
        base_docker_image="python:3.11-slim",
        time_limit_sec=600,
        ram_limit_mb=1024,
    )
    db_session.add_all([task1, task2])
    db_session.flush()
    return ch


# ═══════════════════════════════════════════════════════════════════════════
# Export challenge (GET /api/challenges/<id>/export)
# ═══════════════════════════════════════════════════════════════════════════


class TestExportChallenge:
    """GET /api/challenges/<id>/export"""

    def test_export_challenge_as_admin(
        self, client, auth_headers, tokens, challenge_with_stages_and_tasks
    ):
        ch = challenge_with_stages_and_tasks
        res = client.get(
            f"/api/challenges/{ch.id}/export",
            headers=auth_headers(tokens.admin),
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["title"] == ch.title
        assert data["description"] == ch.description
        assert "tasks" in data
        assert "stages" in data
        assert len(data["tasks"]) == 2
        assert len(data["stages"]) == 2

    def test_export_challenge_as_jury(
        self, client, db_session, auth_headers, challenge_with_stages_and_tasks, create_user
    ):
        ch = challenge_with_stages_and_tasks
        jury = create_user(username="jury_export", role="jury")
        from auth_utils import generate_token

        jury_token = generate_token(jury.id, jury.role)
        res = client.get(
            f"/api/challenges/{ch.id}/export",
            headers=auth_headers(jury_token),
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["title"] == ch.title

    def test_export_challenge_competitor_forbidden(
        self, client, auth_headers, tokens, sample_challenge
    ):
        res = client.get(
            f"/api/challenges/{sample_challenge.id}/export",
            headers=auth_headers(tokens.competitor),
        )
        assert res.status_code == 403
        assert "role" in res.get_json()["error"].lower()

    def test_export_challenge_not_found(self, client, auth_headers, tokens):
        res = client.get(
            "/api/challenges/99999/export",
            headers=auth_headers(tokens.admin),
        )
        assert res.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# Import challenge (POST /api/challenges/import)
# ═══════════════════════════════════════════════════════════════════════════


class TestImportChallenge:
    """POST /api/challenges/import"""

    EXPORT_PAYLOAD = {
        "title": "Imported Challenge",
        "description": "Created via import",
        "max_eval_requests": 20,
        "ram_limit_mb": 4096,
        "time_limit_sec": 300,
        "gpu_required": False,
        "double_blind": True,
        "timezone": "UTC",
        "start_time": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
        "end_time": (datetime.utcnow() + timedelta(hours=24)).isoformat(),
        "stages": [
            {
                "id": 100,
                "stage_number": 1,
                "title": "Preliminary",
                "start_time": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
                "end_time": (datetime.utcnow() + timedelta(hours=12)).isoformat(),
            }
        ],
        "tasks": [
            {
                "stage_id": 100,
                "title": "Task 1",
                "description": "First task",
                "base_docker_image": "python:3.10-slim",
                "time_limit_sec": 300,
                "ram_limit_mb": 512,
                "max_submissions_per_period": 10,
                "submission_period_hours": 24,
            }
        ],
    }

    def _import_json(self, client, headers, payload=None):
        if payload is None:
            payload = self.EXPORT_PAYLOAD
        return client.post(
            "/api/challenges/import",
            data=json.dumps(payload),
            content_type="application/json",
            headers=headers,
        )

    def test_import_challenge_success_json(self, client, csrf_headers, tokens):
        headers = csrf_headers(tokens.admin)
        res = self._import_json(client, headers)
        assert res.status_code == 201
        data = res.get_json()
        assert data["title"] == "Imported Challenge"
        assert data["description"] == "Created via import"
        assert data["max_eval_requests"] == 20
        assert data["ram_limit_mb"] == 4096

    def test_import_challenge_success_file_upload(self, client, csrf_headers, tokens):
        payload_bytes = json.dumps(self.EXPORT_PAYLOAD).encode("utf-8")
        res = client.post(
            "/api/challenges/import",
            headers={
                "Authorization": f"Bearer {tokens.admin}",
                "X-CSRF-Token": "test-csrf-token",
                "Cookie": "csrf_token=test-csrf-token",
            },
            data={"file": (io.BytesIO(payload_bytes), "challenge.json")},
        )
        assert res.status_code == 201
        data = res.get_json()
        assert data["title"] == "Imported Challenge"

    def test_import_challenge_stages_and_tasks_created(
        self, client, csrf_headers, tokens, db_session
    ):
        headers = csrf_headers(tokens.admin)
        res = self._import_json(client, headers)
        assert res.status_code == 201
        ch_id = res.get_json()["id"]

        ch = db_session.get(Challenge, ch_id)
        assert ch is not None
        assert len(ch.tasks) == 1
        assert ch.tasks[0].title == "Task 1"
        assert len(ch.stages) == 1
        assert ch.stages[0].title == "Preliminary"

    def test_import_challenge_missing_title(self, client, csrf_headers, tokens):
        payload = dict(self.EXPORT_PAYLOAD)
        payload.pop("title")
        headers = csrf_headers(tokens.admin)
        res = self._import_json(client, headers, payload)
        assert res.status_code == 400
        assert "title" in res.get_json()["error"].lower()

    def test_import_challenge_invalid_json(self, client, csrf_headers, tokens):
        headers = csrf_headers(tokens.admin)
        res = client.post(
            "/api/challenges/import",
            data=b"not valid json",
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 400
        assert "invalid json" in res.get_json()["error"].lower()

    def test_import_challenge_not_a_dict(self, client, csrf_headers, tokens):
        headers = csrf_headers(tokens.admin)
        res = client.post(
            "/api/challenges/import",
            data=json.dumps(["not", "a", "dict"]),
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 400
        assert "object" in res.get_json()["error"].lower()

    def test_import_challenge_no_data(self, client, csrf_headers, tokens):
        headers = csrf_headers(tokens.admin)
        res = client.post(
            "/api/challenges/import",
            data=b"",
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 400
        assert "no data" in res.get_json()["error"].lower()

    def test_import_challenge_no_file_in_form(self, client, csrf_headers, tokens):
        headers = {
            "Authorization": f"Bearer {tokens.admin}",
            "X-CSRF-Token": "test-csrf-token",
            "Cookie": "csrf_token=test-csrf-token",
        }
        res = client.post(
            "/api/challenges/import",
            headers=headers,
            data={"wrong_field": (io.BytesIO(b"{}"), "challenge.json")},
        )
        assert res.status_code == 400
        assert "no file" in res.get_json()["error"].lower()

    def test_import_challenge_wrong_extension(self, client, csrf_headers, tokens):
        headers = {
            "Authorization": f"Bearer {tokens.admin}",
            "X-CSRF-Token": "test-csrf-token",
            "Cookie": "csrf_token=test-csrf-token",
        }
        res = client.post(
            "/api/challenges/import",
            headers=headers,
            data={"file": (io.BytesIO(b"{}"), "data.csv")},
        )
        assert res.status_code == 400
        assert "extension" in res.get_json()["error"].lower()

    def test_import_challenge_competitor_forbidden(self, client, csrf_headers, tokens):
        headers = csrf_headers(tokens.competitor)
        res = self._import_json(client, headers)
        assert res.status_code == 403
        assert "role" in res.get_json()["error"].lower()

    def test_import_challenge_jury_forbidden(
        self, client, db_session, csrf_headers, challenge_with_stages_and_tasks, create_user
    ):
        ch = challenge_with_stages_and_tasks
        jury = create_user(username="jury_noimport", role="jury")
        from auth_utils import generate_token

        jury_token = generate_token(jury.id, jury.role)
        headers = {
            "Authorization": f"Bearer {jury_token}",
            "X-CSRF-Token": "test-csrf-token",
            "Cookie": "csrf_token=test-csrf-token",
        }
        res = client.post(
            "/api/challenges/import",
            data=json.dumps(self.EXPORT_PAYLOAD),
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 403
        assert "role" in res.get_json()["error"].lower()


# ═══════════════════════════════════════════════════════════════════════════
# Export results CSV (GET /api/challenges/<id>/export-results)
# ═══════════════════════════════════════════════════════════════════════════


class TestExportResultsCsv:
    """GET /api/challenges/<id>/export-results"""

    def test_export_results_as_admin(
        self, client, auth_headers, tokens, challenge_with_stages_and_tasks
    ):
        ch = challenge_with_stages_and_tasks
        res = client.get(
            f"/api/challenges/{ch.id}/export-results",
            headers=auth_headers(tokens.admin),
        )
        assert res.status_code == 200
        assert res.mimetype == "text/csv"
        assert "Rank,Username,Alias ID" in res.data.decode("utf-8")

    def test_export_results_as_jury(
        self, client, db_session, auth_headers, challenge_with_stages_and_tasks, create_user
    ):
        ch = challenge_with_stages_and_tasks
        jury = create_user(username="jury_export_csv", role="jury")
        from auth_utils import generate_token

        jury_token = generate_token(jury.id, jury.role)
        res = client.get(
            f"/api/challenges/{ch.id}/export-results",
            headers=auth_headers(jury_token),
        )
        assert res.status_code == 200
        assert res.mimetype == "text/csv"

    def test_export_results_competitor_forbidden(
        self, client, auth_headers, tokens, sample_challenge
    ):
        res = client.get(
            f"/api/challenges/{sample_challenge.id}/export-results",
            headers=auth_headers(tokens.competitor),
        )
        assert res.status_code == 403
        assert "role" in res.get_json()["error"].lower()

    def test_export_results_not_found(self, client, auth_headers, tokens):
        res = client.get(
            "/api/challenges/99999/export-results",
            headers=auth_headers(tokens.admin),
        )
        assert res.status_code == 404

    def test_export_results_includes_audit_section(
        self, client, auth_headers, tokens, challenge_with_stages_and_tasks
    ):
        ch = challenge_with_stages_and_tasks
        res = client.get(
            f"/api/challenges/{ch.id}/export-results",
            headers=auth_headers(tokens.admin),
        )
        csv_text = res.data.decode("utf-8")
        assert "SCORE CORRECTION AUDIT LOG" in csv_text


# ═══════════════════════════════════════════════════════════════════════════
# Import competitors CSV (POST /api/admin/import-competitors-csv)
# ═══════════════════════════════════════════════════════════════════════════


class TestImportCompetitorsCsv:
    """POST /api/admin/import-competitors-csv"""

    VALID_CSV = (
        "name,surname,grade,school,city\n"
        "Alice,Smith,10,High School A,New York\n"
        "Bob,Jones,11,High School B,Los Angeles\n"
    )

    def _upload_csv(self, client, challenge_id, token, csv_data=None, filename="competitors.csv"):
        if csv_data is None:
            csv_data = self.VALID_CSV
        return client.post(
            f"/api/admin/import-competitors-csv?challenge_id={challenge_id}",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (io.BytesIO(csv_data.encode("utf-8")), filename)},
        )

    def test_import_competitors_success(self, client, tokens, sample_challenge):
        res = self._upload_csv(client, sample_challenge.id, tokens.admin)
        assert res.status_code == 201
        data = res.get_json()
        assert data["message"].startswith("Successfully imported")
        assert len(data["competitors"]) == 2
        assert data["competitors"][0]["name"] == "Alice"
        assert data["competitors"][1]["name"] == "Bob"

    def test_import_competitors_as_jury(
        self, client, db_session, sample_future_challenge, create_user
    ):
        jury = create_user(username="jury_csv", role="jury")
        from auth_utils import generate_token

        jury_token = generate_token(jury.id, jury.role)
        res = self._upload_csv(client, sample_future_challenge.id, jury_token)
        assert res.status_code == 201
        assert len(res.get_json()["competitors"]) == 2

    def test_import_competitors_creates_users_in_db(
        self, client, tokens, sample_challenge, db_session
    ):
        res = self._upload_csv(client, sample_challenge.id, tokens.admin)
        assert res.status_code == 201

        imported = res.get_json()["competitors"]
        assert len(imported) == 2
        for comp in imported:
            user = User.query.filter_by(username=comp["generated_username"]).first()
            assert user is not None
            assert user.challenge_id == sample_challenge.id

    def test_import_competitors_no_challenge_id(self, client, tokens):
        res = client.post(
            "/api/admin/import-competitors-csv",
            headers={"Authorization": f"Bearer {tokens.admin}"},
            data={"file": (io.BytesIO(self.VALID_CSV.encode("utf-8")), "competitors.csv")},
        )
        assert res.status_code == 400
        assert "challenge_id" in res.get_json()["error"].lower()

    def test_import_competitors_invalid_challenge(self, client, tokens):
        res = self._upload_csv(client, 99999, tokens.admin)
        assert res.status_code == 400
        assert "invalid challenge_id" in res.get_json()["error"].lower()

    def test_import_competitors_no_file(self, client, tokens, sample_challenge):
        res = client.post(
            f"/api/admin/import-competitors-csv?challenge_id={sample_challenge.id}",
            headers={"Authorization": f"Bearer {tokens.admin}"},
        )
        assert res.status_code == 400
        assert "no file" in res.get_json()["error"].lower()

    def test_import_competitors_wrong_extension(self, client, tokens, sample_challenge):
        res = client.post(
            f"/api/admin/import-competitors-csv?challenge_id={sample_challenge.id}",
            headers={"Authorization": f"Bearer {tokens.admin}"},
            data={"file": (io.BytesIO(b"a,b\n1,2"), "data.json")},
        )
        assert res.status_code == 400
        assert "extension" in res.get_json()["error"].lower()

    def test_import_competitors_invalid_csv(self, client, tokens, sample_challenge):
        res = client.post(
            f"/api/admin/import-competitors-csv?challenge_id={sample_challenge.id}",
            headers={"Authorization": f"Bearer {tokens.admin}"},
            data={"file": (io.BytesIO(b"\xff\xfe\x00\x01"), "competitors.csv")},
        )
        assert res.status_code == 400

    def test_import_competitors_missing_columns(self, client, tokens, sample_challenge):
        csv_data = "name,grade\nAlice,10\n"
        res = self._upload_csv(client, sample_challenge.id, tokens.admin, csv_data)
        assert res.status_code == 400
        assert "column" in res.get_json()["error"].lower()

    def test_import_competitors_competitor_forbidden(self, client, tokens, sample_challenge):
        res = self._upload_csv(client, sample_challenge.id, tokens.competitor)
        assert res.status_code == 403
        assert "role" in res.get_json()["error"].lower()

    def test_import_competitors_skips_empty_rows(self, client, tokens, sample_challenge):
        csv_data = "name,surname\n" "Alice,Smith\n" ",\n" "Bob,Jones\n"
        res = self._upload_csv(client, sample_challenge.id, tokens.admin, csv_data)
        assert res.status_code == 201
        assert len(res.get_json()["competitors"]) == 2

    def test_import_competitors_with_anonymity_flag(
        self, client, tokens, sample_challenge, db_session
    ):
        csv_data = "name,surname,is_anonymous\n" "Alice,Smith,1\n" "Bob,Jones,0\n"
        res = self._upload_csv(client, sample_challenge.id, tokens.admin, csv_data)
        assert res.status_code == 201
        data = res.get_json()
        assert len(data["competitors"]) == 2

        alice = User.query.filter_by(username=data["competitors"][0]["generated_username"]).first()
        assert alice is not None
        assert alice.is_anonymous is True

        bob = User.query.filter_by(username=data["competitors"][1]["generated_username"]).first()
        assert bob is not None
        assert bob.is_anonymous is False
