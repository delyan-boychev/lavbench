import os
import sys
import json
import pytest
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models import db, User, Challenge
from auth_utils import generate_token


class TestGetAvailableMetrics:
    @pytest.fixture(autouse=True)
    def _setup(self, db_session):
        self.admin = User(username="admin", password_hash="x", role="admin", alias_id="A1")
        db_session.add(self.admin)
        db_session.commit()
        self.admin_token = generate_token(self.admin.id, role="admin")

    def test_returns_available_metrics(self, client, auth_headers):
        resp = client.get(
            "/api/admin/metrics",
            headers=auth_headers(self.admin_token)
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict)
        assert "accuracy" in data
        assert "f1" in data
        assert "bleu" in data
        assert "ssim" in data
        assert "psnr" in data

    def test_requires_admin_role(self, client):
        resp = client.get("/api/admin/metrics")
        assert resp.status_code == 403

    def test_competitor_cannot_access(self, client, db_session, auth_headers):
        comp = User(username="comp1", password_hash="x", role="competitor", alias_id="C1")
        db_session.add(comp)
        db_session.commit()
        token = generate_token(comp.id, role="competitor")
        resp = client.get(
            "/api/admin/metrics",
            headers=auth_headers(token)
        )
        assert resp.status_code == 403


class TestRegisterUser:
    @pytest.fixture(autouse=True)
    def _setup(self, db_session, redis_flush):
        self.challenge = Challenge(
            title="Reg Test", description="Test", max_eval_requests=5,
            start_time=datetime.utcnow() + timedelta(hours=24),
            end_time=datetime.utcnow() + timedelta(hours=72),
            is_frozen=False
        )
        db_session.add(self.challenge)
        self.started_challenge = Challenge(
            title="Started", description="Test", max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=24),
            is_frozen=False
        )
        db_session.add(self.started_challenge)
        self.admin = User(username="admin1", password_hash="x", role="admin", alias_id="A1")
        db_session.add(self.admin)
        self.jury = User(username="jury1", password_hash="x", role="jury", alias_id="J1")
        db_session.add(self.jury)
        self.existing = User(
            username="existing_user", password_hash="x", role="competitor",
            alias_id="EX1", challenge_id=self.challenge.id
        )
        db_session.add(self.existing)
        db_session.commit()
        self.admin_token = generate_token(self.admin.id, role="admin")
        self.jury_token = generate_token(self.jury.id, role="jury")

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_register_competitor_success(self, client):
        resp = client.post(
            "/api/admin/register-user",
            json={
                "name": "John", "surname": "Doe", "role": "competitor",
                "challenge_id": self.challenge.id
            },
            headers=self._auth(self.admin_token)
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert "generated_username" in data
        assert "generated_password" in data
        assert data["message"] == "Competitor registered successfully."

    def test_register_jury_success(self, client):
        resp = client.post(
            "/api/admin/register-user",
            json={
                "username": "newjury", "name": "Jane", "surname": "Juror",
                "role": "jury"
            },
            headers=self._auth(self.admin_token)
        )
        assert resp.status_code == 201

    def test_register_competitor_with_all_fields(self, client):
        resp = client.post(
            "/api/admin/register-user",
            json={
                "username": "johndoe", "name": "John", "surname": "Doe",
                "email": "john@test.com", "role": "competitor",
                "challenge_id": self.challenge.id,
                "grade": "10", "school": "Test HS", "city": "Sofia",
                "is_anonymous": True
            },
            headers=self._auth(self.admin_token)
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["generated_username"] == "johndoe"

    def test_missing_role_returns_400(self, client):
        resp = client.post(
            "/api/admin/register-user",
            json={"name": "John", "surname": "Doe"},
            headers=self._auth(self.admin_token)
        )
        assert resp.status_code == 400
        assert "Valid role" in resp.get_json()["error"]

    def test_invalid_role_returns_400(self, client):
        resp = client.post(
            "/api/admin/register-user",
            json={"name": "John", "surname": "Doe", "role": "superadmin"},
            headers=self._auth(self.admin_token)
        )
        assert resp.status_code == 400

    def test_admin_role_blocked_via_api(self, client):
        resp = client.post(
            "/api/admin/register-user",
            json={"name": "Admin", "surname": "User", "role": "admin"},
            headers=self._auth(self.admin_token)
        )
        assert resp.status_code == 403
        assert "CLI" in resp.get_json()["error"]

    def test_missing_name_or_surname_returns_400(self, client):
        resp = client.post(
            "/api/admin/register-user",
            json={"name": "John", "role": "competitor", "challenge_id": self.challenge.id},
            headers=self._auth(self.admin_token)
        )
        assert resp.status_code == 400
        assert "Name and Surname" in resp.get_json()["error"]

    def test_competitor_missing_challenge_id_returns_400(self, client):
        resp = client.post(
            "/api/admin/register-user",
            json={"name": "John", "surname": "Doe", "role": "competitor"},
            headers=self._auth(self.admin_token)
        )
        assert resp.status_code == 400
        assert "challenge_id" in resp.get_json()["error"]

    def test_competitor_invalid_challenge_returns_400(self, client):
        resp = client.post(
            "/api/admin/register-user",
            json={
                "name": "John", "surname": "Doe", "role": "competitor",
                "challenge_id": 99999
            },
            headers=self._auth(self.admin_token)
        )
        assert resp.status_code == 400
        assert "Invalid challenge_id" in resp.get_json()["error"]

    def test_jury_cannot_register_after_challenge_started(self, client):
        resp = client.post(
            "/api/admin/register-user",
            json={
                "name": "John", "surname": "Doe", "role": "competitor",
                "challenge_id": self.started_challenge.id
            },
            headers=self._auth(self.jury_token)
        )
        assert resp.status_code == 403
        assert "Jury members" in resp.get_json()["error"]

    def test_admin_can_register_after_challenge_started(self, client):
        resp = client.post(
            "/api/admin/register-user",
            json={
                "name": "John", "surname": "Doe", "role": "competitor",
                "challenge_id": self.started_challenge.id
            },
            headers=self._auth(self.admin_token)
        )
        assert resp.status_code == 201

    def test_duplicate_username_returns_400(self, client):
        resp = client.post(
            "/api/admin/register-user",
            json={
                "username": "existing_user", "name": "John", "surname": "Doe",
                "role": "competitor", "challenge_id": self.challenge.id
            },
            headers=self._auth(self.admin_token)
        )
        assert resp.status_code == 400
        assert "already exists" in resp.get_json()["error"]

    def test_unauthorized_access_returns_403(self, client):
        resp = client.post(
            "/api/admin/register-user",
            json={"name": "John", "surname": "Doe", "role": "competitor", "challenge_id": self.challenge.id}
        )
        assert resp.status_code == 403

    def test_random_password_generated_when_omitted(self, client):
        resp = client.post(
            "/api/admin/register-user",
            json={
                "name": "Alice", "surname": "Smith", "role": "competitor",
                "challenge_id": self.challenge.id
            },
            headers=self._auth(self.admin_token)
        )
        data = resp.get_json()
        assert len(data["generated_password"]) == 8

    def test_persists_user_in_database(self, client):
        resp = client.post(
            "/api/admin/register-user",
            json={
                "username": "persist_test", "name": "Persist", "surname": "Test",
                "role": "jury"
            },
            headers=self._auth(self.admin_token)
        )
        assert resp.status_code == 201
        user = User.query.filter_by(username="persist_test").first()
        assert user is not None
        assert user.role == "jury"


class TestGetUsers:
    @pytest.fixture(autouse=True)
    def _setup(self, db_session):
        self.admin = User(username="admin", password_hash="x", role="admin", alias_id="A1")
        db_session.add(self.admin)
        self.comp = User(username="comp1", password_hash="x", role="competitor", alias_id="C1")
        db_session.add(self.comp)
        db_session.commit()
        self.admin_token = generate_token(self.admin.id, role="admin")
        self.comp_token = generate_token(self.comp.id, role="competitor")

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_admin_can_list_users(self, client):
        resp = client.get("/api/admin/users", headers=self._auth(self.admin_token))
        assert resp.status_code == 200
        data = resp.get_json()
        assert "items" in data
        assert len(data["items"]) >= 2

    def test_competitor_cannot_list_users(self, client):
        resp = client.get("/api/admin/users", headers=self._auth(self.comp_token))
        assert resp.status_code == 403

    def test_filter_by_role(self, client):
        resp = client.get("/api/admin/users?role=admin", headers=self._auth(self.admin_token))
        data = resp.get_json()
        for u in data["items"]:
            assert u["role"] == "admin"

    def test_pagination(self, client, db_session):
        for i in range(15):
            u = User(username=f"user{i}", password_hash="x", role="competitor", alias_id=f"U{i}")
            db_session.add(u)
        db_session.commit()
        resp = client.get("/api/admin/users?page=1&per_page=5", headers=self._auth(self.admin_token))
        data = resp.get_json()
        assert len(data["items"]) == 5
        assert data["page"] == 1


class TestDeleteUser:
    @pytest.fixture(autouse=True)
    def _setup(self, db_session):
        self.admin = User(username="admin", password_hash="x", role="admin", alias_id="A1")
        db_session.add(self.admin)
        self.target = User(username="target", password_hash="x", role="competitor", alias_id="T1")
        db_session.add(self.target)
        db_session.commit()
        self.admin_token = generate_token(self.admin.id, role="admin")
        self.comp_token = generate_token(self.target.id, role="competitor")

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_admin_can_delete_user(self, client):
        resp = client.delete(f"/api/admin/users/{self.target.id}", headers=self._auth(self.admin_token))
        assert resp.status_code == 200

    def test_competitor_cannot_delete_user(self, client):
        resp = client.delete(f"/api/admin/users/{self.target.id}", headers=self._auth(self.comp_token))
        assert resp.status_code == 403

    def test_cannot_delete_self(self, client):
        resp = client.delete(f"/api/admin/users/{self.admin.id}", headers=self._auth(self.admin_token))
        assert resp.status_code == 400

    def test_delete_nonexistent_user(self, client):
        resp = client.delete("/api/admin/users/99999", headers=self._auth(self.admin_token))
        assert resp.status_code == 404


class TestUpdateUser:
    @pytest.fixture(autouse=True)
    def _setup(self, db_session):
        self.admin = User(username="admin", password_hash="x", role="admin", alias_id="A1")
        db_session.add(self.admin)
        self.target = User(username="target", password_hash="x", role="competitor", alias_id="T1")
        db_session.add(self.target)
        db_session.commit()
        self.admin_token = generate_token(self.admin.id, role="admin")
        self.comp_token = generate_token(self.target.id, role="competitor")

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_admin_can_update_user_email(self, client, db_session):
        resp = client.put(
            f"/api/admin/users/{self.target.id}",
            json={"email": "updated@test.com"},
            headers=self._auth(self.admin_token)
        )
        assert resp.status_code == 200
        assert db_session.get(User, self.target.id).email == "updated@test.com"

    def test_admin_can_set_is_anonymous(self, client, db_session):
        resp = client.put(
            f"/api/admin/users/{self.target.id}",
            json={"is_anonymous": True},
            headers=self._auth(self.admin_token)
        )
        assert resp.status_code == 200
        assert db_session.get(User, self.target.id).is_anonymous

    def test_competitor_cannot_update_user(self, client):
        resp = client.put(
            f"/api/admin/users/{self.target.id}",
            json={"role": "jury"},
            headers=self._auth(self.comp_token)
        )
        assert resp.status_code == 403

    def test_update_nonexistent_user(self, client):
        resp = client.put(
            "/api/admin/users/99999",
            json={"role": "jury"},
            headers=self._auth(self.admin_token)
        )
        assert resp.status_code == 404
