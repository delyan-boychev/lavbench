"""Tests for the leaderboard's user-field whitelist, the Baseline row and its ranks."""

from datetime import timedelta

import pytest

from config import Config
from models import Challenge, JuryChallenge, Stage, Submission, Task, User
from utils.auth_utils import generate_token
from utils.cache_utils import invalidate_leaderboard_cache
from utils.dates import utcnow

PERSONAL_FIELDS = {"email", "username", "school", "city", "grade", "birth_date", "middle_name"}
COMPETITOR_FIELDS = {"id", "alias_id", "is_anonymous", "manual_points"}
NAME_FIELDS = {"name", "surname"}


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

    def _submit(self, user, score, *, baseline=False, created_at=None):
        sub = Submission(
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            user_id=user.id,
            status="completed",
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
