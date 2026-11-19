"""The submission status helper: the transition table and the races it closes."""

import json
from datetime import timedelta
from itertools import product
from unittest.mock import patch

import pytest

import tasks
from models import Submission, db
from services.submission_service import quota_counted
from services.submission_status import (
    ACTIVE_STATUSES,
    ALLOWED_TRANSITIONS,
    COMPLETED,
    FAILED,
    INFRA_FAILURE,
    KILLED,
    QUEUED,
    RUNNING,
    STATUSES,
    TERMINAL_STATUSES,
    predecessors,
    select_final,
    transition,
)
from utils.dates import utcnow

# The whole table, written out: a run moves forward only, and never leaves a terminal status
EXPECTED_TRANSITIONS = {
    (QUEUED, QUEUED),
    (QUEUED, RUNNING),
    (QUEUED, FAILED),
    (RUNNING, RUNNING),
    (RUNNING, COMPLETED),
    (RUNNING, FAILED),
}


@pytest.fixture
def make_run(db_session, sample_challenge, sample_task, sample_competitor):
    def _make(status=RUNNING, user=None, **kw):
        run = Submission(
            user_id=(user or sample_competitor).id,
            challenge_id=sample_challenge.id,
            task_id=sample_task.id,
            status=status,
            detailed_status=kw.pop("detailed_status", status),
            origin="cells",
            code_cells="[]",
            **kw,
        )
        db_session.add(run)
        db_session.commit()
        return run

    return _make


def _reload(submission_id):
    db.session.expire_all()
    return db.session.get(Submission, submission_id)


def _counts_toward_quota(submission_id):
    return quota_counted(Submission.query.filter(Submission.id == submission_id)).count() == 1


def _completed_first(submission_id, score=0.9):
    """Wrap a writer's transition so the worker's completed report commits just before it."""
    done = []

    def _wrapper(*args, **kwargs):
        if not done:
            done.append(True)
            assert transition(
                submission_id,
                COMPLETED,
                from_statuses=(RUNNING,),
                detailed_status=COMPLETED,
                fields={"public_score": score},
            )
            db.session.commit()
        return transition(*args, **kwargs)

    return _wrapper


# ── The table ──
def test_the_table_is_the_documented_one():
    assert ALLOWED_TRANSITIONS == EXPECTED_TRANSITIONS
    assert not any(src in TERMINAL_STATUSES for src, _dst in ALLOWED_TRANSITIONS)


@pytest.mark.parametrize(("src", "dst"), list(product(STATUSES, STATUSES)))
def test_every_pair_applies_only_when_allowed(make_run, src, dst):
    run = make_run(status=src)
    if (src, dst) in EXPECTED_TRANSITIONS:
        assert transition(run.id, dst, from_statuses=(src,)) is True
        db.session.commit()
        row = _reload(run.id)
        assert row.status == dst
        assert (row.finished_at is not None) == (dst in TERMINAL_STATUSES)
        return
    with pytest.raises(ValueError, match="not allowed"):
        transition(run.id, dst, from_statuses=(src,))
    # Asked from the statuses that may lead there, the row's own status is not among them
    if predecessors(dst):
        assert transition(run.id, dst, from_statuses=predecessors(dst)) is False
    assert _reload(run.id).status == src


@pytest.mark.parametrize("detailed", [KILLED, INFRA_FAILURE])
def test_a_failure_detail_needs_the_failed_status(make_run, detailed):
    run = make_run(status=RUNNING)
    with pytest.raises(ValueError, match="needs status"):
        transition(run.id, COMPLETED, from_statuses=(RUNNING,), detailed_status=detailed)


def test_another_attempt_never_moves_the_row(make_run):
    run = make_run(status=RUNNING, celery_task_id="attempt-now")
    assert not transition(run.id, COMPLETED, from_statuses=(RUNNING,), attempt_id="attempt-old")
    assert transition(run.id, COMPLETED, from_statuses=(RUNNING,), attempt_id="attempt-now")


# ── Kill and queue clear against a completed report ──
def test_a_kill_never_overwrites_a_run_completed_in_between(client, csrf_headers, tokens, make_run):
    run = make_run(status=RUNNING, celery_task_id="attempt-kill-race")
    with (
        patch("routes.submissions.transition", side_effect=_completed_first(run.id)),
        patch.object(tasks.celery.control, "revoke") as revoke,
    ):
        resp = client.post(
            f"/api/submissions/{run.id}/kill", headers=csrf_headers(tokens.competitor)
        )
    assert resp.status_code == 400
    assert resp.get_json()["code"] == "ERR_SUBMISSION_NOT_KILLABLE"
    row = _reload(run.id)
    assert (row.status, row.detailed_status, row.public_score) == (COMPLETED, COMPLETED, 0.9)
    revoke.assert_not_called()
    assert _counts_toward_quota(run.id)


def test_a_kill_that_applies_ends_the_run(client, csrf_headers, tokens, make_run):
    run = make_run(status=RUNNING)
    resp = client.post(f"/api/submissions/{run.id}/kill", headers=csrf_headers(tokens.competitor))
    assert resp.status_code == 200
    row = _reload(run.id)
    assert (row.status, row.detailed_status) == (FAILED, KILLED)
    assert row.finished_at is not None
    assert "killed by competitor" in row.logs


def test_queue_clear_keeps_a_run_completed_in_between(
    client, csrf_headers, tokens, make_run, sample_other_competitor
):
    finishing = make_run(status=RUNNING)
    waiting = make_run(status=QUEUED, user=sample_other_competitor)
    with patch("routes.admin.transition", side_effect=_completed_first(finishing.id)):
        resp = client.post("/api/admin/submissions/queue/clear", headers=csrf_headers(tokens.admin))
    assert resp.status_code == 200
    assert resp.get_json()["message"] == "Cleared 1 submission(s) from the queue."
    assert _reload(finishing.id).status == COMPLETED
    assert (_reload(waiting.id).status, _reload(waiting.id).detailed_status) == (FAILED, KILLED)


# ── The watchdog against a completed report or a claim ──
@pytest.fixture
def watchdog_app(app, redis_flush):
    with patch.object(tasks, "app", app):
        yield


def test_the_watchdog_never_overwrites_a_run_completed_in_between(watchdog_app, make_run):
    run = make_run(
        status=RUNNING,
        celery_task_id="attempt-watchdog-race",
        executed_at=utcnow() - timedelta(hours=2),
    )
    with (
        patch("tasks.transition", side_effect=_completed_first(run.id)),
        patch.object(tasks.celery.control, "revoke") as revoke,
        patch("utils.cache_utils.mark_attempt_ended") as ended,
    ):
        result = tasks.watchdog_stuck_submissions()
    assert result["timed_out"] == 0
    row = _reload(run.id)
    assert (row.status, row.detailed_status, row.public_score) == (COMPLETED, COMPLETED, 0.9)
    assert "WATCHDOG" not in row.logs
    revoke.assert_not_called()
    ended.assert_not_called()
    # No give-back: the completed run uses its quota
    assert _counts_toward_quota(run.id)


def test_the_watchdog_gives_the_quota_back_only_for_a_run_it_failed(watchdog_app, make_run):
    lost = make_run(status=RUNNING, executed_at=utcnow() - timedelta(hours=2))
    assert _counts_toward_quota(lost.id)
    assert tasks.watchdog_stuck_submissions()["timed_out"] == 1
    row = _reload(lost.id)
    assert (row.status, row.detailed_status) == (FAILED, INFRA_FAILURE)
    assert row.finished_at is not None
    assert not _counts_toward_quota(lost.id)


def test_a_lost_queued_run_claimed_in_between_keeps_running(watchdog_app, make_run):
    run = make_run(status=QUEUED, created_at=utcnow() - timedelta(hours=1))
    claimed = []

    def _claim_first(*args, **kwargs):
        if not claimed:
            claimed.append(True)
            assert transition(run.id, RUNNING, from_statuses=(QUEUED,))
            db.session.commit()
        return transition(*args, **kwargs)

    with patch("tasks.transition", side_effect=_claim_first):
        assert tasks.watchdog_stuck_submissions()["timed_out"] == 0
    assert claimed
    assert _reload(run.id).status == RUNNING


def test_a_fallback_never_rewrites_a_run_killed_in_between(watchdog_app, make_run):
    from utils.cache_utils import get_coordination_client, submission_fallback_key

    r = get_coordination_client()
    if r is None:
        pytest.skip("Redis unavailable")
    run = make_run(status=RUNNING, celery_task_id="attempt-fallback-race")
    r.set(f"worker:attempt:{run.celery_task_id}", "worker-a", ex=3600)
    fallback = {
        "attempt_id": run.celery_task_id,
        "worker_id": "worker-a",
        "status": COMPLETED,
        "detailed_status": COMPLETED,
        "public_score": 0.7,
    }
    r.set(submission_fallback_key(run.id), json.dumps(fallback))
    killed = []

    def _kill_first(*args, **kwargs):
        if not killed:
            killed.append(True)
            assert transition(run.id, FAILED, from_statuses=ACTIVE_STATUSES, detailed_status=KILLED)
            db.session.commit()
        return transition(*args, **kwargs)

    with patch("tasks.transition", side_effect=_kill_first):
        assert tasks.watchdog_stuck_submissions()["recovered"] == 0
    row = _reload(run.id)
    assert (row.status, row.detailed_status, row.public_score) == (FAILED, KILLED, None)
    assert r.get(submission_fallback_key(run.id)) is None


def test_a_platform_failure_never_overwrites_a_completed_run(app, make_run):
    run = make_run(status=COMPLETED, public_score=0.5)
    with (
        patch.object(tasks, "app", app),
        patch.object(tasks, "HAS_APP", True),
        patch("utils.sse_utils.publish_submission_status") as published,
    ):
        tasks._fail_as_platform_failure(run.id, None, "[TIMEOUT] soft limit", None)
    row = _reload(run.id)
    assert (row.status, row.public_score) == (COMPLETED, 0.5)
    assert _counts_toward_quota(run.id)
    published.assert_not_called()


# ── Final selection ──
def test_selections_that_race_leave_exactly_one_final(
    client, csrf_headers, tokens, make_run, sample_challenge
):
    first = make_run(status=COMPLETED, public_score=0.4)
    second = make_run(status=COMPLETED, public_score=0.6)
    raced = []

    def _other_select_first(*args, **kwargs):
        if not raced:
            raced.append(True)
            assert select_final(second.id, second.user_id, second.task_id)
            db.session.commit()
        return select_final(*args, **kwargs)

    with patch("routes.submissions.select_final", side_effect=_other_select_first):
        resp = client.post(
            f"/api/submissions/{first.id}/select-final", headers=csrf_headers(tokens.competitor)
        )
    assert resp.status_code == 200
    finals = Submission.query.filter_by(user_id=first.user_id, is_final_selection=True).all()
    assert [s.id for s in finals] == [first.id]


@pytest.mark.parametrize(
    ("status", "baseline"),
    [(QUEUED, False), (RUNNING, False), (FAILED, False), (COMPLETED, True)],
)
def test_only_a_completed_competitor_run_can_be_selected(
    client, csrf_headers, tokens, make_run, status, baseline
):
    selected = make_run(status=COMPLETED, public_score=0.3, is_final_selection=True)
    other = make_run(status=status, is_baseline=baseline)
    resp = client.post(
        f"/api/submissions/{other.id}/select-final", headers=csrf_headers(tokens.competitor)
    )
    assert resp.status_code == 400
    assert resp.get_json()["code"] == "ERR_SUBMISSION_NOT_SELECTABLE"
    # The real selection stays
    assert _reload(selected.id).is_final_selection is True
    assert select_final(other.id, other.user_id, other.task_id) is False


def test_another_competitors_run_cannot_be_selected(
    client, csrf_headers, tokens, make_run, sample_other_competitor
):
    theirs = make_run(status=COMPLETED, user=sample_other_competitor)
    resp = client.post(
        f"/api/submissions/{theirs.id}/select-final", headers=csrf_headers(tokens.competitor)
    )
    assert resp.status_code == 404
    assert _reload(theirs.id).is_final_selection is False
