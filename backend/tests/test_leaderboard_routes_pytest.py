import os
import sys
import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models import db, User, Challenge, Task, Submission
from auth_utils import generate_token


class TestChallengeLeaderboardGetEndpoint:
    @pytest.fixture(autouse=True)
    def _setup(self, db_session, redis_flush):
        self.admin = User(
            username="lb_admin",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            alias_id="Admin-LB",
        )
        db_session.add(self.admin)

        self.challenge = Challenge(
            title="LB Challenge",
            description="Test challenge for leaderboard",
            max_eval_requests=10,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2),
            is_frozen=False,
            double_blind=True,
            reveal_results=True,
            scores_finalized=False,
        )
        db_session.add(self.challenge)
        db_session.commit()

        self.competitor = User(
            username="lb_comp",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Alpha-Comp",
            challenge_id=self.challenge.id,
        )
        self.competitor.set_demographics("Alice", "Smith", "10", "Test School", "Test City")
        db_session.add(self.competitor)

        self.other_competitor = User(
            username="lb_comp2",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Beta-Comp",
            challenge_id=self.challenge.id,
        )
        self.other_competitor.set_demographics("Bob", "Jones", "11", "Other School", "Other City")
        db_session.add(self.other_competitor)

        self.task = Task(
            challenge_id=self.challenge.id,
            title="LB Task",
            description="Task for leaderboard testing",
            ram_limit_mb=4096,
            time_limit_sec=60,
            gpu_required=False,
            files="[]",
        )
        db_session.add(self.task)
        db_session.commit()

        self.admin_token = generate_token(self.admin.id, self.admin.role)
        self.competitor_token = generate_token(self.competitor.id, self.competitor.role)
        self.other_comp_token = generate_token(self.other_competitor.id, self.other_competitor.role)

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    @patch("routes.leaderboard.build_and_cache_leaderboard")
    def test_competitor_registered_can_access(self, mock_build, client):
        mock_build.return_value = []
        res = client.get(
            f"/api/challenges/{self.challenge.id}/leaderboard",
            headers=self._auth(self.competitor_token),
        )
        assert res.status_code == 200
        data = res.get_json()
        assert "leaderboard" in data
        assert "challenge_title" in data
        assert data["challenge_title"] == "LB Challenge"
        mock_build.assert_called_once_with(self.challenge.id, False)

    def test_competitor_not_registered_denied(self, client, db_session):
        other_challenge = Challenge(
            title="Other Challenge",
            description="Unrelated",
            max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2),
        )
        db_session.add(other_challenge)
        db_session.commit()

        unreg_user = User(
            username="unreg_comp",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Unreg",
            challenge_id=other_challenge.id,
        )
        db_session.add(unreg_user)
        db_session.commit()
        unreg_token = generate_token(unreg_user.id, unreg_user.role)

        res = client.get(
            f"/api/challenges/{self.challenge.id}/leaderboard", headers=self._auth(unreg_token)
        )
        assert res.status_code == 403
        assert "not registered" in res.get_json()["error"].lower()

    @patch("routes.leaderboard.build_and_cache_leaderboard")
    def test_admin_can_access_any_leaderboard(self, mock_build, client):
        mock_build.return_value = []
        res = client.get(
            f"/api/challenges/{self.challenge.id}/leaderboard", headers=self._auth(self.admin_token)
        )
        assert res.status_code == 200
        data = res.get_json()
        assert "leaderboard" in data

    def test_challenge_not_found_returns_404(self, client):
        res = client.get("/api/challenges/99999/leaderboard", headers=self._auth(self.admin_token))
        assert res.status_code == 404

    @patch("routes.leaderboard.build_and_cache_leaderboard")
    def test_frozen_view_for_competitor(self, mock_build, client, db_session):
        self.challenge.is_frozen = True
        db_session.flush()

        mock_build.return_value = []
        res = client.get(
            f"/api/challenges/{self.challenge.id}/leaderboard",
            headers=self._auth(self.competitor_token),
        )
        assert res.status_code == 200
        mock_build.assert_called_once_with(self.challenge.id, True)

    @patch("routes.leaderboard.build_and_cache_leaderboard")
    def test_admin_gets_unfrozen_view_even_when_frozen(self, mock_build, client, db_session):
        self.challenge.is_frozen = True
        db_session.flush()

        mock_build.return_value = []
        res = client.get(
            f"/api/challenges/{self.challenge.id}/leaderboard", headers=self._auth(self.admin_token)
        )
        assert res.status_code == 200
        mock_build.assert_called_once_with(self.challenge.id, False)

    @patch("routes.leaderboard.build_and_cache_leaderboard")
    def test_admin_uses_cache(self, mock_build, client):
        mock_build.return_value = []
        from cache_utils import set_cached

        entry = {
            "user": {
                "id": 1,
                "alias_id": "Alpha",
                "role": "competitor",
                "is_anonymous": False,
            },
            "task_scores": {},
            "public_score": 0.95,
            "private_score": 0.92,
            "total_points": 80,
            "has_submitted": True,
        }
        set_cached(f"leaderboard:raw:{self.challenge.id}:unfrozen", [entry], timeout=60)

        res = client.get(
            f"/api/challenges/{self.challenge.id}/leaderboard", headers=self._auth(self.admin_token)
        )
        assert res.status_code == 200
        mock_build.assert_not_called()

    @patch("routes.leaderboard.build_and_cache_leaderboard")
    def test_double_blind_hides_details_for_competitors(self, mock_build, client, db_session):
        self.challenge.double_blind = True
        db_session.flush()

        entry_other = {
            "user": {
                "id": self.other_competitor.id,
                "alias_id": "Beta-Comp",
                "role": "competitor",
                "challenge_id": self.challenge.id,
                "is_anonymous": False,
                "name": "Bob",
                "surname": "Jones",
            },
            "task_scores": {},
            "public_score": None,
            "private_score": None,
            "total_points": 0,
            "has_submitted": False,
        }
        entry_self = {
            "user": {
                "id": self.competitor.id,
                "alias_id": "Alpha-Comp",
                "role": "competitor",
                "challenge_id": self.challenge.id,
                "is_anonymous": False,
                "name": "Alice",
                "surname": "Smith",
            },
            "task_scores": {},
            "public_score": None,
            "private_score": None,
            "total_points": 0,
            "has_submitted": False,
        }
        mock_build.return_value = [entry_other, entry_self]

        res = client.get(
            f"/api/challenges/{self.challenge.id}/leaderboard",
            headers=self._auth(self.competitor_token),
        )
        assert res.status_code == 200
        leaderboard = res.get_json()["leaderboard"]

        other_item = next(
            item for item in leaderboard if item["user"]["id"] == self.other_competitor.id
        )
        assert "name" not in other_item["user"]
        assert other_item["user"]["alias_id"] == "Beta-Comp"

        self_item = next(item for item in leaderboard if item["user"]["id"] == self.competitor.id)
        assert "name" in self_item["user"]
        assert self_item["user"]["name"] == "Alice"

    @patch("routes.leaderboard.build_and_cache_leaderboard")
    def test_scores_finalized_shows_all_details(self, mock_build, client, db_session):
        self.challenge.scores_finalized = True
        self.challenge.reveal_results = True
        db_session.flush()

        entry = {
            "user": {
                "id": self.competitor.id,
                "alias_id": "Alpha-Comp",
                "role": "competitor",
                "challenge_id": self.challenge.id,
                "is_anonymous": False,
                "name": "Alice",
                "surname": "Smith",
                "manual_points": {},
            },
            "task_scores": {},
            "public_score": 0.95,
            "private_score": 0.92,
            "total_points": 80,
            "has_submitted": True,
        }
        mock_build.return_value = [entry]

        res = client.get(
            f"/api/challenges/{self.challenge.id}/leaderboard",
            headers=self._auth(self.competitor_token),
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["is_finalized"] is True

    @patch("routes.leaderboard.build_and_cache_leaderboard")
    def test_scores_finalized_results_hidden_shows_only_public_and_ranks_by_public(
        self, mock_build, client, db_session
    ):
        self.challenge.scores_finalized = True
        self.challenge.reveal_results = False
        db_session.flush()

        entries = [
            {
                "user": {
                    "id": self.competitor.id,
                    "alias_id": "Alpha-Comp",
                    "role": "competitor",
                    "challenge_id": self.challenge.id,
                    "is_anonymous": False,
                    "name": "Alice",
                    "surname": "Smith",
                    "manual_points": {"1": 10},
                },
                "task_scores": {
                    "1": {"public_score": 0.50, "private_score": 0.90, "submission_id": 101}
                },
                "public_score": 0.50,
                "private_score": 0.90,
                "total_points": 10,
                "has_submitted": True,
            },
            {
                "user": {
                    "id": self.other_competitor.id,
                    "alias_id": "Beta-Comp",
                    "role": "competitor",
                    "challenge_id": self.challenge.id,
                    "is_anonymous": False,
                    "name": "Bob",
                    "surname": "Jones",
                    "manual_points": {"1": 20},
                },
                "task_scores": {
                    "1": {"public_score": 0.80, "private_score": 0.40, "submission_id": 102}
                },
                "public_score": 0.80,
                "private_score": 0.40,
                "total_points": 20,
                "has_submitted": True,
            },
        ]
        mock_build.return_value = entries

        res = client.get(
            f"/api/challenges/{self.challenge.id}/leaderboard",
            headers=self._auth(self.competitor_token),
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["is_finalized"] is True
        assert data["reveal_results"] is False

        leaderboard = data["leaderboard"]
        assert len(leaderboard) == 2
        # Since they are ranked on public score (higher is better), Beta-Comp (0.80) should be rank 1, Alpha-Comp (0.50) should be rank 2.
        assert leaderboard[0]["user"]["id"] == self.other_competitor.id
        assert leaderboard[0]["rank"] == 1
        assert leaderboard[0]["private_score"] is None
        assert leaderboard[0]["total_points"] == 0

        assert leaderboard[1]["user"]["id"] == self.competitor.id
        assert leaderboard[1]["rank"] == 2
        assert leaderboard[1]["private_score"] is None
        assert leaderboard[1]["total_points"] == 0

    @patch("routes.leaderboard.build_and_cache_leaderboard")
    def test_leaderboard_response_shape(self, mock_build, client):
        mock_build.return_value = []
        res = client.get(
            f"/api/challenges/{self.challenge.id}/leaderboard", headers=self._auth(self.admin_token)
        )
        assert res.status_code == 200
        data = res.get_json()
        assert "challenge_title" in data
        assert "metric_name" in data
        assert "is_normalized" in data
        assert "is_finalized" in data
        assert "reveal_results" in data
        assert "tasks" in data
        assert "leaderboard" in data


class TestManualPointsEndpoint:
    @pytest.fixture(autouse=True)
    def _setup(self, db_session, redis_flush):
        self.admin = User(
            username="mp_admin",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            alias_id="Admin-MP",
        )
        db_session.add(self.admin)

        self.jury = User(
            username="mp_jury", password_hash="pbkdf2:sha256:...", role="jury", alias_id="Jury-MP"
        )
        db_session.add(self.jury)

        self.challenge = Challenge(
            title="MP Challenge",
            description="Manual points challenge",
            max_eval_requests=10,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2),
            scores_finalized=False,
        )
        db_session.add(self.challenge)
        db_session.commit()

        self.competitor = User(
            username="mp_comp",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="MP-Comp",
            challenge_id=self.challenge.id,
        )
        db_session.add(self.competitor)

        self.task = Task(
            challenge_id=self.challenge.id,
            title="MP Task",
            description="Task for manual points",
            ram_limit_mb=4096,
            time_limit_sec=60,
            gpu_required=False,
            files="[]",
        )
        db_session.add(self.task)
        db_session.commit()

        self.admin_token = generate_token(self.admin.id, self.admin.role)
        self.jury_token = generate_token(self.jury.id, self.jury.role)
        self.competitor_token = generate_token(self.competitor.id, self.competitor.role)

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def _seed_completed_submission(self, db_session):
        sub = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
            public_score=0.8,
            code_cells="[]",
        )
        db_session.add(sub)
        db_session.commit()
        sub_id = sub.id
        db_session.flush()
        return sub_id

    def test_admin_saves_manual_points(self, client, db_session):
        self._seed_completed_submission(db_session)
        payload = {
            "user_id": self.competitor.id,
            "points": {str(self.task.id): 85},
            "reason": "Good performance",
        }
        res = client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            headers=self._auth(self.admin_token),
            json=payload,
        )
        assert res.status_code == 200
        data = res.get_json()
        assert "message" in data
        assert data["user_id"] == self.competitor.id
        assert data["manual_points"][str(self.task.id)] == 85

    def test_jury_saves_manual_points(self, client, db_session):
        self._seed_completed_submission(db_session)
        payload = {
            "user_id": self.competitor.id,
            "points": {str(self.task.id): 75},
            "reason": "Decent solution",
        }
        res = client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            headers=self._auth(self.jury_token),
            json=payload,
        )
        assert res.status_code == 200

    def test_competitor_cannot_save_manual_points(self, client):
        payload = {"user_id": self.competitor.id, "points": {str(self.task.id): 50}}
        res = client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            headers=self._auth(self.competitor_token),
            json=payload,
        )
        assert res.status_code == 403

    def test_missing_user_id_returns_400(self, client):
        payload = {"points": {str(self.task.id): 50}}
        res = client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            headers=self._auth(self.admin_token),
            json=payload,
        )
        assert res.status_code == 400
        assert "Missing" in res.get_json()["error"]

    def test_missing_points_dict_returns_400(self, client):
        payload = {"user_id": self.competitor.id}
        res = client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            headers=self._auth(self.admin_token),
            json=payload,
        )
        assert res.status_code == 400

    def test_user_not_registered_in_challenge_returns_404(self, client, db_session):
        other_challenge = Challenge(
            title="Other MP Challenge",
            description="Unrelated",
            max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2),
        )
        db_session.add(other_challenge)
        db_session.commit()

        payload = {"user_id": 99999, "points": {str(self.task.id): 50}}
        res = client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            headers=self._auth(self.admin_token),
            json=payload,
        )
        assert res.status_code == 404

    def test_reason_required_when_finalized(self, client, db_session):
        self.challenge.scores_finalized = True
        db_session.flush()

        payload = {"user_id": self.competitor.id, "points": {str(self.task.id): 50}}
        res = client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            headers=self._auth(self.admin_token),
            json=payload,
        )
        assert res.status_code == 400
        assert "reason" in res.get_json()["error"].lower()

    def test_invalid_task_id_returns_400(self, client):
        payload = {"user_id": self.competitor.id, "points": {"invalid": 50}}
        res = client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            headers=self._auth(self.admin_token),
            json=payload,
        )
        assert res.status_code == 400

    def test_task_not_in_challenge_returns_400(self, client, db_session):
        other_task = Task(
            challenge_id=99999,
            title="Orphan Task",
            description="Not in this challenge",
            ram_limit_mb=1024,
            time_limit_sec=60,
        )
        db_session.add(other_task)
        db_session.commit()

        payload = {"user_id": self.competitor.id, "points": {str(other_task.id): 50}}
        res = client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            headers=self._auth(self.admin_token),
            json=payload,
        )
        assert res.status_code == 400
        assert "does not belong" in res.get_json()["error"].lower()

    def test_points_must_be_integer_returns_400(self, client):
        payload = {"user_id": self.competitor.id, "points": {str(self.task.id): 50.5}}
        res = client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            headers=self._auth(self.admin_token),
            json=payload,
        )
        assert res.status_code == 400

    def test_points_out_of_bounds_returns_400(self, client):
        payload = {"user_id": self.competitor.id, "points": {str(self.task.id): 150}}
        res = client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            headers=self._auth(self.admin_token),
            json=payload,
        )
        assert res.status_code == 400
        assert "must be between 0 and 100" in res.get_json()["error"]

    def test_no_completed_submissions_returns_400(self, client):
        payload = {
            "user_id": self.competitor.id,
            "points": {str(self.task.id): 50},
            "reason": "Testing",
        }
        res = client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            headers=self._auth(self.admin_token),
            json=payload,
        )
        assert res.status_code == 400
        assert "no completed submissions" in res.get_json()["error"].lower()

    def test_manual_points_updates_single_task(self, client, db_session):
        self._seed_completed_submission(db_session)

        payload = {
            "user_id": self.competitor.id,
            "points": {str(self.task.id): 85},
            "reason": "Initial scoring",
        }
        res = client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            headers=self._auth(self.admin_token),
            json=payload,
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["manual_points"][str(self.task.id)] == 85

    def test_manual_points_accepts_consecutive_calls(self, client, db_session):
        self._seed_completed_submission(db_session)

        payload = {
            "user_id": self.competitor.id,
            "points": {str(self.task.id): 70},
            "reason": "First",
        }
        res = client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            headers=self._auth(self.admin_token),
            json=payload,
        )
        assert res.status_code == 200

        payload["points"] = {str(self.task.id): 90}
        payload["reason"] = "Second"
        res = client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            headers=self._auth(self.admin_token),
            json=payload,
        )
        assert res.status_code == 200

    @patch("cache_utils.invalidate_leaderboard_cache")
    def test_cache_invalidated_on_manual_points_save(self, mock_invalidate, client, db_session):
        self._seed_completed_submission(db_session)
        payload = {
            "user_id": self.competitor.id,
            "points": {str(self.task.id): 80},
            "reason": "Cache test",
        }
        res = client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            headers=self._auth(self.admin_token),
            json=payload,
        )
        assert res.status_code == 200
        mock_invalidate.assert_called_once_with(self.challenge.id)

    def test_challenge_not_found_returns_404(self, client):
        payload = {"user_id": self.competitor.id, "points": {str(self.task.id): 50}}
        res = client.post(
            "/api/challenges/99999/manual-points",
            headers=self._auth(self.admin_token),
            json=payload,
        )
        assert res.status_code == 404
