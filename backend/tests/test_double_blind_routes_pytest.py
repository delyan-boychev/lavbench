import os
import sys
import json
import csv
import io
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models import db, User, Challenge, Task, Submission, AuditLog
from auth_utils import generate_token


class TestDoubleBlindAndLeaderboardRules:
    @pytest.fixture(autouse=True)
    def _setup(self, db_session, redis_flush):
        # 1. Admin
        self.admin = User(
            username="db_admin",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            alias_id="Admin-DB",
        )
        db_session.add(self.admin)

        # 2. Jury
        self.jury = User(
            username="db_jury",
            password_hash="pbkdf2:sha256:...",
            role="jury",
            alias_id="Jury-DB",
        )
        db_session.add(self.jury)

        # 3. Active Double Blind Challenge
        self.challenge = Challenge(
            title="Double Blind Competition",
            description="Active double-blind challenge",
            max_eval_requests=10,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2),
            is_frozen=False,
            double_blind=True,
            reveal_results=False,  # hidden initially
            scores_finalized=False,
        )
        db_session.add(self.challenge)
        db_session.commit()

        # 4. Competitors
        self.competitor = User(
            username="db_comp1",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Comp-Alpha",
            challenge_id=self.challenge.id,
            email="alice@test.com",
        )
        self.competitor.set_demographics("Alice", "Smith", "10", "Test School", "Test City")
        db_session.add(self.competitor)

        self.other_competitor = User(
            username="db_comp2",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Comp-Beta",
            challenge_id=self.challenge.id,
        )
        self.other_competitor.set_demographics("Bob", "Jones", "11", "Other School", "Other City")
        db_session.add(self.other_competitor)

        # 5. Task
        self.task = Task(
            challenge_id=self.challenge.id,
            title="DB Task",
            description="Task for testing",
            ram_limit_mb=4096,
            time_limit_sec=60,
            gpu_required=False,
            files="[]",
        )
        db_session.add(self.task)
        db_session.commit()

        # Generate tokens
        self.admin_token = generate_token(self.admin.id, self.admin.role)
        self.jury_token = generate_token(self.jury.id, self.jury.role)
        self.competitor_token = generate_token(self.competitor.id, self.competitor.role)

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    @patch("routes.leaderboard.build_and_cache_leaderboard")
    def test_jury_cannot_see_names_during_active_double_blind(self, mock_build, client, db_session):
        # Mock leaderboard data
        entry_comp = {
            "user": {
                "id": self.competitor.id,
                "alias_id": "Comp-Alpha",
                "role": "competitor",
                "challenge_id": self.challenge.id,
                "is_anonymous": False,
                "name": "Alice",
                "surname": "Smith",
                "email": "alice@test.com",
            },
            "task_scores": {},
            "public_score": 0.9,
            "private_score": 0.85,
            "total_points": 50,
            "has_submitted": True,
        }
        mock_build.return_value = [entry_comp]

        # Request as jury
        res = client.get(
            f"/api/challenges/{self.challenge.id}/leaderboard", headers=self._auth(self.jury_token)
        )
        assert res.status_code == 200
        data = res.get_json()
        leaderboard = data["leaderboard"]

        user_info = leaderboard[0]["user"]
        assert "name" not in user_info
        assert "email" not in user_info
        assert user_info["alias_id"] == "Comp-Alpha"

        # Request as admin (should see names)
        res_admin = client.get(
            f"/api/challenges/{self.challenge.id}/leaderboard", headers=self._auth(self.admin_token)
        )
        assert res_admin.status_code == 200
        user_info_admin = res_admin.get_json()["leaderboard"][0]["user"]
        assert "name" in user_info_admin
        assert user_info_admin["name"] == "Alice"

    @patch("routes.leaderboard.build_and_cache_leaderboard")
    def test_points_visibility_rules(self, mock_build, client, db_session):
        # Mock manual points inside entry["user"]
        entry_comp = {
            "user": {
                "id": self.competitor.id,
                "alias_id": "Comp-Alpha",
                "role": "competitor",
                "challenge_id": self.challenge.id,
                "is_anonymous": False,
                "name": "Alice",
                "surname": "Smith",
                "manual_points": {str(self.task.id): 45},
            },
            "task_scores": {
                str(self.task.id): {
                    "public_score": 0.9,
                    "private_score": 0.85,
                    "submission_id": 1,
                }
            },
            "public_score": 0.9,
            "private_score": 0.85,
            "total_points": 45,
            "has_submitted": True,
        }
        mock_build.return_value = [entry_comp]

        # Competitor gets public scores but NO points (since not finalized & results hidden)
        res_comp = client.get(
            f"/api/challenges/{self.challenge.id}/leaderboard",
            headers=self._auth(self.competitor_token),
        )
        assert res_comp.status_code == 200
        comp_leaderboard = res_comp.get_json()["leaderboard"]
        assert comp_leaderboard[0]["public_score"] == 0.9
        assert comp_leaderboard[0]["private_score"] is None
        assert comp_leaderboard[0]["total_points"] == 0  # hidden/zeroed
        assert comp_leaderboard[0]["user"]["manual_points"] == {}

        # Jury gets points for grading even if details are anonymized
        res_jury = client.get(
            f"/api/challenges/{self.challenge.id}/leaderboard", headers=self._auth(self.jury_token)
        )
        assert res_jury.status_code == 200
        jury_leaderboard = res_jury.get_json()["leaderboard"]
        assert jury_leaderboard[0]["total_points"] == 45
        assert jury_leaderboard[0]["user"]["manual_points"] == {str(self.task.id): 45}

    @patch("routes.leaderboard.build_and_cache_leaderboard")
    def test_csv_export_anonymization(self, mock_build, client, db_session):
        # Mock leaderboard data
        entry_comp = {
            "user": {
                "id": self.competitor.id,
                "alias_id": "Comp-Alpha",
                "role": "competitor",
                "challenge_id": self.challenge.id,
                "is_anonymous": False,
                "name": "Alice",
                "surname": "Smith",
                "email": "alice@test.com",
                "school": "AliceSchool",
                "city": "AliceCity",
                "grade": "10",
            },
            "task_scores": {},
            "public_score": 0.9,
            "private_score": 0.85,
            "total_points": 50,
            "has_submitted": True,
        }
        mock_build.return_value = [entry_comp]

        # Log some audit log
        audit = AuditLog(
            admin_id=self.admin.id,
            target_user_id=self.competitor.id,
            task_id=self.task.id,
            old_score=0.5,
            new_score=0.9,
            reason="Score corrected",
        )
        db_session.add(audit)
        db_session.commit()

        # 1. Jury export -> Anonymized demographics & audit log target user
        res_jury = client.get(
            f"/api/challenges/{self.challenge.id}/export-results",
            headers=self._auth(self.jury_token),
        )
        assert res_jury.status_code == 200
        csv_text = res_jury.data.decode("utf-8")
        csv_reader = csv.reader(io.StringIO(csv_text))
        rows = list(csv_reader)

        # Check column index mapping in header
        header = rows[0]
        username_idx = header.index("Username")
        name_idx = header.index("Real Name")
        email_idx = header.index("Email")
        school_idx = header.index("School")

        # Competitor row data
        comp_row = rows[1]
        assert comp_row[username_idx] == "Comp-Alpha"
        assert comp_row[name_idx] == "Comp-Alpha"
        assert comp_row[email_idx] == "N/A"
        assert comp_row[school_idx] == "N/A"

        # Check audit log target student
        audit_idx = rows.index(["--- SCORE CORRECTION AUDIT LOG ---"])
        audit_header = rows[audit_idx + 1]
        target_student_idx = audit_header.index("Target Student")
        audit_row = rows[audit_idx + 2]
        assert audit_row[target_student_idx] == "Comp-Alpha"

        # 2. Admin export -> Full unblinded data
        res_admin = client.get(
            f"/api/challenges/{self.challenge.id}/export-results",
            headers=self._auth(self.admin_token),
        )
        assert res_admin.status_code == 200
        csv_text_admin = res_admin.data.decode("utf-8")
        rows_admin = list(csv.reader(io.StringIO(csv_text_admin)))
        comp_row_admin = rows_admin[1]
        assert comp_row_admin[username_idx] == "db_comp1"
        assert comp_row_admin[name_idx] == "Alice Smith"
        assert comp_row_admin[email_idx] == "alice@test.com"
        assert comp_row_admin[school_idx] == "Test School"

        audit_row_admin = rows_admin[audit_idx + 2]
        assert audit_row_admin[target_student_idx] == "db_comp1"
