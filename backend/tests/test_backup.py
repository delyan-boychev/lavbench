import os
import sys
import json
import unittest
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# Use file-based SQLite so tasks.py module-level create_app() shares the same DB
_db_path = tempfile.mktemp(suffix='.db')
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import db, User, Challenge, Task, Submission
from task_modules.system import run_backup, run_register_worker_specs
from tasks import check_and_backup
from auth_utils import generate_token


class TestRunBackup(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['UPLOAD_FOLDER'] = '/tmp/test_uploads'
        self.app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']
        os.makedirs(self.app.config['UPLOAD_FOLDER'], exist_ok=True)

        self.app_context = self.app.app_context()
        self.app_context.push()

        db.create_all()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(_db_path):
            os.unlink(_db_path)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
        import shutil
        shutil.rmtree('/tmp/test_backups', ignore_errors=True)
        shutil.rmtree(self.app.config['UPLOAD_FOLDER'], ignore_errors=True)

    @patch('task_modules.system.subprocess.run')
    @patch('task_modules.system.os.makedirs')
    @patch('task_modules.system.os.path.getsize')
    def test_run_backup_auto(self, mock_getsize, mock_makedirs, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = ""
        mock_getsize.return_value = 1024
        filename = run_backup(self.app, auto=True)
        self.assertIsNotNone(filename)
        self.assertTrue(filename.startswith("auto_"))

    @patch('task_modules.system.subprocess.run')
    @patch('task_modules.system.os.makedirs')
    @patch('task_modules.system.os.path.getsize')
    def test_run_backup_manual(self, mock_getsize, mock_makedirs, mock_run):
        mock_run.return_value.returncode = 0
        mock_getsize.return_value = 1024
        filename = run_backup(self.app, auto=False)
        self.assertTrue(filename.startswith("manual_"))

    @patch('task_modules.system.subprocess.run')
    @patch('task_modules.system.os.makedirs')
    @patch('task_modules.system.os.path.getsize')
    def test_run_backup_with_challenge_and_state(self, mock_getsize, mock_makedirs, mock_run):
        mock_run.return_value.returncode = 0
        mock_getsize.return_value = 1024
        filename = run_backup(self.app, auto=False, challenge_id=42, state="grace_ended")
        self.assertIn("grace_ended", filename)
        # challenge_id goes into the backup directory, not the filename
        mock_makedirs.assert_any_call("/backups/challenge_42", exist_ok=True)

    @patch('task_modules.system.subprocess.run')
    @patch('task_modules.system.os.makedirs')
    def test_run_backup_pg_dump_failure(self, mock_makedirs, mock_run):
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "connection refused"
        with self.assertRaises(RuntimeError) as ctx:
            run_backup(self.app)
        self.assertIn("pg_dump failed", str(ctx.exception))

    @patch('task_modules.system.subprocess.run')
    @patch('task_modules.system.os.makedirs')
    def test_run_backup_tar_failure(self, mock_makedirs, mock_run):
        def side_effect(*args, **kwargs):
            # First call (pg_dump) succeeds, second (tar) fails
            if 'pg_dump' in args[0]:
                result = MagicMock()
                result.returncode = 0
                return result
            result = MagicMock()
            result.returncode = 1
            result.stderr = "tar error"
            return result
        mock_run.side_effect = side_effect
        with self.assertRaises(RuntimeError) as ctx:
            run_backup(self.app)
        self.assertIn("tar failed", str(ctx.exception))


class TestRunRegisterWorkerSpecs(unittest.TestCase):
    @patch('task_modules.system.requests.post')
    @patch('task_modules.system.os.environ.get')
    def test_register_cpu_worker(self, mock_getenv, mock_post):
        def getenv_side_effect(key, default=None):
            env = {
                "WORKER_GPU_ID": None,
                "HOSTNAME": "worker-01",
                "API_BASE": "http://localhost:5001/api"
            }
            return env.get(key, default)
        mock_getenv.side_effect = getenv_side_effect

        mock_celery = MagicMock()
        run_register_worker_specs(mock_celery)
        mock_post.assert_called_once()
        payload = mock_post.call_args[1]["json"]
        self.assertEqual(payload["worker_id"], "worker-01")
        self.assertEqual(payload["gpu_count"], 0)

    @patch('task_modules.system.requests.post')
    @patch('task_modules.system.os.environ.get')
    def test_register_gpu_worker(self, mock_getenv, mock_post):
        def getenv_side_effect(key, default=None):
            env = {
                "WORKER_GPU_ID": "0",
                "HOSTNAME": "gpu-box",
                "API_BASE": "http://localhost:5001/api"
            }
            return env.get(key, default)
        mock_getenv.side_effect = getenv_side_effect

        mock_celery = MagicMock()
        run_register_worker_specs(mock_celery)
        payload = mock_post.call_args[1]["json"]
        self.assertIn("gpu", payload["worker_id"])

    @patch('task_modules.system.requests.post')
    def test_register_handles_timeout(self, mock_post):
        mock_post.side_effect = Exception("timeout")
        mock_celery = MagicMock()
        run_register_worker_specs(mock_celery)


class TestCheckAndBackup(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']
        self.client = self.app.test_client()

        # Patch tasks.app so check_and_backup uses the test app's engine
        import tasks
        tasks.app = self.app

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
            title="Backup Test",
            description="Test",
            max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=48),
            end_time=datetime.utcnow() + timedelta(hours=2),
            is_frozen=False
        )
        db.session.add(self.challenge)
        db.session.commit()

    def test_check_and_backup_returns_dict(self):
        result = check_and_backup()
        self.assertIsInstance(result, dict)

    def test_check_and_backup_with_active_competition(self):
        result = check_and_backup()
        self.assertIn("active_competitions", result)

    def test_check_and_backup_expired_challenge(self):
        self.challenge.end_time = datetime.utcnow() - timedelta(hours=24)
        db.session.commit()
        result = check_and_backup()
        self.assertIn("active_competitions", result)


class TestAdminBackupEndpoints(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['UPLOAD_FOLDER'] = '/tmp/test_uploads'
        os.makedirs(self.app.config['UPLOAD_FOLDER'], exist_ok=True)

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
        import shutil
        shutil.rmtree('/tmp/test_backups', ignore_errors=True)
        shutil.rmtree(self.app.config['UPLOAD_FOLDER'], ignore_errors=True)

    def seed_basic_data(self):
        self.admin = User(
            username="backup_admin",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            alias_id="Admin-Backup"
        )
        db.session.add(self.admin)
        db.session.commit()
        self.admin_token = generate_token(self.admin.id, role="admin")

        # Also create a non-admin
        self.user = User(
            username="normal_user",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="User-001"
        )
        db.session.add(self.user)
        db.session.commit()
        self.user_token = generate_token(self.user.id, role="competitor")

    def _auth_headers(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_list_backups_admin_access(self):
        resp = self.client.get(
            "/api/admin/backups",
            headers=self._auth_headers(self.admin_token)
        )
        # May be empty or list — just check it responds
        self.assertEqual(resp.status_code, 200)

    def test_list_backups_competitor_forbidden(self):
        resp = self.client.get(
            "/api/admin/backups",
            headers=self._auth_headers(self.user_token)
        )
        self.assertEqual(resp.status_code, 403)

    def test_list_backups_unauthenticated(self):
        resp = self.client.get("/api/admin/backups")
        self.assertEqual(resp.status_code, 403)

    def test_force_backup_admin_access(self):
        resp = self.client.post(
            "/api/admin/backups/force",
            headers=self._auth_headers(self.admin_token)
        )
        # Might fail due to no pg_dump — just check auth passes
        self.assertNotEqual(resp.status_code, 403)
        self.assertNotEqual(resp.status_code, 401)

    def test_force_backup_competitor_forbidden(self):
        resp = self.client.post(
            "/api/admin/backups/force",
            headers=self._auth_headers(self.user_token)
        )
        self.assertEqual(resp.status_code, 403)

    def test_download_backup_not_found(self):
        resp = self.client.get(
            "/api/admin/backups/nonexistent.tar.gz/download",
            headers=self._auth_headers(self.admin_token)
        )
        self.assertEqual(resp.status_code, 404)

    def test_download_backup_competitor_forbidden(self):
        resp = self.client.get(
            "/api/admin/backups/test.tar.gz/download",
            headers=self._auth_headers(self.user_token)
        )
        self.assertEqual(resp.status_code, 403)

    def test_delete_backup_not_found(self):
        resp = self.client.delete(
            "/api/admin/backups/delete/nonexistent.tar.gz",
            headers=self._auth_headers(self.admin_token)
        )
        self.assertEqual(resp.status_code, 404)

    def test_delete_backup_competitor_forbidden(self):
        resp = self.client.delete(
            "/api/admin/backups/delete/test.tar.gz",
            headers=self._auth_headers(self.user_token)
        )
        self.assertEqual(resp.status_code, 403)
