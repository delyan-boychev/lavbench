import os
import sys
import json
import io
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from models import db, User, Challenge, Task, Submission, Stage
from auth_utils import generate_token


class TestSelectFinalSubmission:

    @pytest.fixture(autouse=True)
    def setup(self, db_session, client, auth_headers, csrf_headers, redis_flush):
        self.client = client
        self._auth = auth_headers
        self.csrf_headers = csrf_headers
        self.seed_basic_data()

    def seed_basic_data(self):
        self.challenge = Challenge(
            title="Final Sel Test",
            description="Test",
            max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=48),
            end_time=datetime.utcnow() + timedelta(hours=48),
            is_frozen=False,
            scores_finalized=False,
        )
        db.session.add(self.challenge)
        db.session.flush()

        self.task = Task(
            title="T1",
            challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
            metrics_config='{"accuracy": {"weight": 1.0}}',
        )
        db.session.add(self.task)

        self.admin = User(username="admin", password_hash="x", role="admin", alias_id="A1")
        db.session.add(self.admin)

        self.competitor = User(
            username="comp1",
            password_hash="x",
            role="competitor",
            alias_id="C1",
            challenge_id=self.challenge.id,
        )
        db.session.add(self.competitor)

        self.other_comp = User(
            username="comp2",
            password_hash="x",
            role="competitor",
            alias_id="C2",
            challenge_id=self.challenge.id,
        )
        db.session.add(self.other_comp)
        db.session.flush()

        self.stage = Stage(
            title="Stage 1",
            challenge_id=self.challenge.id,
            stage_number=1,
            start_time=datetime.utcnow() - timedelta(hours=24),
            end_time=datetime.utcnow() + timedelta(hours=24),
        )
        db.session.add(self.stage)
        db.session.commit()

        self.task.stage_id = self.stage.id
        db.session.commit()

        self.submission = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
            code_cells="[]",
            created_at=datetime.utcnow() - timedelta(hours=12),
            executed_at=datetime.utcnow() - timedelta(hours=11),
        )
        db.session.add(self.submission)
        db.session.commit()

        self.admin_token = generate_token(self.admin.id, role="admin")
        self.comp_token = generate_token(self.competitor.id, role="competitor")
        self.other_token = generate_token(self.other_comp.id, role="competitor")

    def test_admin_can_select_any_submission(self):
        resp = self.client.post(
            f"/api/submissions/{self.submission.id}/select-final",
            headers=self._auth(self.admin_token),
        )
        assert resp.status_code == 200

    def test_competitor_can_select_own_submission(self):
        resp = self.client.post(
            f"/api/submissions/{self.submission.id}/select-final",
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 200

    def test_competitor_cannot_select_others_submission(self):
        resp = self.client.post(
            f"/api/submissions/{self.submission.id}/select-final",
            headers=self._auth(self.other_token),
        )
        assert resp.status_code == 403
        data = resp.get_json()
        assert data.get("code") == "ERR_NOT_OWNER"

    def test_returns_404_for_missing_submission(self):
        resp = self.client.post(
            "/api/submissions/99999/select-final", headers=self._auth(self.admin_token)
        )
        assert resp.status_code == 404

    def test_select_sets_is_final_selection_true(self):
        self.client.post(
            f"/api/submissions/{self.submission.id}/select-final",
            headers=self._auth(self.comp_token),
        )
        updated = db.session.get(Submission, self.submission.id)
        assert updated.is_final_selection

    def test_select_clears_other_final_selections(self):
        sub2 = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
            code_cells="[]",
            created_at=datetime.utcnow() - timedelta(hours=10),
            is_final_selection=True,
        )
        db.session.add(sub2)
        db.session.commit()
        self.client.post(
            f"/api/submissions/{self.submission.id}/select-final",
            headers=self._auth(self.comp_token),
        )
        updated = db.session.get(Submission, sub2.id)
        assert updated.is_final_selection is False

    def test_blocked_when_scores_finalized(self):
        self.challenge.scores_finalized = True
        db.session.commit()
        resp = self.client.post(
            f"/api/submissions/{self.submission.id}/select-final",
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 403
        data = resp.get_json()
        assert data.get("code") == "ERR_COMPETITION_FINALIZED"

    def test_admin_bypasses_scores_finalized(self):
        self.challenge.scores_finalized = True
        db.session.commit()
        resp = self.client.post(
            f"/api/submissions/{self.submission.id}/select-final",
            headers=self._auth(self.admin_token),
        )
        assert resp.status_code == 200

    def test_submission_after_stage_deadline_blocked(self):
        self.submission.created_at = self.stage.end_time + timedelta(hours=1)
        db.session.commit()
        resp = self.client.post(
            f"/api/submissions/{self.submission.id}/select-final",
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data.get("code") == "ERR_SUBMISSION_LATE"

    def test_selection_window_closed(self):
        closed_stage = Stage(
            title="Closed",
            challenge_id=self.challenge.id,
            stage_number=2,
            start_time=datetime.utcnow() - timedelta(hours=48),
            end_time=datetime.utcnow() - timedelta(hours=2),
        )
        db.session.add(closed_stage)
        db.session.commit()
        self.task.stage_id = closed_stage.id
        db.session.commit()
        late_sub = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
            code_cells="[]",
            created_at=closed_stage.end_time - timedelta(hours=1),
            executed_at=closed_stage.end_time - timedelta(minutes=30),
        )
        db.session.add(late_sub)
        db.session.commit()
        resp = self.client.post(
            f"/api/submissions/{late_sub.id}/select-final", headers=self._auth(self.comp_token)
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data.get("code") == "ERR_SELECTION_WINDOW_CLOSED"

    def test_selection_window_open_within_grace_period(self):
        recent_stage = Stage(
            title="Recent",
            challenge_id=self.challenge.id,
            stage_number=2,
            start_time=datetime.utcnow() - timedelta(hours=48),
            end_time=datetime.utcnow() - timedelta(minutes=2),
        )
        db.session.add(recent_stage)
        db.session.commit()
        self.task.stage_id = recent_stage.id
        self.submission.created_at = recent_stage.end_time - timedelta(hours=1)
        self.submission.executed_at = recent_stage.end_time - timedelta(minutes=30)
        db.session.commit()
        resp = self.client.post(
            f"/api/submissions/{self.submission.id}/select-final",
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 200

    def test_sliding_window_extended_by_other_submissions(self):
        slide_stage = Stage(
            title="Slide",
            challenge_id=self.challenge.id,
            stage_number=2,
            start_time=datetime.utcnow() - timedelta(hours=48),
            end_time=datetime.utcnow() - timedelta(minutes=5),
        )
        db.session.add(slide_stage)
        db.session.commit()
        self.task.stage_id = slide_stage.id
        late_exec = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
            code_cells="[]",
            created_at=slide_stage.end_time - timedelta(seconds=10),
            executed_at=datetime.utcnow() - timedelta(seconds=60),
        )
        db.session.add(late_exec)
        self.submission.created_at = slide_stage.end_time - timedelta(hours=1)
        self.submission.executed_at = slide_stage.end_time - timedelta(minutes=30)
        db.session.commit()
        resp = self.client.post(
            f"/api/submissions/{self.submission.id}/select-final",
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 200


class TestParseNotebook:

    @pytest.fixture(autouse=True)
    def setup(self, db_session, client, auth_headers, csrf_headers, redis_flush):
        self.client = client
        self._auth = auth_headers
        self.csrf_headers = csrf_headers
        self.seed_basic_data()

    def seed_basic_data(self):
        self.challenge = Challenge(
            title="Parse Test",
            description="Test",
            max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=48),
            end_time=datetime.utcnow() + timedelta(hours=48),
            is_frozen=False,
            scores_finalized=False,
            is_active=True,
        )
        db.session.add(self.challenge)
        db.session.flush()

        self.competitor = User(
            username="comp_parse",
            password_hash="x",
            role="competitor",
            alias_id="CP",
            challenge_id=self.challenge.id,
        )
        db.session.add(self.competitor)

        self.admin = User(username="admin_parse", password_hash="x", role="admin", alias_id="AP")
        db.session.add(self.admin)
        db.session.commit()

        self.comp_token = generate_token(self.competitor.id, role="competitor")
        self.admin_token = generate_token(self.admin.id, role="admin")

    def _notebook_content(self):
        return {
            "cells": [
                {"cell_type": "code", "source": ["print('hello')"]},
                {"cell_type": "markdown", "source": ["# Title"]},
            ]
        }

    def test_successful_parse(self):
        nb = self._notebook_content()
        data = {"file": (io.BytesIO(json.dumps(nb).encode()), "test.ipynb")}
        resp = self.client.post(
            f"/api/challenges/{self.challenge.id}/parse-notebook",
            data=data,
            content_type="multipart/form-data",
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert len(body["cells"]) == 2
        assert body["cells"][0]["type"] == "code"
        assert body["cells"][0]["source"] == "print('hello')"
        assert body["filename"] == "test.ipynb"

    def test_no_file_uploaded(self):
        resp = self.client.post(
            f"/api/challenges/{self.challenge.id}/parse-notebook",
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "ERR_NO_FILE_UPLOADED"

    def test_invalid_file_type(self):
        data = {"file": (io.BytesIO(b"content"), "test.txt")}
        resp = self.client.post(
            f"/api/challenges/{self.challenge.id}/parse-notebook",
            data=data,
            content_type="multipart/form-data",
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "ERR_INVALID_FILE_TYPE"

    def test_file_too_large(self):
        data = {"file": (io.BytesIO(b"x" * (5 * 1024 * 1024 + 1)), "test.ipynb")}
        resp = self.client.post(
            f"/api/challenges/{self.challenge.id}/parse-notebook",
            data=data,
            content_type="multipart/form-data",
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 413
        assert resp.get_json()["code"] == "ERR_FILE_TOO_LARGE"

    def test_not_registered_competitor(self):
        other = User(
            username="other_parse",
            password_hash="x",
            role="competitor",
            alias_id="OP",
            challenge_id=999,
        )
        db.session.add(other)
        db.session.commit()
        other_token = generate_token(other.id, role="competitor")
        data = {"file": (io.BytesIO(b"{}"), "test.ipynb")}
        resp = self.client.post(
            f"/api/challenges/{self.challenge.id}/parse-notebook",
            data=data,
            content_type="multipart/form-data",
            headers=self._auth(other_token),
        )
        assert resp.status_code == 403
        assert resp.get_json()["code"] == "ERR_NOT_REGISTERED"

    def test_admin_bypasses_registration_check(self):
        data = {"file": (io.BytesIO(b"{}"), "test.ipynb")}
        resp = self.client.post(
            f"/api/challenges/{self.challenge.id}/parse-notebook",
            data=data,
            content_type="multipart/form-data",
            headers=self._auth(self.admin_token),
        )
        assert resp.status_code == 200
        assert len(resp.get_json()["cells"]) == 0

    def test_invalid_notebook_json(self):
        data = {"file": (io.BytesIO(b"not json"), "test.ipynb")}
        resp = self.client.post(
            f"/api/challenges/{self.challenge.id}/parse-notebook",
            data=data,
            content_type="multipart/form-data",
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "ERR_PARSING_FAILED"


class TestSubmitCode:

    @pytest.fixture(autouse=True)
    def setup(self, db_session, client, auth_headers, csrf_headers, redis_flush, app):
        self.client = client
        self._auth = auth_headers
        self.csrf_headers = csrf_headers
        self.app = app
        self.seed_basic_data()

    def seed_basic_data(self):
        self.challenge = Challenge(
            title="Submit Test",
            description="Test",
            max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=48),
            end_time=datetime.utcnow() + timedelta(hours=48),
            is_frozen=False,
            scores_finalized=False,
            is_active=True,
        )
        db.session.add(self.challenge)
        db.session.flush()

        self.task = Task(
            title="Submit T1",
            challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
            metrics_config='{"accuracy": {"weight": 1.0}}',
        )
        db.session.add(self.task)

        self.competitor = User(
            username="comp_submit",
            password_hash="x",
            role="competitor",
            alias_id="CS",
            challenge_id=self.challenge.id,
        )
        db.session.add(self.competitor)

        self.admin = User(username="admin_submit", password_hash="x", role="admin", alias_id="AS")
        db.session.add(self.admin)
        db.session.commit()

        self.comp_token = generate_token(self.competitor.id, role="competitor")
        self.admin_token = generate_token(self.admin.id, role="admin")

        self.valid_cells = [{"source": "print('hello')", "cell_type": "code"}]

    @patch("tasks.evaluate_submission.apply_async")
    def test_successful_submit(self, mock_apply):
        mock_apply.return_value = None
        resp = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            json={"task_id": self.task.id, "selected_cells": self.valid_cells},
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 202
        body = resp.get_json()
        assert "submission_id" in body
        assert body["status"] == "queued"

    def test_not_registered_competitor(self):
        other = User(
            username="other_submit",
            password_hash="x",
            role="competitor",
            alias_id="OS",
            challenge_id=999,
        )
        db.session.add(other)
        db.session.commit()
        other_token = generate_token(other.id, role="competitor")
        resp = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            json={"task_id": self.task.id, "selected_cells": self.valid_cells},
            headers=self._auth(other_token),
        )
        assert resp.status_code == 403
        assert resp.get_json()["code"] == "ERR_NOT_REGISTERED"

    def test_challenge_inactive(self):
        self.challenge.is_active = False
        db.session.commit()
        resp = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            json={"task_id": self.task.id, "selected_cells": self.valid_cells},
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "ERR_CHALLENGE_INACTIVE"

    def test_challenge_archived(self):
        self.challenge.is_archived = True
        db.session.commit()
        resp = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            json={"task_id": self.task.id, "selected_cells": self.valid_cells},
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "ERR_CHALLENGE_ARCHIVED"

    def test_challenge_frozen(self):
        self.challenge.is_frozen = True
        db.session.commit()
        resp = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            json={"task_id": self.task.id, "selected_cells": self.valid_cells},
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 403
        assert resp.get_json()["code"] == "ERR_COMPETITION_FROZEN"

    def test_scores_finalized(self):
        self.challenge.scores_finalized = True
        db.session.commit()
        resp = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            json={"task_id": self.task.id, "selected_cells": self.valid_cells},
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 403
        assert resp.get_json()["code"] == "ERR_COMPETITION_FINALIZED"

    def test_stage_not_started(self):
        stage = Stage(
            title="Future",
            challenge_id=self.challenge.id,
            stage_number=1,
            start_time=datetime.utcnow() + timedelta(hours=24),
            end_time=datetime.utcnow() + timedelta(hours=48),
        )
        db.session.add(stage)
        db.session.commit()
        self.task.stage_id = stage.id
        db.session.commit()
        resp = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            json={"task_id": self.task.id, "selected_cells": self.valid_cells},
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "ERR_STAGE_NOT_STARTED"

    def test_stage_deadline_passed(self):
        stage = Stage(
            title="Past",
            challenge_id=self.challenge.id,
            stage_number=2,
            start_time=datetime.utcnow() - timedelta(hours=48),
            end_time=datetime.utcnow() - timedelta(hours=24),
        )
        db.session.add(stage)
        db.session.commit()
        self.task.stage_id = stage.id
        db.session.commit()
        resp = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            json={"task_id": self.task.id, "selected_cells": self.valid_cells},
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "ERR_STAGE_DEADLINE_PASSED"

    def test_competition_not_started(self):
        self.challenge.start_time = datetime.utcnow() + timedelta(hours=24)
        db.session.commit()
        resp = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            json={"task_id": self.task.id, "selected_cells": self.valid_cells},
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "ERR_COMPETITION_NOT_STARTED"

    def test_competition_ended(self):
        self.challenge.end_time = datetime.utcnow() - timedelta(hours=24)
        db.session.commit()
        resp = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            json={"task_id": self.task.id, "selected_cells": self.valid_cells},
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "ERR_COMPETITION_ENDED"

    def test_missing_selected_cells(self):
        resp = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            json={"task_id": self.task.id},
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "ERR_MISSING_SELECTED_CELLS"

    def test_missing_task_id(self):
        resp = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            json={"selected_cells": self.valid_cells},
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "ERR_MISSING_TASK_ID"

    def test_invalid_task_id(self):
        resp = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            json={"task_id": 99999, "selected_cells": self.valid_cells},
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "ERR_INVALID_TASK_ID"

    def test_task_from_different_challenge(self):
        other_challenge = Challenge(
            title="Other",
            description="Test",
            max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=48),
            end_time=datetime.utcnow() + timedelta(hours=48),
            is_frozen=False,
            scores_finalized=False,
            is_active=True,
        )
        db.session.add(other_challenge)
        db.session.commit()
        self.task.challenge_id = other_challenge.id
        db.session.commit()
        resp = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            json={"task_id": self.task.id, "selected_cells": self.valid_cells},
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "ERR_INVALID_TASK_ID"

    @patch(
        "services.submission_service.check_execution_rules",
        return_value=(False, "Custom rule failed"),
    )
    def test_ast_rule_failed(self, mock_check):
        resp = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            json={"task_id": self.task.id, "selected_cells": self.valid_cells},
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "ERR_AST_RULE_FAILED"

    def test_daily_limit_reached(self):
        self.challenge.max_eval_requests = 0
        db.session.commit()
        resp = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            json={"task_id": self.task.id, "selected_cells": self.valid_cells},
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 429
        assert resp.get_json()["code"] == "ERR_DAILY_LIMIT_REACHED"

    @patch("tasks.evaluate_submission.apply_async")
    def test_admin_submit_skips_time_checks(self, mock_apply):
        mock_apply.return_value = None
        self.challenge.start_time = datetime.utcnow() + timedelta(hours=24)
        db.session.commit()
        resp = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            json={"task_id": self.task.id, "selected_cells": self.valid_cells},
            headers=self._auth(self.admin_token),
        )
        assert resp.status_code == 202

    @patch("tasks.evaluate_submission.apply_async", side_effect=Exception("Queue down"))
    def test_submission_queue_unavailable(self, mock_apply):
        resp = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            json={"task_id": self.task.id, "selected_cells": self.valid_cells},
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 503
        body = resp.get_json()
        assert "submission_id" in body


class TestGetSubmissions:

    @pytest.fixture(autouse=True)
    def setup(self, db_session, client, auth_headers, csrf_headers, redis_flush):
        self.client = client
        self._auth = auth_headers
        self.csrf_headers = csrf_headers
        self.seed_basic_data()

    def seed_basic_data(self):
        self.challenge = Challenge(
            title="Get Subs Test",
            description="Test",
            max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=48),
            end_time=datetime.utcnow() + timedelta(hours=48),
            is_frozen=False,
            scores_finalized=False,
            is_active=True,
        )
        db.session.add(self.challenge)
        db.session.flush()

        self.task = Task(
            title="Get Subs T1",
            challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
            metrics_config='{"accuracy": {"weight": 1.0}}',
        )
        db.session.add(self.task)
        db.session.flush()

        self.competitor = User(
            username="comp_getsubs",
            password_hash="x",
            role="competitor",
            alias_id="CG",
            challenge_id=self.challenge.id,
        )
        db.session.add(self.competitor)

        self.other_comp = User(
            username="other_getsubs",
            password_hash="x",
            role="competitor",
            alias_id="OG",
            challenge_id=self.challenge.id,
        )
        db.session.add(self.other_comp)

        self.admin = User(username="admin_getsubs", password_hash="x", role="admin", alias_id="AG")
        db.session.add(self.admin)
        db.session.commit()

        self.sub1 = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
            code_cells="[]",
        )
        db.session.add(self.sub1)

        self.sub2 = Submission(
            user_id=self.other_comp.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
            code_cells="[]",
        )
        db.session.add(self.sub2)
        db.session.commit()

        self.comp_token = generate_token(self.competitor.id, role="competitor")
        self.other_token = generate_token(self.other_comp.id, role="competitor")
        self.admin_token = generate_token(self.admin.id, role="admin")

    def test_competitor_sees_only_own_submissions(self):
        resp = self.client.get(
            f"/api/challenges/{self.challenge.id}/submissions", headers=self._auth(self.comp_token)
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert len(body["submissions"]) == 1
        assert body["submissions"][0]["id"] == self.sub1.id

    def test_other_competitor_sees_only_own_submissions(self):
        resp = self.client.get(
            f"/api/challenges/{self.challenge.id}/submissions", headers=self._auth(self.other_token)
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert len(body["submissions"]) == 1
        assert body["submissions"][0]["id"] == self.sub2.id

    def test_admin_sees_all_submissions(self):
        resp = self.client.get(
            f"/api/challenges/{self.challenge.id}/submissions", headers=self._auth(self.admin_token)
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert len(body["submissions"]) == 2

    def test_not_registered_competitor(self):
        unreg = User(
            username="unreg", password_hash="x", role="competitor", alias_id="UR", challenge_id=999
        )
        db.session.add(unreg)
        db.session.commit()
        token = generate_token(unreg.id, role="competitor")
        resp = self.client.get(
            f"/api/challenges/{self.challenge.id}/submissions", headers=self._auth(token)
        )
        assert resp.status_code == 403
        assert resp.get_json()["code"] == "ERR_NOT_REGISTERED"

    def test_pagination_returns_metadata(self):
        resp = self.client.get(
            f"/api/challenges/{self.challenge.id}/submissions?page=1&per_page=1",
            headers=self._auth(self.admin_token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert "page" in body
        assert "per_page" in body
        assert "total" in body
        assert "pages" in body
        assert body["page"] == 1
        assert body["per_page"] == 1
        assert body["total"] == 2

    def test_empty_list_when_no_submissions(self):
        empty_challenge = Challenge(
            title="Empty",
            description="Test",
            max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=48),
            end_time=datetime.utcnow() + timedelta(hours=48),
            is_frozen=False,
            scores_finalized=False,
            is_active=True,
        )
        db.session.add(empty_challenge)
        db.session.commit()
        resp = self.client.get(
            f"/api/challenges/{empty_challenge.id}/submissions",
            headers=self._auth(self.admin_token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert len(body["submissions"]) == 0
        assert body["total"] == 0


class TestGetSubmissionDetail:

    @pytest.fixture(autouse=True)
    def setup(self, db_session, client, auth_headers, csrf_headers, redis_flush):
        self.client = client
        self._auth = auth_headers
        self.csrf_headers = csrf_headers
        self.seed_basic_data()

    def seed_basic_data(self):
        self.challenge = Challenge(
            title="Detail Test",
            description="Test",
            max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=48),
            end_time=datetime.utcnow() + timedelta(hours=48),
            is_frozen=False,
            scores_finalized=False,
            is_active=True,
        )
        db.session.add(self.challenge)
        db.session.flush()

        self.task = Task(
            title="Detail T1",
            challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
            metrics_config='{"accuracy": {"weight": 1.0}}',
        )
        db.session.add(self.task)
        db.session.flush()

        self.owner = User(
            username="owner",
            password_hash="x",
            role="competitor",
            alias_id="OW",
            challenge_id=self.challenge.id,
        )
        db.session.add(self.owner)

        self.other = User(
            username="other_detail",
            password_hash="x",
            role="competitor",
            alias_id="OD",
            challenge_id=self.challenge.id,
        )
        db.session.add(self.other)

        self.admin = User(username="admin_detail", password_hash="x", role="admin", alias_id="AD")
        db.session.add(self.admin)
        db.session.commit()

        self.submission = Submission(
            user_id=self.owner.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
            code_cells="[]",
        )
        db.session.add(self.submission)
        db.session.commit()

        self.owner_token = generate_token(self.owner.id, role="competitor")
        self.other_token = generate_token(self.other.id, role="competitor")
        self.admin_token = generate_token(self.admin.id, role="admin")

    def test_owner_can_view_own_submission(self):
        resp = self.client.get(
            f"/api/submissions/{self.submission.id}", headers=self._auth(self.owner_token)
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["id"] == self.submission.id

    def test_admin_can_view_any_submission(self):
        resp = self.client.get(
            f"/api/submissions/{self.submission.id}", headers=self._auth(self.admin_token)
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["id"] == self.submission.id

    def test_competitor_cannot_view_others_submission(self):
        resp = self.client.get(
            f"/api/submissions/{self.submission.id}", headers=self._auth(self.other_token)
        )
        assert resp.status_code == 403
        assert resp.get_json()["code"] == "ERR_NOT_OWNER"

    def test_returns_404_for_missing_submission(self):
        resp = self.client.get("/api/submissions/99999", headers=self._auth(self.admin_token))
        assert resp.status_code == 404

    def test_to_dict_includes_expected_fields(self):
        resp = self.client.get(
            f"/api/submissions/{self.submission.id}", headers=self._auth(self.owner_token)
        )
        body = resp.get_json()
        assert "id" in body
        assert "status" in body
        assert "task_id" in body
        assert "challenge_id" in body
        assert "created_at" in body
        assert "user" in body


class TestStreamSubmissionLogs:

    @pytest.fixture(autouse=True)
    def setup(self, db_session, client, auth_headers, csrf_headers, redis_flush):
        self.client = client
        self._auth = auth_headers
        self.csrf_headers = csrf_headers
        self.seed_basic_data()

    def seed_basic_data(self):
        self.challenge = Challenge(
            title="Logs Test",
            description="Test",
            max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=48),
            end_time=datetime.utcnow() + timedelta(hours=48),
            is_frozen=False,
            scores_finalized=False,
            is_active=True,
        )
        db.session.add(self.challenge)
        db.session.flush()

        self.task = Task(
            title="Logs T1",
            challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
            metrics_config='{"accuracy": {"weight": 1.0}}',
        )
        db.session.add(self.task)
        db.session.flush()

        self.owner = User(
            username="logs_owner",
            password_hash="x",
            role="competitor",
            alias_id="LO",
            challenge_id=self.challenge.id,
        )
        db.session.add(self.owner)

        self.other = User(
            username="logs_other",
            password_hash="x",
            role="competitor",
            alias_id="LOT",
            challenge_id=self.challenge.id,
        )
        db.session.add(self.other)

        self.admin = User(username="logs_admin", password_hash="x", role="admin", alias_id="LA")
        db.session.add(self.admin)
        db.session.commit()

        self.submission = Submission(
            user_id=self.owner.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="queued",
            code_cells="[]",
        )
        db.session.add(self.submission)
        db.session.commit()

        self.owner_token = generate_token(self.owner.id, role="competitor")
        self.other_token = generate_token(self.other.id, role="competitor")
        self.admin_token = generate_token(self.admin.id, role="admin")

    def test_returns_404_for_missing_submission(self):
        resp = self.client.get(
            "/api/submissions/99999/logs/live", headers=self._auth(self.admin_token)
        )
        assert resp.status_code == 404

    def test_competitor_cannot_view_others_logs(self):
        resp = self.client.get(
            f"/api/submissions/{self.submission.id}/logs/live", headers=self._auth(self.other_token)
        )
        assert resp.status_code == 403

    def test_owner_can_stream_logs(self):
        self.submission.status = "completed"
        db.session.commit()
        resp = self.client.get(
            f"/api/submissions/{self.submission.id}/logs/live", headers=self._auth(self.owner_token)
        )
        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"

    def test_admin_can_stream_logs(self):
        self.submission.status = "completed"
        db.session.commit()
        resp = self.client.get(
            f"/api/submissions/{self.submission.id}/logs/live", headers=self._auth(self.admin_token)
        )
        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"

    def test_sse_response_contains_initial_event(self):
        self.submission.status = "completed"
        db.session.commit()
        resp = self.client.get(
            f"/api/submissions/{self.submission.id}/logs/live", headers=self._auth(self.owner_token)
        )
        data = resp.data.decode("utf-8")
        assert "data: " in data
        assert "info" in data
