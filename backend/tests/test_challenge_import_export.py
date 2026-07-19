"""Tests for challenge import/export routes.

Covers:
  - GET  /api/challenges/<id>/export          JSON export (admin/jury)
  - POST /api/challenges/import               JSON import (admin only)
  - GET  /api/challenges/<id>/export-results   CSV export (admin/jury)
  - POST /api/admin/import-competitors-csv     CSV competitor import
"""

import io
import json
from datetime import timedelta

import pytest

from models import Challenge, Stage, Task, User
from utils.dates import utcnow

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
        start_time=utcnow() - timedelta(days=1),
        end_time=utcnow() + timedelta(days=1),
    )
    stage2 = Stage(
        challenge_id=ch.id,
        stage_number=2,
        title="Stage 2",
        start_time=utcnow() + timedelta(days=2),
        end_time=utcnow() + timedelta(days=5),
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
        import io
        import zipfile

        ch = challenge_with_stages_and_tasks
        res = client.get(
            f"/api/challenges/{ch.id}/export",
            headers=auth_headers(tokens.admin),
        )
        assert res.status_code == 200
        assert res.headers["Content-Type"] == "application/zip"

        zip_buf = io.BytesIO(res.data)
        with zipfile.ZipFile(zip_buf, "r") as zf:
            assert "challenge.json" in zf.namelist()
            challenge_json = zf.read("challenge.json").decode("utf-8")
            data = json.loads(challenge_json)

            assert data["title"] == ch.title
            assert data["description"] == ch.description
            assert "tasks" in data
            assert "stages" in data
            assert len(data["tasks"]) == 2
            assert len(data["stages"]) == 2

    def test_export_challenge_as_jury(
        self,
        client,
        db_session,
        auth_headers,
        challenge_with_stages_and_tasks,
        create_user,
    ):
        import io
        import zipfile

        ch = challenge_with_stages_and_tasks
        jury = create_user(username="jury_export", role="jury")
        from auth_utils import generate_token

        jury_token = generate_token(jury.id, jury.role)
        res = client.get(
            f"/api/challenges/{ch.id}/export",
            headers=auth_headers(jury_token),
        )
        assert res.status_code == 200
        assert res.headers["Content-Type"] == "application/zip"

        zip_buf = io.BytesIO(res.data)
        with zipfile.ZipFile(zip_buf, "r") as zf:
            assert "challenge.json" in zf.namelist()
            challenge_json = zf.read("challenge.json").decode("utf-8")
            data = json.loads(challenge_json)
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

    EXPORT_PAYLOAD = {  # noqa: RUF012
        "title": "Imported Challenge",
        "description": "Created via import",
        "max_eval_requests": 20,
        "ram_limit_mb": 4096,
        "time_limit_sec": 300,
        "gpu_required": False,
        "double_blind": True,
        "timezone": "UTC",
        "start_time": (utcnow() + timedelta(hours=1)).isoformat(),
        "end_time": (utcnow() + timedelta(hours=24)).isoformat(),
        "stages": [
            {
                "id": 100,
                "stage_number": 1,
                "title": "Preliminary",
                "start_time": (utcnow() + timedelta(hours=1)).isoformat(),
                "end_time": (utcnow() + timedelta(hours=12)).isoformat(),
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

    def _import_zip(self, client, headers, payload=None, filename="challenge.zip"):
        import io
        import zipfile

        if payload is None:
            payload = self.EXPORT_PAYLOAD

        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("challenge.json", json.dumps(payload))
        zip_buf.seek(0)

        return client.post(
            "/api/challenges/import",
            headers=headers,
            data={"file": (zip_buf, filename)},
        )

    def test_import_challenge_success_zip(self, client, tokens):
        headers = {
            "Authorization": f"Bearer {tokens.admin}",
            "X-CSRF-Token": "test-csrf-token",
            "Cookie": "csrf_token=test-csrf-token",
        }
        res = self._import_zip(client, headers)
        assert res.status_code == 201
        data = res.get_json()
        assert data["title"] == "Imported Challenge"
        assert data["description"] == "Created via import"
        assert data["max_eval_requests"] == 20
        assert data["ram_limit_mb"] == 4096

    def test_import_challenge_success_file_upload(self, client, tokens):
        headers = {
            "Authorization": f"Bearer {tokens.admin}",
            "X-CSRF-Token": "test-csrf-token",
            "Cookie": "csrf_token=test-csrf-token",
        }
        res = self._import_zip(client, headers)
        assert res.status_code == 201
        data = res.get_json()
        assert data["title"] == "Imported Challenge"

    def test_import_challenge_stages_and_tasks_created(self, client, tokens, db_session):
        headers = {
            "Authorization": f"Bearer {tokens.admin}",
            "X-CSRF-Token": "test-csrf-token",
            "Cookie": "csrf_token=test-csrf-token",
        }
        res = self._import_zip(client, headers)
        assert res.status_code == 201
        ch_id = res.get_json()["id"]

        ch = db_session.get(Challenge, ch_id)
        assert ch is not None
        assert len(ch.tasks) == 1
        assert ch.tasks[0].title == "Task 1"
        assert len(ch.stages) == 1
        assert ch.stages[0].title == "Preliminary"

    def test_import_challenge_missing_title(self, client, tokens):
        payload = dict(self.EXPORT_PAYLOAD)
        payload.pop("title")
        headers = {
            "Authorization": f"Bearer {tokens.admin}",
            "X-CSRF-Token": "test-csrf-token",
            "Cookie": "csrf_token=test-csrf-token",
        }
        res = self._import_zip(client, headers, payload)
        assert res.status_code == 400
        assert "title" in res.get_json()["error"].lower()

    def test_import_challenge_invalid_json(self, client, tokens):
        import io
        import zipfile

        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("challenge.json", b"not valid json")
        zip_buf.seek(0)
        headers = {
            "Authorization": f"Bearer {tokens.admin}",
            "X-CSRF-Token": "test-csrf-token",
            "Cookie": "csrf_token=test-csrf-token",
        }
        res = client.post(
            "/api/challenges/import",
            headers=headers,
            data={"file": (zip_buf, "challenge.zip")},
        )
        assert res.status_code == 400
        assert (
            "invalid" in res.get_json()["error"].lower()
            or "corrupt" in res.get_json()["error"].lower()
        )

    def test_import_challenge_not_a_dict(self, client, tokens):
        import io
        import zipfile

        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("challenge.json", json.dumps(["not", "a", "dict"]))
        zip_buf.seek(0)
        headers = {
            "Authorization": f"Bearer {tokens.admin}",
            "X-CSRF-Token": "test-csrf-token",
            "Cookie": "csrf_token=test-csrf-token",
        }
        res = client.post(
            "/api/challenges/import",
            headers=headers,
            data={"file": (zip_buf, "challenge.zip")},
        )
        assert res.status_code == 400
        assert "object" in res.get_json()["error"].lower()

    def test_import_challenge_no_data(self, client, tokens):
        headers = {
            "Authorization": f"Bearer {tokens.admin}",
            "X-CSRF-Token": "test-csrf-token",
            "Cookie": "csrf_token=test-csrf-token",
        }
        res = client.post(
            "/api/challenges/import",
            data=b"",
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 400
        assert "multipart" in res.get_json()["error"].lower()

    def test_import_challenge_no_file_in_form(self, client, tokens):
        headers = {
            "Authorization": f"Bearer {tokens.admin}",
            "X-CSRF-Token": "test-csrf-token",
            "Cookie": "csrf_token=test-csrf-token",
        }
        res = client.post(
            "/api/challenges/import",
            headers=headers,
            data={"wrong_field": (io.BytesIO(b"{}"), "challenge.zip")},
        )
        assert res.status_code == 400
        assert "no file" in res.get_json()["error"].lower()

    def test_import_challenge_wrong_extension(self, client, tokens):
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

    def test_import_challenge_competitor_forbidden(self, client, tokens):
        headers = {
            "Authorization": f"Bearer {tokens.competitor}",
            "X-CSRF-Token": "test-csrf-token",
            "Cookie": "csrf_token=test-csrf-token",
        }
        res = self._import_zip(client, headers)
        assert res.status_code == 403
        assert "role" in res.get_json()["error"].lower()

    def test_import_challenge_jury_forbidden(
        self, client, db_session, challenge_with_stages_and_tasks, create_user
    ):
        jury = create_user(username="jury_noimport", role="jury")
        from auth_utils import generate_token

        jury_token = generate_token(jury.id, jury.role)
        headers = {
            "Authorization": f"Bearer {jury_token}",
            "X-CSRF-Token": "test-csrf-token",
            "Cookie": "csrf_token=test-csrf-token",
        }
        res = self._import_zip(client, headers, self.EXPORT_PAYLOAD)
        assert res.status_code == 403
        assert "role" in res.get_json()["error"].lower()

    def test_import_challenge_with_zip_files(self, client, db_session, tokens):
        import io
        import os
        import zipfile

        from flask import current_app

        from models import Challenge

        zip_buf = io.BytesIO()
        old_task_uuid = "019efa69-ec26-718d-9fbc-d05408b246f3"
        manifest = {
            "title": "ZIP Import Challenge",
            "description": "ZIP description",
            "max_eval_requests": 15,
            "ram_limit_mb": 2048,
            "time_limit_sec": 120,
            "gpu_required": False,
            "timezone": "UTC",
            "stages": [],
            "tasks": [
                {
                    "id": old_task_uuid,
                    "title": "ZIP Task 1",
                    "description": "ZIP Task 1 description",
                    "files": [
                        {
                            "filename": "labels.parquet",
                            "saved_name": "labels.parquet",
                            "size_bytes": 12,
                        }
                    ],
                    "evaluator_script_path": f"/some/old/path/task_{old_task_uuid}/evaluator.py",
                    "baseline_notebook_path": (
                        f"/some/old/path/task_{old_task_uuid}/baseline_test.ipynb"
                    ),
                }
            ],
        }

        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("challenge.json", json.dumps(manifest))
            eval_py = (
                b'METRIC_NAME = "import_metric"\n'
                b'SUBMISSION_COLUMNS = [{"name": "id", "type": "string"}]\n'
                b'LABELS_COLUMNS = [{"name": "id", "type": "string"}]\n'
                b'print("evaluator")\n'
            )
            zf.writestr(f"tasks/{old_task_uuid}/evaluator.py", eval_py)
            zf.writestr(f"tasks/{old_task_uuid}/baseline_test.ipynb", b"print('notebook')")
            zf.writestr(f"tasks/{old_task_uuid}/labels.parquet", b"labels_content")

        zip_buf.seek(0)

        headers = {
            "Authorization": f"Bearer {tokens.admin}",
            "X-CSRF-Token": "test-csrf-token",
            "Cookie": "csrf_token=test-csrf-token",
        }
        res = client.post(
            "/api/challenges/import",
            headers=headers,
            data={"file": (zip_buf, "challenge.zip")},
        )
        assert res.status_code == 201
        res_data = res.get_json()
        new_ch_id = res_data["id"]

        ch = db_session.get(Challenge, new_ch_id)
        assert ch is not None
        assert len(ch.tasks) == 1
        new_task = ch.tasks[0]
        assert new_task.title == "ZIP Task 1"

        upload_folder = current_app.config.get("UPLOAD_FOLDER")
        new_task_dir = os.path.join(upload_folder, f"task_{new_task.id}")
        assert os.path.isdir(new_task_dir)

        evaluator_local = os.path.join(new_task_dir, "evaluator.py")
        baseline_local = os.path.join(new_task_dir, "baseline_test.ipynb")
        labels_local = os.path.join(new_task_dir, "labels.parquet")

        assert os.path.isfile(evaluator_local)
        assert os.path.isfile(baseline_local)
        assert os.path.isfile(labels_local)

        with open(evaluator_local, "rb") as f:
            assert b"METRIC_NAME" in f.read()

        with open(baseline_local, "rb") as f:
            assert f.read() == b"print('notebook')"

        with open(labels_local, "rb") as f:
            assert f.read() == b"labels_content"

        assert new_task.evaluator_script_path == evaluator_local
        assert new_task.evaluator_metric_name == "import_metric"
        assert new_task.baseline_notebook_path == baseline_local


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
        self,
        client,
        db_session,
        auth_headers,
        challenge_with_stages_and_tasks,
        create_user,
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
        "name,surname,middle_name,birth_date,grade,school,city\n"
        "Alice,Smith,Marie,2008-05-14,10,High School A,New York\n"
        "Bob,Jones,Robert,2007-09-22,11,High School B,Los Angeles\n"
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
        csv_data = (
            "name,surname,middle_name,birth_date,grade,school,city\n"
            "Alice,Smith,Marie,2008-05-14,10,School A,City A\n"
            ",,,,,,\n"
            "Bob,Jones,Robert,2007-09-22,11,School B,City B\n"
        )
        res = self._upload_csv(client, sample_challenge.id, tokens.admin, csv_data)
        assert res.status_code == 201
        assert len(res.get_json()["competitors"]) == 2

    def test_import_competitors_skips_duplicates(self, client, tokens, sample_challenge):
        csv_data1 = (
            "name,surname,middle_name,birth_date,grade,school,city\n"
            "Alice,Smith,Marie,2008-05-14,10,School A,City A\n"
        )
        res1 = self._upload_csv(client, sample_challenge.id, tokens.admin, csv_data1)
        assert res1.status_code == 201
        assert len(res1.get_json()["competitors"]) == 1

        csv_data2 = (
            "name,surname,middle_name,birth_date,grade,school,city\n"
            "Alice,Smith,Marie,2008-05-14,10,School A,City A\n"
            "Bob,Jones,Robert,2007-09-22,11,School B,City B\n"
        )
        res2 = self._upload_csv(client, sample_challenge.id, tokens.admin, csv_data2)
        assert res2.status_code == 201
        assert len(res2.get_json()["competitors"]) == 1
        assert res2.get_json()["competitors"][0]["name"] == "Bob"

    def test_import_competitors_with_anonymity_flag(
        self, client, tokens, sample_challenge, db_session
    ):
        csv_data = (
            "name,surname,middle_name,birth_date,grade,school,city,is_anonymous\n"
            "Alice,Smith,Marie,2008-05-14,10,School A,City A,1\n"
            "Bob,Jones,Robert,2007-09-22,11,School B,City B,0\n"
        )
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

    def test_import_competitors_anonymity_defaults(
        self, client, tokens, sample_challenge, db_session
    ):
        # 1. Test no column for anonymity (neither "anonymous" nor "is_anonymous")
        csv_data_no_col = (
            "name,surname,middle_name,birth_date,grade,school,city\n"
            "Charlie,Brown,C,2008-03-03,10,School A,City A\n"
        )
        res = self._upload_csv(client, sample_challenge.id, tokens.admin, csv_data_no_col)
        assert res.status_code == 201
        data = res.get_json()
        charlie = User.query.filter_by(
            username=data["competitors"][0]["generated_username"]
        ).first()
        assert charlie is not None
        assert charlie.is_anonymous is False

        # 2. Test columns exist but values are empty, spaces, or missing
        csv_data_empty_val = (
            "name,surname,middle_name,birth_date,grade,school,city,anonymous,is_anonymous\n"
            "Dave,Miller,D,2007-04-04,10,School A,City A,,\n"
            "Eve,Wilson,E,2008-05-05,11,School B,City B,  ,  \n"
        )
        res = self._upload_csv(client, sample_challenge.id, tokens.admin, csv_data_empty_val)
        assert res.status_code == 201
        data = res.get_json()
        assert len(data["competitors"]) == 2

        dave = User.query.filter_by(username=data["competitors"][0]["generated_username"]).first()
        assert dave is not None
        assert dave.is_anonymous is False

        eve = User.query.filter_by(username=data["competitors"][1]["generated_username"]).first()
        assert eve is not None
        assert eve.is_anonymous is False
