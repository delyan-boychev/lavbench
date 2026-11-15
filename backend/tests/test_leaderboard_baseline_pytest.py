"""Tests for the leaderboard's user-field whitelist, the Baseline row and its ranks."""

from datetime import timedelta

import pytest

from config import Config
from models import Challenge, JuryChallenge, Stage, Submission, Task, User
from tasks.task_modules.submission_runner import calculate_weighted_score
from utils.auth_utils import generate_token
from utils.cache_utils import invalidate_leaderboard_cache
from utils.dates import utcnow

PERSONAL_FIELDS = {"email", "username", "school", "city", "grade", "birth_date", "middle_name"}
COMPETITOR_FIELDS = {"id", "alias_id", "is_anonymous", "manual_points"}
NAME_FIELDS = {"name", "surname"}
RMSE_CONFIG = {"rmse": {"weight": 1.0}}


def _rmse_score(rmse):
    """Return the score the runner stores for an RMSE result, normalized to higher-is-better."""
    return calculate_weighted_score({"rmse": rmse}, RMSE_CONFIG)


class TestLeaderboardBaselineAndPrivacy:
    @pytest.fixture(autouse=True)
    def _setup(self, db_session, redis_flush):
        self.db = db_session
        self.admin = User(
            username="baseline_admin",
            email="baseline_admin@example.com",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            alias_id="Admin-BL",
        )
        self.admin.set_demographics("Ada", "Admin", "", "Staff School", "Staff City")
        self.jury = User(
            username="baseline_jury",
            email="baseline_jury@example.com",
            password_hash="pbkdf2:sha256:...",
            role="jury",
            alias_id="Jury-BL",
        )
        db_session.add_all([self.admin, self.jury])

        self.challenge = Challenge(
            title="Baseline Challenge",
            description="Leaderboard privacy and baseline rows",
            max_eval_requests=10,
            start_time=utcnow() - timedelta(hours=3),
            end_time=utcnow() + timedelta(hours=3),
            double_blind=False,
            reveal_results=True,
            scores_finalized=False,
        )
        db_session.add(self.challenge)
        db_session.commit()
        assigned = JuryChallenge.query.filter_by(
            jury_id=self.jury.id, challenge_id=self.challenge.id
        ).first()
        if assigned is None:
            db_session.add(JuryChallenge(jury_id=self.jury.id, challenge_id=self.challenge.id))

        self.stage = Stage(
            challenge_id=self.challenge.id,
            stage_number=1,
            title="Round 1",
            start_time=utcnow() - timedelta(hours=3),
            end_time=utcnow() + timedelta(hours=3),
        )
        db_session.add(self.stage)
        db_session.commit()

        self.task = Task(
            challenge_id=self.challenge.id,
            stage_id=self.stage.id,
            title="Baseline Task",
            description="Task with a baseline",
            ram_limit_mb=1024,
            time_limit_sec=60,
            files="[]",
        )
        db_session.add(self.task)

        self.alice = self._competitor("bl_alice", "Alice", "Smith", "Alpha-BL")
        self.bob = self._competitor("bl_bob", "Bob", "Jones", "Beta-BL")
        self.carol = self._competitor("bl_carol", "Carol", "Brown", "Gamma-BL")
        db_session.commit()

        self.tokens = {
            "admin": generate_token(self.admin.id, "admin"),
            "jury": generate_token(self.jury.id, "jury"),
            "competitor": generate_token(self.alice.id, "competitor"),
        }

    def _competitor(self, username, name, surname, alias):
        user = User(
            username=username,
            email=f"{username}@example.com",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id=alias,
            challenge_id=self.challenge.id,
        )
        user.set_demographics(
            name, surname, "11", f"{name} School", f"{name} City", "Middle", "2010-01-01"
        )
        self.db.add(user)
        return user

    def _submit(
        self, user, score, *, baseline=False, created_at=None, task=None, status="completed"
    ):
        sub = Submission(
            challenge_id=self.challenge.id,
            task_id=(task or self.task).id,
            user_id=user.id,
            status=status,
            public_score=score,
            private_score=score,
            execution_time_ms=100,
            code_cells="[]",
            is_baseline=baseline,
            created_at=created_at or utcnow(),
        )
        self.db.add(sub)
        self.db.commit()
        return sub

    def _leaderboard(self, client, role):
        invalidate_leaderboard_cache(self.challenge.id, delete_only=True)
        res = client.get(
            f"/api/challenges/{self.challenge.id}/leaderboard",
            headers={"Authorization": f"Bearer {self.tokens[role]}"},
        )
        assert res.status_code == 200
        return res.get_json()["leaderboard"]

    @staticmethod
    def _baseline_rows(leaderboard):
        return [e for e in leaderboard if e.get("is_baseline_entry")]

    def _row(self, leaderboard, user):
        return next(e for e in leaderboard if e["user"] and e["user"]["id"] == str(user.id))

    # ── Whitelist ──

    def test_competitor_gets_only_alias_and_name_when_names_are_shown(self, client):
        self._submit(self.alice, 0.7)
        self._submit(self.bob, 0.8)
        self._submit(self.admin, 0.5, baseline=True)

        leaderboard = self._leaderboard(client, "competitor")

        users = [e["user"] for e in leaderboard if e["user"] is not None]
        assert len(users) == 3
        for user in users:
            assert not PERSONAL_FIELDS & user.keys()
            assert set(user) == COMPETITOR_FIELDS | NAME_FIELDS
        assert self._row(leaderboard, self.bob)["user"]["name"] == "Bob"

    def test_double_blind_competitor_gets_only_the_alias_of_others(self, client):
        self.challenge.double_blind = True
        self.db.commit()
        self._submit(self.alice, 0.7)
        self._submit(self.bob, 0.8)

        leaderboard = self._leaderboard(client, "competitor")

        assert set(self._row(leaderboard, self.bob)["user"]) == COMPETITOR_FIELDS
        assert self._row(leaderboard, self.bob)["user"]["alias_id"] == "Beta-BL"
        own = self._row(leaderboard, self.alice)["user"]
        assert set(own) == COMPETITOR_FIELDS | NAME_FIELDS
        assert own["name"] == "Alice"

    def test_anonymous_competitor_is_shown_by_alias_only(self, client):
        self.bob.is_anonymous = True
        self.db.commit()
        self._submit(self.bob, 0.8)

        user = self._row(self._leaderboard(client, "competitor"), self.bob)["user"]

        assert set(user) == COMPETITOR_FIELDS
        assert user["is_anonymous"] is True

    def test_staff_still_get_the_full_record(self, client):
        self._submit(self.bob, 0.8)

        for role in ("admin", "jury"):
            user = self._row(self._leaderboard(client, role), self.bob)["user"]
            assert user["email"] == "bl_bob@example.com"
            assert user["school"] == "Bob School"
            assert user["username"] == "bl_bob"

    # ── Baseline row ──

    @pytest.mark.parametrize("role", ["admin", "jury", "competitor"])
    def test_baseline_row_has_no_user_data(self, client, role):
        self._submit(self.alice, 0.7)
        self._submit(self.admin, 0.5, baseline=True)

        rows = self._baseline_rows(self._leaderboard(client, role))

        assert len(rows) == 1
        assert rows[0]["user"] is None
        assert rows[0]["label"] == "Baseline"
        assert rows[0]["task_scores"][str(self.task.id)]["public_score"] == 0.5
        serialized = str(rows[0])
        for value in ("baseline_admin", "Admin-BL", "Staff School", str(self.admin.id)):
            assert value not in serialized

    def test_admin_run_that_outscores_the_baseline_keeps_the_baseline_row(self, client):
        self._submit(self.alice, 0.7)
        self._submit(self.admin, 0.5, baseline=True)
        self._submit(self.admin, 0.99)

        rows = self._baseline_rows(self._leaderboard(client, "admin"))

        assert len(rows) == 1
        assert rows[0]["task_scores"][str(self.task.id)]["public_score"] == 0.5

    def test_baseline_completed_after_the_deadline_is_still_shown(self, client):
        ended = utcnow() - timedelta(hours=1)
        self.challenge.end_time = ended
        self.stage.end_time = ended
        self.db.commit()
        late = ended + timedelta(seconds=Config.DEADLINE_GRACE_PERIOD_SECONDS + 60)
        self._submit(self.alice, 0.7, created_at=ended - timedelta(minutes=5))
        self._submit(self.bob, 0.9, created_at=late)
        self._submit(self.admin, 0.6, baseline=True, created_at=late)

        leaderboard = self._leaderboard(client, "admin")

        rows = self._baseline_rows(leaderboard)
        assert len(rows) == 1
        assert rows[0]["task_scores"][str(self.task.id)]["public_score"] == 0.6
        # A competitor's late run still does not count
        assert self._row(leaderboard, self.bob)["has_submitted"] is False

    # ── Ranks ──

    @pytest.mark.parametrize("role", ["admin", "jury", "competitor"])
    def test_best_competitor_is_rank_one_on_task_and_stage_tabs(self, client, role):
        self._submit(self.alice, 0.9)
        self._submit(self.bob, 0.8)
        self._submit(self.admin, 0.95, baseline=True)

        leaderboard = self._leaderboard(client, role)
        tid, sid = str(self.task.id), str(self.stage.id)

        alice = self._row(leaderboard, self.alice)
        bob = self._row(leaderboard, self.bob)
        assert (alice["rank"], alice["task_ranks"][tid], alice["stage_ranks"][sid]) == (1, 1, 1)
        assert (bob["rank"], bob["task_ranks"][tid], bob["stage_ranks"][sid]) == (2, 2, 2)
        (baseline,) = self._baseline_rows(leaderboard)
        assert baseline["rank"] is None
        assert baseline["task_ranks"][tid] is None
        assert baseline["stage_ranks"][sid] is None

    def test_competitor_without_a_scored_submission_has_no_rank(self, client):
        self._submit(self.alice, 0.9)

        for role in ("admin", "competitor"):
            leaderboard = self._leaderboard(client, role)
            assert self._row(leaderboard, self.alice)["rank"] == 1
            assert self._row(leaderboard, self.carol)["rank"] is None

    def test_finalized_competitor_with_points_but_no_scored_run_is_ranked(self, client):
        self.challenge.scores_finalized = True
        self.db.commit()
        dave = self._competitor("bl_dave", "Dave", "Green", "Delta-BL")
        self.db.commit()
        tid = str(self.task.id)
        self._submit(self.alice, 0.9)
        self._submit(self.bob, None, status="failed")
        self._submit(self.carol, 0.5)
        self.alice.manual_points = {tid: 30}
        self.bob.manual_points = {tid: 20}
        self.carol.manual_points = {tid: 10}
        self.db.commit()

        for role in ("admin", "jury", "competitor"):
            leaderboard = self._leaderboard(client, role)
            ranks = [
                (self._row(leaderboard, user)["rank"], self._row(leaderboard, user)["task_ranks"])
                for user in (self.alice, self.bob, self.carol, dave)
            ]
            assert ranks == [(1, {tid: 1}), (2, {tid: 2}), (3, {tid: 3}), (None, {tid: None})]
            assert self._row(leaderboard, self.bob)["has_submitted"] is False
            # An unranked row is listed after every ranked one
            assert leaderboard[-1]["user"]["id"] == str(dave.id)

    def test_task_ranks_follow_the_normalized_score_on_a_lower_is_better_task(self, client):
        self.task.metrics_config = RMSE_CONFIG
        self.db.commit()
        self._submit(self.alice, _rmse_score(3.0))
        self._submit(self.bob, _rmse_score(1.0))
        self._submit(self.carol, _rmse_score(2.0))

        leaderboard = self._leaderboard(client, "admin")
        tid, sid = str(self.task.id), str(self.stage.id)

        # The lowest RMSE is the best run on every tab
        for user, rank in ((self.bob, 1), (self.carol, 2), (self.alice, 3)):
            row = self._row(leaderboard, user)
            assert (row["rank"], row["task_ranks"][tid], row["stage_ranks"][sid]) == (rank,) * 3

    # ── Baseline placement on task tabs ──

    @pytest.mark.parametrize("role", ["admin", "jury", "competitor"])
    def test_baseline_is_placed_after_the_competitors_that_match_or_beat_it(self, client, role):
        self._submit(self.alice, 0.9)
        self._submit(self.bob, 0.7)
        self._submit(self.carol, 0.5)
        self._submit(self.admin, 0.7, baseline=True)

        (baseline,) = self._baseline_rows(self._leaderboard(client, role))

        # Bob ties the baseline and is listed before it
        assert baseline["task_rows_before"] == {str(self.task.id): 2}

    def test_baseline_is_placed_by_the_normalized_score_on_a_lower_is_better_task(self, client):
        self.task.metrics_config = RMSE_CONFIG
        self.db.commit()
        self._submit(self.alice, _rmse_score(3.0))
        self._submit(self.bob, _rmse_score(1.0))
        self._submit(self.carol, _rmse_score(2.0))
        self._submit(self.admin, _rmse_score(2.0), baseline=True)

        (baseline,) = self._baseline_rows(self._leaderboard(client, "admin"))

        # Bob beats the baseline's RMSE and Carol ties it; Alice's higher RMSE follows it
        assert baseline["task_rows_before"] == {str(self.task.id): 2}

    def test_baseline_beating_every_competitor_is_placed_first(self, client):
        self._submit(self.alice, 0.9)
        self._submit(self.admin, 0.95, baseline=True)

        (baseline,) = self._baseline_rows(self._leaderboard(client, "competitor"))

        assert baseline["task_rows_before"] == {str(self.task.id): 0}

    @pytest.mark.parametrize("role", ["admin", "jury", "competitor"])
    def test_baseline_has_no_place_once_results_are_final_and_revealed(self, client, role):
        self.challenge.scores_finalized = True
        self.db.commit()
        self.alice.manual_points = {str(self.task.id): 10}
        self.db.commit()
        self._submit(self.alice, 0.9)
        self._submit(self.admin, 0.5, baseline=True)

        (baseline,) = self._baseline_rows(self._leaderboard(client, role))

        assert baseline["task_rows_before"] == {}

    def test_baseline_has_a_place_while_final_results_stay_hidden(self, client):
        self.challenge.scores_finalized = True
        self.challenge.reveal_results = False
        self.db.commit()
        self._submit(self.alice, 0.9)
        self._submit(self.admin, 0.5, baseline=True)

        (baseline,) = self._baseline_rows(self._leaderboard(client, "admin"))

        assert baseline["task_rows_before"] == {str(self.task.id): 1}

    def test_baseline_has_no_place_on_a_task_it_has_no_score_on(self, client):
        other_task = Task(
            challenge_id=self.challenge.id,
            stage_id=self.stage.id,
            title="Task Without A Baseline",
            description="No baseline run",
            ram_limit_mb=1024,
            time_limit_sec=60,
            files="[]",
        )
        self.db.add(other_task)
        self.db.commit()
        self._submit(self.alice, 0.9)
        self._submit(self.alice, 0.8, task=other_task)
        self._submit(self.admin, 0.5, baseline=True)

        (baseline,) = self._baseline_rows(self._leaderboard(client, "admin"))

        assert baseline["task_rows_before"] == {str(self.task.id): 1}
