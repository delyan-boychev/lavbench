import os
import sys
import json
import unittest
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import db, User, Challenge, Task, Submission, Stage
from auth_utils import generate_token


class TestCheckCompetitorAccess(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.challenge = Challenge(
            title="Test", description="Test", max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2), is_frozen=False
        )
        db.session.add(self.challenge)
        db.session.flush()
        self.user = User(
            username="comp1", password_hash="x", role="competitor",
            alias_id="C1", challenge_id=self.challenge.id
        )
        db.session.add(self.user)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_competitor_belongs_to_challenge(self):
        from routes.tasks import check_competitor_access
        self.assertTrue(check_competitor_access(self.user.id, self.challenge.id))

    def test_competitor_wrong_challenge(self):
        from routes.tasks import check_competitor_access
        self.assertFalse(check_competitor_access(self.user.id, 99999))

    def test_user_not_found(self):
        from routes.tasks import check_competitor_access
        self.assertFalse(check_competitor_access(99999, self.challenge.id))


class TestCheckTaskStarted(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.challenge = Challenge(
            title="Test", description="Test", max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2),
            is_frozen=False, timezone="UTC"
        )
        db.session.add(self.challenge)
        db.session.flush()
        self.task = Task(
            title="T1", challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim", time_limit_sec=300,
            ram_limit_mb=512, max_submissions_per_period=10
        )
        db.session.add(self.task)
        self.user = User(
            username="comp1", password_hash="x", role="competitor",
            alias_id="C1", challenge_id=self.challenge.id
        )
        db.session.add(self.user)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_admin_always_allowed(self):
        from routes.tasks import check_task_started
        self.assertTrue(check_task_started(self.task, "admin", None))

    def test_jury_always_allowed(self):
        from routes.tasks import check_task_started
        self.assertTrue(check_task_started(self.task, "jury", None))

    def test_competitor_not_in_challenge(self):
        from routes.tasks import check_task_started
        self.assertFalse(check_task_started(self.task, "competitor", 99999))

    def test_competitor_challenge_not_started(self):
        from routes.tasks import check_task_started
        self.challenge.start_time = datetime.utcnow() + timedelta(hours=24)
        self.challenge.end_time = datetime.utcnow() + timedelta(hours=48)
        db.session.commit()
        self.assertFalse(check_task_started(self.task, "competitor", self.user.id))

    def test_competitor_stage_not_started(self):
        from routes.tasks import check_task_started
        stage = Stage(
            title="Future Stage", challenge_id=self.challenge.id,
            start_time=datetime.utcnow() + timedelta(hours=24),
            end_time=datetime.utcnow() + timedelta(hours=48)
        )
        db.session.add(stage)
        db.session.commit()
        self.task.stage_id = stage.id
        db.session.commit()
        self.assertFalse(check_task_started(self.task, "competitor", self.user.id))


class TestQueueSystemSubmission(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.challenge = Challenge(
            title="Test", description="Test", max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2), is_frozen=False
        )
        db.session.add(self.challenge)
        db.session.flush()
        self.task = Task(
            title="Task 1", challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim", time_limit_sec=300,
            ram_limit_mb=512, max_submissions_per_period=10,
            metrics_config='{"accuracy": {"weight": 1.0}}',
            hf_datasets='["dataset1"]', hf_models='["model1"]',
            public_eval_percentage=50, gpu_required=False
        )
        db.session.add(self.task)
        self.admin = User(
            username="admin", password_hash="x", role="admin", alias_id="A1"
        )
        db.session.add(self.admin)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    @patch('tasks.evaluate_submission.apply_async')
    @patch('routes.tasks.extract_code_from_cells')
    def test_creates_baseline_submission(self, mock_extract, mock_apply):
        mock_extract.return_value = ["print('hello')"]
        from routes.tasks import queue_system_submission
        queue_system_submission(
            self.task, self.challenge,
            [{"cell_type": "code", "source": ["print('hello')"]}],
            self.admin.id
        )
        sub = Submission.query.filter_by(task_id=self.task.id, is_baseline=True).first()
        self.assertIsNotNone(sub)
        self.assertEqual(sub.status, 'queued')
        self.assertEqual(sub.user_id, self.admin.id)
        mock_apply.assert_called_once()

    @patch('tasks.evaluate_submission.apply_async')
    def test_gpu_queue_when_required(self, mock_apply):
        self.task.gpu_required = True
        db.session.commit()
        from routes.tasks import queue_system_submission
        queue_system_submission(
            self.task, self.challenge,
            [{"cell_type": "code", "source": ["x=1"]}],
            self.admin.id
        )
        self.assertEqual(mock_apply.call_args[1]['queue'], 'gpu_queue')

    @patch('tasks.evaluate_submission.apply_async')
    def test_celery_queue_by_default(self, mock_apply):
        self.task.gpu_required = False
        db.session.commit()
        from routes.tasks import queue_system_submission
        queue_system_submission(
            self.task, self.challenge,
            [{"cell_type": "code", "source": ["x=1"]}],
            self.admin.id
        )
        self.assertEqual(mock_apply.call_args[1]['queue'], 'celery')

    @patch('tasks.evaluate_submission.apply_async')
    @patch('routes.tasks.extract_code_from_cells')
    def test_metadata_contents(self, mock_extract, mock_apply):
        mock_extract.return_value = ["print('hi')"]
        from routes.tasks import queue_system_submission
        queue_system_submission(
            self.task, self.challenge,
            [{"cell_type": "code", "source": ["print('hi')"]}],
            self.admin.id
        )
        metadata = mock_apply.call_args[1]['args'][1]
        self.assertEqual(metadata['time_limit'], 300)
        self.assertEqual(metadata['ram_limit'], 512)
        self.assertFalse(metadata['gpu_required'])
        self.assertEqual(metadata['public_eval_percentage'], 50)
        self.assertEqual(metadata['base_docker_image'], 'python:3.10-slim')

    @patch('tasks.evaluate_submission.apply_async')
    @patch('routes.tasks.extract_code_from_cells')
    def test_gen_worker_token_in_metadata(self, mock_extract, mock_apply):
        mock_extract.return_value = []
        from routes.tasks import queue_system_submission
        queue_system_submission(
            self.task, self.challenge,
            [{"cell_type": "code", "source": ["x=1"]}],
            self.admin.id
        )
        metadata = mock_apply.call_args[1]['args'][1]
        self.assertIn('worker_secret_key', metadata)
        self.assertIsInstance(metadata['worker_secret_key'], str)

    @patch('tasks.evaluate_submission.apply_async')
    @patch('routes.tasks.os.path.exists')
    @patch('builtins.open')
    def test_custom_eval_from_script(self, mock_open, mock_exists, mock_apply):
        mock_exists.return_value = True
        mock_open.return_value.__enter__.return_value.read.return_value = "def evaluate(): pass"
        self.task.evaluator_script_path = "/tmp/evaluator.py"
        db.session.commit()
        from routes.tasks import queue_system_submission
        queue_system_submission(
            self.task, self.challenge,
            [{"cell_type": "code", "source": ["x=1"]}],
            self.admin.id
        )
        metadata = mock_apply.call_args[1]['args'][1]
        self.assertTrue(metadata['is_custom_eval'])
        self.assertEqual(metadata['custom_eval_code'], "def evaluate(): pass")

    @patch('tasks.evaluate_submission.apply_async')
    def test_custom_eval_code_direct(self, mock_apply):
        self.task.custom_eval_code = "def custom(): pass"
        db.session.commit()
        from routes.tasks import queue_system_submission
        queue_system_submission(
            self.task, self.challenge,
            [{"cell_type": "code", "source": ["x=1"]}],
            self.admin.id
        )
        metadata = mock_apply.call_args[1]['args'][1]
        self.assertEqual(metadata['custom_eval_code'], "def custom(): pass")

    @patch('tasks.evaluate_submission.apply_async')
    def test_priority_passed_to_celery(self, mock_apply):
        from routes.tasks import queue_system_submission
        queue_system_submission(
            self.task, self.challenge,
            [{"cell_type": "code", "source": ["x=1"]}],
            self.admin.id, priority=5
        )
        self.assertEqual(mock_apply.call_args[1]['priority'], 5)

    @patch('tasks.evaluate_submission.apply_async')
    @patch('routes.tasks.extract_code_from_cells')
    def test_time_limit_fallsback_to_challenge(self, mock_extract, mock_apply):
        mock_extract.return_value = [""]
        self.task.time_limit_sec = None
        self.challenge.time_limit_sec = 600
        db.session.commit()
        from routes.tasks import queue_system_submission
        queue_system_submission(
            self.task, self.challenge,
            [{"cell_type": "code", "source": ["x=1"]}],
            self.admin.id
        )
        metadata = mock_apply.call_args[1]['args'][1]
        self.assertEqual(metadata['time_limit'], 600)


class TestMaybeQueueBaseline(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.challenge = Challenge(
            title="Test", description="Test", max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2), is_frozen=False
        )
        db.session.add(self.challenge)
        db.session.flush()
        self.task = Task(
            title="Task 1", challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim", time_limit_sec=300,
            ram_limit_mb=512, max_submissions_per_period=10
        )
        db.session.add(self.task)
        self.admin = User(
            username="admin", password_hash="x", role="admin", alias_id="A1"
        )
        db.session.add(self.admin)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    @patch('routes.tasks.queue_system_submission')
    @patch('routes.tasks.os.path.exists')
    @patch('routes.tasks.extract_code_from_notebook')
    def test_queues_baseline_when_notebook_exists(self, mock_extract, mock_exists, mock_queue):
        mock_exists.return_value = True
        mock_extract.return_value = [{"cell_type": "code", "source": ["x=1"]}]
        self.task.baseline_notebook_path = "/tmp/baseline.ipynb"
        db.session.commit()
        from routes.tasks import _maybe_queue_baseline
        _maybe_queue_baseline(self.task, self.challenge, self.admin.id)
        mock_queue.assert_called_once()

    @patch('routes.tasks.queue_system_submission')
    def test_no_notebook_does_nothing(self, mock_queue):
        from routes.tasks import _maybe_queue_baseline
        _maybe_queue_baseline(self.task, self.challenge, self.admin.id)
        mock_queue.assert_not_called()

    @patch('routes.tasks.queue_system_submission')
    @patch('routes.tasks.os.path.exists')
    def test_deletes_old_baselines(self, mock_exists, mock_queue):
        mock_exists.return_value = False
        old = Submission(
            user_id=self.admin.id, challenge_id=self.challenge.id,
            task_id=self.task.id, status='completed', is_baseline=True,
            code_cells='[]', code_storage_path="/tmp/old_code.py",
            log_storage_path="/tmp/old_log.txt"
        )
        db.session.add(old)
        db.session.commit()
        from routes.tasks import _maybe_queue_baseline
        _maybe_queue_baseline(self.task, self.challenge, self.admin.id)
        remaining = Submission.query.filter_by(task_id=self.task.id, is_baseline=True).all()
        self.assertEqual(len(remaining), 0)

    @patch('routes.tasks.queue_system_submission')
    @patch('routes.tasks.os.path.exists')
    def test_empty_notebook_does_not_queue(self, mock_exists, mock_queue):
        mock_exists.return_value = True
        self.task.baseline_notebook_path = "/tmp/empty.ipynb"
        db.session.commit()
        from routes.tasks import _maybe_queue_baseline
        import routes.tasks
        with patch.object(routes.tasks, 'extract_code_from_notebook', return_value=[]):
            _maybe_queue_baseline(self.task, self.challenge, self.admin.id)
        mock_queue.assert_not_called()


class TestGetTask(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.challenge = Challenge(
            title="Test", description="Test", max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2), is_frozen=False, timezone="UTC"
        )
        db.session.add(self.challenge)
        db.session.flush()
        self.task = Task(
            title="Task 1", challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim", time_limit_sec=300,
            ram_limit_mb=512, max_submissions_per_period=10, gpu_required=False
        )
        db.session.add(self.task)
        self.admin = User(username="admin", password_hash="x", role="admin", alias_id="A1")
        db.session.add(self.admin)
        self.comp = User(username="comp1", password_hash="x", role="competitor", alias_id="C1", challenge_id=self.challenge.id)
        db.session.add(self.comp)
        db.session.commit()
        self.admin_token = generate_token(self.admin.id, role="admin")
        self.comp_token = generate_token(self.comp.id, role="competitor")

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_admin_can_get_task(self):
        resp = self.client.get(f"/api/tasks/{self.task.id}", headers=self._auth(self.admin_token))
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["title"], "Task 1")

    def test_competitor_can_get_accessible_task(self):
        resp = self.client.get(f"/api/tasks/{self.task.id}", headers=self._auth(self.comp_token))
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["title"], "Task 1")

    def test_competitor_blocked_when_task_not_started(self):
        self.challenge.start_time = datetime.utcnow() + timedelta(hours=24)
        self.challenge.end_time = datetime.utcnow() + timedelta(hours=48)
        db.session.commit()
        resp = self.client.get(f"/api/tasks/{self.task.id}", headers=self._auth(self.comp_token))
        self.assertEqual(resp.status_code, 403)

    def test_returns_404_for_nonexistent_task(self):
        resp = self.client.get("/api/tasks/99999", headers=self._auth(self.admin_token))
        self.assertEqual(resp.status_code, 404)

    def test_unauthenticated_returns_401(self):
        resp = self.client.get(f"/api/tasks/{self.task.id}")
        self.assertEqual(resp.status_code, 401)


class TestDeleteTask(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.challenge = Challenge(
            title="Test", description="Test", max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2), is_frozen=False
        )
        db.session.add(self.challenge)
        db.session.flush()
        self.task = Task(
            title="Task 1", challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim", time_limit_sec=300,
            ram_limit_mb=512, max_submissions_per_period=10, gpu_required=False
        )
        db.session.add(self.task)
        self.admin = User(username="admin", password_hash="x", role="admin", alias_id="A1")
        db.session.add(self.admin)
        self.competitor = User(username="comp1", password_hash="x", role="competitor", alias_id="C1", challenge_id=self.challenge.id)
        db.session.add(self.competitor)
        db.session.commit()
        self.admin_token = generate_token(self.admin.id, role="admin")
        self.comp_token = generate_token(self.competitor.id, role="competitor")

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_admin_can_delete_task(self):
        resp = self.client.delete(f"/api/tasks/{self.task.id}", headers=self._auth(self.admin_token))
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("deleted", data.get("message", ""))

    def test_competitor_cannot_delete_task(self):
        resp = self.client.delete(f"/api/tasks/{self.task.id}", headers=self._auth(self.comp_token))
        self.assertEqual(resp.status_code, 403)

    def test_returns_404_for_nonexistent_task(self):
        resp = self.client.delete("/api/tasks/99999", headers=self._auth(self.admin_token))
        self.assertEqual(resp.status_code, 404)

    def test_delete_removes_submissions(self):
        sub = Submission(
            user_id=self.admin.id, challenge_id=self.challenge.id,
            task_id=self.task.id, status="completed", code_cells="[]"
        )
        db.session.add(sub)
        db.session.commit()
        sub_id = sub.id
        resp = self.client.delete(f"/api/tasks/{self.task.id}", headers=self._auth(self.admin_token))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(Submission.query.filter_by(id=sub_id).first())


class TestDownloadTaskFile(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['UPLOAD_FOLDER'] = tempfile.mkdtemp()
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.challenge = Challenge(
            title="Test", description="Test", max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2), is_frozen=False
        )
        db.session.add(self.challenge)
        db.session.flush()
        self.task = Task(
            title="Task 1", challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim", time_limit_sec=300,
            ram_limit_mb=512, max_submissions_per_period=10, gpu_required=False
        )
        db.session.add(self.task)
        self.admin = User(username="admin", password_hash="x", role="admin", alias_id="A1")
        db.session.add(self.admin)
        self.comp = User(username="comp1", password_hash="x", role="competitor", alias_id="C1", challenge_id=self.challenge.id)
        db.session.add(self.comp)
        db.session.commit()
        self.admin_token = generate_token(self.admin.id, role="admin")
        self.comp_token = generate_token(self.comp.id, role="competitor")

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
        import shutil
        shutil.rmtree(self.app.config['UPLOAD_FOLDER'], ignore_errors=True)

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_returns_404_for_nonexistent_file(self):
        resp = self.client.get(
            f"/api/tasks/{self.task.id}/download/nonexistent.txt",
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(resp.status_code, 404)

    def test_competitor_blocked_from_labels_parquet(self):
        resp = self.client.get(
            f"/api/tasks/{self.task.id}/download/labels.parquet",
            headers=self._auth(self.comp_token)
        )
        self.assertEqual(resp.status_code, 403)

    def test_competitor_blocked_when_task_not_started(self):
        self.challenge.start_time = datetime.utcnow() + timedelta(hours=24)
        self.challenge.end_time = datetime.utcnow() + timedelta(hours=48)
        db.session.commit()
        resp = self.client.get(
            f"/api/tasks/{self.task.id}/download/test.txt",
            headers=self._auth(self.comp_token)
        )
        self.assertEqual(resp.status_code, 403)

    def test_admin_can_download_baseline_notebook(self):
        test_file = os.path.join(self.app.config['UPLOAD_FOLDER'], "test_notebook.ipynb")
        with open(test_file, "w") as f:
            f.write("{}")
        self.task.baseline_notebook_path = test_file
        db.session.commit()
        resp = self.client.get(
            f"/api/tasks/{self.task.id}/download/test_notebook.ipynb",
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(resp.status_code, 200)

    def test_unauthenticated_returns_401(self):
        resp = self.client.get(f"/api/tasks/{self.task.id}/download/test.txt")
        self.assertEqual(resp.status_code, 401)


class TestGetTaskSubmissions(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.challenge = Challenge(
            title="Test", description="Test", max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2), is_frozen=False
        )
        db.session.add(self.challenge)
        db.session.flush()
        self.task = Task(
            title="Task 1", challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim", time_limit_sec=300,
            ram_limit_mb=512, max_submissions_per_period=10, gpu_required=False
        )
        db.session.add(self.task)
        self.admin = User(username="admin", password_hash="x", role="admin", alias_id="A1")
        db.session.add(self.admin)
        self.comp = User(username="comp1", password_hash="x", role="competitor", alias_id="C1", challenge_id=self.challenge.id)
        db.session.add(self.comp)
        db.session.flush()
        self.sub1 = Submission(user_id=self.comp.id, challenge_id=self.challenge.id, task_id=self.task.id, status="completed", code_cells="[]")
        db.session.add(self.sub1)
        self.sub2 = Submission(user_id=self.admin.id, challenge_id=self.challenge.id, task_id=self.task.id, status="completed", code_cells="[]")
        db.session.add(self.sub2)
        db.session.commit()
        self.admin_token = generate_token(self.admin.id, role="admin")
        self.comp_token = generate_token(self.comp.id, role="competitor")

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_admin_sees_all_submissions(self):
        resp = self.client.get(f"/api/tasks/{self.task.id}/submissions?page=1", headers=self._auth(self.admin_token))
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("items", data)
        self.assertEqual(len(data["items"]), 2)

    def test_competitor_only_sees_own_submissions(self):
        resp = self.client.get(f"/api/tasks/{self.task.id}/submissions?page=1", headers=self._auth(self.comp_token))
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("items", data)
        for s in data["items"]:
            self.assertEqual(s["user"]["id"], self.comp.id)

    def test_competitor_blocked_when_task_not_started(self):
        self.challenge.start_time = datetime.utcnow() + timedelta(hours=24)
        self.challenge.end_time = datetime.utcnow() + timedelta(hours=48)
        db.session.commit()
        resp = self.client.get(f"/api/tasks/{self.task.id}/submissions", headers=self._auth(self.comp_token))
        self.assertEqual(resp.status_code, 403)

    def test_competitor_blocked_when_scores_finalized(self):
        self.challenge.scores_finalized = True
        db.session.commit()
        resp = self.client.get(f"/api/tasks/{self.task.id}/submissions", headers=self._auth(self.comp_token))
        self.assertEqual(resp.status_code, 403)

    def test_admin_can_access_when_scores_finalized(self):
        self.challenge.scores_finalized = True
        db.session.commit()
        resp = self.client.get(f"/api/tasks/{self.task.id}/submissions", headers=self._auth(self.admin_token))
        self.assertEqual(resp.status_code, 200)

    def test_returns_404_for_nonexistent_task(self):
        resp = self.client.get("/api/tasks/99999/submissions", headers=self._auth(self.admin_token))
        self.assertEqual(resp.status_code, 403)

    def test_includes_submission_details(self):
        resp = self.client.get(f"/api/tasks/{self.task.id}/submissions?page=1", headers=self._auth(self.admin_token))
        data = resp.get_json()
        item = data["items"][0]
        self.assertIn("status", item)
        self.assertIn("user", item)
        self.assertIn("task_id", item)

    def test_unauthenticated_returns_401(self):
        resp = self.client.get(f"/api/tasks/{self.task.id}/submissions")
        self.assertEqual(resp.status_code, 401)


class TestGetTaskLeaderboard(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.challenge = Challenge(
            title="Test", description="Test", max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2), is_frozen=False
        )
        db.session.add(self.challenge)
        db.session.flush()
        self.task = Task(
            title="Task 1", challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim", time_limit_sec=300,
            ram_limit_mb=512, max_submissions_per_period=10, gpu_required=False
        )
        db.session.add(self.task)
        self.admin = User(username="admin", password_hash="x", role="admin", alias_id="A1")
        db.session.add(self.admin)
        db.session.commit()
        self.admin_token = generate_token(self.admin.id, role="admin")

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    @patch('services.leaderboard_service.get_task_leaderboard_data')
    def test_returns_leaderboard_data(self, mock_get_data):
        mock_get_data.return_value = {"leaderboard": [{"rank": 1, "score": 0.95}]}
        resp = self.client.get(f"/api/tasks/{self.task.id}/leaderboard", headers=self._auth(self.admin_token))
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("leaderboard", data)

    @patch('services.leaderboard_service.get_task_leaderboard_data')
    def test_returns_403_on_error(self, mock_get_data):
        mock_get_data.return_value = {"error": "Access denied"}
        resp = self.client.get(f"/api/tasks/{self.task.id}/leaderboard", headers=self._auth(self.admin_token))
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_returns_401(self):
        resp = self.client.get(f"/api/tasks/{self.task.id}/leaderboard")
        self.assertEqual(resp.status_code, 401)


class TestWorkerDownloadTaskFile(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['UPLOAD_FOLDER'] = tempfile.mkdtemp()
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.challenge = Challenge(
            title="Test", description="Test", max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2), is_frozen=False
        )
        db.session.add(self.challenge)
        db.session.flush()
        self.task = Task(
            title="Task 1", challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim", time_limit_sec=300,
            ram_limit_mb=512, max_submissions_per_period=10, gpu_required=False
        )
        db.session.add(self.task)
        db.session.commit()
        task_dir = os.path.join(self.app.config['UPLOAD_FOLDER'], f"task_{self.task.id}")
        os.makedirs(task_dir, exist_ok=True)
        with open(os.path.join(task_dir, "saved_test.txt"), "w") as f:
            f.write("file content")
        self.task.files = json.dumps([{"filename": "test.txt", "saved_name": "saved_test.txt"}])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
        import shutil
        shutil.rmtree(self.app.config['UPLOAD_FOLDER'], ignore_errors=True)

    @patch('auth_utils.verify_worker_token')
    def test_downloads_file_with_valid_token(self, mock_verify):
        mock_verify.return_value = True
        resp = self.client.get(f"/api/worker/tasks/{self.task.id}/files/test.txt",
                               headers={"X-Worker-Token": "valid-token"})
        self.assertEqual(resp.status_code, 200)

    @patch('auth_utils.verify_worker_token')
    def test_returns_401_without_valid_token(self, mock_verify):
        mock_verify.return_value = False
        resp = self.client.get(f"/api/worker/tasks/{self.task.id}/files/test.txt",
                               headers={"X-Worker-Token": "bad-token"})
        self.assertEqual(resp.status_code, 401)

    @patch('auth_utils.verify_worker_token')
    def test_returns_404_for_nonexistent_file(self, mock_verify):
        mock_verify.return_value = True
        resp = self.client.get(f"/api/worker/tasks/{self.task.id}/files/missing.txt",
                               headers={"X-Worker-Token": "valid-token"})
        self.assertEqual(resp.status_code, 404)


class TestGetActiveDatasets(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.challenge = Challenge(
            title="Test", description="Test", max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2), is_frozen=False, is_archived=False
        )
        db.session.add(self.challenge)
        db.session.flush()
        self.task = Task(
            title="Task 1", challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim", time_limit_sec=300,
            ram_limit_mb=512, max_submissions_per_period=10, gpu_required=False,
            custom_eval_code='load_dataset("dataset1")'
        )
        db.session.add(self.task)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    @patch('auth_utils.verify_worker_token')
    def test_returns_datasets_from_custom_eval(self, mock_verify):
        mock_verify.return_value = True
        resp = self.client.get("/api/worker/active-datasets", headers={"X-Worker-Token": "token"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("dataset1", data["datasets"])

    @patch('auth_utils.verify_worker_token')
    def test_skips_archived_challenges(self, mock_verify):
        mock_verify.return_value = True
        self.challenge.is_archived = True
        db.session.commit()
        resp = self.client.get("/api/worker/active-datasets", headers={"X-Worker-Token": "token"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["datasets"], [])

    @patch('auth_utils.verify_worker_token')
    def test_returns_401_without_valid_token(self, mock_verify):
        mock_verify.return_value = False
        resp = self.client.get("/api/worker/active-datasets", headers={"X-Worker-Token": "bad"})
        self.assertEqual(resp.status_code, 401)


class TestGetTaskHfKey(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.challenge = Challenge(
            title="Test", description="Test", max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2), is_frozen=False
        )
        db.session.add(self.challenge)
        db.session.flush()
        self.task = Task(
            title="Task 1", challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim", time_limit_sec=300,
            ram_limit_mb=512, max_submissions_per_period=10, gpu_required=False
        )
        db.session.add(self.task)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    @patch('auth_utils.verify_worker_token')
    def test_returns_hf_key(self, mock_verify):
        mock_verify.return_value = True
        with patch.object(Task, 'get_hf_api_key', return_value="my-key"):
            resp = self.client.get(f"/api/worker/tasks/{self.task.id}/hf-key",
                                   headers={"X-Worker-Token": "token"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["hf_key"], "my-key")

    @patch('auth_utils.verify_worker_token')
    def test_returns_401_without_valid_token(self, mock_verify):
        mock_verify.return_value = False
        resp = self.client.get(f"/api/worker/tasks/{self.task.id}/hf-key",
                               headers={"X-Worker-Token": "bad"})
        self.assertEqual(resp.status_code, 401)

    @patch('auth_utils.verify_worker_token')
    def test_returns_404_for_nonexistent_task(self, mock_verify):
        mock_verify.return_value = True
        resp = self.client.get("/api/worker/tasks/99999/hf-key",
                               headers={"X-Worker-Token": "token"})
        self.assertEqual(resp.status_code, 404)


if __name__ == '__main__':
    unittest.main()
