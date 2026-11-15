"""Tests for the baseline lifecycle and every way a baseline run ends."""

import base64
import json
import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import tasks
from models import Submission, Task, db
from services.baseline_service import apply_baseline_outcome, current_baseline
from utils.dates import utcnow
from utils.sse_utils import get_submission_final_status
from utils.worker_auth import issue_worker_capability, sign_worker_token

BASELINE_FAILED = "ERR_BASELINE_FAILED"


class _BaselineFixture:
    """Seed a task with a baseline run and read the task back from the database."""

    @pytest.fixture(autouse=True)
    def _seed(self, db_session, redis_flush, sample_challenge, sample_task, sample_admin, tmp_path):
        self.challenge = sample_challenge
        self.task = sample_task
        self.admin = sample_admin
        notebook = tmp_path / "baseline.ipynb"
        notebook.write_text(json.dumps({"cells": [{"cell_type": "code", "source": ["x = 1"]}]}))
        self.task.baseline_notebook_path = str(notebook)
        db.session.commit()

    def _baseline(self, status="running", detailed_status=None, retries=0, **fields):
        fields.setdefault("celery_task_id", f"attempt-{uuid.uuid4().hex}")
        sub = Submission(
            user_id=self.admin.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status=status,
            detailed_status=detailed_status or status,
            is_baseline=True,
            infra_retry_count=retries,
            code_cells=json.dumps([{"source": "x = 1"}]),
            **fields,
        )
        db.session.add(sub)
        db.session.commit()
        return sub

    def _set_codes(self, codes):
        self.task.problem_codes = codes
        db.session.commit()

    def _codes(self):
        db.session.expire_all()
        return db.session.get(Task, self.task.id).problem_codes

    def _reload(self, sub_id):
        db.session.expire_all()
        return db.session.get(Submission, sub_id)

    def _baselines(self):
        db.session.expire_all()
        query = Submission.query.filter_by(task_id=self.task.id, is_baseline=True)
        return query.order_by(Submission.id).all()

    def _rerun_of(self, ended):
        """Return the single baseline row created after *ended*."""
        newer = [s for s in self._baselines() if s.id > ended.id]
        assert len(newer) == 1
        return newer[0]


class TestApplyBaselineOutcome(_BaselineFixture):
    def test_completed_clears_the_code(self):
        self._set_codes([BASELINE_FAILED, "ERR_TASK_BUILD_FAILED"])
        sub = self._baseline(status="completed")
        apply_baseline_outcome(sub)
        assert self._codes() == ["ERR_TASK_BUILD_FAILED"]

    def test_completed_clears_the_last_code(self):
        self._set_codes([BASELINE_FAILED])
        sub = self._baseline(status="completed")
        apply_baseline_outcome(sub)
        assert self._codes() is None

    def test_failed_sets_the_code(self):
        sub = self._baseline(status="failed", detailed_status="failed")
        apply_baseline_outcome(sub)
        assert self._codes() == [BASELINE_FAILED]

    def test_failed_keeps_other_codes(self):
        self._set_codes(["ERR_TASK_BUILD_FAILED"])
        sub = self._baseline(status="failed", detailed_status="failed")
        apply_baseline_outcome(sub)
        assert self._codes() == [BASELINE_FAILED, "ERR_TASK_BUILD_FAILED"]

    @patch("tasks.evaluate_submission.apply_async")
    def test_infra_failure_reruns_as_a_new_row(self, mock_apply):
        old_created = utcnow() - timedelta(hours=3)
        ended = self._baseline(
            status="failed",
            detailed_status="failed_infra",
            created_at=old_created,
            executed_at=old_created,
            logs="worker log",
        )
        old_attempt = ended.celery_task_id

        apply_baseline_outcome(ended)

        rerun = self._rerun_of(ended)
        assert rerun.status == "queued"
        assert rerun.infra_retry_count == 1
        assert rerun.user_id == ended.user_id
        assert json.loads(rerun.code_cells) == [{"source": "x = 1"}]
        assert current_baseline(self.task.id).id == rerun.id
        mock_apply.assert_called_once()
        assert mock_apply.call_args.kwargs["priority"] == 0
        assert mock_apply.call_args.kwargs["task_id"] == rerun.celery_task_id
        assert self._codes() is None
        # The failed run stays as it ended
        ended = self._reload(ended.id)
        assert ended.status == "failed"
        assert ended.detailed_status == "failed_infra"
        assert ended.infra_retry_count == 0
        assert ended.celery_task_id == old_attempt
        assert ended.created_at == old_created
        assert ended.executed_at == old_created
        assert ended.logs == "worker log"

    @patch("tasks.evaluate_submission.apply_async")
    def test_reruns_stop_at_two_then_set_the_code(self, mock_apply):
        run = self._baseline(status="failed", detailed_status="failed_infra")
        for expected_retries in (1, 2):
            apply_baseline_outcome(run)
            run = self._rerun_of(run)
            assert run.infra_retry_count == expected_retries
            assert mock_apply.call_count == expected_retries
            assert self._codes() is None
            # The new run fails on the platform again
            run.status = "failed"
            run.detailed_status = "failed_infra"
            db.session.commit()

        apply_baseline_outcome(run)

        assert mock_apply.call_count == 2
        assert len(self._baselines()) == 3
        assert self._codes() == [BASELINE_FAILED]

    @patch("tasks.evaluate_submission.apply_async")
    def test_infra_failure_reruns_despite_an_earlier_baseline_failure(self, mock_apply):
        self._set_codes([BASELINE_FAILED])
        ended = self._baseline(status="failed", detailed_status="failed_infra")
        apply_baseline_outcome(ended)
        assert self._rerun_of(ended).infra_retry_count == 1
        assert self._codes() == [BASELINE_FAILED]

    @patch("tasks.evaluate_submission.apply_async")
    def test_no_rerun_when_the_task_is_blocked(self, mock_apply):
        # The worker reports a build failure before the run's failed_infra status
        self._set_codes(["ERR_TASK_BUILD_FAILED"])
        ended = self._baseline(status="failed", detailed_status="failed_infra")
        apply_baseline_outcome(ended)
        mock_apply.assert_not_called()
        assert len(self._baselines()) == 1
        assert self._codes() == [BASELINE_FAILED, "ERR_TASK_BUILD_FAILED"]

    @patch("tasks.evaluate_submission.apply_async")
    def test_no_rerun_after_a_refused_enqueue(self, mock_apply):
        ended = self._baseline(status="failed", detailed_status="failed_infra", celery_task_id=None)
        apply_baseline_outcome(ended)
        mock_apply.assert_not_called()
        assert len(self._baselines()) == 1
        assert self._codes() == [BASELINE_FAILED]

    @patch("tasks.evaluate_submission.apply_async", side_effect=RuntimeError("broker down"))
    def test_refused_rerun_sets_the_code(self, mock_apply):
        ended = self._baseline(status="failed", detailed_status="failed_infra")
        apply_baseline_outcome(ended)
        mock_apply.assert_called_once()
        refused = self._rerun_of(ended)
        assert refused.detailed_status == "failed_infra"
        assert refused.infra_retry_count == 1
        assert refused.celery_task_id is None
        assert "Submission queue unavailable: broker down" in refused.logs
        assert self._reload(ended.id).infra_retry_count == 0
        assert self._codes() == [BASELINE_FAILED]

    def test_rerun_without_baseline_code_sets_the_code(self):
        self.task.baseline_notebook_path = None
        db.session.commit()
        ended = self._baseline(status="failed", detailed_status="failed_infra")
        apply_baseline_outcome(ended)
        assert len(self._baselines()) == 1
        assert self._codes() == [BASELINE_FAILED]

    @patch("tasks.evaluate_submission.apply_async")
    def test_stale_update_on_a_superseded_run_changes_nothing(self, mock_apply):
        ended = self._baseline(status="failed", detailed_status="failed_infra")
        apply_baseline_outcome(ended)
        rerun = self._rerun_of(ended)

        # A late handler of the old attempt rewrites the old row and settles it again
        ended = self._reload(ended.id)
        ended.detailed_status = "failed"
        db.session.commit()
        apply_baseline_outcome(ended)

        assert mock_apply.call_count == 1
        assert self._reload(rerun.id).status == "queued"
        assert len(self._baselines()) == 2
        assert self._codes() is None

    def test_non_current_baseline_changes_nothing(self):
        self._set_codes([BASELINE_FAILED])
        old = self._baseline(status="completed")
        newer = self._baseline(status="running")
        assert current_baseline(self.task.id).id == newer.id
        apply_baseline_outcome(old)
        assert self._codes() == [BASELINE_FAILED]

    @patch("tasks.evaluate_submission.apply_async")
    def test_non_current_infra_failure_is_not_rerun(self, mock_apply):
        old = self._baseline(status="failed", detailed_status="failed_infra")
        self._baseline(status="running")
        apply_baseline_outcome(old)
        mock_apply.assert_not_called()
        assert self._reload(old.id).status == "failed"
        assert self._codes() is None

    def test_competitor_submission_changes_nothing(self, sample_competitor):
        sub = Submission(
            user_id=sample_competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="failed",
            detailed_status="failed",
        )
        db.session.add(sub)
        db.session.commit()
        apply_baseline_outcome(sub)
        assert self._codes() is None

    def test_running_baseline_changes_nothing(self):
        self._set_codes([BASELINE_FAILED])
        sub = self._baseline(status="running")
        apply_baseline_outcome(sub)
        assert self._codes() == [BASELINE_FAILED]

    def test_readiness_change_invalidates_the_challenge_cache(self):
        sub = self._baseline(status="failed", detailed_status="failed")
        with patch("utils.cache.invalidate_entity_cache") as invalidate:
            apply_baseline_outcome(sub)
        invalidate.assert_called_once_with(self.challenge.id)

    def test_unchanged_readiness_keeps_the_cache(self):
        sub = self._baseline(status="completed")
        with patch("utils.cache.invalidate_entity_cache") as invalidate:
            apply_baseline_outcome(sub)
        invalidate.assert_not_called()


class TestReportRoute(_BaselineFixture):
    @pytest.fixture(autouse=True)
    def _worker(self, client, monkeypatch):
        self.client = client
        key = Ed25519PrivateKey.generate()
        self.worker_id = "baseline-worker"
        private_key = base64.urlsafe_b64encode(key.private_bytes_raw()).decode()
        public_key = base64.urlsafe_b64encode(key.public_key().public_bytes_raw()).decode()
        monkeypatch.setenv("WORKER_ID", self.worker_id)
        monkeypatch.setenv("WORKER_PRIVATE_KEY", private_key)
        monkeypatch.setenv("WORKER_PUBLIC_KEYS_JSON", json.dumps({self.worker_id: public_key}))
        monkeypatch.setenv("WORKER_CAPABILITY_SECRET", "test-worker-capability-secret")

    def _report(self, sub, payload, attempt_id=None):
        from utils.cache_utils import get_coordination_client

        attempt_id = attempt_id or sub.celery_task_id
        capability = issue_worker_capability(
            worker_id=self.worker_id,
            method="POST",
            operation="report_submission",
            resource_type="submission",
            resource_id=sub.id,
            attempt_id=attempt_id,
        )
        coordination = get_coordination_client()
        assert coordination is not None
        coordination.set(f"worker:attempt:{attempt_id}", self.worker_id, ex=3600)
        return self.client.post(
            f"/api/worker/report/{sub.id}",
            json=payload,
            headers={
                "X-Worker-Token": sign_worker_token(),
                "X-Worker-Capability": capability,
                "Content-Type": "application/json",
            },
        )

    def test_completed_report_clears_the_code(self):
        self._set_codes([BASELINE_FAILED])
        sub = self._baseline(status="running")
        resp = self._report(sub, {"status": "completed", "detailed_status": "completed"})
        assert resp.status_code == 200
        assert self._codes() is None

    def test_failed_report_sets_the_code(self):
        sub = self._baseline(status="running")
        resp = self._report(sub, {"status": "failed", "detailed_status": "failed"})
        assert resp.status_code == 200
        assert self._codes() == [BASELINE_FAILED]

    @patch("tasks.evaluate_submission.apply_async")
    def test_platform_failure_report_reruns_instead_of_blocking(self, mock_apply):
        sub = self._baseline(status="running")

        resp = self._report(sub, {"status": "failed", "detailed_status": "failed_infra"})

        assert resp.status_code == 200
        assert self._reload(sub.id).status == "failed"
        # The ended run is final like any other
        assert get_submission_final_status(sub.id) == "failed"
        rerun = self._rerun_of(sub)
        assert rerun.status == "queued"
        assert rerun.infra_retry_count == 1
        assert mock_apply.call_args.kwargs["priority"] == 0
        assert self._codes() is None
        # A late report from the old attempt touches neither the task nor the new run
        late_failed = self._report(sub, {"status": "failed", "detailed_status": "failed"})
        assert late_failed.status_code == 200
        assert self._report(sub, {"status": "completed"}).status_code == 409
        assert self._reload(sub.id).detailed_status == "failed_infra"
        assert self._reload(rerun.id).status == "queued"
        assert self._codes() is None

    @patch("tasks.evaluate_submission.apply_async")
    def test_platform_failure_after_a_build_failure_is_not_rerun(self, mock_apply):
        sub = self._baseline(status="running")
        # The worker reports the build failure while the run is still active
        self._set_codes(["ERR_TASK_BUILD_FAILED"])
        resp = self._report(sub, {"status": "failed", "detailed_status": "failed_infra"})
        assert resp.status_code == 200
        mock_apply.assert_not_called()
        assert self._codes() == [BASELINE_FAILED, "ERR_TASK_BUILD_FAILED"]

    def test_platform_failure_report_after_retries_sets_the_code(self):
        sub = self._baseline(status="running", retries=2)
        resp = self._report(sub, {"status": "failed", "detailed_status": "failed_infra"})
        assert resp.status_code == 200
        assert self._reload(sub.id).status == "failed"
        assert self._codes() == [BASELINE_FAILED]


class TestWatchdogAndFallback(_BaselineFixture):
    @pytest.fixture(autouse=True)
    def _app(self, app, app_ctx):
        tasks.app = app

    @patch("tasks.evaluate_submission.apply_async")
    def test_never_picked_up_reruns_at_priority_zero(self, mock_apply):
        sub = self._baseline(status="queued", created_at=utcnow() - timedelta(hours=2))

        result = tasks.watchdog_stuck_submissions()

        assert result["timed_out"] == 1
        assert self._reload(sub.id).detailed_status == "failed_infra"
        assert get_submission_final_status(sub.id) == "failed"
        rerun = self._rerun_of(sub)
        assert rerun.status == "queued"
        assert rerun.infra_retry_count == 1
        assert mock_apply.call_args.kwargs["priority"] == 0
        assert self._codes() is None
        # The new run is not timed out again on the next run
        assert tasks.watchdog_stuck_submissions()["timed_out"] == 0

    def test_never_picked_up_after_retries_sets_the_code(self):
        sub = self._baseline(status="queued", retries=2, created_at=utcnow() - timedelta(hours=2))
        tasks.watchdog_stuck_submissions()
        assert self._reload(sub.id).detailed_status == "failed_infra"
        assert self._codes() == [BASELINE_FAILED]
        assert get_submission_final_status(sub.id) == "failed"

    @patch("tasks.evaluate_submission.apply_async")
    def test_lost_worker_reruns(self, mock_apply):
        sub = self._baseline(status="running", executed_at=utcnow() - timedelta(seconds=1000))
        tasks.watchdog_stuck_submissions()
        assert "worker lost" in self._reload(sub.id).logs
        rerun = self._rerun_of(sub)
        assert rerun.status == "queued"
        assert rerun.executed_at is None
        assert mock_apply.call_args.kwargs["priority"] == 0
        assert self._codes() is None

    def test_lost_worker_after_retries_sets_the_code(self):
        sub = self._baseline(
            status="running", retries=2, executed_at=utcnow() - timedelta(seconds=1000)
        )
        tasks.watchdog_stuck_submissions()
        assert "worker lost" in self._reload(sub.id).logs
        assert self._codes() == [BASELINE_FAILED]

    def _store_fallback(self, sub, status, detailed_status):
        from utils.cache_utils import get_coordination_client

        r = get_coordination_client()
        if not r:
            pytest.skip("Redis unavailable")
        r.delete(f"worker:attempt:{sub.celery_task_id}")
        r.set(
            f"submission:{sub.id}:fallback",
            json.dumps(
                {
                    "status": status,
                    "detailed_status": detailed_status,
                    "attempt_id": sub.celery_task_id,
                    "worker_id": "worker-a",
                    "public_score": 0.5 if status == "completed" else None,
                }
            ),
        )

    def test_fallback_completed_clears_an_older_failure(self):
        self._set_codes([BASELINE_FAILED])
        sub = self._baseline(status="running")
        self._store_fallback(sub, "completed", "completed")

        result = tasks.watchdog_stuck_submissions()

        assert result["recovered"] == 1
        assert self._reload(sub.id).status == "completed"
        assert self._codes() is None
        assert get_submission_final_status(sub.id) == "completed"

    def test_fallback_failed_sets_the_code(self):
        sub = self._baseline(status="running")
        self._store_fallback(sub, "failed", "failed")
        tasks.watchdog_stuck_submissions()
        assert self._codes() == [BASELINE_FAILED]

    @patch("tasks.evaluate_submission.apply_async")
    def test_fallback_platform_failure_reruns(self, mock_apply):
        sub = self._baseline(status="running")
        self._store_fallback(sub, "failed", "failed_infra")
        tasks.watchdog_stuck_submissions()
        assert self._reload(sub.id).status == "failed"
        assert self._rerun_of(sub).infra_retry_count == 1
        assert mock_apply.call_args.kwargs["priority"] == 0
        assert self._codes() is None


class TestSoftTimeLimit(_BaselineFixture):
    @pytest.fixture(autouse=True)
    def _app(self, app, app_ctx, mocker):
        mocker.patch.object(tasks, "app", app)
        mocker.patch.object(tasks, "HAS_APP", True)
        mocker.patch.object(tasks, "run_eval_submission", side_effect=SoftTimeLimitExceeded())

    @patch("tasks.evaluate_submission.apply_async")
    def test_soft_limit_reruns_at_priority_zero(self, mock_apply):
        sub = self._baseline(status="running")
        tasks.evaluate_submission(sub.id, None)
        assert self._reload(sub.id).detailed_status == "failed_infra"
        assert get_submission_final_status(sub.id) == "failed"
        assert self._rerun_of(sub).infra_retry_count == 1
        assert mock_apply.call_args.kwargs["priority"] == 0
        assert self._codes() is None

    @patch("tasks.evaluate_submission.apply_async")
    def test_late_soft_limit_of_a_superseded_run_changes_nothing(self, mock_apply):
        ended = self._baseline(status="failed", detailed_status="failed_infra")
        rerun = self._baseline(status="running", retries=1)
        tasks.evaluate_submission(ended.id, None)
        mock_apply.assert_not_called()
        assert self._reload(rerun.id).status == "running"
        assert len(self._baselines()) == 2
        assert self._codes() is None

    def test_soft_limit_after_retries_sets_the_code(self):
        sub = self._baseline(status="running", retries=2)
        tasks.evaluate_submission(sub.id, None)
        failed = self._reload(sub.id)
        assert failed.detailed_status == "failed_infra"
        assert self._codes() == [BASELINE_FAILED]
        assert get_submission_final_status(sub.id) == "failed"


class TestKillRoute(_BaselineFixture):
    @pytest.fixture(autouse=True)
    def _client(self, client, tokens, auth_headers, mocker):
        self.client = client
        self.headers = auth_headers(tokens.admin)
        mocker.patch.object(tasks.celery.control, "revoke")

    @pytest.mark.parametrize("status", ["queued", "running"])
    def test_kill_sets_the_code(self, status):
        sub = self._baseline(status=status)
        resp = self.client.post(f"/api/submissions/{sub.id}/kill", headers=self.headers)
        assert resp.status_code == 200
        assert self._reload(sub.id).detailed_status == "killed"
        assert self._codes() == [BASELINE_FAILED]

    @patch("tasks.evaluate_submission.apply_async")
    def test_kill_is_never_rerun(self, mock_apply):
        sub = self._baseline(status="running")
        self.client.post(f"/api/submissions/{sub.id}/kill", headers=self.headers)
        mock_apply.assert_not_called()
        assert self._reload(sub.id).status == "failed"

    @patch("tasks.evaluate_submission.apply_async")
    def test_admin_queue_clear_sets_the_code(self, mock_apply):
        sub = self._baseline(status="queued")
        resp = self.client.post("/api/admin/submissions/queue/clear", headers=self.headers)
        assert resp.status_code == 200
        assert self._reload(sub.id).detailed_status == "killed"
        assert self._codes() == [BASELINE_FAILED]
        mock_apply.assert_not_called()
