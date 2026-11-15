"""Private scores follow one rule on every path, and admins may edit manual points."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from models import AuditLog, Challenge, Stage, Submission, Task, User
from utils.auth_utils import generate_token
from utils.dates import utcnow
from utils.score_visibility import (
    can_view_private_scores,
    private_scores_revealed,
    scores_final,
)


def _challenge(finalized=False, reveal=False):
    return SimpleNamespace(scores_finalized=finalized, reveal_results=reveal)


def _stage(finalized=False, reveal=False):
    return SimpleNamespace(is_finalized=finalized, reveal_results=reveal)


class TestScoreVisibilityRule:
    def test_admin_always_sees_private_scores(self):
        assert can_view_private_scores("admin", _challenge(), None)
        assert can_view_private_scores("admin", None, None)

    def test_jury_sees_private_scores_only_once_final(self):
        assert not can_view_private_scores("jury", _challenge(), None)
        assert not can_view_private_scores("jury", _challenge(), _stage())
        assert can_view_private_scores("jury", _challenge(), _stage(finalized=True))
        assert can_view_private_scores("jury", _challenge(finalized=True), None)

    def test_competitor_needs_final_and_reveal(self):
        assert not can_view_private_scores("competitor", _challenge(finalized=True), None)
        assert can_view_private_scores("competitor", _challenge(finalized=True, reveal=True), None)
        assert not can_view_private_scores("competitor", _challenge(), _stage(finalized=True))
        assert can_view_private_scores(
            "competitor", _challenge(), _stage(finalized=True, reveal=True)
        )

    def test_the_challenge_reveal_flag_wins_once_the_challenge_is_final(self):
        stage = _stage(finalized=True, reveal=True)
        assert not private_scores_revealed(_challenge(finalized=True, reveal=False), stage)
        assert scores_final(_challenge(finalized=True), None)
        assert not scores_final(_challenge(), _stage())


class TestPrivateScoresAcrossPaths:
    @pytest.fixture(autouse=True)
    def _setup(self, db_session, redis_flush):
        now = utcnow()
        self.challenge = Challenge(
            title="Visibility",
            description="private score gating",
            max_eval_requests=10,
            start_time=now - timedelta(hours=3),
            end_time=now + timedelta(hours=3),
            double_blind=False,
            reveal_results=False,
            scores_finalized=False,
        )
        db_session.add(self.challenge)
        db_session.commit()

        self.stage = Stage(
            challenge_id=self.challenge.id,
            title="Stage 1",
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
        )
        db_session.add(self.stage)
        db_session.commit()

        self.staged_task = Task(
            challenge_id=self.challenge.id,
            stage_id=self.stage.id,
            title="Staged task",
            files="[]",
        )
        self.loose_task = Task(challenge_id=self.challenge.id, title="Loose task", files="[]")
        self.admin = User(username="vis_admin", password_hash="x", role="admin", alias_id="A")
        self.jury = User(username="vis_jury", password_hash="x", role="jury", alias_id="J")
        self.competitor = User(
            username="vis_comp",
            password_hash="x",
            role="competitor",
            alias_id="C",
            challenge_id=self.challenge.id,
        )
        db_session.add_all([self.staged_task, self.loose_task, self.admin, self.jury])
        db_session.add(self.competitor)
        db_session.commit()

        self.staged_sub = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.staged_task.id,
            status="completed",
            public_score=0.5,
            private_score=0.9,
            code_cells="[]",
        )
        db_session.add(self.staged_sub)
        db_session.commit()

        self.tokens = {
            "admin": generate_token(self.admin.id, "admin"),
            "jury": generate_token(self.jury.id, "jury"),
            "competitor": generate_token(self.competitor.id, "competitor"),
        }

    def _get(self, client, path, role):
        return client.get(path, headers={"Authorization": f"Bearer {self.tokens[role]}"})

    def _entry(self):
        return {
            "user": {
                "id": self.competitor.id,
                "alias_id": "C",
                "role": "competitor",
                "challenge_id": self.challenge.id,
                "is_anonymous": False,
                "manual_points": {},
            },
            "task_scores": {
                str(self.staged_task.id): {
                    "public_score": 0.5,
                    "private_score": 0.9,
                    "submission_id": self.staged_sub.id,
                },
                str(self.loose_task.id): {
                    "public_score": 0.4,
                    "private_score": 0.7,
                    "submission_id": None,
                },
            },
            "public_score": 0.9,
            "private_score": 1.6,
            "total_points": 0,
            "has_submitted": True,
        }

    def _leaderboard_entry(self, client, role):
        with patch("routes.leaderboard.build_and_cache_leaderboard", return_value=[self._entry()]):
            res = self._get(client, f"/api/challenges/{self.challenge.id}/leaderboard", role)
        assert res.status_code == 200
        return res.get_json()["leaderboard"][0]

    def test_leaderboard_hides_private_scores_from_the_jury_until_final(self, client):
        entry = self._leaderboard_entry(client, "jury")
        assert entry["private_score"] is None
        assert all(s["private_score"] is None for s in entry["task_scores"].values())
        assert entry["task_scores"][str(self.staged_task.id)]["public_score"] == 0.5

    def test_leaderboard_shows_admins_every_private_score(self, client):
        entry = self._leaderboard_entry(client, "admin")
        assert entry["private_score"] == pytest.approx(1.6)
        assert entry["task_scores"][str(self.loose_task.id)]["private_score"] == 0.7

    def test_a_finalised_stage_reveals_only_its_tasks_to_the_jury(self, client, db_session):
        self.stage.is_finalized = True
        db_session.commit()
        entry = self._leaderboard_entry(client, "jury")
        assert entry["task_scores"][str(self.staged_task.id)]["private_score"] == 0.9
        assert entry["task_scores"][str(self.loose_task.id)]["private_score"] is None
        # The total only sums what the viewer may see
        assert entry["private_score"] == pytest.approx(0.9)

    def test_a_finalised_challenge_reveals_everything_to_the_jury(self, client, db_session):
        self.challenge.scores_finalized = True
        db_session.commit()
        entry = self._leaderboard_entry(client, "jury")
        assert entry["private_score"] == pytest.approx(1.6)

    def test_submission_detail_follows_the_same_rule(self, client, db_session):
        path = f"/api/submissions/{self.staged_sub.id}"
        assert self._get(client, path, "jury").get_json()["private_score"] is None
        assert self._get(client, path, "admin").get_json()["private_score"] == 0.9

        self.stage.is_finalized = True
        db_session.commit()
        assert self._get(client, path, "jury").get_json()["private_score"] == 0.9

        # Competitors read their own list (detail locks once the stage has ended)
        own_list = f"/api/tasks/{self.staged_task.id}/submissions"
        items = self._get(client, own_list, "competitor").get_json()["items"]
        assert items[0]["private_score"] is None

        self.stage.reveal_results = True
        db_session.commit()
        items = self._get(client, own_list, "competitor").get_json()["items"]
        assert items[0]["private_score"] == 0.9

    def test_admin_saves_manual_points_and_the_change_is_audited(self, client, db_session):
        res = client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            headers={"Authorization": f"Bearer {self.tokens['admin']}"},
            json={
                "user_id": str(self.competitor.id),
                "points": {str(self.staged_task.id): 42},
            },
        )
        assert res.status_code == 200
        assert res.get_json()["manual_points"][str(self.staged_task.id)] == 42
        audit = AuditLog.query.filter_by(target_user_id=self.competitor.id).one()
        assert audit.admin_id == self.admin.id
        assert audit.new_score == 42

    def test_jury_still_saves_manual_points(self, client):
        res = client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            headers={"Authorization": f"Bearer {self.tokens['jury']}"},
            json={
                "user_id": str(self.competitor.id),
                "points": {str(self.staged_task.id): 30},
            },
        )
        assert res.status_code == 200

    def test_competitor_cannot_save_manual_points(self, client):
        res = client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            headers={"Authorization": f"Bearer {self.tokens['competitor']}"},
            json={
                "user_id": str(self.competitor.id),
                "points": {str(self.staged_task.id): 30},
            },
        )
        assert res.status_code == 403
