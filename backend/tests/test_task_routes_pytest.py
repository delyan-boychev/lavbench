"""Tests for the task routes."""

import json
import os
import sys
import tempfile
from datetime import timedelta
from unittest.mock import patch

import pytest

from utils.dates import utcnow

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models import Challenge, Stage, Submission, Task, User, db
from services.submission_service import create_submission
from utils.auth_utils import generate_token


class TestCheckCompetitorAccess:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, redis_flush):
        self.challenge = Challenge(
            title="Test",
            description="Test",
            max_eval_requests=5,
            start_time=utcnow() - timedelta(hours=2),
            end_time=utcnow() + timedelta(hours=2),
            is_frozen=False,
        )
        db.session.add(self.challenge)
        db.session.flush()
        self.user = User(
            username="comp1",
            password_hash="x",
            role="competitor",
            alias_id="C1",
            challenge_id=self.challenge.id,
        )
        db.session.add(self.user)
        db.session.commit()

    def test_competitor_belongs_to_challenge(self):
        from routes.tasks import check_competitor_access

        assert check_competitor_access(self.user.id, self.challenge.id)

    def test_competitor_wrong_challenge(self):
        from routes.tasks import check_competitor_access

        assert check_competitor_access(self.user.id, 99999) is False

    def test_user_not_found(self):
        from routes.tasks import check_competitor_access

        assert check_competitor_access(99999, self.challenge.id) is False


class TestCheckTaskStarted:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, redis_flush):
        self.challenge = Challenge(
            title="Test",
            description="Test",
            max_eval_requests=5,
            start_time=utcnow() - timedelta(hours=2),
            end_time=utcnow() + timedelta(hours=2),
            is_frozen=False,
            timezone="UTC",
        )
        db.session.add(self.challenge)
        db.session.flush()
        self.task = Task(
            title="T1",
            challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
        )
        db.session.add(self.task)
        self.user = User(
            username="comp1",
            password_hash="x",
            role="competitor",
            alias_id="C1",
            challenge_id=self.challenge.id,
        )
        db.session.add(self.user)
        db.session.commit()

    def test_admin_always_allowed(self):
        from routes.tasks import check_task_started

        assert check_task_started(self.task, "admin", None)

    def test_jury_always_allowed(self):
        from routes.tasks import check_task_started

        assert check_task_started(self.task, "jury", None)

    def test_competitor_not_in_challenge(self):
        from routes.tasks import check_task_started

        assert check_task_started(self.task, "competitor", 99999) is False

    def test_competitor_challenge_not_started(self):
        from routes.tasks import check_task_started

        self.challenge.start_time = utcnow() + timedelta(hours=24)
        self.challenge.end_time = utcnow() + timedelta(hours=48)
        db.session.commit()
        assert check_task_started(self.task, "competitor", self.user.id) is False

    def test_competitor_stage_not_started(self):
        from routes.tasks import check_task_started

        stage = Stage(
            title="Future Stage",
            challenge_id=self.challenge.id,
            start_time=utcnow() + timedelta(hours=24),
            end_time=utcnow() + timedelta(hours=48),
        )
        db.session.add(stage)
        db.session.commit()
        self.task.stage_id = stage.id
        db.session.commit()
        assert check_task_started(self.task, "competitor", self.user.id) is False


class TestCreateBaselineSubmission:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, redis_flush):
        self.challenge = Challenge(
            title="Test",
            description="Test",
            max_eval_requests=5,
            start_time=utcnow() - timedelta(hours=2),
            end_time=utcnow() + timedelta(hours=2),
            is_frozen=False,
        )
        db.session.add(self.challenge)
        db.session.flush()
        self.task = Task(
            title="Task 1",
            challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
            metrics_config='{"accuracy": {"weight": 1.0}}',
            hf_datasets='["dataset1"]',
            hf_models='["model1"]',
            public_eval_percentage=50,
            gpu_required=False,
        )
        db.session.add(self.task)
        self.admin = User(username="admin", password_hash="x", role="admin", alias_id="A1")
        db.session.add(self.admin)
        db.session.commit()

    @patch("tasks.evaluate_submission.apply_async")
    @patch("routes.tasks.extract_code_from_cells")
    def test_creates_baseline_submission(self, mock_extract, mock_apply):
        mock_extract.return_value = ["print('hello')"]
        create_submission(
            self.task,
            self.challenge,
            self.admin.id,
            "admin",
            [{"cell_type": "code", "source": ["print('hello')"]}],
            is_baseline=True,
            priority=8,
            origin="baseline",
        )
        sub = Submission.query.filter_by(task_id=self.task.id, is_baseline=True).first()
        assert sub is not None
        assert sub.status == "queued"
        assert sub.user_id == self.admin.id
        mock_apply.assert_called_once()

    @patch("tasks.evaluate_submission.apply_async")
    def test_gpu_queue_when_required(self, mock_apply):
        self.task.gpu_required = True
        db.session.commit()
        create_submission(
            self.task,
            self.challenge,
            self.admin.id,
            "admin",
            [{"cell_type": "code", "source": ["x=1"]}],
            is_baseline=True,
            priority=8,
            origin="baseline",
        )
        assert mock_apply.call_args[1]["queue"] == "gpu_queue"

    @patch("tasks.evaluate_submission.apply_async")
    def test_celery_queue_by_default(self, mock_apply):
        self.task.gpu_required = False
        db.session.commit()
        create_submission(
            self.task,
            self.challenge,
            self.admin.id,
            "admin",
            [{"cell_type": "code", "source": ["x=1"]}],
            is_baseline=True,
            priority=8,
            origin="baseline",
        )
        assert mock_apply.call_args[1]["queue"] == "cpu_queue"

    @patch("tasks.evaluate_submission.apply_async")
    @patch("routes.tasks.extract_code_from_cells")
    def test_metadata_contents(self, mock_extract, mock_apply):
        mock_extract.return_value = ["print('hi')"]
        create_submission(
            self.task,
            self.challenge,
            self.admin.id,
            "admin",
            [{"cell_type": "code", "source": ["print('hi')"]}],
            is_baseline=True,
            priority=8,
            origin="baseline",
        )
        metadata = mock_apply.call_args[1]["args"][1]
        assert metadata["time_limit"] == 300
        assert metadata["ram_limit"] == 512
        assert metadata["gpu_required"] is False
        assert metadata["public_eval_percentage"] == 50
        assert metadata["base_docker_image"] == "python:3.10-slim"

    @patch("tasks.evaluate_submission.apply_async")
    @patch("routes.tasks.extract_code_from_cells")
    def test_gen_worker_token_in_metadata(self, mock_extract, mock_apply):
        mock_extract.return_value = []
        create_submission(
            self.task,
            self.challenge,
            self.admin.id,
            "admin",
            [{"cell_type": "code", "source": ["x=1"]}],
            is_baseline=True,
            priority=8,
            origin="baseline",
        )
        metadata = mock_apply.call_args[1]["args"][1]
        assert "submission_id" in metadata
        assert "main_server_url" in metadata

    @patch("tasks.evaluate_submission.apply_async")
    @patch("routes.tasks.os.path.exists")
    @patch("builtins.open")
    def test_custom_eval_from_script(self, mock_open, mock_exists, mock_apply):
        mock_exists.return_value = True
        mock_open.return_value.__enter__.return_value.read.return_value = "def evaluate(): pass"
        self.task.evaluator_script_path = "/tmp/evaluator.py"
        db.session.commit()
        create_submission(
            self.task,
            self.challenge,
            self.admin.id,
            "admin",
            [{"cell_type": "code", "source": ["x=1"]}],
            is_baseline=True,
            priority=8,
            origin="baseline",
        )
        metadata = mock_apply.call_args[1]["args"][1]
        assert metadata["is_custom_eval"]
        # The evaluator script is fetched by the worker via the signed
        # Run-content endpoint; it is no longer embedded in the message
        assert "custom_eval_code" not in metadata

    @patch("tasks.evaluate_submission.apply_async")
    def test_custom_eval_code_direct(self, mock_apply):
        self.task.custom_eval_code = "def custom(): pass"
        db.session.commit()
        create_submission(
            self.task,
            self.challenge,
            self.admin.id,
            "admin",
            [{"cell_type": "code", "source": ["x=1"]}],
            is_baseline=True,
            priority=8,
            origin="baseline",
        )
        metadata = mock_apply.call_args[1]["args"][1]
        assert "custom_eval_code" not in metadata

    @patch("utils.cache_utils.get_queue_depth", return_value=10_000)
    @patch("tasks.evaluate_submission.apply_async")
    def test_baseline_is_queued_even_when_the_queue_is_full(self, mock_apply, mock_depth):
        # The old baseline is already gone, so dropping the new one would block the task
        result = create_submission(
            self.task,
            self.challenge,
            self.admin.id,
            "admin",
            [{"source": "x=1"}],
            is_baseline=True,
            priority=8,
            origin="baseline",
        )
        assert not isinstance(result, tuple)
        assert result.is_baseline is True
        mock_apply.assert_called_once()

    @patch("tasks.evaluate_submission.apply_async")
    def test_priority_passed_to_celery(self, mock_apply):
        create_submission(
            self.task,
            self.challenge,
            self.admin.id,
            "admin",
            [{"cell_type": "code", "source": ["x=1"]}],
            is_baseline=True,
            priority=5,
            origin="baseline",
        )
        assert mock_apply.call_args[1]["priority"] == 5

    @patch("tasks.evaluate_submission.apply_async")
    @patch("routes.tasks.extract_code_from_cells")
    def test_time_limit_fallsback_to_challenge(self, mock_extract, mock_apply):
        mock_extract.return_value = [""]
        self.task.time_limit_sec = None
        self.challenge.time_limit_sec = 600
        db.session.commit()
        create_submission(
            self.task,
            self.challenge,
            self.admin.id,
            "admin",
            [{"cell_type": "code", "source": ["x=1"]}],
            is_baseline=True,
            priority=8,
            origin="baseline",
        )
        metadata = mock_apply.call_args[1]["args"][1]
        assert metadata["time_limit"] == 600


class TestMaybeQueueBaseline:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, redis_flush):
        self.challenge = Challenge(
            title="Test",
            description="Test",
            max_eval_requests=5,
            start_time=utcnow() - timedelta(hours=2),
            end_time=utcnow() + timedelta(hours=2),
            is_frozen=False,
        )
        db.session.add(self.challenge)
        db.session.flush()
        self.task = Task(
            title="Task 1",
            challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
        )
        db.session.add(self.task)
        self.admin = User(username="admin", password_hash="x", role="admin", alias_id="A1")
        db.session.add(self.admin)
        db.session.commit()

    @patch("services.baseline_service.create_submission")
    @patch("services.baseline_service.os.path.exists")
    @patch("services.baseline_service.extract_code_from_notebook")
    def test_queues_baseline_when_notebook_exists(self, mock_extract, mock_exists, mock_queue):
        mock_exists.return_value = True
        mock_extract.return_value = [{"cell_type": "code", "source": ["x=1"]}]
        self.task.baseline_notebook_path = "/tmp/baseline.ipynb"
        db.session.commit()
        from routes.tasks import _maybe_queue_baseline

        _maybe_queue_baseline(self.task, self.challenge, self.admin.id)
        mock_queue.assert_called_once()

    @patch("services.baseline_service.create_submission")
    def test_no_notebook_does_nothing(self, mock_queue):
        from routes.tasks import _maybe_queue_baseline

        _maybe_queue_baseline(self.task, self.challenge, self.admin.id)
        mock_queue.assert_not_called()

    @patch("services.baseline_service.create_submission")
    @patch("routes.tasks.os.path.exists")
    def test_deletes_old_baselines(self, mock_exists, mock_queue):
        mock_exists.return_value = False
        old = Submission(
            user_id=self.admin.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
            is_baseline=True,
            code_cells="[]",
            code_storage_path="/tmp/old_code.py",
            log_storage_path="/tmp/old_log.txt",
        )
        db.session.add(old)
        db.session.commit()
        from routes.tasks import _maybe_queue_baseline

        _maybe_queue_baseline(self.task, self.challenge, self.admin.id)
        remaining = Submission.query.filter_by(task_id=self.task.id, is_baseline=True).all()
        assert len(remaining) == 0

    @patch("services.baseline_service.create_submission")
    @patch("services.baseline_service.os.path.exists")
    def test_empty_notebook_does_not_queue(self, mock_exists, mock_queue):
        mock_exists.return_value = True
        self.task.baseline_notebook_path = "/tmp/empty.ipynb"
        db.session.commit()
        import services.baseline_service
        from routes.tasks import _maybe_queue_baseline

        with patch.object(services.baseline_service, "extract_code_from_notebook", return_value=[]):
            _maybe_queue_baseline(self.task, self.challenge, self.admin.id)
        mock_queue.assert_not_called()

    def _write_baseline_notebook(self, tmp_path):
        notebook = tmp_path / "baseline.ipynb"
        notebook.write_text(json.dumps({"cells": [{"cell_type": "code", "source": ["x = 1"]}]}))
        self.task.baseline_notebook_path = str(notebook)
        db.session.commit()

    @patch("tasks.evaluate_submission.apply_async")
    def test_dispatches_at_priority_zero(self, mock_apply, tmp_path):
        # Baselines decide readiness: they tie with staff (0) and run ahead of competitor (1) jobs
        self._write_baseline_notebook(tmp_path)
        from routes.tasks import _maybe_queue_baseline

        _maybe_queue_baseline(self.task, self.challenge, self.admin.id)

        mock_apply.assert_called_once()
        assert mock_apply.call_args.kwargs["priority"] == 0
        sub = Submission.query.filter_by(task_id=self.task.id, is_baseline=True).one()
        assert sub.status == "queued"

    @patch("tasks.evaluate_submission.apply_async", side_effect=RuntimeError("broker down"))
    def test_refused_enqueue_blocks_the_task_without_a_retry(self, mock_apply, tmp_path):
        # The broker is down, so an immediate retry cannot help; saving the task queues it again
        self._write_baseline_notebook(tmp_path)
        from routes.tasks import _maybe_queue_baseline

        _maybe_queue_baseline(self.task, self.challenge, self.admin.id)

        mock_apply.assert_called_once()
        db.session.expire_all()
        sub = Submission.query.filter_by(task_id=self.task.id, is_baseline=True).one()
        assert sub.detailed_status == "failed_infra"
        assert sub.celery_task_id is None
        assert sub.infra_retry_count == 0
        assert db.session.get(Task, self.task.id).problem_codes == ["ERR_BASELINE_FAILED"]

    @patch("tasks.evaluate_submission.apply_async")
    def test_saving_the_task_replaces_failed_baseline_runs(self, mock_apply, tmp_path):
        self._write_baseline_notebook(tmp_path)
        for retries in (0, 1):
            db.session.add(
                Submission(
                    user_id=self.admin.id,
                    challenge_id=self.challenge.id,
                    task_id=self.task.id,
                    status="failed",
                    detailed_status="failed_infra",
                    is_baseline=True,
                    infra_retry_count=retries,
                    code_cells="[]",
                )
            )
        db.session.commit()
        from routes.tasks import _maybe_queue_baseline

        _maybe_queue_baseline(self.task, self.challenge, self.admin.id)

        sub = Submission.query.filter_by(task_id=self.task.id, is_baseline=True).one()
        assert sub.status == "queued"
        assert sub.infra_retry_count == 0


class TestGetTask:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, client, auth_headers, redis_flush):
        self.client = client
        self._auth = auth_headers
        self.challenge = Challenge(
            title="Test",
            description="Test",
            max_eval_requests=5,
            start_time=utcnow() - timedelta(hours=2),
            end_time=utcnow() + timedelta(hours=2),
            is_frozen=False,
            timezone="UTC",
        )
        db.session.add(self.challenge)
        db.session.flush()
        self.task = Task(
            title="Task 1",
            challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
            gpu_required=False,
        )
        db.session.add(self.task)
        self.admin = User(username="admin", password_hash="x", role="admin", alias_id="A1")
        db.session.add(self.admin)
        self.comp = User(
            username="comp1",
            password_hash="x",
            role="competitor",
            alias_id="C1",
            challenge_id=self.challenge.id,
        )
        db.session.add(self.comp)
        db.session.commit()
        self.admin_token = generate_token(self.admin.id, role="admin")
        self.comp_token = generate_token(self.comp.id, role="competitor")

    def test_admin_can_get_task(self):
        resp = self.client.get(f"/api/tasks/{self.task.id}", headers=self._auth(self.admin_token))
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["title"] == "Task 1"

    def test_competitor_can_get_accessible_task(self):
        resp = self.client.get(f"/api/tasks/{self.task.id}", headers=self._auth(self.comp_token))
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["title"] == "Task 1"

    def test_competitor_blocked_when_task_not_started(self):
        self.challenge.start_time = utcnow() + timedelta(hours=24)
        self.challenge.end_time = utcnow() + timedelta(hours=48)
        db.session.commit()
        resp = self.client.get(f"/api/tasks/{self.task.id}", headers=self._auth(self.comp_token))
        assert resp.status_code == 403

    def test_returns_404_for_nonexistent_task(self):
        resp = self.client.get("/api/tasks/99999", headers=self._auth(self.admin_token))
        assert resp.status_code == 404

    def test_unauthenticated_returns_401(self):
        resp = self.client.get(f"/api/tasks/{self.task.id}")
        assert resp.status_code == 401


class TestDeleteTask:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, client, auth_headers, redis_flush):
        self.client = client
        self._auth = auth_headers
        self.challenge = Challenge(
            title="Test",
            description="Test",
            max_eval_requests=5,
            start_time=utcnow() - timedelta(hours=2),
            end_time=utcnow() + timedelta(hours=2),
            is_frozen=False,
        )
        db.session.add(self.challenge)
        db.session.flush()
        self.task = Task(
            title="Task 1",
            challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
            gpu_required=False,
        )
        db.session.add(self.task)
        self.admin = User(username="admin", password_hash="x", role="admin", alias_id="A1")
        db.session.add(self.admin)
        self.competitor = User(
            username="comp1",
            password_hash="x",
            role="competitor",
            alias_id="C1",
            challenge_id=self.challenge.id,
        )
        db.session.add(self.competitor)
        db.session.commit()
        self.admin_token = generate_token(self.admin.id, role="admin")
        self.comp_token = generate_token(self.competitor.id, role="competitor")

    def test_admin_can_delete_task(self):
        resp = self.client.delete(
            f"/api/tasks/{self.task.id}", headers=self._auth(self.admin_token)
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "deleted" in data.get("message", "")

    def test_competitor_cannot_delete_task(self):
        resp = self.client.delete(f"/api/tasks/{self.task.id}", headers=self._auth(self.comp_token))
        assert resp.status_code == 403

    def test_returns_404_for_nonexistent_task(self):
        resp = self.client.delete("/api/tasks/99999", headers=self._auth(self.admin_token))
        assert resp.status_code == 404

    def test_delete_removes_submissions(self):
        sub = Submission(
            user_id=self.admin.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
            code_cells="[]",
        )
        db.session.add(sub)
        db.session.commit()
        sub_id = sub.id
        resp = self.client.delete(
            f"/api/tasks/{self.task.id}", headers=self._auth(self.admin_token)
        )
        assert resp.status_code == 200
        assert Submission.query.filter_by(id=sub_id).first() is None


class TestDownloadTaskFile:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, client, auth_headers, redis_flush, app):
        self.client = client
        self._auth = auth_headers
        self.app = app
        self.app.config["UPLOAD_FOLDER"] = tempfile.mkdtemp()
        self.challenge = Challenge(
            title="Test",
            description="Test",
            max_eval_requests=5,
            start_time=utcnow() - timedelta(hours=2),
            end_time=utcnow() + timedelta(hours=2),
            is_frozen=False,
        )
        db.session.add(self.challenge)
        db.session.flush()
        self.task = Task(
            title="Task 1",
            challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
            gpu_required=False,
        )
        db.session.add(self.task)
        self.admin = User(username="admin", password_hash="x", role="admin", alias_id="A1")
        db.session.add(self.admin)
        self.comp = User(
            username="comp1",
            password_hash="x",
            role="competitor",
            alias_id="C1",
            challenge_id=self.challenge.id,
        )
        db.session.add(self.comp)
        db.session.commit()
        self.admin_token = generate_token(self.admin.id, role="admin")
        self.comp_token = generate_token(self.comp.id, role="competitor")
        self._upload_dir = self.app.config["UPLOAD_FOLDER"]

    def test_returns_404_for_nonexistent_file(self):
        resp = self.client.get(
            f"/api/tasks/{self.task.id}/download/nonexistent.txt",
            headers=self._auth(self.admin_token),
        )
        assert resp.status_code == 404

    def test_competitor_blocked_from_labels_parquet(self):
        resp = self.client.get(
            f"/api/tasks/{self.task.id}/download/labels.parquet",
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 403

    def test_competitor_blocked_when_task_not_started(self):
        self.challenge.start_time = utcnow() + timedelta(hours=24)
        self.challenge.end_time = utcnow() + timedelta(hours=48)
        db.session.commit()
        resp = self.client.get(
            f"/api/tasks/{self.task.id}/download/test.txt",
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 403

    def test_admin_can_download_baseline_notebook(self):
        test_file = os.path.join(self._upload_dir, "test_notebook.ipynb")
        with open(test_file, "w") as f:
            f.write("{}")
        self.task.baseline_notebook_path = test_file
        db.session.commit()
        resp = self.client.get(
            f"/api/tasks/{self.task.id}/download/test_notebook.ipynb",
            headers=self._auth(self.admin_token),
        )
        assert resp.status_code == 200

    def test_unauthenticated_returns_401(self):
        resp = self.client.get(f"/api/tasks/{self.task.id}/download/test.txt")
        assert resp.status_code == 401


class TestGetTaskSubmissions:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, client, auth_headers, redis_flush):
        self.client = client
        self._auth = auth_headers
        self.challenge = Challenge(
            title="Test",
            description="Test",
            max_eval_requests=5,
            start_time=utcnow() - timedelta(hours=2),
            end_time=utcnow() + timedelta(hours=2),
            is_frozen=False,
        )
        db.session.add(self.challenge)
        db.session.flush()
        self.task = Task(
            title="Task 1",
            challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
            gpu_required=False,
        )
        db.session.add(self.task)
        self.admin = User(username="admin", password_hash="x", role="admin", alias_id="A1")
        db.session.add(self.admin)
        self.comp = User(
            username="comp1",
            password_hash="x",
            role="competitor",
            alias_id="C1",
            challenge_id=self.challenge.id,
        )
        db.session.add(self.comp)
        db.session.flush()
        self.sub1 = Submission(
            user_id=self.comp.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
            code_cells="[]",
        )
        db.session.add(self.sub1)
        self.sub2 = Submission(
            user_id=self.admin.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
            code_cells="[]",
        )
        db.session.add(self.sub2)
        db.session.commit()
        self.admin_token = generate_token(self.admin.id, role="admin")
        self.comp_token = generate_token(self.comp.id, role="competitor")

    def test_admin_sees_all_submissions(self):
        resp = self.client.get(
            f"/api/tasks/{self.task.id}/submissions?page=1",
            headers=self._auth(self.admin_token),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "items" in data
        assert len(data["items"]) == 2

    def test_competitor_only_sees_own_submissions(self):
        resp = self.client.get(
            f"/api/tasks/{self.task.id}/submissions?page=1",
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "items" in data
        for s in data["items"]:
            assert s["user"]["id"] == self.comp.id

    def test_competitor_blocked_when_task_not_started(self):
        self.challenge.start_time = utcnow() + timedelta(hours=24)
        self.challenge.end_time = utcnow() + timedelta(hours=48)
        db.session.commit()
        resp = self.client.get(
            f"/api/tasks/{self.task.id}/submissions",
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 403

    def test_competitor_blocked_when_scores_finalized(self):
        self.challenge.scores_finalized = True
        db.session.commit()
        resp = self.client.get(
            f"/api/tasks/{self.task.id}/submissions",
            headers=self._auth(self.comp_token),
        )
        assert resp.status_code == 403
        # The same code as the challenge list, detail and live logs, so the page explains it
        assert resp.get_json()["code"] == "ERR_SUBMISSIONS_LOCKED"

    def test_admin_can_access_when_scores_finalized(self):
        self.challenge.scores_finalized = True
        db.session.commit()
        resp = self.client.get(
            f"/api/tasks/{self.task.id}/submissions",
            headers=self._auth(self.admin_token),
        )
        assert resp.status_code == 200

    def test_returns_404_for_nonexistent_task(self):
        import uuid

        dummy_uuid = str(uuid.uuid4())
        resp = self.client.get(
            f"/api/tasks/{dummy_uuid}/submissions", headers=self._auth(self.admin_token)
        )
        assert resp.status_code == 403

    def test_includes_submission_details(self):
        resp = self.client.get(
            f"/api/tasks/{self.task.id}/submissions?page=1",
            headers=self._auth(self.admin_token),
        )
        data = resp.get_json()
        item = data["items"][0]
        assert "status" in item
        assert "user" in item
        assert "task_id" in item

    def test_unauthenticated_returns_401(self):
        resp = self.client.get(f"/api/tasks/{self.task.id}/submissions")
        assert resp.status_code == 401


class TestWorkerDownloadTaskFile:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, redis_flush, app):
        self.app = app
        self.app.config["UPLOAD_FOLDER"] = tempfile.mkdtemp()
        self.client = self.app.test_client()
        self.challenge = Challenge(
            title="Test",
            description="Test",
            max_eval_requests=5,
            start_time=utcnow() - timedelta(hours=2),
            end_time=utcnow() + timedelta(hours=2),
            is_frozen=False,
        )
        db.session.add(self.challenge)
        db.session.flush()
        self.task = Task(
            title="Task 1",
            challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
            gpu_required=False,
        )
        db.session.add(self.task)
        db.session.commit()
        task_dir = os.path.join(self.app.config["UPLOAD_FOLDER"], f"task_{self.task.id}")
        os.makedirs(task_dir, exist_ok=True)
        with open(os.path.join(task_dir, "saved_test.txt"), "w") as f:
            f.write("file content")
        self.task.files = json.dumps([{"filename": "test.txt", "saved_name": "saved_test.txt"}])
        db.session.commit()
        self._upload_dir = self.app.config["UPLOAD_FOLDER"]

    @patch("routes.tasks._task_capability")
    def test_downloads_file_with_valid_token(self, mock_verify):
        mock_verify.return_value = {"attempt_id": "attempt"}
        resp = self.client.get(
            f"/api/worker/tasks/{self.task.id}/files/test.txt",
            headers={"X-Worker-Token": "valid-token"},
        )
        assert resp.status_code == 200

    @patch("routes.tasks._task_capability")
    def test_returns_401_without_valid_token(self, mock_verify):
        mock_verify.return_value = False
        resp = self.client.get(
            f"/api/worker/tasks/{self.task.id}/files/test.txt",
            headers={"X-Worker-Token": "bad-token"},
        )
        assert resp.status_code == 401

    @patch("routes.tasks._task_capability")
    def test_returns_404_for_nonexistent_file(self, mock_verify):
        mock_verify.return_value = {"attempt_id": "attempt"}
        resp = self.client.get(
            f"/api/worker/tasks/{self.task.id}/files/missing.txt",
            headers={"X-Worker-Token": "valid-token"},
        )
        assert resp.status_code == 404


class TestGetActiveDatasets:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, client, redis_flush):
        self.client = client
        self.challenge = Challenge(
            title="Test",
            description="Test",
            max_eval_requests=5,
            start_time=utcnow() - timedelta(hours=2),
            end_time=utcnow() + timedelta(hours=2),
            is_frozen=False,
            is_archived=False,
        )
        db.session.add(self.challenge)
        db.session.flush()
        self.task = Task(
            title="Task 1",
            challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
            gpu_required=False,
            custom_eval_code='load_dataset("dataset1")',
        )
        db.session.add(self.task)
        db.session.commit()

    def test_global_dataset_enumeration_is_retired(self):
        resp = self.client.get("/api/worker/active-datasets", headers={"X-Worker-Token": "token"})
        assert resp.status_code == 401

    def test_global_dataset_enumeration_stays_retired_for_archived_challenges(self):
        self.challenge.is_archived = True
        db.session.commit()
        resp = self.client.get("/api/worker/active-datasets", headers={"X-Worker-Token": "token"})
        assert resp.status_code == 401

    @patch("routes.tasks.check_worker_auth")
    def test_returns_401_without_valid_token(self, mock_verify):
        mock_verify.return_value = False
        resp = self.client.get("/api/worker/active-datasets", headers={"X-Worker-Token": "bad"})
        assert resp.status_code == 401


class TestGetTaskHfKey:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, client, redis_flush):
        self.client = client
        self.challenge = Challenge(
            title="Test",
            description="Test",
            max_eval_requests=5,
            start_time=utcnow() - timedelta(hours=2),
            end_time=utcnow() + timedelta(hours=2),
            is_frozen=False,
        )
        db.session.add(self.challenge)
        db.session.flush()
        self.task = Task(
            title="Task 1",
            challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
            gpu_required=False,
        )
        db.session.add(self.task)
        db.session.commit()

    @patch("routes.tasks._task_capability")
    def test_returns_hf_key(self, mock_verify):
        mock_verify.return_value = {"attempt_id": "attempt"}
        with patch.object(Task, "get_hf_api_key", return_value="my-key"):
            resp = self.client.get(
                f"/api/worker/tasks/{self.task.id}/hf-key",
                headers={"X-Worker-Token": "token"},
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["hf_key"] == "my-key"

    @patch("routes.tasks._task_capability")
    def test_returns_401_without_valid_token(self, mock_verify):
        mock_verify.return_value = False
        resp = self.client.get(
            f"/api/worker/tasks/{self.task.id}/hf-key",
            headers={"X-Worker-Token": "bad"},
        )
        assert resp.status_code == 401

    @patch("routes.tasks._task_capability")
    def test_returns_404_for_nonexistent_task(self, mock_verify):
        mock_verify.return_value = {"attempt_id": "attempt"}
        resp = self.client.get(
            "/api/worker/tasks/99999/hf-key", headers={"X-Worker-Token": "token"}
        )
        assert resp.status_code == 404


class TestGetActiveTasks:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, client, redis_flush):
        self.client = client
        self.challenge = Challenge(
            title="Active Tasks Test",
            description="Test",
            max_eval_requests=5,
            start_time=utcnow() - timedelta(hours=2),
            end_time=utcnow() + timedelta(hours=2),
            is_frozen=False,
            is_archived=False,
        )
        db.session.add(self.challenge)
        db.session.flush()
        self.task = Task(
            title="Task With Files",
            challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
            gpu_required=False,
            files=json.dumps([{"filename": "data.csv", "saved_name": "data.csv"}]),
            custom_eval_code="def evaluate(): pass",
        )
        db.session.add(self.task)
        db.session.commit()

    def test_global_task_enumeration_is_retired(self):
        resp = self.client.get(
            "/api/worker/active-tasks",
            headers={"X-Worker-Token": "valid"},
        )
        assert resp.status_code == 401

    def test_global_task_enumeration_stays_retired_for_archived_challenges(self):
        self.challenge.is_archived = True
        db.session.commit()
        resp = self.client.get(
            "/api/worker/active-tasks",
            headers={"X-Worker-Token": "valid"},
        )
        assert resp.status_code == 401

    @patch("routes.tasks.check_worker_auth")
    def test_returns_401_without_valid_token(self, mock_verify):
        mock_verify.return_value = False
        resp = self.client.get(
            "/api/worker/active-tasks",
            headers={"X-Worker-Token": "bad"},
        )
        assert resp.status_code == 401


class TestGetSubmissionRunContent:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, client, redis_flush):
        self.client = client
        self.challenge = Challenge(
            title="Run Content",
            description="Test",
            max_eval_requests=5,
            start_time=utcnow() - timedelta(hours=2),
            end_time=utcnow() + timedelta(hours=2),
            is_frozen=False,
            is_archived=False,
        )
        db.session.add(self.challenge)
        db.session.flush()
        self.task = Task(
            title="Task 1",
            challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            gpu_required=False,
            custom_eval_code="def evaluate(): pass",
        )
        db.session.add(self.task)
        db.session.flush()
        user = User(
            username="runcontent_comp",
            password_hash="x",
            role="competitor",
            challenge_id=self.challenge.id,
        )
        db.session.add(user)
        db.session.flush()
        self.submission = Submission(
            user_id=user.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="queued",
            code_cells=json.dumps([{"source": ["x=1", "y=2"]}, {"source": "print(y)"}]),
        )
        db.session.add(self.submission)
        db.session.commit()

    @patch("routes.tasks._worker_capability")
    def test_returns_401_on_missing_token(self, mock_verify):
        mock_verify.return_value = False
        resp = self.client.get(
            f"/api/worker/submission-run-content/{self.submission.id}",
            headers={"X-Worker-Token": "bad"},
        )
        assert resp.status_code == 401

    @patch("routes.tasks._worker_capability")
    def test_returns_401_on_submission_id_mismatch(self, mock_verify):
        mock_verify.return_value = None
        resp = self.client.get(
            f"/api/worker/submission-run-content/{self.submission.id}",
            headers={"X-Worker-Token": "valid"},
        )
        assert resp.status_code == 401

    @patch("routes.tasks._worker_capability")
    def test_returns_404_for_missing_submission(self, mock_verify):
        missing_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        mock_verify.return_value = {"attempt_id": "attempt"}
        resp = self.client.get(
            f"/api/worker/submission-run-content/{missing_id}",
            headers={"X-Worker-Token": "valid"},
        )
        assert resp.status_code == 404

    @patch("routes.tasks._worker_capability")
    def test_returns_user_code_and_evaluator(self, mock_verify):
        mock_verify.return_value = {"attempt_id": "attempt"}
        resp = self.client.get(
            f"/api/worker/submission-run-content/{self.submission.id}",
            headers={"X-Worker-Token": "valid"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["user_code"] == "x=1y=2\n\nprint(y)"
        assert data["custom_eval_code"] == "def evaluate(): pass"

    @patch("routes.tasks._worker_capability")
    @patch("routes.tasks.open")
    def test_reads_evaluator_script_file_when_code_is_null(self, mock_open, mock_verify):
        self.task.custom_eval_code = None
        self.task.evaluator_script_path = "/tmp/evaluator.py"
        db.session.commit()
        mock_verify.return_value = {"attempt_id": "attempt"}
        mock_open.return_value.__enter__.return_value.read.return_value = "def ev(): pass"
        resp = self.client.get(
            f"/api/worker/submission-run-content/{self.submission.id}",
            headers={"X-Worker-Token": "valid"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["custom_eval_code"] == "def ev(): pass"
