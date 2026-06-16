import os
import sys
import tempfile
import unittest

os.environ["SECRET_KEY"] = "test-key"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import db, Submission, User, Challenge, Task
from datetime import datetime


class TestSubmissionFileCleanup(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['UPLOAD_FOLDER'] = tempfile.mkdtemp()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.submission_code_dir = os.path.join(self.app.config['UPLOAD_FOLDER'], "submissions")
        self.submission_log_dir = os.path.join(self.app.config['UPLOAD_FOLDER'], "logs")
        os.makedirs(self.submission_code_dir, exist_ok=True)
        os.makedirs(self.submission_log_dir, exist_ok=True)

        user = User(username='testuser', password_hash='x', role='competitor')
        db.session.add(user)
        challenge = Challenge(title='Test', start_time=datetime(2024, 1, 1), end_time=datetime(2026, 1, 1))
        db.session.add(challenge)
        db.session.commit()

        task = Task(challenge_id=challenge.id, title='Test Task')
        db.session.add(task)
        db.session.commit()

        self.sub = Submission(
            user_id=user.id, challenge_id=challenge.id, task_id=task.id, status='completed'
        )
        self.sub.code_cells = '[]'
        self.sub.logs = 'test log'
        db.session.add(self.sub)
        db.session.commit()
        self.code_path = self.sub.code_storage_path
        self.log_path = self.sub.log_storage_path

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_files_deleted_on_orm_delete(self):
        self.assertTrue(os.path.exists(self.code_path))
        self.assertTrue(os.path.exists(self.log_path))

        db.session.delete(self.sub)
        db.session.commit()

        self.assertFalse(os.path.exists(self.code_path))
        self.assertFalse(os.path.exists(self.log_path))

    def test_no_error_on_missing_files(self):
        os.remove(self.code_path)
        os.remove(self.log_path)
        # Should not raise
        db.session.delete(self.sub)
        db.session.commit()


if __name__ == '__main__':
    unittest.main()
