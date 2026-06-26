import hashlib
from datetime import datetime, timedelta

import pytest
from auth_utils import generate_token
from models import Challenge, User, db
from werkzeug.security import generate_password_hash


class TestAuthLogin:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, app_ctx):
        self.password = "testpass123"

        self.challenge = Challenge(
            title="Active Challenge",
            description="An active competition",
            max_eval_requests=10,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2),
            is_archived=False,
        )
        db.session.add(self.challenge)
        db.session.flush()

        self.archived = Challenge(
            title="Archived Challenge",
            description="An archived competition",
            max_eval_requests=10,
            start_time=datetime.utcnow() - timedelta(days=10),
            end_time=datetime.utcnow() - timedelta(days=5),
            is_archived=True,
        )
        db.session.add(self.archived)
        db.session.flush()

        self.user = self._create_user(
            "test_competitor",
            self.password,
            role="competitor",
            alias_id="Comp-001",
            challenge_id=self.challenge.id,
        )
        self.admin = self._create_user(
            "test_admin", self.password, role="admin", alias_id="Admin-001"
        )
        self.banned = self._create_user(
            "archived_comp",
            self.password,
            role="competitor",
            alias_id="Arch-001",
            challenge_id=self.archived.id,
        )

        db.session.commit()

    def _create_user(self, username, password, role="competitor", alias_id=None, challenge_id=None):
        client_hash = hashlib.sha256(password.encode()).hexdigest()
        pw_hash = generate_password_hash(client_hash, method="pbkdf2:sha256")
        user = User(
            username=username,
            password_hash=pw_hash,
            role=role,
            alias_id=alias_id or f"{role}-{username}",
            challenge_id=challenge_id,
        )
        db.session.add(user)
        db.session.flush()
        return user

    def test_login_success_competitor(self, client):
        res = client.post(
            "/api/auth/login",
            json={"username": "test_competitor", "password": self.password},
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["message"] == "Logged in successfully."
        assert "user" in data
        assert data["user"]["alias_id"] == "Comp-001"

    def test_login_success_admin(self, client):
        res = client.post(
            "/api/auth/login",
            json={"username": "test_admin", "password": self.password},
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["message"] == "Logged in successfully."
        assert "user" in data
        assert data["user"]["alias_id"] == "Admin-001"

    def test_login_wrong_password(self, client):
        res = client.post(
            "/api/auth/login",
            json={"username": "test_competitor", "password": "wrongpassword"},
        )
        assert res.status_code == 401
        assert res.get_json()["code"] == "ERR_INVALID_CREDENTIALS"

    def test_login_nonexistent_user(self, client):
        res = client.post("/api/auth/login", json={"username": "nobody", "password": self.password})
        assert res.status_code == 401
        assert res.get_json()["code"] == "ERR_INVALID_CREDENTIALS"

    def test_login_missing_username(self, client):
        res = client.post("/api/auth/login", json={"password": self.password})
        assert res.status_code == 400
        assert res.get_json()["code"] == "ERR_MISSING_CREDENTIALS"

    def test_login_missing_password(self, client):
        res = client.post("/api/auth/login", json={"username": "test_competitor"})
        assert res.status_code == 400
        assert res.get_json()["code"] == "ERR_MISSING_CREDENTIALS"

    def test_login_empty_body(self, client):
        res = client.post("/api/auth/login", json={})
        assert res.status_code == 400
        assert res.get_json()["code"] == "ERR_MISSING_CREDENTIALS"

    def test_login_archived_challenge_blocked(self, client):
        res = client.post(
            "/api/auth/login",
            json={"username": "archived_comp", "password": self.password},
        )
        assert res.status_code == 403
        assert res.get_json()["code"] == "ERR_COMPETITION_ARCHIVED"

    def test_login_competitor_no_challenge_succeeds(self, client):
        self._create_user(
            "no_challenge_comp", self.password, role="competitor", alias_id="NoChal-001"
        )
        db.session.commit()
        res = client.post(
            "/api/auth/login",
            json={"username": "no_challenge_comp", "password": self.password},
        )
        assert res.status_code == 200


class TestAuthLogout:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, app_ctx):
        self.user = User(
            username="logout_user",
            password_hash="x",
            role="competitor",
            alias_id="Logout-001",
        )
        db.session.add(self.user)
        db.session.commit()
        self.token = generate_token(self.user.id, self.user.role)

    def test_logout_success_with_token(self, client):
        res = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {self.token}"})
        assert res.status_code == 200
        assert res.get_json()["message"] == "Logged out successfully."

    def test_logout_without_token_still_succeeds(self, client):
        res = client.post("/api/auth/logout")
        assert res.status_code == 200
        assert res.get_json()["message"] == "Logged out successfully."


class TestAuthMe:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, app_ctx):
        self.user = User(
            username="me_user", password_hash="x", role="competitor", alias_id="Me-001"
        )
        db.session.add(self.user)
        db.session.commit()
        self.token = generate_token(self.user.id, self.user.role)

    def test_me_authenticated(self, client):
        res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {self.token}"})
        assert res.status_code == 200
        data = res.get_json()
        assert "user" in data
        assert data["user"]["alias_id"] == "Me-001"
        assert data["user"]["username"] == "me_user"

    def test_me_unauthenticated(self, client):
        res = client.get("/api/auth/me")
        assert res.status_code == 401
        assert "error" in res.get_json()

    def test_me_user_not_found(self, client):
        token = generate_token(99999, "competitor")
        res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 404
        assert res.get_json()["code"] == "ERR_USER_NOT_FOUND"
