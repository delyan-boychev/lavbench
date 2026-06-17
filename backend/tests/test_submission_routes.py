import os
import sys
import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import db, User, Challenge, Task, Submission, Stage
from auth_utils import generate_token


class TestSelectFinalSubmission(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
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

    def seed_basic_data(self):
        self.challenge = Challenge(
            title="Final Sel Test", description="Test", max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=48),
            end_time=datetime.utcnow() + timedelta(hours=48),
            is_frozen=False, scores_finalized=False
        )
        db.session.add(self.challenge)
        db.session.flush()

        self.task = Task(
            title="T1", challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim", time_limit_sec=300,
            ram_limit_mb=512, max_submissions_per_period=10,
            metrics_config='{"accuracy": {"weight": 1.0}}'
        )
        db.session.add(self.task)

        self.admin = User(
            username="admin", password_hash="x", role="admin", alias_id="A1"
        )
        db.session.add(self.admin)

        self.competitor = User(
            username="comp1", password_hash="x", role="competitor",
            alias_id="C1", challenge_id=self.challenge.id
        )
        db.session.add(self.competitor)

        self.other_comp = User(
            username="comp2", password_hash="x", role="competitor",
            alias_id="C2", challenge_id=self.challenge.id
        )
        db.session.add(self.other_comp)
        db.session.flush()

        self.stage = Stage(
            title="Stage 1", challenge_id=self.challenge.id,
            stage_number=1,
            start_time=datetime.utcnow() - timedelta(hours=24),
            end_time=datetime.utcnow() + timedelta(hours=24)
        )
        db.session.add(self.stage)
        db.session.commit()

        self.task.stage_id = self.stage.id
        db.session.commit()

        self.submission = Submission(
            user_id=self.competitor.id, challenge_id=self.challenge.id,
            task_id=self.task.id, status='completed', code_cells='[]',
            created_at=datetime.utcnow() - timedelta(hours=12),
            executed_at=datetime.utcnow() - timedelta(hours=11)
        )
        db.session.add(self.submission)
        db.session.commit()

        self.admin_token = generate_token(self.admin.id, role="admin")
        self.comp_token = generate_token(self.competitor.id, role="competitor")
        self.other_token = generate_token(self.other_comp.id, role="competitor")

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_admin_can_select_any_submission(self):
        resp = self.client.post(
            f"/api/submissions/{self.submission.id}/select-final",
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(resp.status_code, 200)

    def test_competitor_can_select_own_submission(self):
        resp = self.client.post(
            f"/api/submissions/{self.submission.id}/select-final",
            headers=self._auth(self.comp_token)
        )
        self.assertEqual(resp.status_code, 200)

    def test_competitor_cannot_select_others_submission(self):
        resp = self.client.post(
            f"/api/submissions/{self.submission.id}/select-final",
            headers=self._auth(self.other_token)
        )
        self.assertEqual(resp.status_code, 403)
        data = resp.get_json()
        self.assertEqual(data.get("code"), "ERR_NOT_OWNER")

    def test_returns_404_for_missing_submission(self):
        resp = self.client.post(
            "/api/submissions/99999/select-final",
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(resp.status_code, 404)

    def test_select_sets_is_final_selection_true(self):
        self.client.post(
            f"/api/submissions/{self.submission.id}/select-final",
            headers=self._auth(self.comp_token)
        )
        updated = db.session.get(Submission, self.submission.id)
        self.assertTrue(updated.is_final_selection)

    def test_select_clears_other_final_selections(self):
        sub2 = Submission(
            user_id=self.competitor.id, challenge_id=self.challenge.id,
            task_id=self.task.id, status='completed', code_cells='[]',
            created_at=datetime.utcnow() - timedelta(hours=10),
            is_final_selection=True
        )
        db.session.add(sub2)
        db.session.commit()
        self.client.post(
            f"/api/submissions/{self.submission.id}/select-final",
            headers=self._auth(self.comp_token)
        )
        updated = db.session.get(Submission, sub2.id)
        self.assertFalse(updated.is_final_selection)

    def test_blocked_when_scores_finalized(self):
        self.challenge.scores_finalized = True
        db.session.commit()
        resp = self.client.post(
            f"/api/submissions/{self.submission.id}/select-final",
            headers=self._auth(self.comp_token)
        )
        self.assertEqual(resp.status_code, 403)
        data = resp.get_json()
        self.assertEqual(data.get("code"), "ERR_COMPETITION_FINALIZED")

    def test_admin_bypasses_scores_finalized(self):
        self.challenge.scores_finalized = True
        db.session.commit()
        resp = self.client.post(
            f"/api/submissions/{self.submission.id}/select-final",
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(resp.status_code, 200)

    def test_submission_after_stage_deadline_blocked(self):
        self.submission.created_at = self.stage.end_time + timedelta(hours=1)
        db.session.commit()
        resp = self.client.post(
            f"/api/submissions/{self.submission.id}/select-final",
            headers=self._auth(self.comp_token)
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertEqual(data.get("code"), "ERR_SUBMISSION_LATE")

    def test_selection_window_closed(self):
        closed_stage = Stage(
            title="Closed", challenge_id=self.challenge.id,
            stage_number=2,
            start_time=datetime.utcnow() - timedelta(hours=48),
            end_time=datetime.utcnow() - timedelta(hours=2)
        )
        db.session.add(closed_stage)
        db.session.commit()
        self.task.stage_id = closed_stage.id
        db.session.commit()
        late_sub = Submission(
            user_id=self.competitor.id, challenge_id=self.challenge.id,
            task_id=self.task.id, status='completed', code_cells='[]',
            created_at=closed_stage.end_time - timedelta(hours=1),
            executed_at=closed_stage.end_time - timedelta(minutes=30)
        )
        db.session.add(late_sub)
        db.session.commit()
        resp = self.client.post(
            f"/api/submissions/{late_sub.id}/select-final",
            headers=self._auth(self.comp_token)
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertEqual(data.get("code"), "ERR_SELECTION_WINDOW_CLOSED")

    def test_selection_window_open_within_grace_period(self):
        recent_stage = Stage(
            title="Recent", challenge_id=self.challenge.id,
            stage_number=2,
            start_time=datetime.utcnow() - timedelta(hours=48),
            end_time=datetime.utcnow() - timedelta(minutes=2)
        )
        db.session.add(recent_stage)
        db.session.commit()
        self.task.stage_id = recent_stage.id
        self.submission.created_at = recent_stage.end_time - timedelta(hours=1)
        self.submission.executed_at = recent_stage.end_time - timedelta(minutes=30)
        db.session.commit()
        resp = self.client.post(
            f"/api/submissions/{self.submission.id}/select-final",
            headers=self._auth(self.comp_token)
        )
        self.assertEqual(resp.status_code, 200)

    def test_sliding_window_extended_by_other_submissions(self):
        slide_stage = Stage(
            title="Slide", challenge_id=self.challenge.id,
            stage_number=2,
            start_time=datetime.utcnow() - timedelta(hours=48),
            end_time=datetime.utcnow() - timedelta(minutes=5)
        )
        db.session.add(slide_stage)
        db.session.commit()
        self.task.stage_id = slide_stage.id
        late_exec = Submission(
            user_id=self.competitor.id, challenge_id=self.challenge.id,
            task_id=self.task.id, status='completed', code_cells='[]',
            created_at=slide_stage.end_time - timedelta(seconds=10),
            executed_at=datetime.utcnow() - timedelta(seconds=60)
        )
        db.session.add(late_exec)
        self.submission.created_at = slide_stage.end_time - timedelta(hours=1)
        self.submission.executed_at = slide_stage.end_time - timedelta(minutes=30)
        db.session.commit()
        resp = self.client.post(
            f"/api/submissions/{self.submission.id}/select-final",
            headers=self._auth(self.comp_token)
        )
        self.assertEqual(resp.status_code, 200)


if __name__ == '__main__':
    unittest.main()
