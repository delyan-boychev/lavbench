"""Tests for the fair-share queue: active-run limit, priorities, ceiling and the deadline."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from config import Config
from models import Challenge, Submission, Task, db
from tests.helpers.task_files import LABELLED
from utils.dates import utcnow


@pytest.fixture
def enqueued():
    with patch("tasks.evaluate_submission.apply_async") as mocked:
        yield mocked


@pytest.fixture
def task(sample_task, db_session):
    sample_task.files = LABELLED
    sample_task.max_submissions_per_period = None
    sample_task.challenge.max_eval_requests = 100
    db_session.commit()
    return sample_task


def _row(user, task, status="completed", **fields):
    submission = Submission(
        user_id=user.id,
        challenge_id=task.challenge_id,
        task_id=task.id,
        status=status,
        detailed_status=fields.pop("detailed_status", status),
        origin=fields.pop("origin", "cells"),
        **fields,
    )
    db.session.add(submission)
    db.session.commit()
    return submission


def _submit(client, headers, task):
    return client.post(
        f"/api/tasks/{task.id}/submit",
        json={"selected_cells": [{"source": "print(1)"}]},
        headers=headers,
    )


class TestActiveRunLimit:
    def test_a_third_run_is_refused_with_no_row_and_no_quota(
        self, client, auth_headers, tokens, task, sample_competitor, enqueued, redis_flush
    ):
        headers = auth_headers(tokens.competitor)
        assert _submit(client, headers, task).status_code == 202
        assert _submit(client, headers, task).status_code == 202
        refused = _submit(client, headers, task)
        assert refused.status_code == 429
        body = refused.get_json()
        assert body["code"] == "ERR_TOO_MANY_ACTIVE_RUNS"
        assert body["limit"] == Config.MAX_ACTIVE_RUNS_PER_USER == 2
        assert Submission.query.filter_by(user_id=sample_competitor.id).count() == 2
        assert enqueued.call_count == 2

    def test_runs_on_other_tasks_and_competitions_count(
        self, client, auth_headers, tokens, task, sample_competitor, enqueued, redis_flush
    ):
        other_challenge = Challenge(
            title="Other",
            start_time=utcnow() - timedelta(hours=1),
            end_time=utcnow() + timedelta(hours=1),
        )
        db.session.add(other_challenge)
        db.session.flush()
        other_task = Task(title="Other", challenge_id=other_challenge.id)
        db.session.add(other_task)
        db.session.commit()
        _row(sample_competitor, other_task, status="running")
        _row(sample_competitor, task, status="queued", origin="workspace")
        refused = _submit(client, auth_headers(tokens.competitor), task)
        assert refused.get_json()["code"] == "ERR_TOO_MANY_ACTIVE_RUNS"

    def test_finished_runs_and_baselines_free_the_slots(
        self, client, auth_headers, tokens, task, sample_competitor, enqueued, redis_flush
    ):
        _row(sample_competitor, task, status="completed")
        _row(sample_competitor, task, status="failed", detailed_status="failed_infra")
        _row(sample_competitor, task, status="queued", is_baseline=True, origin="baseline")
        _row(sample_competitor, task, status="running")
        assert _submit(client, auth_headers(tokens.competitor), task).status_code == 202

    def test_staff_test_runs_have_no_active_limit(
        self, client, auth_headers, tokens, task, sample_admin, enqueued, redis_flush
    ):
        for _ in range(3):
            _row(sample_admin, task, status="queued")
        assert _submit(client, auth_headers(tokens.admin), task).status_code == 202

    def test_the_file_precheck_applies_the_same_limit(self, task, sample_competitor):
        from services.submission_service import file_precheck

        _row(sample_competitor, task, status="queued")
        _row(sample_competitor, task, status="running")
        refused = file_precheck(task, task.challenge, sample_competitor.id, "competitor", "0" * 64)
        assert refused is not None
        assert refused[0].get_json()["code"] == "ERR_TOO_MANY_ACTIVE_RUNS"


class TestPriorityAtDispatch:
    def _priority(self, client, headers, task, enqueued):
        assert _submit(client, headers, task).status_code == 202
        return enqueued.call_args.kwargs["priority"]

    def test_staff_runs_go_first(
        self, client, auth_headers, tokens, task, sample_admin, enqueued, redis_flush
    ):
        for _ in range(7):
            _row(sample_admin, task)
        assert self._priority(client, auth_headers(tokens.admin), task, enqueued) == 0

    @pytest.mark.parametrize(("used", "priority"), [(0, 1), (2, 2), (3, 3), (5, 3), (6, 4)])
    def test_competitors_by_runs_used_today_on_the_task(
        self,
        client,
        auth_headers,
        tokens,
        task,
        sample_competitor,
        enqueued,
        redis_flush,
        used,
        priority,
    ):
        for _ in range(used):
            _row(sample_competitor, task)
        assert self._priority(client, auth_headers(tokens.competitor), task, enqueued) == priority

    def test_only_runs_that_count_today_on_this_task_move_the_group(
        self, client, auth_headers, tokens, task, sample_competitor, enqueued, redis_flush
    ):
        other_task = Task(title="Second", challenge_id=task.challenge_id, files=LABELLED)
        db.session.add(other_task)
        db.session.commit()
        for _ in range(4):
            _row(sample_competitor, other_task)
            _row(sample_competitor, task, status="failed", detailed_status="failed_infra")
            _row(sample_competitor, task, created_at=utcnow() - timedelta(days=2))
        assert self._priority(client, auth_headers(tokens.competitor), task, enqueued) == 1

    def test_the_file_path_uses_the_same_priority(self, task, sample_competitor, enqueued):
        from services.submission_service import create_submission

        task.evaluation_mode = "file"
        db.session.commit()
        for _ in range(3):
            _row(sample_competitor, task)
        files = MagicMock(artifact_sha256="a" * 64)
        with (
            patch("services.file_submission.is_duplicate", return_value=False),
            patch("services.submission_service.validate_submission_allowed", return_value=None),
            patch("utils.metadata.build_submission_metadata", return_value={}),
        ):
            result = create_submission(
                task,
                task.challenge,
                sample_competitor.id,
                "competitor",
                [],
                files=files,
                origin="workspace",
            )
        assert isinstance(result, Submission)
        assert enqueued.call_args.kwargs["priority"] == 3


class TestNoRefusalForLoad:
    @pytest.mark.parametrize("depth", [100, 1000, 4999])
    def test_a_long_queue_below_the_ceiling_accepts(
        self, client, auth_headers, tokens, task, enqueued, redis_flush, depth
    ):
        with patch("utils.cache_utils.get_queue_depth", return_value=depth):
            assert _submit(client, auth_headers(tokens.competitor), task).status_code == 202

    @pytest.fixture
    def watchdog(self, app, monkeypatch):
        import tasks

        monkeypatch.setattr(tasks, "app", app)
        return tasks.watchdog_stuck_submissions

    def test_a_pending_run_waits_however_long_the_queue_is(
        self, task, sample_competitor, watchdog, redis_flush
    ):
        from utils.cache_utils import mark_attempt_pending

        queued = _row(
            sample_competitor,
            task,
            status="queued",
            created_at=utcnow() - timedelta(hours=7),
            celery_task_id="attempt-pending",
        )
        mark_attempt_pending("attempt-pending")
        watchdog()
        db.session.refresh(queued)
        assert queued.status == "queued"

    def test_a_run_whose_message_is_in_the_broker_waits(
        self, task, sample_competitor, watchdog, redis_flush, monkeypatch
    ):
        queued = _row(
            sample_competitor,
            task,
            status="queued",
            created_at=utcnow() - timedelta(hours=7),
            celery_task_id="attempt-in-broker",
        )
        monkeypatch.setattr(
            "utils.cache_utils.broker_message_ids", lambda queues: {"attempt-in-broker"}
        )
        watchdog()
        db.session.refresh(queued)
        assert queued.status == "queued"

    def test_a_lost_message_ends_the_run_after_ten_minutes_not_six_hours(
        self, task, sample_competitor, watchdog, redis_flush
    ):
        import tasks

        recent = _row(
            sample_competitor,
            task,
            status="queued",
            created_at=utcnow() - timedelta(minutes=5),
            celery_task_id="attempt-recent",
        )
        lost = _row(
            sample_competitor,
            task,
            status="queued",
            created_at=utcnow() - timedelta(seconds=tasks.LOST_MESSAGE_CHECK_SECONDS + 60),
            celery_task_id="attempt-lost",
        )
        watchdog()
        db.session.refresh(recent)
        db.session.refresh(lost)
        assert recent.status == "queued"
        assert (lost.status, lost.detailed_status) == ("failed", "failed_infra")
        assert "lost" in lost.logs

    def test_the_broker_scan_reads_queued_and_unacknowledged_messages(self, redis_flush):
        import json

        from utils.cache_utils import broker_message_ids, get_coordination_client

        r = get_coordination_client()
        r.lpush("ptest_cpu", json.dumps({"headers": {"id": "a-waiting"}}))
        r.lpush("ptest_cpu\x06\x163", json.dumps({"headers": {"id": "a-low"}}))
        r.hset("unacked", "tag", json.dumps([{"headers": {"id": "a-reserved"}}, "", "ptest_cpu"]))
        try:
            assert broker_message_ids(["ptest_cpu"]) >= {"a-waiting", "a-low", "a-reserved"}
        finally:
            r.delete("ptest_cpu", "ptest_cpu\x06\x163")
            r.hdel("unacked", "tag")

    def test_dispatch_marks_the_attempt_pending_and_the_claim_clears_it(
        self, client, auth_headers, tokens, task, enqueued, redis_flush
    ):
        from utils.cache_utils import (
            EVAL_PENDING_SET,
            attempt_claimed_key,
            get_coordination_client,
            record_attempt_claimed,
        )

        assert _submit(client, auth_headers(tokens.competitor), task).status_code == 202
        attempt = enqueued.call_args.kwargs["task_id"]
        r = get_coordination_client()
        assert r.sismember(EVAL_PENDING_SET, attempt)
        record_attempt_claimed(attempt)
        assert not r.sismember(EVAL_PENDING_SET, attempt)
        assert r.get(attempt_claimed_key(attempt))

    def test_a_claimed_run_that_never_started_ends_after_its_hard_limit(
        self, task, sample_competitor, watchdog, redis_flush
    ):
        import time as clock

        from utils.cache_utils import attempt_claimed_key, get_coordination_client

        fresh = _row(sample_competitor, task, status="running", celery_task_id="claim-fresh")
        stale = _row(sample_competitor, task, status="running", celery_task_id="claim-stale")
        r = get_coordination_client()
        r.set(attempt_claimed_key("claim-fresh"), str(clock.time() - 60))
        r.set(
            attempt_claimed_key("claim-stale"),
            str(clock.time() - Config.CELERY_TASK_TIME_LIMIT - 400),
        )
        watchdog()
        db.session.refresh(fresh)
        db.session.refresh(stale)
        assert fresh.status == "running"
        assert (stale.status, stale.detailed_status) == ("failed", "failed_infra")

    def test_killing_a_running_run_ends_its_attempt_for_the_worker(
        self, client, csrf_headers, tokens, task, sample_competitor, redis_flush
    ):
        from utils.cache_utils import attempt_ended_key, get_coordination_client

        running = _row(sample_competitor, task, status="running", celery_task_id="attempt-kill")
        response = client.post(
            f"/api/submissions/{running.id}/kill", headers=csrf_headers(tokens.competitor)
        )
        assert response.status_code == 200
        assert get_coordination_client().exists(attempt_ended_key("attempt-kill"))


class TestBusyRedis:
    def test_a_lock_error_is_a_busy_503_not_a_held_lock(
        self, client, auth_headers, tokens, task, enqueued, monkeypatch
    ):
        broker = MagicMock()
        broker.exists.return_value = 0
        broker.eval.return_value = [1, 60]
        broker.set.side_effect = ConnectionError("No connection available.")
        monkeypatch.setattr("utils.cache_utils.get_coordination_client", lambda: broker)
        refused = _submit(client, auth_headers(tokens.competitor), task)
        assert refused.status_code == 503
        assert refused.get_json()["code"] == "ERR_SERVICE_BUSY"
        assert refused.headers["Retry-After"] == "5"
        assert Submission.query.count() == 0
        enqueued.assert_not_called()


class TestFinaliseWaitsForTheQueue:
    def _jury(self, create_user, assign_jury, challenge, name):
        from utils.auth_utils import generate_token

        jury = create_user(username=name, role="jury")
        assign_jury(jury, challenge)
        return generate_token(jury.id, "jury")

    def _finalize(self, client, csrf_headers, challenge, token):
        return client.post(
            f"/api/challenges/{challenge.id}/finalize",
            json={"reveal_results": True},
            headers=csrf_headers(token),
        )

    def _ended(self, task, minutes):
        challenge = task.challenge
        challenge.end_time = utcnow() - timedelta(minutes=minutes)
        db.session.commit()
        return challenge

    def test_finalising_during_the_grace_period_is_refused_with_the_time(
        self, client, csrf_headers, task, create_user, assign_jury
    ):
        challenge = self._ended(task, minutes=1)
        token = self._jury(create_user, assign_jury, challenge, "jury0")
        response = self._finalize(client, csrf_headers, challenge, token)
        assert response.status_code == 409
        body = response.get_json()
        assert body["code"] == "ERR_COMPETITION_NOT_ENDED"
        expected = challenge.end_time + timedelta(seconds=Config.DEADLINE_GRACE_PERIOD_SECONDS)
        assert body["available_at"] == expected.isoformat() + "Z"

    def test_finalising_with_competitor_runs_still_queued_is_refused(
        self, client, csrf_headers, task, sample_competitor, create_user, assign_jury
    ):
        challenge = self._ended(task, minutes=30)
        _row(sample_competitor, task, status="queued")
        _row(sample_competitor, task, status="queued", is_baseline=True, origin="baseline")
        token = self._jury(create_user, assign_jury, challenge, "jury1")
        response = self._finalize(client, csrf_headers, challenge, token)
        assert response.status_code == 409
        body = response.get_json()
        assert (body["code"], body["count"]) == ("ERR_EVALUATIONS_PENDING", 1)
        db.session.refresh(challenge)
        assert challenge.scores_finalized is False

    def test_staff_test_runs_never_block_finalising(
        self, client, csrf_headers, task, sample_admin, sample_competitor, create_user, assign_jury
    ):
        challenge = self._ended(task, minutes=30)
        _row(sample_admin, task, status="queued")
        sample_competitor.manual_points = {}
        db.session.commit()
        token = self._jury(create_user, assign_jury, challenge, "jury3")
        assert self._finalize(client, csrf_headers, challenge, token).status_code == 200

    def test_an_open_final_selection_window_blocks_finalising_until_it_closes(
        self, client, csrf_headers, task, sample_competitor, create_user, assign_jury
    ):
        challenge = self._ended(task, minutes=30)
        finished = utcnow() - timedelta(minutes=1)
        _row(
            sample_competitor,
            task,
            status="completed",
            created_at=challenge.end_time - timedelta(minutes=1),
            finished_at=finished,
        )
        token = self._jury(create_user, assign_jury, challenge, "jury4")
        response = self._finalize(client, csrf_headers, challenge, token)
        assert response.status_code == 409
        body = response.get_json()
        assert body["code"] == "ERR_FINAL_SELECTION_OPEN"
        assert body["available_at"] == (finished + timedelta(seconds=300)).isoformat() + "Z"

    def test_a_stage_with_runs_still_running_is_not_finalised(
        self, client, csrf_headers, task, sample_stage, sample_competitor, create_user, assign_jury
    ):
        sample_stage.end_time = utcnow() - timedelta(minutes=30)
        task.stage_id = sample_stage.id
        db.session.commit()
        _row(sample_competitor, task, status="running")
        token = self._jury(create_user, assign_jury, task.challenge, "jury2")
        response = client.post(
            f"/api/challenges/{task.challenge_id}/stages/{sample_stage.id}/finalize",
            json={"reveal_results": True},
            headers=csrf_headers(token),
        )
        assert response.status_code == 409
        assert response.get_json()["code"] == "ERR_EVALUATIONS_PENDING"

    def test_the_finalize_status_route_reports_every_scope(
        self, client, csrf_headers, task, sample_stage, sample_competitor, create_user, assign_jury
    ):
        challenge = self._ended(task, minutes=30)
        sample_stage.end_time = utcnow() + timedelta(hours=1)
        db.session.commit()
        _row(sample_competitor, task, status="queued")
        token = self._jury(create_user, assign_jury, challenge, "jury5")
        response = client.get(
            f"/api/challenges/{challenge.id}/finalize-status", headers=csrf_headers(token)
        )
        assert response.status_code == 200
        body = response.get_json()
        assert body["challenge"] == {
            "ready": False,
            "reason": "runs_pending",
            "available_at": None,
            "pending_runs": 1,
        }
        [stage] = body["stages"]
        assert stage["stage_id"] == str(sample_stage.id)
        assert stage["reason"] == "not_ended"
