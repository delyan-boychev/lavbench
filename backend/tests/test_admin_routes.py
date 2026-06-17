import os
import sys
import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import db, User, Challenge
from auth_utils import generate_token


class TestGetAvailableMetrics(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.admin = User(
            username="admin", password_hash="x", role="admin", alias_id="A1"
        )
        db.session.add(self.admin)
        db.session.commit()
        self.admin_token = generate_token(self.admin.id, role="admin")

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_returns_available_metrics(self):
        resp = self.client.get(
            "/api/admin/metrics",
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIsInstance(data, dict)
        self.assertIn("accuracy", data)
        self.assertIn("f1", data)
        self.assertIn("bleu", data)
        self.assertIn("ssim", data)
        self.assertIn("psnr", data)

    def test_requires_admin_role(self):
        resp = self.client.get("/api/admin/metrics")
        self.assertEqual(resp.status_code, 403)

    def test_competitor_cannot_access(self):
        comp = User(
            username="comp1", password_hash="x", role="competitor",
            alias_id="C1"
        )
        db.session.add(comp)
        db.session.commit()
        token = generate_token(comp.id, role="competitor")
        resp = self.client.get(
            "/api/admin/metrics",
            headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(resp.status_code, 403)


class TestRegisterUser(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        from cache_utils import get_redis_client
        r = get_redis_client()
        if r:
            try:
                r.flushdb()
            except Exception:
                pass

        db.create_all()
        self.seed_basic_data()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def seed_basic_data(self):
        self.challenge = Challenge(
            title="Reg Test", description="Test", max_eval_requests=5,
            start_time=datetime.utcnow() + timedelta(hours=24),
            end_time=datetime.utcnow() + timedelta(hours=72),
            is_frozen=False
        )
        db.session.add(self.challenge)
        self.started_challenge = Challenge(
            title="Started", description="Test", max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=24),
            is_frozen=False
        )
        db.session.add(self.started_challenge)
        self.admin = User(
            username="admin1", password_hash="x", role="admin", alias_id="A1"
        )
        db.session.add(self.admin)
        self.jury = User(
            username="jury1", password_hash="x", role="jury", alias_id="J1"
        )
        db.session.add(self.jury)
        self.existing = User(
            username="existing_user", password_hash="x", role="competitor",
            alias_id="EX1", challenge_id=self.challenge.id
        )
        db.session.add(self.existing)
        db.session.commit()
        self.admin_token = generate_token(self.admin.id, role="admin")
        self.jury_token = generate_token(self.jury.id, role="jury")

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_register_competitor_success(self):
        resp = self.client.post(
            "/api/admin/register-user",
            json={
                "name": "John", "surname": "Doe", "role": "competitor",
                "challenge_id": self.challenge.id
            },
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertIn("generated_username", data)
        self.assertIn("generated_password", data)
        self.assertEqual(data["message"], "Competitor registered successfully.")

    def test_register_jury_success(self):
        resp = self.client.post(
            "/api/admin/register-user",
            json={
                "username": "newjury", "name": "Jane", "surname": "Juror",
                "role": "jury"
            },
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(resp.status_code, 201)

    def test_register_competitor_with_all_fields(self):
        resp = self.client.post(
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
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertEqual(data["generated_username"], "johndoe")

    def test_missing_role_returns_400(self):
        resp = self.client.post(
            "/api/admin/register-user",
            json={"name": "John", "surname": "Doe"},
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Valid role", resp.get_json()["error"])

    def test_invalid_role_returns_400(self):
        resp = self.client.post(
            "/api/admin/register-user",
            json={"name": "John", "surname": "Doe", "role": "superadmin"},
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(resp.status_code, 400)

    def test_admin_role_blocked_via_api(self):
        resp = self.client.post(
            "/api/admin/register-user",
            json={"name": "Admin", "surname": "User", "role": "admin"},
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("CLI", resp.get_json()["error"])

    def test_missing_name_or_surname_returns_400(self):
        resp = self.client.post(
            "/api/admin/register-user",
            json={"name": "John", "role": "competitor", "challenge_id": self.challenge.id},
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Name and Surname", resp.get_json()["error"])

    def test_competitor_missing_challenge_id_returns_400(self):
        resp = self.client.post(
            "/api/admin/register-user",
            json={"name": "John", "surname": "Doe", "role": "competitor"},
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("challenge_id", resp.get_json()["error"])

    def test_competitor_invalid_challenge_returns_400(self):
        resp = self.client.post(
            "/api/admin/register-user",
            json={
                "name": "John", "surname": "Doe", "role": "competitor",
                "challenge_id": 99999
            },
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Invalid challenge_id", resp.get_json()["error"])

    def test_jury_cannot_register_after_challenge_started(self):
        resp = self.client.post(
            "/api/admin/register-user",
            json={
                "name": "John", "surname": "Doe", "role": "competitor",
                "challenge_id": self.started_challenge.id
            },
            headers=self._auth(self.jury_token)
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("Jury members", resp.get_json()["error"])

    def test_admin_can_register_after_challenge_started(self):
        resp = self.client.post(
            "/api/admin/register-user",
            json={
                "name": "John", "surname": "Doe", "role": "competitor",
                "challenge_id": self.started_challenge.id
            },
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(resp.status_code, 201)

    def test_duplicate_username_returns_400(self):
        resp = self.client.post(
            "/api/admin/register-user",
            json={
                "username": "existing_user", "name": "John", "surname": "Doe",
                "role": "competitor", "challenge_id": self.challenge.id
            },
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("already exists", resp.get_json()["error"])

    def test_unauthorized_access_returns_403(self):
        resp = self.client.post(
            "/api/admin/register-user",
            json={"name": "John", "surname": "Doe", "role": "competitor", "challenge_id": self.challenge.id}
        )
        self.assertEqual(resp.status_code, 403)

    def test_random_password_generated_when_omitted(self):
        resp = self.client.post(
            "/api/admin/register-user",
            json={
                "name": "Alice", "surname": "Smith", "role": "competitor",
                "challenge_id": self.challenge.id
            },
            headers=self._auth(self.admin_token)
        )
        data = resp.get_json()
        self.assertEqual(len(data["generated_password"]), 8)

    def test_persists_user_in_database(self):
        resp = self.client.post(
            "/api/admin/register-user",
            json={
                "username": "persist_test", "name": "Persist", "surname": "Test",
                "role": "jury"
            },
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(resp.status_code, 201)
        user = User.query.filter_by(username="persist_test").first()
        self.assertIsNotNone(user)
        self.assertEqual(user.role, "jury")


class TestGetUsers(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.admin = User(username="admin", password_hash="x", role="admin", alias_id="A1")
        db.session.add(self.admin)
        self.comp = User(username="comp1", password_hash="x", role="competitor", alias_id="C1")
        db.session.add(self.comp)
        db.session.commit()
        self.admin_token = generate_token(self.admin.id, role="admin")
        self.comp_token = generate_token(self.comp.id, role="competitor")

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_admin_can_list_users(self):
        resp = self.client.get("/api/admin/users", headers=self._auth(self.admin_token))
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("items", data)
        self.assertGreaterEqual(len(data["items"]), 2)

    def test_competitor_cannot_list_users(self):
        resp = self.client.get("/api/admin/users", headers=self._auth(self.comp_token))
        self.assertEqual(resp.status_code, 403)

    def test_filter_by_role(self):
        resp = self.client.get("/api/admin/users?role=admin", headers=self._auth(self.admin_token))
        data = resp.get_json()
        for u in data["items"]:
            self.assertEqual(u["role"], "admin")

    def test_pagination(self):
        for i in range(15):
            u = User(username=f"user{i}", password_hash="x", role="competitor", alias_id=f"U{i}")
            db.session.add(u)
        db.session.commit()
        resp = self.client.get("/api/admin/users?page=1&per_page=5", headers=self._auth(self.admin_token))
        data = resp.get_json()
        self.assertEqual(len(data["items"]), 5)
        self.assertEqual(data["page"], 1)


class TestDeleteUser(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.admin = User(username="admin", password_hash="x", role="admin", alias_id="A1")
        db.session.add(self.admin)
        self.target = User(username="target", password_hash="x", role="competitor", alias_id="T1")
        db.session.add(self.target)
        db.session.commit()
        self.admin_token = generate_token(self.admin.id, role="admin")
        self.comp_token = generate_token(self.target.id, role="competitor")

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_admin_can_delete_user(self):
        resp = self.client.delete(f"/api/admin/users/{self.target.id}", headers=self._auth(self.admin_token))
        self.assertEqual(resp.status_code, 200)

    def test_competitor_cannot_delete_user(self):
        resp = self.client.delete(f"/api/admin/users/{self.target.id}", headers=self._auth(self.comp_token))
        self.assertEqual(resp.status_code, 403)

    def test_cannot_delete_self(self):
        resp = self.client.delete(f"/api/admin/users/{self.admin.id}", headers=self._auth(self.admin_token))
        self.assertEqual(resp.status_code, 400)

    def test_delete_nonexistent_user(self):
        resp = self.client.delete("/api/admin/users/99999", headers=self._auth(self.admin_token))
        self.assertEqual(resp.status_code, 404)


class TestUpdateUser(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.admin = User(username="admin", password_hash="x", role="admin", alias_id="A1")
        db.session.add(self.admin)
        self.target = User(username="target", password_hash="x", role="competitor", alias_id="T1")
        db.session.add(self.target)
        db.session.commit()
        self.admin_token = generate_token(self.admin.id, role="admin")
        self.comp_token = generate_token(self.target.id, role="competitor")

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_admin_can_update_user_email(self):
        resp = self.client.put(
            f"/api/admin/users/{self.target.id}",
            json={"email": "updated@test.com"},
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(db.session.get(User, self.target.id).email, "updated@test.com")

    def test_admin_can_set_is_anonymous(self):
        resp = self.client.put(
            f"/api/admin/users/{self.target.id}",
            json={"is_anonymous": True},
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(db.session.get(User, self.target.id).is_anonymous)

    def test_competitor_cannot_update_user(self):
        resp = self.client.put(
            f"/api/admin/users/{self.target.id}",
            json={"role": "jury"},
            headers=self._auth(self.comp_token)
        )
        self.assertEqual(resp.status_code, 403)

    def test_update_nonexistent_user(self):
        resp = self.client.put(
            "/api/admin/users/99999",
            json={"role": "jury"},
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(resp.status_code, 404)


if __name__ == '__main__':
    unittest.main()
