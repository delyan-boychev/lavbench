import os
import sys
import json
import pytest
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models import User, Challenge, Task, Submission
from auth_utils import generate_token


class TestLeaderboardOrderingAndFinalizationConstraints:
    @pytest.fixture(autouse=True)
    def _setup(self, db_session, client, redis_flush):
        self.client = client

        # Create Jury member
        self.jury = User(
            username="test_jury_eq",
            email="jury_eq@example.com",
            role="jury",
            password_hash="pbkdf2:sha256:...",
        )
        db_session.add(self.jury)

        # Create Admin member
        self.admin = User(
            username="test_admin_eq",
            email="admin_eq@example.com",
            role="admin",
            password_hash="pbkdf2:sha256:...",
        )
        db_session.add(self.admin)

        # Create Challenge (active, ends in past to allow finalization)
        self.challenge = Challenge(
            title="Ordering Edge Cases Challenge",
            description="Test challenge",
            max_eval_requests=10,
            start_time=datetime.utcnow() - timedelta(hours=5),
            end_time=datetime.utcnow() - timedelta(minutes=10),
            is_frozen=False,
            double_blind=False,
            reveal_results=True,
            scores_finalized=False,
        )
        db_session.add(self.challenge)
        db_session.commit()

        # Tasks for the challenge
        self.task1 = Task(
            challenge_id=self.challenge.id,
            title="Task Alpha",
            description="First task",
            ram_limit_mb=4096,
            time_limit_sec=60,
        )
        self.task2 = Task(
            challenge_id=self.challenge.id,
            title="Task Beta",
            description="Second task",
            ram_limit_mb=4096,
            time_limit_sec=60,
        )
        db_session.add_all([self.task1, self.task2])
        db_session.commit()

        # Set up competitor accounts with password hashes
        self.comp_no_sub = User(
            username="student_no_sub",
            role="competitor",
            alias_id="NoSubStudent",
            password_hash="pbkdf2:sha256:...",
            challenge_id=self.challenge.id,
        )
        self.comp_failed_sub = User(
            username="student_failed_sub",
            role="competitor",
            alias_id="FailedSubStudent",
            password_hash="pbkdf2:sha256:...",
            challenge_id=self.challenge.id,
        )
        self.comp_successful_sub_high = User(
            username="student_high_score",
            role="competitor",
            alias_id="HighScoreStudent",
            password_hash="pbkdf2:sha256:...",
            challenge_id=self.challenge.id,
        )
        self.comp_successful_sub_low = User(
            username="student_low_score",
            role="competitor",
            alias_id="LowScoreStudent",
            password_hash="pbkdf2:sha256:...",
            challenge_id=self.challenge.id,
        )
        db_session.add_all(
            [
                self.comp_no_sub,
                self.comp_failed_sub,
                self.comp_successful_sub_high,
                self.comp_successful_sub_low,
            ]
        )
        db_session.commit()

        # Generate tokens
        self.jury_token = generate_token(self.jury.id, "jury")
        self.admin_token = generate_token(self.admin.id, "admin")
        self.comp_token = generate_token(self.comp_successful_sub_high.id, "competitor")

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_permissions_for_setting_points_and_finalization(self):
        # Competitor tries to save manual points -> 403 Forbidden
        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            headers=self._auth(self.comp_token),
            json={"user_id": self.comp_successful_sub_high.id, "points": {str(self.task1.id): 50}},
        )
        assert res.status_code == 403

        # Competitor tries to finalize -> 403 Forbidden
        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/finalize",
            headers=self._auth(self.comp_token),
            json={"reveal_results": True},
        )
        assert res.status_code == 403

        # Jury / Admin tries to save manual points for user with no submissions -> 400 Bad Request
        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            headers=self._auth(self.jury_token),
            json={"user_id": self.comp_no_sub.id, "points": {str(self.task1.id): 10}},
        )
        assert res.status_code == 400
        assert "only students with submissions" in res.get_json()["error"].lower()

    def test_failed_submissions_require_jury_points(self, db_session):
        # Student failed sub has 1 failed submission
        sub = Submission(
            challenge_id=self.challenge.id,
            task_id=self.task1.id,
            user_id=self.comp_failed_sub.id,
            status="failed",
            code_cells="[]",
        )
        db_session.add(sub)
        db_session.commit()

        # Try to finalize with missing manual points for comp_failed_sub -> 400 Bad Request
        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/finalize",
            headers=self._auth(self.jury_token),
            json={"reveal_results": True},
        )
        assert res.status_code == 400
        assert "missing manual points" in res.get_json()["error"].lower()

        # Assign 0 points to comp_failed_sub -> 200 OK (0 points are valid points)
        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            headers=self._auth(self.jury_token),
            json={
                "user_id": self.comp_failed_sub.id,
                "points": {str(self.task1.id): 0},
                "reason": "Failed submission graded as 0",
            },
        )
        assert res.status_code == 200

        # Now finalize should succeed (other users have no submissions, so they default to 0 and don't block finalization)
        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/finalize",
            headers=self._auth(self.jury_token),
            json={"reveal_results": True},
        )
        assert res.status_code == 200
        assert self.challenge.scores_finalized is True

    def test_ordering_rules_before_and_after_finalization(self, db_session):
        # Create successful submissions for High & Low
        sub_high = Submission(
            challenge_id=self.challenge.id,
            task_id=self.task1.id,
            user_id=self.comp_successful_sub_high.id,
            status="completed",
            public_score=90.0,
            private_score=95.0,
            execution_time_ms=100,
        )
        sub_low = Submission(
            challenge_id=self.challenge.id,
            task_id=self.task1.id,
            user_id=self.comp_successful_sub_low.id,
            status="completed",
            public_score=40.0,
            private_score=50.0,
            execution_time_ms=200,
        )
        # Create a failed submission for failed_sub student
        sub_failed = Submission(
            challenge_id=self.challenge.id,
            task_id=self.task1.id,
            user_id=self.comp_failed_sub.id,
            status="failed",
        )
        db_session.add_all([sub_high, sub_low, sub_failed])
        db_session.commit()

        # Before finalization, check sorting:
        # High score student (public_score = 90.0) should be 1st
        # Low score student (public_score = 40.0) should be 2nd
        # Failed/No sub students should be ranked below active ones (or based on has_submitted)
        res = self.client.get(
            f"/api/challenges/{self.challenge.id}/leaderboard",
            headers=self._auth(self.jury_token),
        )
        assert res.status_code == 200
        data = res.get_json()
        leaderboard = data["leaderboard"]

        # High score student is first
        assert leaderboard[0]["user"]["username"] == "student_high_score"
        # Low score student is second
        assert leaderboard[1]["user"]["username"] == "student_low_score"

        # Now, try to finalize. Will fail because points are missing for task1 & task2
        # (For High, Low, and FailedSub students since they have submissions)
        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/finalize",
            headers=self._auth(self.jury_token),
            json={"reveal_results": True},
        )
        assert res.status_code == 400

        # Save manual points:
        # Give High Score student -> 5 points
        # Give Low Score student -> 95 points (so they will rank 1st after finalization!)
        # Give Failed Sub student -> 0 points
        res1 = self.client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            headers=self._auth(self.jury_token),
            json={"user_id": self.comp_successful_sub_high.id, "points": {str(self.task1.id): 5}},
        )
        assert res1.status_code == 200

        res2 = self.client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            headers=self._auth(self.jury_token),
            json={"user_id": self.comp_successful_sub_low.id, "points": {str(self.task1.id): 95}},
        )
        assert res2.status_code == 200

        res3 = self.client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            headers=self._auth(self.jury_token),
            json={"user_id": self.comp_failed_sub.id, "points": {str(self.task1.id): 0}},
        )
        assert res3.status_code == 200

        # Now finalize should work!
        res_fin = self.client.post(
            f"/api/challenges/{self.challenge.id}/finalize",
            headers=self._auth(self.jury_token),
            json={"reveal_results": True},
        )
        assert res_fin.status_code == 200
        assert self.challenge.scores_finalized is True

        # Expire all to clear the session cache
        db_session.expire_all()

        from cache_utils import invalidate_leaderboard_cache

        invalidate_leaderboard_cache(self.challenge.id, delete_only=True)

        # Fetch leaderboard again.
        # Now, it must sort based on manual points (total_points):
        # 1. Low score student: 95 points
        # 2. High score student: 5 points
        # 3. Failed sub student: 0 points
        # 4. No sub student: 0 points (rank 3 or 4)
        res = self.client.get(
            f"/api/challenges/{self.challenge.id}/leaderboard",
            headers=self._auth(self.jury_token),
        )
        assert res.status_code == 200
        data = res.get_json()
        leaderboard = data["leaderboard"]
        print("LEADERBOARD:", json.dumps(leaderboard, indent=2))

        assert leaderboard[0]["user"]["username"] == "student_low_score"
        assert leaderboard[0]["total_points"] == 95
        assert leaderboard[0]["rank"] == 1

        assert leaderboard[1]["user"]["username"] == "student_high_score"
        assert leaderboard[1]["total_points"] == 5
        assert leaderboard[1]["rank"] == 2

        # The third and fourth place are both 0 points.
        # Ranks should share/be tied or determined appropriately
        assert leaderboard[2]["total_points"] == 0
        assert leaderboard[3]["total_points"] == 0
        assert leaderboard[2]["rank"] == 3
        assert leaderboard[3]["rank"] == 3
