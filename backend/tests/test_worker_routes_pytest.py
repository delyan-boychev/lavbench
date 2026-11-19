"""Tests for the worker routes."""

import base64
import json
import os
import time
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from models import Challenge, Submission, Task, User, db
from services.submission_status import COMPLETED, RUNNING, transition
from utils.auth_utils import generate_token
from utils.dates import utcnow
from utils.worker_auth import issue_worker_capability, sign_worker_token


class TestWorkerEndpoints:
    @pytest.fixture(autouse=True)
    def setup(self, client, db_session, app_ctx, redis_flush, monkeypatch):
        self.client = client
        self._monkeypatch = monkeypatch
        import tempfile

        upload_folder = tempfile.mkdtemp()
        from flask import current_app

        current_app.config["UPLOAD_FOLDER"] = upload_folder
        self.upload_folder = upload_folder
        self.seed_basic_data()
        yield
        import shutil

        shutil.rmtree(upload_folder, ignore_errors=True)

    def seed_basic_data(self):
        self.challenge = Challenge(
            title="Test Challenge",
            description="Test",
            max_eval_requests=5,
            start_time=utcnow() - timedelta(hours=2),
            end_time=utcnow() + timedelta(hours=2),
            is_frozen=False,
        )
        db.session.add(self.challenge)
        db.session.commit()

        self.task = Task(
            title="Task 1",
            challenge_id=self.challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
            metrics_config={"accuracy": {"weight": 1.0, "higher_is_better": True}},
        )
        db.session.add(self.task)

        self.competitor = User(
            username="test_comp",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Comp-001",
            challenge_id=self.challenge.id,
        )
        self.competitor.set_demographics("Jane", "Doe", "12", "School", "City")
        db.session.add(self.competitor)
        db.session.commit()

        self.submission = Submission(
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            user_id=self.competitor.id,
            status="running",
            celery_task_id="attempt-test-worker-routes",
            code_cells="[]",
        )
        db.session.add(self.submission)
        db.session.commit()

        # Generate test Ed25519 keypair and sign a nonce for worker auth
        self._worker_key = Ed25519PrivateKey.generate()
        self.worker_id = "test-worker"
        private_key = base64.urlsafe_b64encode(self._worker_key.private_bytes_raw()).decode()
        public_key = base64.urlsafe_b64encode(
            self._worker_key.public_key().public_bytes_raw()
        ).decode()
        self._monkeypatch.setenv("WORKER_ID", self.worker_id)
        self._monkeypatch.setenv("WORKER_PRIVATE_KEY", private_key)
        self._monkeypatch.setenv(
            "WORKER_PUBLIC_KEYS_JSON", json.dumps({self.worker_id: public_key})
        )
        self._monkeypatch.setenv("WORKER_CAPABILITY_SECRET", "test-worker-capability-secret")

        self.admin = User(
            username="test_admin",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            alias_id="Admin-001",
        )
        db.session.add(self.admin)
        db.session.commit()
        self.admin_token = generate_token(self.admin.id, role="admin")

    def _worker_headers(
        self,
        operation="report_submission",
        resource_type="submission",
        resource_id=None,
        attempt_id=None,
        method=None,
    ):
        resource_id = resource_id or self.submission.id
        attempt_id = attempt_id or self.submission.celery_task_id
        method = method or ("POST" if operation.startswith("report") else "GET")
        capability = issue_worker_capability(
            worker_id=self.worker_id,
            method=method,
            operation=operation,
            resource_type=resource_type,
            resource_id=resource_id,
            attempt_id=attempt_id,
        )
        from utils.cache_utils import get_coordination_client

        coordination = get_coordination_client()
        assert coordination is not None
        coordination.set(f"worker:attempt:{attempt_id}", self.worker_id, ex=3600)
        return {
            "X-Worker-Token": sign_worker_token(),
            "X-Worker-Capability": capability,
            "Content-Type": "application/json",
        }

    def _auth_headers(self, token=None):
        t = token or self.admin_token
        return {"Authorization": f"Bearer {t}"}

    def test_report_progress_success(self):
        resp = self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={"status": "completed", "detailed_status": "done"},
            headers=self._worker_headers(),
        )
        assert resp.status_code == 200

    def test_report_progress_updates_submission(self):
        resp = self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={
                "status": "completed",
                "detailed_status": "done",
                "public_score": 0.95,
                "private_score": 0.85,
                "execution_time_ms": 1234,
                "logs": "eval completed",
            },
            headers=self._worker_headers(),
        )
        assert resp.status_code == 200

        # Wait for the log to be committed and visible (max 5 seconds)
        timeout = 5
        start = time.time()
        while time.time() - start < timeout:
            db.session.expire_all()
            sub = db.session.get(Submission, self.submission.id)
            if "eval completed" in sub.logs:
                break
            time.sleep(0.1)

        # Final assertions
        assert sub.status == "completed"
        assert sub.public_score == 0.95
        assert sub.private_score == 0.85
        assert sub.execution_time_ms == 1234
        assert "eval completed" in sub.logs

    def test_report_progress_invalid_token(self):
        resp = self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={"status": "completed", "detailed_status": "done"},
            headers={"X-Worker-Token": "invalid-token"},
        )
        assert resp.status_code == 401

    def test_report_progress_wrong_submission_id(self):
        resp = self.client.post(
            "/api/worker/report/99999",
            json={"status": "completed", "detailed_status": "done"},
            headers=self._worker_headers(),
        )
        assert resp.status_code == 404

    def test_report_progress_missing_token(self):
        resp = self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={"status": "completed", "detailed_status": "done"},
        )
        assert resp.status_code == 401

    def test_report_progress_stores_the_scoring_time(self):
        resp = self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={"status": "running", "evaluation_time_ms": 1500},
            headers=self._worker_headers(),
        )
        assert resp.status_code == 200
        db.session.refresh(self.submission)
        assert self.submission.evaluation_time_ms == 1500
        bad = self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={"evaluation_time_ms": -1},
            headers=self._worker_headers(),
        )
        assert bad.status_code == 400

    def test_report_progress_rejects_nan_score(self):
        resp = self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={"status": "completed", "public_score": float("nan")},
            headers=self._worker_headers(),
        )
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "ERR_INVALID_PUBLIC_SCORE"

    def test_report_progress_rejects_non_numeric_execution_time(self):
        resp = self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={"status": "completed", "execution_time_ms": "not-a-number"},
            headers=self._worker_headers(),
        )
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "ERR_INVALID_EXECUTION_TIME"

    def test_report_progress_rejects_negative_execution_time(self):
        resp = self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={"status": "completed", "execution_time_ms": -5},
            headers=self._worker_headers(),
        )
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "ERR_INVALID_EXECUTION_TIME"

    def test_report_progress_rejected_for_killed_submission(self):
        killed = Submission(
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            user_id=self.competitor.id,
            status="failed",
            detailed_status="killed",
            celery_task_id="attempt-killed",
            code_cells="[]",
        )
        db.session.add(killed)
        db.session.commit()
        headers = self._worker_headers(resource_id=killed.id, attempt_id=killed.celery_task_id)
        resp = self.client.post(
            f"/api/worker/report/{killed.id}",
            json={"status": "completed", "detailed_status": "done", "public_score": 0.9},
            headers=headers,
        )
        assert resp.status_code == 409
        assert resp.get_json()["code"] == "ERR_SUBMISSION_KILLED"
        db.session.expire_all()
        sub = db.session.get(Submission, killed.id)
        assert sub.detailed_status == "killed"
        assert sub.public_score is None

    def test_report_without_status_never_writes_onto_a_terminal_run(self):
        assert transition(
            self.submission.id,
            COMPLETED,
            from_statuses=(RUNNING,),
            fields={"public_score": 0.9},
        )
        self.submission.logs = "scored"
        db.session.commit()
        resp = self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={"public_score": 0.1, "detailed_status": "evaluating", "logs": "late"},
            headers=self._worker_headers(),
        )
        assert resp.status_code == 409
        assert resp.get_json()["code"] == "ERR_STALE_WORKER_ATTEMPT"
        db.session.expire_all()
        sub = db.session.get(Submission, self.submission.id)
        assert (sub.status, sub.public_score, sub.logs) == (COMPLETED, 0.9, "scored")

    def test_report_without_status_updates_an_active_run(self):
        resp = self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={"detailed_status": "evaluating", "logs": "scoring"},
            headers=self._worker_headers(),
        )
        assert resp.status_code == 200
        db.session.expire_all()
        sub = db.session.get(Submission, self.submission.id)
        assert (sub.status, sub.detailed_status, sub.logs) == (RUNNING, "evaluating", "scoring")
        assert sub.finished_at is None

    @pytest.mark.parametrize("detailed", ["failed_infra", "killed"])
    def test_a_failure_detail_is_refused_without_the_failed_status(self, detailed):
        resp = self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={"status": "completed", "detailed_status": detailed, "public_score": 0.5},
            headers=self._worker_headers(),
        )
        assert resp.status_code == 400
        db.session.expire_all()
        assert db.session.get(Submission, self.submission.id).status == RUNNING

    def test_a_completed_report_records_when_the_run_finished(self):
        before = utcnow()
        resp = self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={"status": "completed", "detailed_status": "completed", "public_score": 0.5},
            headers=self._worker_headers(),
        )
        assert resp.status_code == 200
        db.session.expire_all()
        sub = db.session.get(Submission, self.submission.id)
        assert sub.status == COMPLETED
        assert sub.finished_at is not None and sub.finished_at >= before

    def test_report_progress_building_env_does_not_stamp_executed_at(self):
        # Pre-execution phase (image build / GPU acquisition) must not start the
        # Watchdog clock
        self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={"status": "running", "detailed_status": "building_env"},
            headers=self._worker_headers(),
        )
        sub = db.session.get(Submission, self.submission.id)
        assert sub.executed_at is None

    def test_report_progress_running_inference_stamps_executed_at(self):
        self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={"status": "running", "detailed_status": "running_inference"},
            headers=self._worker_headers(),
        )
        sub = db.session.get(Submission, self.submission.id)
        assert sub.executed_at is not None

    def test_report_progress_saves_metrics_payload(self):
        self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={
                "status": "completed",
                "detailed_status": "done",
                "metrics_payload_public": json.dumps({"accuracy": 0.9}),
                "metrics_payload_private": json.dumps({"accuracy": 0.8}),
            },
            headers=self._worker_headers(),
        )
        sub = db.session.get(Submission, self.submission.id)
        assert sub.metrics_payload_public is not None
        assert sub.metrics_payload_private is not None

    def test_report_progress_saves_gpu_node_and_short_metric_keys(self):
        self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={
                "status": "completed",
                "detailed_status": "done",
                "metrics_payload_pub": json.dumps({"accuracy": 0.9}),
                "metrics_payload_priv": json.dumps({"accuracy": 0.8}),
                "gpu_node": "gpu-01",
            },
            headers=self._worker_headers(),
        )
        sub = db.session.get(Submission, self.submission.id)
        assert sub.metrics_payload_public is not None
        assert sub.metrics_payload_private is not None
        assert sub.gpu_node == "gpu-01"

    def test_report_progress_with_fallback_data(self):
        from utils.cache_utils import get_redis_client

        r = get_redis_client()
        if r:
            r.delete(f"submission:{self.submission.id}:fallback")
        resp = self.client.post(
            f"/api/worker/report/{self.submission.id}",
            json={
                "status": "completed",
                "detailed_status": "done",
                "fallback_data": {"test": True},
            },
            headers=self._worker_headers(),
        )
        assert resp.status_code == 200

    def test_download_task_file_success(self):
        os.makedirs(os.path.join(self.upload_folder, "task_" + str(self.task.id)), exist_ok=True)
        task_dir = os.path.join(self.upload_folder, "task_" + str(self.task.id))
        with open(os.path.join(task_dir, "data.csv"), "w") as f:
            f.write("col1,col2\n1,2")
        self.task.files = json.dumps([{"filename": "data.csv", "saved_name": "data.csv"}])
        db.session.commit()

        resp = self.client.get(
            f"/api/worker/tasks/{self.task.id}/files/data.csv",
            headers=self._worker_headers("task_file", "task", self.task.id),
        )
        assert resp.status_code == 200
        assert b"col1,col2" in resp.data

    def _write_task_file(self, body: bytes, **extra):
        task_dir = os.path.join(self.upload_folder, "task_" + str(self.task.id))
        os.makedirs(task_dir, exist_ok=True)
        with open(os.path.join(task_dir, "data.csv"), "wb") as f:
            f.write(body)
        entry = {"filename": "data.csv", "saved_name": "data.csv", **extra}
        self.task.files = json.dumps([entry])
        db.session.commit()

    def test_download_task_file_sends_length_and_sha256_etag(self):
        import hashlib

        body = b"col1,col2\n1,2"
        digest = hashlib.sha256(body).hexdigest()
        self._write_task_file(body, size_bytes=len(body), sha256=digest)
        resp = self.client.get(
            f"/api/worker/tasks/{self.task.id}/files/data.csv",
            headers=self._worker_headers("task_file", "task", self.task.id),
        )
        assert resp.status_code == 200
        assert resp.headers["Content-Length"] == str(len(body))
        assert resp.headers["ETag"] == f'"{digest}"'
        assert resp.data == body

    def test_download_task_file_without_sha256_has_no_etag(self):
        self._write_task_file(b"legacy")
        resp = self.client.get(
            f"/api/worker/tasks/{self.task.id}/files/data.csv",
            headers=self._worker_headers("task_file", "task", self.task.id),
        )
        assert resp.status_code == 200
        assert resp.headers["Content-Length"] == "6"
        assert "ETag" not in resp.headers

    def test_download_task_file_missing_on_disk_is_404(self):
        self.task.files = json.dumps([{"filename": "data.csv", "saved_name": "gone.csv"}])
        db.session.commit()
        resp = self.client.get(
            f"/api/worker/tasks/{self.task.id}/files/data.csv",
            headers=self._worker_headers("task_file", "task", self.task.id),
        )
        assert resp.status_code == 404
        assert resp.get_json()["code"] == "ERR_FILE_NOT_FOUND"

    def test_download_rate_limit_allows_syncing_many_files(self):
        self._write_task_file(b"x")
        url = f"/api/worker/tasks/{self.task.id}/files/data.csv"
        codes = [
            self.client.get(
                url, headers=self._worker_headers("task_file", "task", self.task.id)
            ).status_code
            for _ in range(30)
        ]
        assert codes == [200] * 30

    def test_download_task_file_wrong_task(self):
        resp = self.client.get(
            "/api/worker/tasks/99999/files/data.csv",
            headers=self._worker_headers("task_file", "task", self.task.id),
        )
        assert resp.status_code == 404

    def test_retired_hf_routes_are_gone(self):
        headers = self._worker_headers()
        assert self.client.get("/api/worker/active-datasets", headers=headers).status_code == 404
        hf_key = self.client.get(f"/api/worker/tasks/{self.task.id}/hf-key", headers=headers)
        assert hf_key.status_code == 404

    # ── The worker fetches a file task's Parquet only with that submission's capability ──

    def _artifact(self, submission, body):
        path = os.path.join(self.upload_folder, f"artifact_{submission.id}.parquet")
        with open(path, "wb") as handle:
            handle.write(body)
        submission.artifact_path = path
        submission.artifact_sha256 = "a" * 64
        db.session.commit()

    def test_the_capability_for_this_submission_reads_its_file(self):
        self._artifact(self.submission, b"PAR1 data")
        headers = self._worker_headers(operation="submission_artifact")
        resp = self.client.get(
            f"/api/worker/submission-artifact/{self.submission.id}", headers=headers
        )
        assert resp.status_code == 200
        assert resp.data == b"PAR1 data"
        assert resp.headers["ETag"] == f'"{"a" * 64}"'

    def test_another_operation_or_submission_is_refused(self):
        self._artifact(self.submission, b"PAR1 data")
        other = Submission(
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            user_id=self.competitor.id,
            status="running",
            celery_task_id="attempt-other",
        )
        db.session.add(other)
        db.session.commit()
        self._artifact(other, b"PAR1 other")
        wrong_operation = self._worker_headers(operation="submission_run_content")
        resp = self.client.get(
            f"/api/worker/submission-artifact/{self.submission.id}", headers=wrong_operation
        )
        assert resp.status_code == 401
        own = self._worker_headers(operation="submission_artifact")
        resp = self.client.get(f"/api/worker/submission-artifact/{other.id}", headers=own)
        assert resp.status_code == 401
        assert b"other" not in resp.data

    def test_a_finished_attempt_is_refused(self):
        self._artifact(self.submission, b"PAR1 data")
        headers = self._worker_headers(operation="submission_artifact")
        self.submission.celery_task_id = "attempt-newer"
        db.session.commit()
        resp = self.client.get(
            f"/api/worker/submission-artifact/{self.submission.id}", headers=headers
        )
        assert resp.status_code == 401

    # ── A worker fetches a task's HF ZIP only for a live attempt of that task ──

    def _store(self, data=b"PK zip bytes"):
        import hashlib

        sha256 = hashlib.sha256(data).hexdigest()
        os.makedirs(os.path.join(self.upload_folder, "hf"), exist_ok=True)
        with open(os.path.join(self.upload_folder, "hf", f"{sha256}.zip"), "wb") as handle:
            handle.write(data)
        self.task.hf_zip_sha256 = sha256
        # Dispatch records the task's ZIP on the run
        self.submission.hf_zip_sha256 = sha256
        db.session.commit()
        return sha256

    def _claim(self):
        resp = self.client.post(
            f"/api/worker/capabilities/{self.submission.id}",
            json={"attempt_id": self.submission.celery_task_id},
            headers={"X-Worker-Token": sign_worker_token()},
        )
        assert resp.status_code == 200, resp.get_json()
        return resp.get_json()["capabilities"]

    def test_the_capability_is_issued_only_for_a_run_that_recorded_a_zip(self):
        assert "hf_zip" not in self._claim()
        assert "task_hf_key" not in self._claim()
        self._store()
        assert "hf_zip" in self._claim()
        self.submission.hf_zip_sha256 = None
        db.session.commit()
        assert "hf_zip" not in self._claim()

    def test_dispatch_records_the_zip_of_notebook_runs_only(self):
        from utils.metadata import build_submission_metadata

        sha256 = self._store()
        self.submission.hf_zip_sha256 = None
        metadata = build_submission_metadata(self.task, self.challenge, self.submission, [], False)
        assert self.submission.hf_zip_sha256 == sha256 == metadata["hf_zip_sha256"]
        self.task.evaluation_mode = "file"
        metadata = build_submission_metadata(self.task, self.challenge, self.submission, [], False)
        assert self.submission.hf_zip_sha256 is None
        assert metadata["hf_zip_sha256"] is None

    def test_a_run_keeps_its_recorded_zip_after_the_task_replaces_it(self):
        sha256 = self._store()
        newer = self._store(b"PK newer bytes")
        self.submission.hf_zip_sha256 = sha256
        db.session.commit()
        assert self.task.hf_zip_sha256 == newer
        headers = self._worker_headers("hf_zip", "hf_zip", sha256)
        resp = self.client.get(f"/api/worker/hf-zip/{sha256}", headers=headers)
        assert resp.status_code == 200
        assert resp.data == b"PK zip bytes"
        stale = self._worker_headers("hf_zip", "hf_zip", newer)
        assert self.client.get(f"/api/worker/hf-zip/{newer}", headers=stale).status_code == 401

    def test_the_task_zip_streams_with_its_hash(self):
        sha256 = self._store()
        headers = self._worker_headers("hf_zip", "hf_zip", sha256)
        resp = self.client.get(f"/api/worker/hf-zip/{sha256}", headers=headers)
        assert resp.status_code == 200
        assert resp.data == b"PK zip bytes"
        assert resp.headers["ETag"] == f'"{sha256}"'

    def test_another_zip_or_a_finished_attempt_is_refused(self):
        sha256 = self._store()
        other = "c" * 64
        with open(os.path.join(self.upload_folder, "hf", f"{other}.zip"), "wb") as handle:
            handle.write(b"other")
        headers = self._worker_headers("hf_zip", "hf_zip", other)
        assert self.client.get(f"/api/worker/hf-zip/{other}", headers=headers).status_code == 401
        headers = self._worker_headers("task_file", "task", self.task.id)
        assert self.client.get(f"/api/worker/hf-zip/{sha256}", headers=headers).status_code == 401
        headers = self._worker_headers("hf_zip", "hf_zip", sha256)
        assert transition(self.submission.id, COMPLETED, from_statuses=(RUNNING,))
        db.session.commit()
        assert self.client.get(f"/api/worker/hf-zip/{sha256}", headers=headers).status_code == 401

    def test_a_missing_or_malformed_zip_is_not_found(self):
        sha256 = self._store()
        os.remove(os.path.join(self.upload_folder, "hf", f"{sha256}.zip"))
        headers = self._worker_headers("hf_zip", "hf_zip", sha256)
        assert self.client.get(f"/api/worker/hf-zip/{sha256}", headers=headers).status_code == 404
        assert self.client.get("/api/worker/hf-zip/not-a-hash", headers=headers).status_code == 404
