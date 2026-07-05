"""Tests for stage CRUD routes — create and update.

Delete tests already exist in test_challenges_routes.py (TestDeleteStage).
"""

import json
from datetime import timedelta

import pytest

from utils.dates import utcnow


def _iso(dt):
    return dt.isoformat()


def _past():
    return utcnow() - timedelta(days=1)


def _future():
    return utcnow() + timedelta(days=1)


@pytest.fixture(autouse=True)
def widen_challenge_bounds(db_session, sample_challenge):
    sample_challenge.start_time = utcnow() - timedelta(days=5)
    sample_challenge.end_time = utcnow() + timedelta(days=5)
    db_session.commit()


class TestCreateStage:
    """POST /api/challenges/<id>/stages"""

    def test_create_stage_success(
        self, client, db_session, sample_challenge, sample_admin, tokens, csrf_headers
    ):
        payload = {
            "title": "Qualification Round",
            "stage_number": 1,
            "start_time": _iso(_past()),
            "end_time": _iso(_future()),
        }
        res = client.post(
            f"/api/challenges/{sample_challenge.id}/stages",
            data=json.dumps(payload),
            content_type="application/json",
            headers=csrf_headers(tokens.admin),
        )
        assert res.status_code == 201
        data = res.get_json()
        assert data["title"] == "Qualification Round"
        assert data["stage_number"] == 1
        assert data["challenge_id"] == sample_challenge.id
        assert "id" in data

    def test_create_stage_auto_number(
        self, client, db_session, sample_challenge, sample_admin, tokens, csrf_headers
    ):
        payload = {
            "title": "Auto Number Stage",
            "start_time": _iso(_past()),
            "end_time": _iso(_future()),
        }
        res = client.post(
            f"/api/challenges/{sample_challenge.id}/stages",
            data=json.dumps(payload),
            content_type="application/json",
            headers=csrf_headers(tokens.admin),
        )
        assert res.status_code == 201
        assert res.get_json()["stage_number"] == 1

        payload2 = {
            "title": "Auto Number Stage 2",
            "start_time": _iso(_past()),
            "end_time": _iso(_future()),
        }
        res2 = client.post(
            f"/api/challenges/{sample_challenge.id}/stages",
            data=json.dumps(payload2),
            content_type="application/json",
            headers=csrf_headers(tokens.admin),
        )
        assert res2.status_code == 201
        assert res2.get_json()["stage_number"] == 2

    def test_create_stage_explicit_number(
        self, client, db_session, sample_challenge, sample_admin, tokens, csrf_headers
    ):
        payload = {
            "title": "Explicit Number",
            "stage_number": 5,
            "start_time": _iso(_past()),
            "end_time": _iso(_future()),
        }
        res = client.post(
            f"/api/challenges/{sample_challenge.id}/stages",
            data=json.dumps(payload),
            content_type="application/json",
            headers=csrf_headers(tokens.admin),
        )
        assert res.status_code == 201
        assert res.get_json()["stage_number"] == 5

    def test_create_stage_missing_title(
        self, client, db_session, sample_challenge, sample_admin, tokens, csrf_headers
    ):
        payload = {
            "start_time": _iso(_past()),
            "end_time": _iso(_future()),
        }
        res = client.post(
            f"/api/challenges/{sample_challenge.id}/stages",
            data=json.dumps(payload),
            content_type="application/json",
            headers=csrf_headers(tokens.admin),
        )
        assert res.status_code == 422
        assert res.get_json()["code"] == "ERR_VALIDATION"

    def test_create_stage_missing_start_time(
        self, client, db_session, sample_challenge, sample_admin, tokens, csrf_headers
    ):
        payload = {
            "title": "No Start",
            "end_time": _iso(_future()),
        }
        res = client.post(
            f"/api/challenges/{sample_challenge.id}/stages",
            data=json.dumps(payload),
            content_type="application/json",
            headers=csrf_headers(tokens.admin),
        )
        assert res.status_code == 422
        assert res.get_json()["code"] == "ERR_VALIDATION"

    def test_create_stage_missing_end_time(
        self, client, db_session, sample_challenge, sample_admin, tokens, csrf_headers
    ):
        payload = {
            "title": "No End",
            "start_time": _iso(_past()),
        }
        res = client.post(
            f"/api/challenges/{sample_challenge.id}/stages",
            data=json.dumps(payload),
            content_type="application/json",
            headers=csrf_headers(tokens.admin),
        )
        assert res.status_code == 422
        assert res.get_json()["code"] == "ERR_VALIDATION"

    def test_create_stage_invalid_date_format(
        self, client, db_session, sample_challenge, sample_admin, tokens, csrf_headers
    ):
        payload = {
            "title": "Bad Dates",
            "start_time": "not-a-date-end",
            "end_time": "not-a-date-start",
        }
        res = client.post(
            f"/api/challenges/{sample_challenge.id}/stages",
            data=json.dumps(payload),
            content_type="application/json",
            headers=csrf_headers(tokens.admin),
        )
        assert res.status_code == 422
        assert res.get_json()["code"] == "ERR_INVALID_DATE_FORMAT"

    def test_create_stage_competitor_forbidden(
        self,
        client,
        db_session,
        sample_challenge,
        sample_competitor,
        tokens,
        csrf_headers,
    ):
        payload = {
            "title": "Competitor Stage",
            "start_time": _iso(_past()),
            "end_time": _iso(_future()),
        }
        res = client.post(
            f"/api/challenges/{sample_challenge.id}/stages",
            data=json.dumps(payload),
            content_type="application/json",
            headers=csrf_headers(tokens.competitor),
        )
        assert res.status_code == 403

    def test_create_stage_challenge_not_found(
        self, client, db_session, sample_admin, tokens, csrf_headers
    ):
        payload = {
            "title": "No Challenge",
            "start_time": _iso(_past()),
            "end_time": _iso(_future()),
        }
        res = client.post(
            "/api/challenges/99999/stages",
            data=json.dumps(payload),
            content_type="application/json",
            headers=csrf_headers(tokens.admin),
        )
        assert res.status_code == 404


class TestUpdateStage:
    """PUT /api/challenges/<id>/stages/<id>"""

    def test_update_stage_title(
        self,
        client,
        db_session,
        sample_challenge,
        sample_stage,
        sample_admin,
        tokens,
        csrf_headers,
    ):
        payload = {"title": "Updated Title"}
        res = client.put(
            f"/api/challenges/{sample_challenge.id}/stages/{sample_stage.id}",
            data=json.dumps(payload),
            content_type="application/json",
            headers=csrf_headers(tokens.admin),
        )
        assert res.status_code == 200
        assert res.get_json()["title"] == "Updated Title"

    def test_update_stage_dates(
        self,
        client,
        db_session,
        sample_challenge,
        sample_stage,
        sample_admin,
        tokens,
        csrf_headers,
    ):
        new_start = _iso(utcnow() - timedelta(days=2))
        new_end = _iso(utcnow() + timedelta(days=2))
        payload = {"start_time": new_start, "end_time": new_end}
        res = client.put(
            f"/api/challenges/{sample_challenge.id}/stages/{sample_stage.id}",
            data=json.dumps(payload),
            content_type="application/json",
            headers=csrf_headers(tokens.admin),
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["start_time"] == new_start + "Z"
        assert data["end_time"] == new_end + "Z"

    def test_update_stage_stage_number(
        self,
        client,
        db_session,
        sample_challenge,
        sample_stage,
        sample_admin,
        tokens,
        csrf_headers,
    ):
        payload = {"stage_number": 10}
        res = client.put(
            f"/api/challenges/{sample_challenge.id}/stages/{sample_stage.id}",
            data=json.dumps(payload),
            content_type="application/json",
            headers=csrf_headers(tokens.admin),
        )
        assert res.status_code == 200
        assert res.get_json()["stage_number"] == 10

    def test_update_stage_partial(
        self,
        client,
        db_session,
        sample_challenge,
        sample_stage,
        sample_admin,
        tokens,
        csrf_headers,
    ):
        original_data = sample_stage.to_dict()
        payload = {"title": "Partial Update"}
        res = client.put(
            f"/api/challenges/{sample_challenge.id}/stages/{sample_stage.id}",
            data=json.dumps(payload),
            content_type="application/json",
            headers=csrf_headers(tokens.admin),
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["title"] == "Partial Update"
        assert data["stage_number"] == original_data["stage_number"]
        assert data["start_time"] == original_data["start_time"]
        assert data["end_time"] == original_data["end_time"]

    def test_update_stage_competitor_forbidden(
        self,
        client,
        db_session,
        sample_challenge,
        sample_stage,
        sample_competitor,
        tokens,
        csrf_headers,
    ):
        payload = {"title": "Hacked"}
        res = client.put(
            f"/api/challenges/{sample_challenge.id}/stages/{sample_stage.id}",
            data=json.dumps(payload),
            content_type="application/json",
            headers=csrf_headers(tokens.competitor),
        )
        assert res.status_code == 403

    def test_update_stage_not_found(
        self, client, db_session, sample_challenge, sample_admin, tokens, csrf_headers
    ):
        payload = {"title": "Nope"}
        res = client.put(
            f"/api/challenges/{sample_challenge.id}/stages/99999",
            data=json.dumps(payload),
            content_type="application/json",
            headers=csrf_headers(tokens.admin),
        )
        assert res.status_code == 404

    def test_update_stage_challenge_not_found(
        self, client, db_session, sample_admin, tokens, csrf_headers
    ):
        payload = {"title": "Nope"}
        res = client.put(
            "/api/challenges/99999/stages/1",
            data=json.dumps(payload),
            content_type="application/json",
            headers=csrf_headers(tokens.admin),
        )
        assert res.status_code == 404
