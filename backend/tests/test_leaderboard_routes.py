import os
import sys
import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import db, User, Challenge, Task, Submission
from auth_utils import generate_token


class TestChallengeLeaderboardGetEndpoint(unittest.TestCase):
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
        self.admin = User(
            username="lb_admin",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            alias_id="Admin-LB"
        )
        db.session.add(self.admin)

        self.challenge = Challenge(
            title="LB Challenge",
            description="Test challenge for leaderboard",
            max_eval_requests=10,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2),
            is_frozen=False,
            double_blind=True,
            reveal_public_scores=True,
            reveal_private_scores=False,
            reveal_points=False,
            scores_finalized=False
        )
        db.session.add(self.challenge)
        db.session.commit()

        self.competitor = User(
            username="lb_comp",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Alpha-Comp",
            challenge_id=self.challenge.id
        )
        self.competitor.set_demographics("Alice", "Smith", "10", "Test School", "Test City")
        db.session.add(self.competitor)

        self.other_competitor = User(
            username="lb_comp2",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Beta-Comp",
            challenge_id=self.challenge.id
        )
        self.other_competitor.set_demographics("Bob", "Jones", "11", "Other School", "Other City")
        db.session.add(self.other_competitor)

        self.task = Task(
            challenge_id=self.challenge.id,
            title="LB Task",
            description="Task for leaderboard testing",
            ram_limit_mb=4096,
            time_limit_sec=60,
            gpu_required=False,
            files="[]"
        )
        db.session.add(self.task)
        db.session.commit()

        self.admin_token = generate_token(self.admin.id, self.admin.role)
        self.competitor_token = generate_token(self.competitor.id, self.competitor.role)
        self.other_comp_token = generate_token(self.other_competitor.id, self.other_competitor.role)

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    @patch('routes.leaderboard.build_and_cache_leaderboard')
    def test_competitor_registered_can_access(self, mock_build):
        mock_build.return_value = []
        res = self.client.get(
            f'/api/challenges/{self.challenge.id}/leaderboard',
            headers=self._auth(self.competitor_token)
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("leaderboard", data)
        self.assertIn("challenge_title", data)
        self.assertEqual(data["challenge_title"], "LB Challenge")
        mock_build.assert_called_once_with(self.challenge.id, False)

    def test_competitor_not_registered_denied(self):
        other_challenge = Challenge(
            title="Other Challenge",
            description="Unrelated",
            max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2)
        )
        db.session.add(other_challenge)
        db.session.commit()

        unreg_user = User(
            username="unreg_comp",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Unreg",
            challenge_id=other_challenge.id
        )
        db.session.add(unreg_user)
        db.session.commit()
        unreg_token = generate_token(unreg_user.id, unreg_user.role)

        res = self.client.get(
            f'/api/challenges/{self.challenge.id}/leaderboard',
            headers=self._auth(unreg_token)
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn("not registered", res.get_json()["error"].lower())

    @patch('routes.leaderboard.build_and_cache_leaderboard')
    def test_admin_can_access_any_leaderboard(self, mock_build):
        mock_build.return_value = []
        res = self.client.get(
            f'/api/challenges/{self.challenge.id}/leaderboard',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("leaderboard", data)

    def test_challenge_not_found_returns_404(self):
        res = self.client.get(
            '/api/challenges/99999/leaderboard',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 404)

    @patch('routes.leaderboard.build_and_cache_leaderboard')
    def test_frozen_view_for_competitor(self, mock_build):
        self.challenge.is_frozen = True
        db.session.flush()

        mock_build.return_value = []
        res = self.client.get(
            f'/api/challenges/{self.challenge.id}/leaderboard',
            headers=self._auth(self.competitor_token)
        )
        self.assertEqual(res.status_code, 200)
        mock_build.assert_called_once_with(self.challenge.id, True)

    @patch('routes.leaderboard.build_and_cache_leaderboard')
    def test_admin_gets_unfrozen_view_even_when_frozen(self, mock_build):
        self.challenge.is_frozen = True
        db.session.flush()

        mock_build.return_value = []
        res = self.client.get(
            f'/api/challenges/{self.challenge.id}/leaderboard',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 200)
        mock_build.assert_called_once_with(self.challenge.id, False)

    @patch('routes.leaderboard.build_and_cache_leaderboard')
    def test_admin_bypasses_cache(self, mock_build):
        mock_build.return_value = []
        from cache_utils import set_cached
        set_cached(f"leaderboard:raw:{self.challenge.id}:unfrozen", ["stale"], timeout=60)

        res = self.client.get(
            f'/api/challenges/{self.challenge.id}/leaderboard',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 200)
        mock_build.assert_called_once()

    @patch('routes.leaderboard.build_and_cache_leaderboard')
    def test_double_blind_hides_details_for_competitors(self, mock_build):
        self.challenge.double_blind = True
        db.session.flush()

        entry_other = {
            "user": {
                "id": self.other_competitor.id,
                "alias_id": "Beta-Comp",
                "role": "competitor",
                "challenge_id": self.challenge.id,
                "is_anonymous": False,
                "name": "Bob",
                "surname": "Jones"
            },
            "task_scores": {},
            "public_score": None,
            "private_score": None,
            "total_points": 0,
            "has_submitted": False
        }
        entry_self = {
            "user": {
                "id": self.competitor.id,
                "alias_id": "Alpha-Comp",
                "role": "competitor",
                "challenge_id": self.challenge.id,
                "is_anonymous": False,
                "name": "Alice",
                "surname": "Smith"
            },
            "task_scores": {},
            "public_score": None,
            "private_score": None,
            "total_points": 0,
            "has_submitted": False
        }
        mock_build.return_value = [entry_other, entry_self]

        res = self.client.get(
            f'/api/challenges/{self.challenge.id}/leaderboard',
            headers=self._auth(self.competitor_token)
        )
        self.assertEqual(res.status_code, 200)
        leaderboard = res.get_json()["leaderboard"]

        other_item = next(item for item in leaderboard if item["user"]["id"] == self.other_competitor.id)
        self.assertNotIn("name", other_item["user"])
        self.assertEqual(other_item["user"]["alias_id"], "Beta-Comp")

        self_item = next(item for item in leaderboard if item["user"]["id"] == self.competitor.id)
        self.assertIn("name", self_item["user"])
        self.assertEqual(self_item["user"]["name"], "Alice")

    @patch('routes.leaderboard.build_and_cache_leaderboard')
    def test_scores_finalized_shows_all_details(self, mock_build):
        self.challenge.scores_finalized = True
        self.challenge.reveal_points = True
        db.session.flush()

        entry = {
            "user": {
                "id": self.competitor.id,
                "alias_id": "Alpha-Comp",
                "role": "competitor",
                "challenge_id": self.challenge.id,
                "is_anonymous": False,
                "name": "Alice",
                "surname": "Smith",
                "manual_points": {}
            },
            "task_scores": {},
            "public_score": 0.95,
            "private_score": 0.92,
            "total_points": 80,
            "has_submitted": True
        }
        mock_build.return_value = [entry]

        res = self.client.get(
            f'/api/challenges/{self.challenge.id}/leaderboard',
            headers=self._auth(self.competitor_token)
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["is_finalized"])

    @patch('routes.leaderboard.build_and_cache_leaderboard')
    def test_leaderboard_response_shape(self, mock_build):
        mock_build.return_value = []
        res = self.client.get(
            f'/api/challenges/{self.challenge.id}/leaderboard',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("challenge_title", data)
        self.assertIn("metric_name", data)
        self.assertIn("is_normalized", data)
        self.assertIn("is_finalized", data)
        self.assertIn("reveal_public_scores", data)
        self.assertIn("reveal_private_scores", data)
        self.assertIn("reveal_points", data)
        self.assertIn("tasks", data)
        self.assertIn("leaderboard", data)


class TestManualPointsEndpoint(unittest.TestCase):
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
        self.admin = User(
            username="mp_admin",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            alias_id="Admin-MP"
        )
        db.session.add(self.admin)

        self.jury = User(
            username="mp_jury",
            password_hash="pbkdf2:sha256:...",
            role="jury",
            alias_id="Jury-MP"
        )
        db.session.add(self.jury)

        self.challenge = Challenge(
            title="MP Challenge",
            description="Manual points challenge",
            max_eval_requests=10,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2),
            scores_finalized=False
        )
        db.session.add(self.challenge)
        db.session.commit()

        self.competitor = User(
            username="mp_comp",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="MP-Comp",
            challenge_id=self.challenge.id
        )
        db.session.add(self.competitor)

        self.task = Task(
            challenge_id=self.challenge.id,
            title="MP Task",
            description="Task for manual points",
            ram_limit_mb=4096,
            time_limit_sec=60,
            gpu_required=False,
            files="[]"
        )
        db.session.add(self.task)
        db.session.commit()

        self.admin_token = generate_token(self.admin.id, self.admin.role)
        self.jury_token = generate_token(self.jury.id, self.jury.role)
        self.competitor_token = generate_token(self.competitor.id, self.competitor.role)

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def _seed_completed_submission(self):
        sub = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
            public_score=0.8,
            code_cells="[]"
        )
        db.session.add(sub)
        db.session.commit()
        sub_id = sub.id
        db.session.flush()
        return sub_id

    def test_admin_saves_manual_points(self):
        self._seed_completed_submission()
        payload = {
            "user_id": self.competitor.id,
            "points": {str(self.task.id): 85},
            "reason": "Good performance"
        }
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/manual-points',
            headers=self._auth(self.admin_token),
            json=payload
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("message", data)
        self.assertEqual(data["user_id"], self.competitor.id)
        self.assertEqual(data["manual_points"][str(self.task.id)], 85)

    def test_jury_saves_manual_points(self):
        self._seed_completed_submission()
        payload = {
            "user_id": self.competitor.id,
            "points": {str(self.task.id): 75},
            "reason": "Decent solution"
        }
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/manual-points',
            headers=self._auth(self.jury_token),
            json=payload
        )
        self.assertEqual(res.status_code, 200)

    def test_competitor_cannot_save_manual_points(self):
        payload = {
            "user_id": self.competitor.id,
            "points": {str(self.task.id): 50}
        }
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/manual-points',
            headers=self._auth(self.competitor_token),
            json=payload
        )
        self.assertEqual(res.status_code, 403)

    def test_missing_user_id_returns_400(self):
        payload = {
            "points": {str(self.task.id): 50}
        }
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/manual-points',
            headers=self._auth(self.admin_token),
            json=payload
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Missing", res.get_json()["error"])

    def test_missing_points_dict_returns_400(self):
        payload = {
            "user_id": self.competitor.id
        }
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/manual-points',
            headers=self._auth(self.admin_token),
            json=payload
        )
        self.assertEqual(res.status_code, 400)

    def test_user_not_registered_in_challenge_returns_404(self):
        other_challenge = Challenge(
            title="Other MP Challenge",
            description="Unrelated",
            max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2)
        )
        db.session.add(other_challenge)
        db.session.commit()

        payload = {
            "user_id": 99999,
            "points": {str(self.task.id): 50}
        }
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/manual-points',
            headers=self._auth(self.admin_token),
            json=payload
        )
        self.assertEqual(res.status_code, 404)

    def test_reason_required_when_finalized(self):
        self.challenge.scores_finalized = True
        db.session.flush()

        payload = {
            "user_id": self.competitor.id,
            "points": {str(self.task.id): 50}
        }
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/manual-points',
            headers=self._auth(self.admin_token),
            json=payload
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("reason", res.get_json()["error"].lower())

    def test_invalid_task_id_returns_400(self):
        payload = {
            "user_id": self.competitor.id,
            "points": {"invalid": 50}
        }
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/manual-points',
            headers=self._auth(self.admin_token),
            json=payload
        )
        self.assertEqual(res.status_code, 400)

    def test_task_not_in_challenge_returns_400(self):
        other_task = Task(
            challenge_id=99999,
            title="Orphan Task",
            description="Not in this challenge",
            ram_limit_mb=1024,
            time_limit_sec=60
        )
        db.session.add(other_task)
        db.session.commit()

        payload = {
            "user_id": self.competitor.id,
            "points": {str(other_task.id): 50}
        }
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/manual-points',
            headers=self._auth(self.admin_token),
            json=payload
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("does not belong", res.get_json()["error"].lower())

    def test_points_must_be_integer_returns_400(self):
        payload = {
            "user_id": self.competitor.id,
            "points": {str(self.task.id): 50.5}
        }
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/manual-points',
            headers=self._auth(self.admin_token),
            json=payload
        )
        self.assertEqual(res.status_code, 400)

    def test_points_out_of_bounds_returns_400(self):
        payload = {
            "user_id": self.competitor.id,
            "points": {str(self.task.id): 150}
        }
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/manual-points',
            headers=self._auth(self.admin_token),
            json=payload
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("must be between 0 and 100", res.get_json()["error"])

    def test_no_completed_submissions_returns_400(self):
        payload = {
            "user_id": self.competitor.id,
            "points": {str(self.task.id): 50},
            "reason": "Testing"
        }
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/manual-points',
            headers=self._auth(self.admin_token),
            json=payload
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("no completed submissions", res.get_json()["error"].lower())

    def test_manual_points_updates_single_task(self):
        self._seed_completed_submission()

        payload = {
            "user_id": self.competitor.id,
            "points": {str(self.task.id): 85},
            "reason": "Initial scoring"
        }
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/manual-points',
            headers=self._auth(self.admin_token),
            json=payload
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["manual_points"][str(self.task.id)], 85)

    def test_manual_points_accepts_consecutive_calls(self):
        self._seed_completed_submission()

        payload = {
            "user_id": self.competitor.id,
            "points": {str(self.task.id): 70},
            "reason": "First"
        }
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/manual-points',
            headers=self._auth(self.admin_token),
            json=payload
        )
        self.assertEqual(res.status_code, 200)

        payload["points"] = {str(self.task.id): 90}
        payload["reason"] = "Second"
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/manual-points',
            headers=self._auth(self.admin_token),
            json=payload
        )
        self.assertEqual(res.status_code, 200)

    @patch('cache_utils.invalidate_leaderboard_cache')
    def test_cache_invalidated_on_manual_points_save(self, mock_invalidate):
        self._seed_completed_submission()
        payload = {
            "user_id": self.competitor.id,
            "points": {str(self.task.id): 80},
            "reason": "Cache test"
        }
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/manual-points',
            headers=self._auth(self.admin_token),
            json=payload
        )
        self.assertEqual(res.status_code, 200)
        mock_invalidate.assert_called_once_with(self.challenge.id)

    def test_challenge_not_found_returns_404(self):
        payload = {
            "user_id": self.competitor.id,
            "points": {str(self.task.id): 50}
        }
        res = self.client.post(
            '/api/challenges/99999/manual-points',
            headers=self._auth(self.admin_token),
            json=payload
        )
        self.assertEqual(res.status_code, 404)

