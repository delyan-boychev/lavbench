"""Table-driven tests of services.contest_rules: deadlines, counted run, selection, finalising."""

import csv
import io
from datetime import timedelta

import pytest

from config import Config
from models import Stage, Submission, Task, db
from services import contest_rules as rules
from services.challenge_service import generate_scores_csv
from services.leaderboard_service import build_and_cache_leaderboard
from services.submission_status import COMPLETED, QUEUED, RUNNING, transition
from utils.dates import utcnow

GRACE = timedelta(seconds=Config.DEADLINE_GRACE_PERIOD_SECONDS)


@pytest.fixture
def ended(sample_challenge, sample_task, db_session):
    """A competition that ended an hour ago, with one task."""
    sample_challenge.end_time = utcnow() - timedelta(hours=1)
    db_session.commit()
    return sample_challenge, sample_task


def _run(user, task, *, public=None, private=None, ms=None, created=None, final=False, **kw):
    sub = Submission(
        user_id=user.id,
        challenge_id=task.challenge_id,
        task_id=task.id,
        status=kw.pop("status", "completed"),
        detailed_status="completed",
        origin="cells",
        public_score=public,
        private_score=private,
        execution_time_ms=ms,
        is_final_selection=final,
        created_at=created,
        **kw,
    )
    db.session.add(sub)
    db.session.commit()
    return sub


# ── The counted run ──
# Each case: runs as (public, private, ms, minutes before the end, selected), and the index
# Of the run that counts
COUNTED_CASES = [
    ("best public wins", [(0.5, 0.9, 10, 30, False), (0.8, 0.1, 10, 30, False)], 1),
    ("private never decides", [(0.8, 0.0, 10, 30, False), (0.7, 1.0, 10, 30, False)], 0),
    ("selection beats better scores", [(0.9, 0.9, 1, 30, False), (0.1, 0.1, 99, 30, True)], 1),
    ("equal public: faster run", [(0.8, 0.0, 50, 30, False), (0.8, 0.0, 20, 30, False)], 1),
    ("equal public and time: earlier", [(0.8, 0.0, 20, 10, False), (0.8, 0.0, 20, 40, False)], 1),
    ("no public score ranks last", [(None, 0.9, 10, 30, False), (0.1, 0.1, 10, 30, False)], 1),
    ("no run time ranks last", [(0.8, 0.0, None, 30, False), (0.8, 0.0, 999, 30, False)], 1),
]


@pytest.mark.parametrize("revealed", [False, True], ids=["before reveal", "after reveal"])
@pytest.mark.parametrize(
    ("name", "runs", "expected"), COUNTED_CASES, ids=[c[0] for c in COUNTED_CASES]
)
def test_one_counted_run_in_python_and_both_sql_paths(
    ended, sample_competitor, revealed, name, runs, expected
):
    challenge, task = ended
    challenge.scores_finalized = revealed
    challenge.reveal_results = revealed
    db.session.commit()
    subs = [
        _run(
            sample_competitor,
            task,
            public=public,
            private=private,
            ms=ms,
            created=challenge.end_time - timedelta(minutes=before),
            final=final,
        )
        for public, private, ms, before, final in runs
    ]
    want = subs[expected]
    assert rules.counted_run(task, subs, challenge).id == want.id
    entry = build_and_cache_leaderboard(challenge.id)[0]
    assert entry["task_scores"][str(task.id)]["submission_id"] == want.id
    rows = list(csv.reader(io.StringIO(generate_scores_csv(challenge))))
    score = want.private_score if want.private_score is not None else (want.public_score or 0.0)
    assert float(rows[1][rows[0].index(f"Task: {task.title}")]) == pytest.approx(score)


def test_the_sql_and_python_orderings_agree(ended, sample_competitor):
    challenge, task = ended
    end = challenge.end_time
    for public, ms, before, final in [
        (0.5, 10, 5, False),
        (0.5, 10, 9, False),
        (None, 1, 1, False),
        (0.9, None, 3, False),
        (0.9, 5, 3, False),
        (0.1, 1, 2, True),
        (0.9, 5, 3, False),
    ]:
        _run(
            sample_competitor,
            task,
            public=public,
            ms=ms,
            created=end - timedelta(minutes=before),
            final=final,
        )
    sql = Submission.query.order_by(*rules.counted_run_order()).all()
    assert [s.id for s in sql] == [s.id for s in sorted(sql, key=rules.counted_run_key)]


# ── Deadlines ──
@pytest.mark.parametrize(
    ("offset", "eligible"),
    [(-1, True), (0, True), (1, False)],
    ids=["a second before the grace ends", "at the end of the grace", "a second after"],
)
def test_the_grace_period_bounds_eligibility(ended, sample_competitor, offset, eligible):
    challenge, task = ended
    deadline = challenge.end_time + GRACE
    assert rules.submission_deadline(task, challenge) == deadline
    sub = _run(sample_competitor, task, public=1.0, created=deadline + timedelta(seconds=offset))
    assert rules.is_submission_eligible(sub, task, challenge) is eligible
    assert (rules.counted_run(task, [sub], challenge) is not None) is eligible


def test_a_stage_task_uses_the_stage_deadline(ended, sample_stage):
    challenge, task = ended
    sample_stage.end_time = utcnow() - timedelta(hours=3)
    task.stage_id = sample_stage.id
    db.session.commit()
    assert rules.submission_deadline(task, challenge) == sample_stage.end_time + GRACE


# ── Final selection ──
def test_the_selection_window_follows_the_last_run_finished(ended, sample_competitor):
    challenge, task = ended
    deadline = challenge.end_time + GRACE
    window = rules.selection_window(sample_competitor.id, task, challenge)
    assert window.closes_at == deadline + rules.FINAL_SELECTION_WINDOW
    assert window.open is False
    finished = utcnow() - timedelta(minutes=2)
    _run(
        sample_competitor,
        task,
        public=1.0,
        created=deadline - timedelta(seconds=5),
        executed_at=deadline - timedelta(seconds=1),
        finished_at=finished,
    )
    window = rules.selection_window(sample_competitor.id, task, challenge)
    assert window == rules.SelectionWindow(
        open=True, closes_at=finished + rules.FINAL_SELECTION_WINDOW
    )


def test_a_run_finishing_after_the_window_reopens_it_for_five_minutes(ended, sample_competitor):
    """A run sent before the deadline that ends long after it never closes the window unseen."""
    challenge, task = ended
    deadline = challenge.end_time + GRACE
    run = _run(
        sample_competitor,
        task,
        status=QUEUED,
        created=deadline - timedelta(seconds=5),
    )
    assert transition(run.id, RUNNING, from_statuses=(QUEUED,), fields={"executed_at": deadline})
    db.session.commit()
    # Started at the deadline, still running well past deadline + 5 minutes
    assert rules.selection_window(sample_competitor.id, task, challenge).open is True
    assert transition(run.id, COMPLETED, from_statuses=(RUNNING,), fields={"public_score": 0.4})
    db.session.commit()
    finished = db.session.get(Submission, run.id).finished_at
    assert finished > deadline + rules.FINAL_SELECTION_WINDOW
    window = rules.selection_window(sample_competitor.id, task, challenge)
    assert window == rules.SelectionWindow(
        open=True, closes_at=finished + rules.FINAL_SELECTION_WINDOW
    )
    later = finished + rules.FINAL_SELECTION_WINDOW + timedelta(seconds=1)
    assert rules.selection_window(sample_competitor.id, task, challenge, now=later).open is False


def test_a_run_still_pending_keeps_the_window_open(ended, sample_competitor):
    challenge, task = ended
    _run(sample_competitor, task, status="queued", created=challenge.end_time)
    assert rules.selection_window(sample_competitor.id, task, challenge) == rules.SelectionWindow(
        open=True, closes_at=None
    )


def test_select_final_follows_the_window(client, csrf_headers, tokens, ended, sample_competitor):
    challenge, task = ended
    late = _run(sample_competitor, task, public=0.5, created=challenge.end_time)
    closed = client.post(
        f"/api/submissions/{late.id}/select-final", headers=csrf_headers(tokens.competitor)
    )
    assert closed.get_json()["code"] == "ERR_SELECTION_WINDOW_CLOSED"
    late.finished_at = utcnow() - timedelta(minutes=1)
    db.session.commit()
    ok = client.post(
        f"/api/submissions/{late.id}/select-final", headers=csrf_headers(tokens.competitor)
    )
    assert ok.status_code == 200


def test_the_list_carries_the_window_and_the_counted_run(
    client, auth_headers, tokens, ended, sample_competitor
):
    challenge, task = ended
    best = _run(sample_competitor, task, public=0.9, created=challenge.end_time)
    _run(sample_competitor, task, public=0.1, private=1.0, created=challenge.end_time)
    task.files = '[{"filename": "labels.parquet", "saved_name": "labels.parquet"}]'
    db.session.commit()
    body = client.get(
        f"/api/tasks/{task.id}/submissions", headers=auth_headers(tokens.competitor)
    ).get_json()
    state = body["final_selection"]
    assert state["counted_submission"]["id"] == str(best.id)
    task_view = client.get(f"/api/tasks/{task.id}", headers=auth_headers(tokens.competitor))
    assert task_view.get_json()["submission_deadline"] == (
        (challenge.end_time + GRACE).isoformat() + "Z"
    )
    assert state["open"] is False
    closes = challenge.end_time + GRACE + rules.FINAL_SELECTION_WINDOW
    assert state["closes_at"] == closes.isoformat() + "Z"


# ── Finalising ──
def _readiness(challenge, stage=None):
    return rules.finalize_readiness(challenge, stage)


def test_finalising_waits_for_the_grace_then_the_runs_then_the_window(ended, sample_competitor):
    challenge, task = ended
    challenge.end_time = utcnow() - timedelta(seconds=10)
    db.session.commit()
    assert _readiness(challenge) == rules.FinalizeReadiness(
        False, rules.FINALIZE_NOT_ENDED, challenge.end_time + GRACE
    )
    challenge.end_time = utcnow() - timedelta(hours=1)
    db.session.commit()
    queued = _run(sample_competitor, task, status="queued", created=challenge.end_time)
    assert _readiness(challenge) == rules.FinalizeReadiness(
        False, rules.FINALIZE_RUNS_PENDING, None, 1
    )
    assert transition(queued.id, RUNNING, from_statuses=(QUEUED,))
    assert transition(queued.id, COMPLETED, from_statuses=(RUNNING,))
    db.session.commit()
    finished = queued.finished_at
    assert finished is not None
    assert _readiness(challenge) == rules.FinalizeReadiness(
        False, rules.FINALIZE_SELECTION_OPEN, finished + rules.FINAL_SELECTION_WINDOW
    )
    queued.finished_at = utcnow() - timedelta(minutes=10)
    db.session.commit()
    assert _readiness(challenge).ready is True


def test_staff_runs_and_baselines_never_hold_finalising(ended, sample_admin, sample_competitor):
    challenge, task = ended
    _run(sample_admin, task, status="running", created=challenge.end_time)
    _run(sample_competitor, task, status="queued", is_baseline=True, created=challenge.end_time)
    assert _readiness(challenge).ready is True


def test_a_test_stage_never_holds_the_competition(ended, sample_competitor):
    challenge, _task = ended
    test_stage = Stage(
        challenge_id=challenge.id,
        title="Practice",
        stage_number=9,
        start_time=utcnow() - timedelta(hours=5),
        end_time=utcnow() - timedelta(hours=2),
        is_test=True,
    )
    db.session.add(test_stage)
    db.session.flush()
    practice = Task(title="Practice task", challenge_id=challenge.id, stage_id=test_stage.id)
    db.session.add(practice)
    db.session.commit()
    _run(sample_competitor, practice, status="queued", created=test_stage.end_time)
    assert _readiness(challenge).ready is True
    assert _readiness(challenge, test_stage).reason == rules.FINALIZE_RUNS_PENDING


def test_a_stage_is_judged_on_its_own_tasks_and_deadline(ended, sample_stage, sample_competitor):
    challenge, task = ended
    sample_stage.end_time = utcnow() - timedelta(minutes=30)
    db.session.commit()
    _run(sample_competitor, task, status="queued", created=challenge.end_time)
    # The pending run is on a task outside the stage
    assert _readiness(challenge, sample_stage).ready is True
    task.stage_id = sample_stage.id
    db.session.commit()
    assert _readiness(challenge, sample_stage).reason == rules.FINALIZE_RUNS_PENDING
