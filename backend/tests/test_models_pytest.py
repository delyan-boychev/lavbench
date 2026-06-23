import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models import db, Submission, User, Challenge, Task
from datetime import datetime


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
            user_id=user.id, challenge_id=challenge.id, task_id=task.id, status="completed"
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
            title="Test Dict", start_time=datetime(2024, 1, 1), end_time=datetime(2026, 1, 1)
        )
        db.session.add(challenge)
        db.session.commit()

        task = Task(challenge_id=challenge.id, title="Test Task Dict")
        db.session.add(task)
        db.session.commit()

        sub = Submission(
            user_id=user.id, challenge_id=challenge.id, task_id=task.id, status="completed"
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
            res = self.sub.to_dict_light()
            mock_open.assert_not_called()
