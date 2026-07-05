import json
import os
import sys
from datetime import timedelta

import pytest

from utils.dates import utcnow

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from auth_utils import generate_token
from models import Challenge, Stage, User


class TestCreateChallenge:
    @pytest.fixture(autouse=True)
    def _setup(self, db_session, redis_flush):
        self.admin = User(
            username="create_admin",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            alias_id="Create-Admin-001",
        )
        db_session.add(self.admin)

        self.competitor = User(
            username="create_comp",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Create-Comp-001",
        )
        db_session.add(self.competitor)
        db_session.commit()

        self.admin_token = generate_token(self.admin.id, self.admin.role)
        self.competitor_token = generate_token(self.competitor.id, self.competitor.role)

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def _valid_payload(self):
        return {
            "title": "Test Challenge",
            "description": "A test challenge",
            "start_time": (utcnow() + timedelta(hours=1)).isoformat(),
            "end_time": (utcnow() + timedelta(hours=24)).isoformat(),
            "max_eval_requests": 10,
            "ram_limit_mb": 4096,
            "time_limit_sec": 300,
            "gpu_required": False,
            "double_blind": True,
            "timezone": "UTC",
        }

    def test_create_challenge_success(self, client):
        payload = self._valid_payload()
        res = client.post(
            "/api/challenges",
            data=json.dumps(payload),
            content_type="application/json",
            headers=self._auth(self.admin_token),
        )
        assert res.status_code == 201
        data = res.get_json()
        assert data["title"] == "Test Challenge"
        assert data["description"] == "A test challenge"
        assert data["max_eval_requests"] == 10
        assert data["ram_limit_mb"] == 4096
        assert data["time_limit_sec"] == 300
        assert data["gpu_required"] is False
        assert data["double_blind"] is True
        assert data["timezone"] == "UTC"
        assert "id" in data

    def test_create_challenge_missing_title(self, client):
        payload = self._valid_payload()
        payload.pop("title")
        res = client.post(
            "/api/challenges",
            data=json.dumps(payload),
            content_type="application/json",
            headers=self._auth(self.admin_token),
        )
        assert res.status_code == 422
        assert res.get_json()["code"] == "ERR_VALIDATION"

    def test_create_challenge_missing_dates(self, client):
        payload = self._valid_payload()
        payload.pop("start_time")
        res = client.post(
            "/api/challenges",
            data=json.dumps(payload),
            content_type="application/json",
            headers=self._auth(self.admin_token),
        )
        assert res.status_code == 422
        assert res.get_json()["code"] == "ERR_VALIDATION"

    def test_create_challenge_end_before_start(self, client):
        payload = self._valid_payload()
        payload["start_time"] = (utcnow() + timedelta(hours=24)).isoformat()
        payload["end_time"] = (utcnow() + timedelta(hours=1)).isoformat()
        res = client.post(
            "/api/challenges",
            data=json.dumps(payload),
            content_type="application/json",
            headers=self._auth(self.admin_token),
        )
        assert res.status_code == 422
        assert res.get_json()["code"] == "ERR_INVALID_DATE_RANGE"

    def test_create_challenge_invalid_limits(self, client):
        payload = self._valid_payload()
        payload["max_eval_requests"] = 0
        res = client.post(
            "/api/challenges",
            data=json.dumps(payload),
            content_type="application/json",
            headers=self._auth(self.admin_token),
        )
        assert res.status_code == 422
        assert res.get_json()["code"] == "ERR_VALIDATION"

    def test_create_challenge_ram_too_low(self, client):
        payload = self._valid_payload()
        payload["ram_limit_mb"] = 64
        res = client.post(
            "/api/challenges",
            data=json.dumps(payload),
            content_type="application/json",
            headers=self._auth(self.admin_token),
        )
        assert res.status_code == 422
        assert res.get_json()["code"] == "ERR_VALIDATION"

    def test_create_challenge_competitor_forbidden(self, client):
        payload = self._valid_payload()
        res = client.post(
            "/api/challenges",
            data=json.dumps(payload),
            content_type="application/json",
            headers=self._auth(self.competitor_token),
        )
        assert res.status_code == 403
        assert "requires role" in res.get_json()["error"].lower()


class TestUpdateChallenge:
    @pytest.fixture(autouse=True)
    def _setup(self, db_session, redis_flush):
        self.admin = User(
            username="upd_admin",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            alias_id="Upd-Admin-001",
        )
        db_session.add(self.admin)

        self.competitor = User(
            username="upd_comp",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Upd-Comp-001",
        )
        db_session.add(self.competitor)

        self.challenge = Challenge(
            title="Original Title",
            description="Original description",
            max_eval_requests=5,
            ram_limit_mb=4096,
            time_limit_sec=300,
            gpu_required=True,
            start_time=utcnow() + timedelta(hours=1),
            end_time=utcnow() + timedelta(hours=24),
            double_blind=True,
            timezone="UTC",
        )
        db_session.add(self.challenge)
        db_session.commit()

        self.admin_token = generate_token(self.admin.id, self.admin.role)
        self.competitor_token = generate_token(self.competitor.id, self.competitor.role)

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_update_challenge_title(self, client):
        res = client.put(
            f"/api/challenges/{self.challenge.id}",
            data=json.dumps({"title": "Updated Title"}),
            content_type="application/json",
            headers=self._auth(self.admin_token),
        )
        assert res.status_code == 200
        assert res.get_json()["title"] == "Updated Title"

    def test_update_challenge_description(self, client):
        res = client.put(
            f"/api/challenges/{self.challenge.id}",
            data=json.dumps({"description": "New description"}),
            content_type="application/json",
            headers=self._auth(self.admin_token),
        )
        assert res.status_code == 200
        assert res.get_json()["description"] == "New description"

    def test_update_challenge_max_eval_requests(self, client):
        res = client.put(
            f"/api/challenges/{self.challenge.id}",
            data=json.dumps({"max_eval_requests": 20}),
            content_type="application/json",
            headers=self._auth(self.admin_token),
        )
        assert res.status_code == 200
        assert res.get_json()["max_eval_requests"] == 20

    def test_update_challenge_invalid_max_eval_requests(self, client):
        res = client.put(
            f"/api/challenges/{self.challenge.id}",
            data=json.dumps({"max_eval_requests": 0}),
            content_type="application/json",
            headers=self._auth(self.admin_token),
        )
        assert res.status_code == 422
        assert res.get_json()["code"] == "ERR_VALIDATION"

    def test_update_challenge_invalid_ram(self, client):
        res = client.put(
            f"/api/challenges/{self.challenge.id}",
            data=json.dumps({"ram_limit_mb": 64}),
            content_type="application/json",
            headers=self._auth(self.admin_token),
        )
        assert res.status_code == 422
        assert res.get_json()["code"] == "ERR_VALIDATION"

    def test_update_challenge_invalid_time_limit(self, client):
        res = client.put(
            f"/api/challenges/{self.challenge.id}",
            data=json.dumps({"time_limit_sec": 0}),
            content_type="application/json",
            headers=self._auth(self.admin_token),
        )
        assert res.status_code == 422
        assert res.get_json()["code"] == "ERR_VALIDATION"

    def test_update_challenge_gpu_required(self, client):
        res = client.put(
            f"/api/challenges/{self.challenge.id}",
            data=json.dumps({"gpu_required": False}),
            content_type="application/json",
            headers=self._auth(self.admin_token),
        )
        assert res.status_code == 200
        assert res.get_json()["gpu_required"] is False

    def test_update_challenge_dates_invalid_order(self, client):
        res = client.put(
            f"/api/challenges/{self.challenge.id}",
            data=json.dumps(
                {
                    "start_time": (utcnow() + timedelta(hours=10)).isoformat(),
                    "end_time": (utcnow() + timedelta(hours=5)).isoformat(),
                }
            ),
            content_type="application/json",
            headers=self._auth(self.admin_token),
        )
        assert res.status_code == 422
        assert res.get_json()["code"] == "ERR_INVALID_DATE_RANGE"

    def test_update_challenge_is_frozen_and_double_blind(self, client):
        res = client.put(
            f"/api/challenges/{self.challenge.id}",
            data=json.dumps({"is_frozen": True, "double_blind": False}),
            content_type="application/json",
            headers=self._auth(self.admin_token),
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["is_frozen"] is True
        assert data["double_blind"] is False

    def test_update_challenge_competitor_forbidden(self, client):
        res = client.put(
            f"/api/challenges/{self.challenge.id}",
            data=json.dumps({"title": "Hacked"}),
            content_type="application/json",
            headers=self._auth(self.competitor_token),
        )
        assert res.status_code == 403

    def test_update_challenge_not_found(self, client):
        res = client.put(
            "/api/challenges/99999",
            data=json.dumps({"title": "Nope"}),
            content_type="application/json",
            headers=self._auth(self.admin_token),
        )
        assert res.status_code == 404


class TestArchiveChallenge:
    @pytest.fixture(autouse=True)
    def _setup(self, db_session, redis_flush):
        self.admin = User(
            username="arch_admin",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            alias_id="Arch-Admin-001",
        )
        db_session.add(self.admin)

        self.competitor = User(
            username="arch_comp",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Arch-Comp-001",
        )
        db_session.add(self.competitor)

        self.challenge = Challenge(
            title="Archivable Challenge",
            description="To be archived",
            is_archived=False,
            start_time=utcnow() + timedelta(hours=1),
            end_time=utcnow() + timedelta(hours=24),
        )
        db_session.add(self.challenge)
        db_session.commit()

        self.admin_token = generate_token(self.admin.id, self.admin.role)
        self.competitor_token = generate_token(self.competitor.id, self.competitor.role)

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_archive_challenge_toggle_on(self, client):
        assert self.challenge.is_archived is False
        res = client.post(
            f"/api/challenges/{self.challenge.id}/archive",
            headers=self._auth(self.admin_token),
        )
        assert res.status_code == 200
        data = res.get_json()
        assert "archived" in data["message"].lower()
        assert data["challenge"]["is_archived"] is True

    def test_archive_challenge_toggle_off(self, client, db_session):
        self.challenge.is_archived = True
        db_session.commit()
        res = client.post(
            f"/api/challenges/{self.challenge.id}/archive",
            headers=self._auth(self.admin_token),
        )
        assert res.status_code == 200
        data = res.get_json()
        assert "restored" in data["message"].lower()
        assert data["challenge"]["is_archived"] is False

    def test_archive_challenge_competitor_forbidden(self, client):
        res = client.post(
            f"/api/challenges/{self.challenge.id}/archive",
            headers=self._auth(self.competitor_token),
        )
        assert res.status_code == 403

    def test_archive_challenge_not_found(self, client):
        res = client.post("/api/challenges/99999/archive", headers=self._auth(self.admin_token))
        assert res.status_code == 404


class TestDeleteStage:
    @pytest.fixture(autouse=True)
    def _setup(self, db_session, redis_flush):
        self.admin = User(
            username="stage_del_admin",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            alias_id="Stage-Del-Admin",
        )
        db_session.add(self.admin)

        self.competitor = User(
            username="stage_del_comp",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Stage-Del-Comp",
        )
        db_session.add(self.competitor)

        self.challenge = Challenge(
            title="Stage Delete Challenge",
            description="Has stages",
            start_time=utcnow() + timedelta(hours=1),
            end_time=utcnow() + timedelta(hours=24),
        )
        db_session.add(self.challenge)
        db_session.commit()

        self.stage = Stage(
            challenge_id=self.challenge.id,
            stage_number=1,
            title="Stage To Delete",
            start_time=utcnow() + timedelta(hours=2),
            end_time=utcnow() + timedelta(hours=20),
        )
        db_session.add(self.stage)
        db_session.commit()

        self.admin_token = generate_token(self.admin.id, self.admin.role)
        self.competitor_token = generate_token(self.competitor.id, self.competitor.role)

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_delete_stage_success(self, client, db_session):
        stage_id = self.stage.id
        res = client.delete(
            f"/api/challenges/{self.challenge.id}/stages/{stage_id}",
            headers=self._auth(self.admin_token),
        )
        assert res.status_code == 200
        assert "deleted" in res.get_json()["message"].lower()

        db_session.close()
        deleted = db_session.get(Stage, stage_id)
        assert deleted is None

    def test_delete_stage_competitor_forbidden(self, client):
        res = client.delete(
            f"/api/challenges/{self.challenge.id}/stages/{self.stage.id}",
            headers=self._auth(self.competitor_token),
        )
        assert res.status_code == 403

    def test_delete_stage_not_found(self, client):
        res = client.delete(
            f"/api/challenges/{self.challenge.id}/stages/99999",
            headers=self._auth(self.admin_token),
        )
        assert res.status_code == 404

    def test_delete_stage_challenge_not_found(self, client):
        res = client.delete("/api/challenges/99999/stages/1", headers=self._auth(self.admin_token))
        assert res.status_code == 404


class TestListChallenges:
    @pytest.fixture(autouse=True)
    def _setup(self, db_session, redis_flush):
        self.admin = User(
            username="list_admin",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            alias_id="List-Admin",
        )
        db_session.add(self.admin)

        self.competitor = User(
            username="list_comp",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="List-Comp",
        )
        db_session.add(self.competitor)

        self.challenge1 = Challenge(
            title="Challenge Alpha",
            description="First challenge",
            start_time=utcnow() + timedelta(hours=1),
            end_time=utcnow() + timedelta(hours=24),
        )
        db_session.add(self.challenge1)

        self.challenge2 = Challenge(
            title="Challenge Beta",
            description="Second challenge",
            start_time=utcnow() + timedelta(hours=2),
            end_time=utcnow() + timedelta(hours=48),
        )
        db_session.add(self.challenge2)
        db_session.commit()

        self.admin_token = generate_token(self.admin.id, self.admin.role)
        self.competitor_token = generate_token(self.competitor.id, self.competitor.role)

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_list_challenges_admin_non_paginated(self, client):
        res = client.get("/api/challenges", headers=self._auth(self.admin_token))
        assert res.status_code == 200
        data = res.get_json()
        assert isinstance(data, list)
        assert len(data) >= 2
        titles = [c["title"] for c in data]
        assert "Challenge Alpha" in titles
        assert "Challenge Beta" in titles

    def test_list_challenges_admin_paginated(self, client):
        res = client.get("/api/challenges?page=1&per_page=1", headers=self._auth(self.admin_token))
        assert res.status_code == 200
        data = res.get_json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "pages" in data
        assert len(data["items"]) == 1
        assert data["page"] == 1
        assert data["total"] == 2

    def test_list_challenges_competitor_not_registered(self, client):
        res = client.get("/api/challenges", headers=self._auth(self.competitor_token))
        assert res.status_code == 200
        assert res.get_json() == []


class TestStageBoundariesValidation:
    @pytest.fixture(autouse=True)
    def _setup(self, db_session, redis_flush):
        self.admin = User(
            username="boundary_admin",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            alias_id="Boundary-Admin-001",
        )
        db_session.add(self.admin)

        self.challenge = Challenge(
            title="Boundary Challenge",
            description="Challenge timeframe bounds",
            start_time=utcnow() + timedelta(hours=1),
            end_time=utcnow() + timedelta(hours=24),
            timezone="UTC",
        )
        db_session.add(self.challenge)
        db_session.commit()
        self.admin_token = generate_token(self.admin.id, self.admin.role)

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_create_stage_outside_competition_bounds(self, client):
        # Stage starts before challenge start time
        payload = {
            "title": "Early Stage",
            "start_time": (utcnow()).isoformat() + "Z",
            "end_time": (utcnow() + timedelta(hours=5)).isoformat() + "Z",
        }
        res = client.post(
            f"/api/challenges/{self.challenge.id}/stages",
            data=json.dumps(payload),
            content_type="application/json",
            headers=self._auth(self.admin_token),
        )
        assert res.status_code == 400
        assert "ERR_STAGE_OUT_OF_COMPETITION_BOUNDS" in res.get_json()["code"]

        # Stage ends after challenge end time
        payload = {
            "title": "Late Stage",
            "start_time": (utcnow() + timedelta(hours=2)).isoformat() + "Z",
            "end_time": (utcnow() + timedelta(hours=26)).isoformat() + "Z",
        }
        res = client.post(
            f"/api/challenges/{self.challenge.id}/stages",
            data=json.dumps(payload),
            content_type="application/json",
            headers=self._auth(self.admin_token),
        )
        assert res.status_code == 400
        assert "ERR_STAGE_OUT_OF_COMPETITION_BOUNDS" in res.get_json()["code"]

    def test_create_stage_end_before_start(self, client):
        payload = {
            "title": "Backward Stage",
            "start_time": (utcnow() + timedelta(hours=5)).isoformat() + "Z",
            "end_time": (utcnow() + timedelta(hours=4)).isoformat() + "Z",
        }
        res = client.post(
            f"/api/challenges/{self.challenge.id}/stages",
            data=json.dumps(payload),
            content_type="application/json",
            headers=self._auth(self.admin_token),
        )
        assert res.status_code == 422
        assert res.get_json()["code"] == "ERR_INVALID_DATE_RANGE"
