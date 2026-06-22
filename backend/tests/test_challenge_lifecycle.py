"""pytest tests for challenge lifecycle endpoints: finalize, archive, test-competition.

Uses fixture-based patterns from conftest.py.
"""

import json
import pytest

from models import Challenge

# ═══════════════════════════════════════════════════════════════════════════
# Finalize endpoint:  POST /challenges/<id>/finalize
# Requires role: jury
# ═══════════════════════════════════════════════════════════════════════════


class TestFinalizeChallenge:
    """Tests for POST /challenges/<id>/finalize."""

    def test_finalize_as_jury_success(
        self, client, db_session, sample_challenge, sample_competitor, sample_task, create_user
    ):
        jury = create_user(username="finalize-jury", role="jury")
        from auth_utils import generate_token

        token = generate_token(jury.id, "jury")
        headers = {"Authorization": f"Bearer {token}"}

        sample_competitor.manual_points = {str(sample_task.id): 90}
        db_session.commit()

        res = client.post(
            f"/api/challenges/{sample_challenge.id}/finalize",
            data=json.dumps(
                {
                    "reveal_public_scores": True,
                    "reveal_private_scores": True,
                    "reveal_points": True,
                }
            ),
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["challenge"]["scores_finalized"] is True

        db_session.refresh(sample_challenge)
        assert sample_challenge.scores_finalized is True

    def test_finalize_admin_forbidden(self, client, db_session, sample_challenge, tokens):
        headers = {"Authorization": f"Bearer {tokens.admin}"}
        res = client.post(
            f"/api/challenges/{sample_challenge.id}/finalize",
            data=json.dumps({}),
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 403

    def test_finalize_competitor_forbidden(self, client, sample_challenge, tokens):
        headers = {"Authorization": f"Bearer {tokens.competitor}"}
        res = client.post(
            f"/api/challenges/{sample_challenge.id}/finalize",
            data=json.dumps({}),
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 403

    def test_finalize_challenge_not_found(self, client, create_user):
        jury = create_user(username="finalize-jury-nf", role="jury")
        from auth_utils import generate_token

        token = generate_token(jury.id, "jury")
        headers = {"Authorization": f"Bearer {token}"}

        res = client.post(
            "/api/challenges/99999/finalize",
            data=json.dumps({}),
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 404

    def test_finalize_missing_manual_points(
        self, client, db_session, sample_challenge, sample_competitor, sample_task, create_user
    ):
        jury = create_user(username="finalize-jury-mp", role="jury")
        from auth_utils import generate_token

        token = generate_token(jury.id, "jury")
        headers = {"Authorization": f"Bearer {token}"}

        sample_competitor.manual_points = None
        db_session.commit()

        res = client.post(
            f"/api/challenges/{sample_challenge.id}/finalize",
            data=json.dumps({}),
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 400
        assert "missing manual points" in res.get_json()["error"].lower()

    def test_finalize_repeat_finalize(
        self, client, db_session, sample_challenge, sample_competitor, sample_task, create_user
    ):
        jury = create_user(username="finalize-jury-rf", role="jury")
        from auth_utils import generate_token

        token = generate_token(jury.id, "jury")
        headers = {"Authorization": f"Bearer {token}"}

        sample_competitor.manual_points = {str(sample_task.id): 85}
        db_session.commit()

        res1 = client.post(
            f"/api/challenges/{sample_challenge.id}/finalize",
            data=json.dumps({}),
            content_type="application/json",
            headers=headers,
        )
        assert res1.status_code == 200

        res2 = client.post(
            f"/api/challenges/{sample_challenge.id}/finalize",
            data=json.dumps({}),
            content_type="application/json",
            headers=headers,
        )
        assert res2.status_code == 200
        assert res2.get_json()["challenge"]["scores_finalized"] is True

    def test_finalize_reveal_options(
        self, client, db_session, sample_challenge, sample_competitor, sample_task, create_user
    ):
        jury = create_user(username="finalize-jury-ro", role="jury")
        from auth_utils import generate_token

        token = generate_token(jury.id, "jury")
        headers = {"Authorization": f"Bearer {token}"}

        sample_competitor.manual_points = {str(sample_task.id): 75}
        db_session.commit()

        res = client.post(
            f"/api/challenges/{sample_challenge.id}/finalize",
            data=json.dumps(
                {
                    "reveal_public_scores": False,
                    "reveal_private_scores": False,
                    "reveal_points": False,
                }
            ),
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 200
        db_session.refresh(sample_challenge)
        assert sample_challenge.reveal_public_scores is False
        assert sample_challenge.reveal_private_scores is False
        assert sample_challenge.reveal_points is False


# ═══════════════════════════════════════════════════════════════════════════
# Test-Competition endpoint:  POST /challenges/<id>/test-competition
# Requires role: admin or jury
# ═══════════════════════════════════════════════════════════════════════════


class TestCreateTestCompetition:
    """Tests for POST /challenges/<id>/test-competition."""

    def test_test_competition_admin_creates(
        self, client, db_session, sample_challenge, sample_task, tokens
    ):
        headers = {"Authorization": f"Bearer {tokens.admin}"}
        res = client.post(
            f"/api/challenges/{sample_challenge.id}/test-competition",
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 201
        data = res.get_json()
        tc = data["test_competition"]
        assert tc["title"].startswith("Test: ")
        assert tc["max_eval_requests"] == 100
        assert tc["double_blind"] is False
        assert len(tc["tasks"]) == 1
        assert tc["tasks"][0]["title"] == "Warm-up Test Task"

        created = db_session.get(Challenge, tc["id"])
        assert created is not None
        assert created.title.startswith("Test:")

    def test_test_competition_jury_creates(
        self, client, db_session, sample_challenge, sample_task, create_user
    ):
        jury = create_user(username="testcomp-jury", role="jury")
        from auth_utils import generate_token

        token = generate_token(jury.id, "jury")
        headers = {"Authorization": f"Bearer {token}"}

        res = client.post(
            f"/api/challenges/{sample_challenge.id}/test-competition",
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 201

    def test_test_competition_competitor_forbidden(self, client, sample_challenge, tokens):
        headers = {"Authorization": f"Bearer {tokens.competitor}"}
        res = client.post(
            f"/api/challenges/{sample_challenge.id}/test-competition",
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 403

    def test_test_competition_challenge_not_found(self, client, tokens):
        headers = {"Authorization": f"Bearer {tokens.admin}"}
        res = client.post(
            "/api/challenges/99999/test-competition",
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 404

    def test_test_competition_unauthorized_no_token(self, client, sample_challenge):
        res = client.post(
            f"/api/challenges/{sample_challenge.id}/test-competition",
            content_type="application/json",
        )
        assert res.status_code == 401

    def test_test_competition_cleans_up_expired(
        self, client, db_session, sample_challenge, sample_task, tokens
    ):
        from datetime import datetime, timedelta

        expired = Challenge(
            title="Test: Old Expired (Warm-up)",
            description="Old test comp",
            start_time=datetime.utcnow() - timedelta(hours=10),
            end_time=datetime.utcnow() - timedelta(hours=8),
            double_blind=False,
            timezone="UTC",
        )
        db_session.add(expired)
        db_session.commit()

        headers = {"Authorization": f"Bearer {tokens.admin}"}
        res = client.post(
            f"/api/challenges/{sample_challenge.id}/test-competition",
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 201

        still_exists = Challenge.query.filter_by(title="Test: Old Expired (Warm-up)").count()
        assert still_exists == 0, "Expired test competition was not cleaned up"

        new_exists = Challenge.query.filter(Challenge.title.like("Test: % (Warm-up)")).count()
        assert new_exists == 1, "Should have exactly one test competition remaining"


# ═══════════════════════════════════════════════════════════════════════════
# Archive endpoint:  POST /challenges/<id>/archive
# (Basic toggle tested in TestArchiveChallenge — pytest-style coverage here)
# ═══════════════════════════════════════════════════════════════════════════


class TestArchiveChallengePytest:
    """Additional archive edge-cases not covered by TestArchiveChallenge."""

    def test_archive_jury_can_toggle(self, client, db_session, sample_challenge, create_user):
        jury = create_user(username="archive-jury", role="jury")
        from auth_utils import generate_token

        token = generate_token(jury.id, "jury")
        headers = {"Authorization": f"Bearer {token}"}

        assert sample_challenge.is_archived is False
        res = client.post(
            f"/api/challenges/{sample_challenge.id}/archive",
            headers=headers,
        )
        assert res.status_code == 200
        db_session.refresh(sample_challenge)
        assert sample_challenge.is_archived is True

        res = client.post(
            f"/api/challenges/{sample_challenge.id}/archive",
            headers=headers,
        )
        assert res.status_code == 200
        db_session.refresh(sample_challenge)
        assert sample_challenge.is_archived is False

    def test_archive_sets_computed_status(self, client, db_session, sample_challenge, tokens):
        headers = {"Authorization": f"Bearer {tokens.admin}"}
        res = client.post(
            f"/api/challenges/{sample_challenge.id}/archive",
            headers=headers,
        )
        assert res.status_code == 200
        assert res.get_json()["challenge"]["status"] == "archived"

    def test_archive_challenge_persisted(self, client, db_session, sample_challenge, tokens):
        headers = {"Authorization": f"Bearer {tokens.admin}"}
        client.post(
            f"/api/challenges/{sample_challenge.id}/archive",
            headers=headers,
        )
        db_session.refresh(sample_challenge)
        assert sample_challenge.is_archived is True

        client.post(
            f"/api/challenges/{sample_challenge.id}/archive",
            headers=headers,
        )
        db_session.refresh(sample_challenge)
        assert sample_challenge.is_archived is False
