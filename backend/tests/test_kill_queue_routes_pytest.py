import os
import sys
from unittest.mock import patch

import pytest

from utils.dates import utcnow

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from auth_utils import generate_token
from models import Challenge, Submission, Task, User, db


class TestKillSubmission:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, client, auth_headers, csrf_headers, redis_flush):
        self.client = client
        self._auth = auth_headers
        self.csrf_headers = csrf_headers
        self.seed_basic_data()

    def seed_basic_data(self):
        self.challenge = Challenge(
            title="Kill Test",
            description="Test",
            max_eval_requests=10,
            start_time=utcnow(),
            end_time=utcnow(),
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
        )
        db.session.add(self.task)

        self.admin = User(username="admin", password_hash="x", role="admin", alias_id="Admin")
        db.session.add(self.admin)

        self.jury = User(username="jury", password_hash="x", role="jury", alias_id="Jury")
        db.session.add(self.jury)

        self.competitor = User(
            username="comp",
            password_hash="x",
            role="competitor",
            alias_id="Comp",
            challenge_id=self.challenge.id,
        )
        db.session.add(self.competitor)

        self.other_comp = User(
            username="other",
            password_hash="x",
            role="competitor",
            alias_id="Other",
            challenge_id=self.challenge.id,
        )
        db.session.add(self.other_comp)
        db.session.flush()

        # Queued submission (owned by competitor)
        self.queued_sub = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="queued",
            celery_task_id="celery-task-queued",
        )
        db.session.add(self.queued_sub)

        # Running submission (owned by competitor)
        self.running_sub = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="running",
            celery_task_id="celery-task-running",
        )
        db.session.add(self.running_sub)

        # Completed submission (not killable)
        self.completed_sub = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
        )
        db.session.add(self.completed_sub)

        # Failed submission (not killable)
        self.failed_sub = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="failed",
        )
        db.session.add(self.failed_sub)

        # Submission owned by other_comp (for permission tests)
        self.other_sub = Submission(
            user_id=self.other_comp.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="queued",
            celery_task_id="celery-task-other",
        )
        db.session.add(self.other_sub)

        db.session.commit()

        self.admin_token = generate_token(self.admin.id, "admin")
        self.jury_token = generate_token(self.jury.id, "jury")
        self.comp_token = generate_token(self.competitor.id, "competitor")
        self.other_token = generate_token(self.other_comp.id, "competitor")

    # ── Admin tests ──

    def test_admin_kills_queued(self):
        resp = self.client.post(
            f"/api/submissions/{self.queued_sub.id}/kill",
            headers=self._auth(self.admin_token),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["message"] == "Submission killed successfully."
        sub = db.session.get(Submission, self.queued_sub.id)
        assert sub.status == "failed"
        assert sub.detailed_status == "killed"

    def test_admin_kills_running(self):
        resp = self.client.post(
            f"/api/submissions/{self.running_sub.id}/kill",
            headers=self._auth(self.admin_token),
        )
        assert resp.status_code == 200
        sub = db.session.get(Submission, self.running_sub.id)
        assert sub.status == "failed"
        assert sub.detailed_status == "killed"

    def test_admin_cannot_kill_completed(self):
        resp = self.client.post(
            f"/api/submissions/{self.completed_sub.id}/kill",
            headers=self._auth(self.admin_token),
        )
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "ERR_SUBMISSION_NOT_KILLABLE"

    def test_admin_cannot_kill_failed(self):
        resp = self.client.post(
            f"/api/submissions/{self.failed_sub.id}/kill",
            headers=self._auth(self.admin_token),
        )
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "ERR_SUBMISSION_NOT_KILLABLE"

    def test_admin_kills_others_submission(self):
        resp = self.client.post(
            f"/api/submissions/{self.other_sub.id}/kill",
            headers=self._auth(self.admin_token),
        )
        assert resp.status_code == 200
        sub = db.session.get(Submission, self.other_sub.id)
        assert sub.status == "failed"

    # ── Jury tests ──

    def test_jury_kills_queued(self):
        resp = self.client.post(
            f"/api/submissions/{self.queued_sub.id}/kill",
            headers=self._auth(self.jury_token),
        )
        assert resp.status_code == 200
        sub = db.session.get(Submission, self.queued_sub.id)
        assert sub.status == "failed"

    # ── Competitor tests ──

    def test_competitor_kills_own_queued(self):
        resp = self.client.post(
            f"/api/submissions/{self.queued_sub.id}/kill",
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 200
        sub = db.session.get(Submission, self.queued_sub.id)
        assert sub.status == "failed"

    def test_competitor_cannot_kill_others(self):
        resp = self.client.post(
            f"/api/submissions/{self.other_sub.id}/kill",
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 403
        assert resp.get_json()["code"] == "ERR_SUBMISSION_KILL_DENIED"

    # ── Auth / edge cases ──

    def test_kill_nonexistent_submission(self):
        resp = self.client.post(
            "/api/submissions/00000000-0000-0000-0000-000000000000/kill",
            headers=self._auth(self.admin_token),
        )
        assert resp.status_code == 404

    def test_kill_unauthenticated(self):
        resp = self.client.post(f"/api/submissions/{self.queued_sub.id}/kill")
        assert resp.status_code == 401

    def test_kill_calls_celery_revoke(self):
        with patch("tasks.celery.control.revoke") as mock_revoke:
            resp = self.client.post(
                f"/api/submissions/{self.queued_sub.id}/kill",
                headers=self._auth(self.admin_token),
            )
            assert resp.status_code == 200
            mock_revoke.assert_called_once_with(self.queued_sub.celery_task_id, terminate=True)


class TestSubmissionQueue:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, client, auth_headers, csrf_headers, redis_flush):
        self.client = client
        self._auth = auth_headers
        self.csrf_headers = csrf_headers
        self.seed_basic_data()

    def seed_basic_data(self):
        self.challenge = Challenge(
            title="Queue Test",
            description="Test",
            max_eval_requests=10,
            start_time=utcnow(),
            end_time=utcnow(),
        )
        db.session.add(self.challenge)
        db.session.flush()

        self.task = Task(
            title="Queue Task",
            challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
        )
        db.session.add(self.task)

        self.admin = User(username="qadmin", password_hash="x", role="admin", alias_id="QAdmin")
        db.session.add(self.admin)

        self.jury = User(username="qjury", password_hash="x", role="jury", alias_id="QJury")
        db.session.add(self.jury)

        self.competitor = User(
            username="qcomp",
            password_hash="x",
            role="competitor",
            alias_id="QComp",
            challenge_id=self.challenge.id,
        )
        db.session.add(self.competitor)
        db.session.flush()

        # Two queued submissions at different times
        from datetime import timedelta

        self.sub1 = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="queued",
            created_at=utcnow() - timedelta(minutes=10),
        )
        db.session.add(self.sub1)

        self.sub2 = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="queued",
            created_at=utcnow() - timedelta(minutes=5),
        )
        db.session.add(self.sub2)

        # Running submission should also appear
        self.sub3 = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="running",
            created_at=utcnow() - timedelta(minutes=1),
        )
        db.session.add(self.sub3)

        # Completed/failed should NOT appear
        self.completed_sub = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
        )
        db.session.add(self.completed_sub)

        self.failed_sub = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="failed",
        )
        db.session.add(self.failed_sub)

        db.session.commit()

        self.admin_token = generate_token(self.admin.id, "admin")
        self.jury_token = generate_token(self.jury.id, "jury")
        self.comp_token = generate_token(self.competitor.id, "competitor")

    def test_admin_sees_queue(self):
        resp = self.client.get(
            "/api/admin/submissions/queue?page=1&per_page=10",
            headers=self._auth(self.admin_token),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "items" in data
        assert data["total"] == 3
        assert len(data["items"]) == 3

    def test_jury_sees_queue(self):
        resp = self.client.get(
            "/api/admin/submissions/queue?page=1&per_page=10",
            headers=self._auth(self.jury_token),
        )
        assert resp.status_code == 200

    def test_competitor_cannot_view_queue(self):
        resp = self.client.get(
            "/api/admin/submissions/queue?page=1&per_page=10",
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 403

    def test_queue_order_ascending(self):
        resp = self.client.get(
            "/api/admin/submissions/queue?page=1&per_page=10",
            headers=self._auth(self.admin_token),
        )
        data = resp.get_json()
        items = data["items"]
        assert len(items) >= 2
        assert items[0]["id"] == str(self.sub1.id)
        assert items[1]["id"] == str(self.sub2.id)

    def test_queue_pagination(self):
        resp = self.client.get(
            "/api/admin/submissions/queue?page=1&per_page=2",
            headers=self._auth(self.admin_token),
        )
        data = resp.get_json()
        assert len(data["items"]) == 2
        assert data["total"] == 3
        assert data["page"] == 1
        assert data["pages"] == 2

    def test_queue_only_queued_and_running(self):
        resp = self.client.get(
            "/api/admin/submissions/queue?page=1&per_page=10",
            headers=self._auth(self.admin_token),
        )
        data = resp.get_json()
        statuses = {item["status"] for item in data["items"]}
        assert statuses == {"queued", "running"}
        assert "completed" not in statuses
        assert "failed" not in statuses


class TestClearQueue:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, client, auth_headers, csrf_headers, redis_flush):
        self.client = client
        self._auth = auth_headers
        self.csrf_headers = csrf_headers
        self.seed_basic_data()

    def seed_basic_data(self):
        self.challenge = Challenge(
            title="Clear Test",
            description="Test",
            max_eval_requests=10,
            start_time=utcnow(),
            end_time=utcnow(),
        )
        db.session.add(self.challenge)
        db.session.flush()

        self.task = Task(
            title="Clear Task",
            challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
        )
        db.session.add(self.task)

        self.admin = User(username="cadmin", password_hash="x", role="admin", alias_id="CAdmin")
        db.session.add(self.admin)

        self.jury = User(username="cjury", password_hash="x", role="jury", alias_id="CJury")
        db.session.add(self.jury)

        self.competitor = User(
            username="ccomp",
            password_hash="x",
            role="competitor",
            alias_id="CComp",
            challenge_id=self.challenge.id,
        )
        db.session.add(self.competitor)
        db.session.flush()

        self.queued_sub = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="queued",
            celery_task_id="celery-clear-queued",
        )
        db.session.add(self.queued_sub)

        self.running_sub = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="running",
            celery_task_id="celery-clear-running",
        )
        db.session.add(self.running_sub)

        self.completed_sub = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
        )
        db.session.add(self.completed_sub)

        db.session.commit()

        self.admin_token = generate_token(self.admin.id, "admin")
        self.jury_token = generate_token(self.jury.id, "jury")

    def test_admin_clears_queue(self):
        with patch("tasks.celery.control.revoke") as mock_revoke:
            resp = self.client.post(
                "/api/admin/submissions/queue/clear",
                headers=self._auth(self.admin_token),
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert "Cleared 2 submission(s)" in data["message"]

            # Queued and running should be killed
            assert db.session.get(Submission, self.queued_sub.id).status == "failed"
            assert db.session.get(Submission, self.running_sub.id).status == "failed"

            # Completed should remain
            assert db.session.get(Submission, self.completed_sub.id).status == "completed"

            assert mock_revoke.call_count == 2

    def test_jury_cannot_clear_queue(self):
        resp = self.client.post(
            "/api/admin/submissions/queue/clear",
            headers=self._auth(self.jury_token),
        )
        assert resp.status_code == 403
