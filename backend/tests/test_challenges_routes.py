import os
import sys
import json
import unittest
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import db, User, Challenge, Stage
from auth_utils import generate_token


class TestCreateChallenge(unittest.TestCase):
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

        self.admin = User(
            username="create_admin",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            alias_id="Create-Admin-001"
        )
        db.session.add(self.admin)
        db.session.commit()

        self.competitor = User(
            username="create_comp",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Create-Comp-001"
        )
        db.session.add(self.competitor)
        db.session.commit()

        self.admin_token = generate_token(self.admin.id, self.admin.role)
        self.competitor_token = generate_token(self.competitor.id, self.competitor.role)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def _valid_payload(self):
        return {
            "title": "Test Challenge",
            "description": "A test challenge",
            "start_time": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(hours=24)).isoformat(),
            "max_eval_requests": 10,
            "ram_limit_mb": 4096,
            "time_limit_sec": 300,
            "gpu_required": False,
            "double_blind": True,
            "timezone": "UTC"
        }

    def test_create_challenge_success(self):
        payload = self._valid_payload()
        res = self.client.post(
            '/api/challenges',
            data=json.dumps(payload),
            content_type='application/json',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data["title"], "Test Challenge")
        self.assertEqual(data["description"], "A test challenge")
        self.assertEqual(data["max_eval_requests"], 10)
        self.assertEqual(data["ram_limit_mb"], 4096)
        self.assertEqual(data["time_limit_sec"], 300)
        self.assertEqual(data["gpu_required"], False)
        self.assertEqual(data["double_blind"], True)
        self.assertEqual(data["timezone"], "UTC")
        self.assertIn("id", data)

    def test_create_challenge_missing_title(self):
        payload = self._valid_payload()
        payload.pop("title")
        res = self.client.post(
            '/api/challenges',
            data=json.dumps(payload),
            content_type='application/json',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("title is required", res.get_json()["error"].lower())

    def test_create_challenge_missing_dates(self):
        payload = self._valid_payload()
        payload.pop("start_time")
        res = self.client.post(
            '/api/challenges',
            data=json.dumps(payload),
            content_type='application/json',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("start time and end time are required", res.get_json()["error"].lower())

    def test_create_challenge_end_before_start(self):
        payload = self._valid_payload()
        payload["start_time"] = (datetime.utcnow() + timedelta(hours=24)).isoformat()
        payload["end_time"] = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        res = self.client.post(
            '/api/challenges',
            data=json.dumps(payload),
            content_type='application/json',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("end time must be after start time", res.get_json()["error"].lower())

    def test_create_challenge_invalid_limits(self):
        payload = self._valid_payload()
        payload["max_eval_requests"] = 0
        res = self.client.post(
            '/api/challenges',
            data=json.dumps(payload),
            content_type='application/json',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("at least 1", res.get_json()["error"].lower())

    def test_create_challenge_ram_too_low(self):
        payload = self._valid_payload()
        payload["ram_limit_mb"] = 64
        res = self.client.post(
            '/api/challenges',
            data=json.dumps(payload),
            content_type='application/json',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("at least 128", res.get_json()["error"].lower())

    def test_create_challenge_competitor_forbidden(self):
        payload = self._valid_payload()
        res = self.client.post(
            '/api/challenges',
            data=json.dumps(payload),
            content_type='application/json',
            headers=self._auth(self.competitor_token)
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn("requires role", res.get_json()["error"].lower())


class TestUpdateChallenge(unittest.TestCase):
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

        self.admin = User(
            username="upd_admin",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            alias_id="Upd-Admin-001"
        )
        db.session.add(self.admin)

        self.competitor = User(
            username="upd_comp",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Upd-Comp-001"
        )
        db.session.add(self.competitor)

        self.challenge = Challenge(
            title="Original Title",
            description="Original description",
            max_eval_requests=5,
            ram_limit_mb=4096,
            time_limit_sec=300,
            gpu_required=True,
            start_time=datetime.utcnow() + timedelta(hours=1),
            end_time=datetime.utcnow() + timedelta(hours=24),
            double_blind=True,
            timezone="UTC"
        )
        db.session.add(self.challenge)
        db.session.commit()

        self.admin_token = generate_token(self.admin.id, self.admin.role)
        self.competitor_token = generate_token(self.competitor.id, self.competitor.role)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_update_challenge_title(self):
        res = self.client.put(
            f'/api/challenges/{self.challenge.id}',
            data=json.dumps({"title": "Updated Title"}),
            content_type='application/json',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["title"], "Updated Title")

    def test_update_challenge_description(self):
        res = self.client.put(
            f'/api/challenges/{self.challenge.id}',
            data=json.dumps({"description": "New description"}),
            content_type='application/json',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["description"], "New description")

    def test_update_challenge_max_eval_requests(self):
        res = self.client.put(
            f'/api/challenges/{self.challenge.id}',
            data=json.dumps({"max_eval_requests": 20}),
            content_type='application/json',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["max_eval_requests"], 20)

    def test_update_challenge_invalid_max_eval_requests(self):
        res = self.client.put(
            f'/api/challenges/{self.challenge.id}',
            data=json.dumps({"max_eval_requests": 0}),
            content_type='application/json',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("at least 1", res.get_json()["error"].lower())

    def test_update_challenge_invalid_ram(self):
        res = self.client.put(
            f'/api/challenges/{self.challenge.id}',
            data=json.dumps({"ram_limit_mb": 64}),
            content_type='application/json',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("at least 128", res.get_json()["error"].lower())

    def test_update_challenge_invalid_time_limit(self):
        res = self.client.put(
            f'/api/challenges/{self.challenge.id}',
            data=json.dumps({"time_limit_sec": 0}),
            content_type='application/json',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("at least 1", res.get_json()["error"].lower())

    def test_update_challenge_gpu_required(self):
        res = self.client.put(
            f'/api/challenges/{self.challenge.id}',
            data=json.dumps({"gpu_required": False}),
            content_type='application/json',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["gpu_required"], False)

    def test_update_challenge_dates_invalid_order(self):
        res = self.client.put(
            f'/api/challenges/{self.challenge.id}',
            data=json.dumps({
                "start_time": (datetime.utcnow() + timedelta(hours=10)).isoformat(),
                "end_time": (datetime.utcnow() + timedelta(hours=5)).isoformat()
            }),
            content_type='application/json',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("end time must be after start time", res.get_json()["error"].lower())

    def test_update_challenge_is_frozen_and_double_blind(self):
        res = self.client.put(
            f'/api/challenges/{self.challenge.id}',
            data=json.dumps({"is_frozen": True, "double_blind": False}),
            content_type='application/json',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["is_frozen"], True)
        self.assertEqual(data["double_blind"], False)

    def test_update_challenge_competitor_forbidden(self):
        res = self.client.put(
            f'/api/challenges/{self.challenge.id}',
            data=json.dumps({"title": "Hacked"}),
            content_type='application/json',
            headers=self._auth(self.competitor_token)
        )
        self.assertEqual(res.status_code, 403)

    def test_update_challenge_not_found(self):
        res = self.client.put(
            '/api/challenges/99999',
            data=json.dumps({"title": "Nope"}),
            content_type='application/json',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 404)


class TestArchiveChallenge(unittest.TestCase):
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

        self.admin = User(
            username="arch_admin",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            alias_id="Arch-Admin-001"
        )
        db.session.add(self.admin)

        self.competitor = User(
            username="arch_comp",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Arch-Comp-001"
        )
        db.session.add(self.competitor)

        self.challenge = Challenge(
            title="Archivable Challenge",
            description="To be archived",
            is_archived=False,
            start_time=datetime.utcnow() + timedelta(hours=1),
            end_time=datetime.utcnow() + timedelta(hours=24),
        )
        db.session.add(self.challenge)
        db.session.commit()

        self.admin_token = generate_token(self.admin.id, self.admin.role)
        self.competitor_token = generate_token(self.competitor.id, self.competitor.role)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_archive_challenge_toggle_on(self):
        self.assertFalse(self.challenge.is_archived)
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/archive',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("archived", data["message"].lower())
        self.assertTrue(data["challenge"]["is_archived"])

    def test_archive_challenge_toggle_off(self):
        self.challenge.is_archived = True
        db.session.commit()
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/archive',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("restored", data["message"].lower())
        self.assertFalse(data["challenge"]["is_archived"])

    def test_archive_challenge_competitor_forbidden(self):
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/archive',
            headers=self._auth(self.competitor_token)
        )
        self.assertEqual(res.status_code, 403)

    def test_archive_challenge_not_found(self):
        res = self.client.post(
            '/api/challenges/99999/archive',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 404)


class TestDeleteStage(unittest.TestCase):
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

        self.admin = User(
            username="stage_del_admin",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            alias_id="Stage-Del-Admin"
        )
        db.session.add(self.admin)

        self.competitor = User(
            username="stage_del_comp",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Stage-Del-Comp"
        )
        db.session.add(self.competitor)

        self.challenge = Challenge(
            title="Stage Delete Challenge",
            description="Has stages",
            start_time=datetime.utcnow() + timedelta(hours=1),
            end_time=datetime.utcnow() + timedelta(hours=24),
        )
        db.session.add(self.challenge)
        db.session.commit()

        self.stage = Stage(
            challenge_id=self.challenge.id,
            stage_number=1,
            title="Stage To Delete",
            start_time=datetime.utcnow() + timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=20),
        )
        db.session.add(self.stage)
        db.session.commit()

        self.admin_token = generate_token(self.admin.id, self.admin.role)
        self.competitor_token = generate_token(self.competitor.id, self.competitor.role)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_delete_stage_success(self):
        res = self.client.delete(
            f'/api/challenges/{self.challenge.id}/stages/{self.stage.id}',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("deleted", res.get_json()["message"].lower())

        deleted = db.session.get(Stage, self.stage.id)
        self.assertIsNone(deleted)

    def test_delete_stage_competitor_forbidden(self):
        res = self.client.delete(
            f'/api/challenges/{self.challenge.id}/stages/{self.stage.id}',
            headers=self._auth(self.competitor_token)
        )
        self.assertEqual(res.status_code, 403)

    def test_delete_stage_not_found(self):
        res = self.client.delete(
            f'/api/challenges/{self.challenge.id}/stages/99999',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 404)

    def test_delete_stage_challenge_not_found(self):
        res = self.client.delete(
            '/api/challenges/99999/stages/1',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 404)


class TestListChallenges(unittest.TestCase):
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

        self.admin = User(
            username="list_admin",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            alias_id="List-Admin"
        )
        db.session.add(self.admin)

        self.competitor = User(
            username="list_comp",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="List-Comp"
        )
        db.session.add(self.competitor)

        self.challenge1 = Challenge(
            title="Challenge Alpha",
            description="First challenge",
            start_time=datetime.utcnow() + timedelta(hours=1),
            end_time=datetime.utcnow() + timedelta(hours=24),
        )
        db.session.add(self.challenge1)

        self.challenge2 = Challenge(
            title="Challenge Beta",
            description="Second challenge",
            start_time=datetime.utcnow() + timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=48),
        )
        db.session.add(self.challenge2)
        db.session.commit()

        self.admin_token = generate_token(self.admin.id, self.admin.role)
        self.competitor_token = generate_token(self.competitor.id, self.competitor.role)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_list_challenges_admin_non_paginated(self):
        res = self.client.get(
            '/api/challenges',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 2)
        titles = [c["title"] for c in data]
        self.assertIn("Challenge Alpha", titles)
        self.assertIn("Challenge Beta", titles)

    def test_list_challenges_admin_paginated(self):
        res = self.client.get(
            '/api/challenges?page=1&per_page=1',
            headers=self._auth(self.admin_token)
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("items", data)
        self.assertIn("total", data)
        self.assertIn("page", data)
        self.assertIn("pages", data)
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["total"], 2)

    def test_list_challenges_competitor_not_registered(self):
        res = self.client.get(
            '/api/challenges',
            headers=self._auth(self.competitor_token)
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json(), [])


if __name__ == '__main__':
    unittest.main()
