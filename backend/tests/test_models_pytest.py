import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime import datetime, timedelta

from models import AuditLog, Challenge, Stage, Submission, Task, User, db


class TestSubmissionFileCleanup:
    @pytest.fixture(autouse=True)
    def setup(self, app, db_session):
        app.config["UPLOAD_FOLDER"] = tempfile.mkdtemp()
        self.submission_code_dir = os.path.join(app.config["UPLOAD_FOLDER"], "submissions")
        self.submission_log_dir = os.path.join(app.config["UPLOAD_FOLDER"], "logs")
        os.makedirs(self.submission_code_dir, exist_ok=True)
        os.makedirs(self.submission_log_dir, exist_ok=True)

        user = User(username="testuser", password_hash="x", role="competitor")
        db.session.add(user)
        challenge = Challenge(
            title="Test", start_time=datetime(2024, 1, 1), end_time=datetime(2026, 1, 1)
        )
        db.session.add(challenge)
        db.session.commit()

        task = Task(challenge_id=challenge.id, title="Test Task")
        db.session.add(task)
        db.session.commit()

        sub = Submission(
            user_id=user.id,
            challenge_id=challenge.id,
            task_id=task.id,
            status="completed",
        )
        sub.code_cells = "[]"
        sub.logs = "test log"
        db.session.add(sub)
        db.session.commit()
        self.code_path = sub.code_storage_path
        self.log_path = sub.log_storage_path
        self.sub = sub

    def test_files_deleted_on_orm_delete(self):
        assert os.path.exists(self.code_path)
        assert os.path.exists(self.log_path)

        db.session.delete(self.sub)
        db.session.commit()

        assert not os.path.exists(self.code_path)
        assert not os.path.exists(self.log_path)

    def test_no_error_on_missing_files(self):
        os.remove(self.code_path)
        os.remove(self.log_path)
        db.session.delete(self.sub)
        db.session.commit()


class TestSubmissionToDict:
    @pytest.fixture(autouse=True)
    def setup(self, app, db_session):
        app.config["UPLOAD_FOLDER"] = tempfile.mkdtemp()
        user = User(username="testuser_dict", password_hash="x", role="competitor")
        db.session.add(user)
        challenge = Challenge(
            title="Test Dict",
            start_time=datetime(2024, 1, 1),
            end_time=datetime(2026, 1, 1),
        )
        db.session.add(challenge)
        db.session.commit()

        task = Task(challenge_id=challenge.id, title="Test Task Dict")
        db.session.add(task)
        db.session.commit()

        sub = Submission(
            user_id=user.id,
            challenge_id=challenge.id,
            task_id=task.id,
            status="completed",
        )
        sub.code_cells = '["print(1)"]'
        sub.logs = "evaluated logs"
        db.session.add(sub)
        db.session.commit()
        self.sub = sub

    def test_to_dict_includes_large_fields(self):
        res = self.sub.to_dict()
        assert res["code_cells"] == '["print(1)"]'
        assert res["logs"] == "evaluated logs"

    def test_to_dict_excludes_large_fields(self):
        res = self.sub.to_dict(include_large_fields=False)
        assert res["code_cells"] == "[]"
        assert res["logs"] is None

    def test_to_dict_light_excludes_large_fields_and_keys(self):
        res = self.sub.to_dict_light()
        assert "code_cells" not in res
        assert "logs" not in res

    def test_to_dict_light_no_disk_read(self):
        from unittest.mock import patch

        with patch("builtins.open") as mock_open:
            self.sub.to_dict_light()
            mock_open.assert_not_called()


class TestUserDemographicsAndFields:
    @pytest.fixture(autouse=True)
    def setup(self, app, db_session):
        self.challenge = Challenge(
            title="User Test Challenge",
            start_time=datetime(2024, 1, 1),
            end_time=datetime(2026, 1, 1),
            double_blind=True,
            reveal_results=True,
        )
        db.session.add(self.challenge)
        db.session.commit()

        self.user = User(
            username="demouser",
            password_hash="pw_hash",
            role="competitor",
            challenge_id=self.challenge.id,
            is_anonymous=False,
            manual_points={"1": 10},
        )
        self.user.set_demographics("John", "Doe", "12", "High School", "Sofia")
        db.session.add(self.user)
        db.session.commit()

    def test_demographics_symmetric_encryption(self):
        # Verify demographics are encrypted (stored differently from plaintext)
        raw_user = db.session.query(User).filter_by(username="demouser").first()
        assert raw_user.name != "John"
        assert raw_user.surname != "Doe"
        assert raw_user.grade != "12"
        assert raw_user.school != "High School"
        assert raw_user.city != "Sofia"

    def test_to_dict_authorized_viewers(self):
        # Admin viewer: should decrypt demographics
        res_admin = self.user.to_dict(view_role="admin")
        assert res_admin["name"] == "John"
        assert res_admin["surname"] == "Doe"
        assert res_admin["city"] == "Sofia"

        # Self viewer: should decrypt demographics
        res_self = self.user.to_dict(view_role="competitor", current_user_id=self.user.id)
        assert res_self["name"] == "John"
        assert res_self["surname"] == "Doe"

    def test_to_dict_double_blind_hiding(self):
        # Other competitor viewer: should hide demographics
        res_other = self.user.to_dict(view_role="competitor", current_user_id=999)
        assert "name" not in res_other
        assert "surname" not in res_other
        assert res_other["alias_id"] == self.user.alias_id

        # Jury viewer after challenge has started: should hide demographics
        self.challenge.start_time = datetime.utcnow() - timedelta(hours=1)
        db.session.commit()
        res_jury = self.user.to_dict(view_role="jury", current_user_id=999)
        assert "name" not in res_jury
        assert "surname" not in res_jury

    def test_to_dict_anonymous_user(self):
        # Anonymous user details hidden from other competitors even if double-blind is false
        self.challenge.double_blind = False
        self.user.is_anonymous = True
        db.session.commit()

        res = self.user.to_dict(view_role="competitor", current_user_id=999)
        assert "name" not in res
        assert "username" not in res


class TestChallengeStatusAndTiming:
    def test_challenge_timing_properties(self, db_session):
        challenge = Challenge(
            title="Timing Challenge",
            timezone="UTC",
            start_time=datetime.utcnow(),
            end_time=datetime.utcnow() + timedelta(hours=5),
        )
        db.session.add(challenge)
        db.session.commit()

        now_local = challenge._now_local()

        # Not started
        challenge.start_time = now_local + timedelta(hours=2)
        challenge.end_time = now_local + timedelta(hours=4)
        db.session.commit()
        assert challenge.is_started is False
        assert challenge.is_ended is False
        assert challenge.computed_status == "not_started"

        # Started/Active
        challenge.start_time = now_local - timedelta(hours=1)
        db.session.commit()
        assert challenge.is_started is True
        assert challenge.is_ended is False
        assert challenge.computed_status == "active"

        # Frozen
        challenge.is_frozen = True
        db.session.commit()
        assert challenge.computed_status == "frozen"

        # Ended
        challenge.is_frozen = False
        challenge.end_time = now_local - timedelta(minutes=10)
        db.session.commit()
        assert challenge.is_ended is True
        assert challenge.computed_status == "ended"

        # Finalized
        challenge.scores_finalized = True
        db.session.commit()
        assert challenge.computed_status == "finalized"

        # Archived
        challenge.is_archived = True
        db.session.commit()
        assert challenge.computed_status == "archived"


class TestStageConstraints:
    def test_stage_uniqueness_constraint(self, db_session):
        from sqlalchemy.exc import IntegrityError

        challenge = Challenge(
            title="Stage Constraint Challenge",
            start_time=datetime(2024, 1, 1),
            end_time=datetime(2026, 1, 1),
        )
        db.session.add(challenge)
        db.session.commit()

        stage1 = Stage(
            challenge_id=challenge.id,
            stage_number=1,
            title="Qualification",
            start_time=datetime.utcnow(),
            end_time=datetime.utcnow() + timedelta(hours=1),
        )
        db.session.add(stage1)
        db.session.commit()

        # Duplicate stage_number for the same challenge should raise IntegrityError
        stage2 = Stage(
            challenge_id=challenge.id,
            stage_number=1,
            title="Duplicate",
            start_time=datetime.utcnow(),
            end_time=datetime.utcnow() + timedelta(hours=1),
        )
        db.session.add(stage2)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


class TestTaskCredentials:
    def test_task_hf_api_key_encryption(self, db_session):
        challenge = Challenge(
            title="Task Credentials Challenge",
            start_time=datetime(2024, 1, 1),
            end_time=datetime(2026, 1, 1),
        )
        db.session.add(challenge)
        db.session.commit()

        task = Task(challenge_id=challenge.id, title="HF Credentials Task")
        task.set_hf_api_key("hf_secret_token_123")
        db.session.add(task)
        db.session.commit()

        # Key should be encrypted in DB, but decryptable via getter
        raw_task = db.session.query(Task).filter_by(title="HF Credentials Task").first()
        assert raw_task.hf_api_key != "hf_secret_token_123"
        assert raw_task.get_hf_api_key() == "hf_secret_token_123"


class TestAuditLogRelationships:
    def test_audit_log_fields_and_admin_ref(self, db_session):
        admin = User(username="audit_admin", password_hash="x", role="admin")
        target = User(username="audit_user", password_hash="x", role="competitor")
        db.session.add_all([admin, target])
        db.session.commit()

        audit = AuditLog(
            admin_id=admin.id,
            target_user_id=target.id,
            action_type="update",
            target_type="user",
            details={"ip": "127.0.0.1"},
            old_score=10,
            new_score=20,
            reason="Score corrected",
        )
        db.session.add(audit)
        db.session.commit()

        retrieved = db.session.get(AuditLog, audit.id)
        assert retrieved.admin.username == "audit_admin"
        assert retrieved.target_user.username == "audit_user"
        assert retrieved.old_score == 10
        assert retrieved.new_score == 20
        assert retrieved.reason == "Score corrected"


class TestCompositeIndexes:
    def test_submissions_composite_indexes_exist(self):
        indexes = {idx.name for idx in Submission.__table__.indexes}
        assert "idx_sub_challenge_status_baseline" in indexes
        assert "idx_sub_challenge_created" in indexes
        assert "idx_sub_task_created" in indexes
        assert "idx_sub_task_user_created" in indexes
