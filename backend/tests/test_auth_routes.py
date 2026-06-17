import os
import sys
import hashlib
import unittest
from datetime import datetime, timedelta

os.environ["SECRET_KEY"] = "test-secret-key-for-auth-routes"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from werkzeug.security import generate_password_hash
from app import create_app
from models import db, User, Challenge
from auth_utils import generate_token


class TestAuthLogin(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

        self.app_context = self.app.app_context()
        self.app_context.push()

        db.create_all()
        self.seed_data()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _create_user(self, username, password, role="competitor", alias_id=None, challenge_id=None):
        client_hash = hashlib.sha256(password.encode()).hexdigest()
        pw_hash = generate_password_hash(client_hash, method="pbkdf2:sha256")
        user = User(
            username=username,
            password_hash=pw_hash,
            role=role,
            alias_id=alias_id or f"{role}-{username}",
            challenge_id=challenge_id
        )
        db.session.add(user)
        db.session.flush()
        return user

    def seed_data(self):
        self.password = "testpass123"

        self.challenge = Challenge(
            title="Active Challenge",
            description="An active competition",
            max_eval_requests=10,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2),
            is_archived=False
        )
        db.session.add(self.challenge)
        db.session.flush()

        self.archived = Challenge(
            title="Archived Challenge",
            description="An archived competition",
            max_eval_requests=10,
            start_time=datetime.utcnow() - timedelta(days=10),
            end_time=datetime.utcnow() - timedelta(days=5),
            is_archived=True
        )
        db.session.add(self.archived)
        db.session.flush()

        self.user = self._create_user(
            "test_competitor", self.password,
            role="competitor", alias_id="Comp-001",
            challenge_id=self.challenge.id
        )
        self.admin = self._create_user(
            "test_admin", self.password,
            role="admin", alias_id="Admin-001"
        )
        self.banned = self._create_user(
            "archived_comp", self.password,
            role="competitor", alias_id="Arch-001",
            challenge_id=self.archived.id
        )

        db.session.commit()

    def test_login_success_competitor(self):
        res = self.client.post('/api/auth/login', json={
            "username": "test_competitor",
            "password": self.password
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["message"], "Logged in successfully.")
        self.assertIn("user", data)
        self.assertEqual(data["user"]["alias_id"], "Comp-001")

    def test_login_success_admin(self):
        res = self.client.post('/api/auth/login', json={
            "username": "test_admin",
            "password": self.password
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["message"], "Logged in successfully.")
        self.assertIn("user", data)
        self.assertEqual(data["user"]["alias_id"], "Admin-001")

    def test_login_wrong_password(self):
        res = self.client.post('/api/auth/login', json={
            "username": "test_competitor",
            "password": "wrongpassword"
        })
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()["code"], "ERR_INVALID_CREDENTIALS")

    def test_login_nonexistent_user(self):
        res = self.client.post('/api/auth/login', json={
            "username": "nobody",
            "password": self.password
        })
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()["code"], "ERR_INVALID_CREDENTIALS")

    def test_login_missing_username(self):
        res = self.client.post('/api/auth/login', json={"password": self.password})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "ERR_MISSING_CREDENTIALS")

    def test_login_missing_password(self):
        res = self.client.post('/api/auth/login', json={"username": "test_competitor"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "ERR_MISSING_CREDENTIALS")

    def test_login_empty_body(self):
        res = self.client.post('/api/auth/login', json={})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "ERR_MISSING_CREDENTIALS")

    def test_login_archived_challenge_blocked(self):
        res = self.client.post('/api/auth/login', json={
            "username": "archived_comp",
            "password": self.password
        })
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "ERR_COMPETITION_ARCHIVED")

    def test_login_competitor_no_challenge_succeeds(self):
        no_challenge = self._create_user(
            "no_challenge_comp", self.password,
            role="competitor", alias_id="NoChal-001"
        )
        db.session.commit()
        res = self.client.post('/api/auth/login', json={
            "username": "no_challenge_comp",
            "password": self.password
        })
        self.assertEqual(res.status_code, 200)


class TestAuthLogout(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

        self.app_context = self.app.app_context()
        self.app_context.push()

        db.create_all()
        self.seed_data()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def seed_data(self):
        self.user = User(
            username="logout_user",
            password_hash="x",
            role="competitor",
            alias_id="Logout-001"
        )
        db.session.add(self.user)
        db.session.commit()
        self.token = generate_token(self.user.id, self.user.role)

    def test_logout_success_with_token(self):
        res = self.client.post('/api/auth/logout', headers={
            "Authorization": f"Bearer {self.token}"
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["message"], "Logged out successfully.")

    def test_logout_without_token_still_succeeds(self):
        res = self.client.post('/api/auth/logout')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["message"], "Logged out successfully.")


class TestAuthMe(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

        self.app_context = self.app.app_context()
        self.app_context.push()

        db.create_all()
        self.seed_data()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def seed_data(self):
        self.user = User(
            username="me_user",
            password_hash="x",
            role="competitor",
            alias_id="Me-001"
        )
        db.session.add(self.user)
        db.session.commit()
        self.token = generate_token(self.user.id, self.user.role)

    def test_me_authenticated(self):
        res = self.client.get('/api/auth/me', headers={
            "Authorization": f"Bearer {self.token}"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("user", data)
        self.assertEqual(data["user"]["alias_id"], "Me-001")
        self.assertEqual(data["user"]["username"], "me_user")

    def test_me_unauthenticated(self):
        res = self.client.get('/api/auth/me')
        self.assertEqual(res.status_code, 401)
        self.assertIn("error", res.get_json())

    def test_me_user_not_found(self):
        token = generate_token(99999, "competitor")
        res = self.client.get('/api/auth/me', headers={
            "Authorization": f"Bearer {token}"
        })
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json()["code"], "ERR_USER_NOT_FOUND")


if __name__ == '__main__':
    unittest.main()
