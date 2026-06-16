import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ["SECRET_KEY"] = "test-secret-key-for-unit-tests-do-not-use-in-production"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from auth_utils import generate_token, verify_token, login_required, role_required, generate_worker_token, verify_worker_token, SECRET_KEY, rate_limit, revoke_token, is_token_revoked
from flask import Flask, request, jsonify

class TestAuthUtils(unittest.TestCase):
    def test_generate_token_returns_valid_jwt(self):
        token = generate_token(42, 'competitor')
        self.assertIsNotNone(token)
        self.assertTrue(len(token) > 20)

    def test_verify_token_returns_user_data(self):
        token = generate_token(42, 'competitor')
        result = verify_token(token)
        self.assertIsNotNone(result)
        self.assertEqual(result['user_id'], 42)
        self.assertEqual(result['role'], 'competitor')

    def test_verify_token_returns_none_for_empty_token(self):
        self.assertIsNone(verify_token(''))
        self.assertIsNone(verify_token(None))

    def test_verify_token_handles_bearer_prefix(self):
        token = generate_token(42, 'admin')
        result = verify_token(f'Bearer {token}')
        self.assertIsNotNone(result)
        self.assertEqual(result['user_id'], 42)
        self.assertEqual(result['role'], 'admin')

    def test_verify_token_returns_none_for_expired_token(self):
        with patch('auth_utils.SECRET_KEY', SECRET_KEY), \
             patch('auth_utils.datetime') as mock_dt:
            mock_dt.utcnow.return_value = datetime(2020, 1, 1, 12, 0, 0)
            token = generate_token(1, 'competitor')
            mock_dt.utcnow.return_value = datetime(2020, 1, 3, 12, 0, 0)
            result = verify_token(token)
            self.assertIsNone(result)

    def test_verify_token_returns_none_for_malformed_token(self):
        self.assertIsNone(verify_token('not-a-valid-token!!!'))

    def test_verify_token_returns_none_for_tampered_token(self):
        token = generate_token(42, 'competitor')
        # Corrupt the payload section to invalidate the signature
        tampered = token[:len(token)//2] + 'AAAA' + token[len(token)//2 + 4:]
        self.assertIsNone(verify_token(tampered))

    def test_generate_worker_token_has_correct_claims(self):
        token = generate_worker_token(100, 200, 600)
        result = verify_worker_token(token, submission_id=100, task_id=200)
        self.assertTrue(result)

    def test_verify_worker_token_rejects_wrong_submission_id(self):
        token = generate_worker_token(100, 200, 600)
        result = verify_worker_token(token, submission_id=999, task_id=200)
        self.assertFalse(result)

    def test_verify_worker_token_rejects_wrong_task_id(self):
        token = generate_worker_token(100, 200, 600)
        result = verify_worker_token(token, submission_id=100, task_id=999)
        self.assertFalse(result)

    def test_verify_worker_token_rejects_empty_token(self):
        self.assertFalse(verify_worker_token(''))
        self.assertFalse(verify_worker_token(None))

    def test_verify_worker_token_rejects_non_worker_token(self):
        token = generate_token(42, 'competitor')
        result = verify_worker_token(token, submission_id=42, task_id=100)
        self.assertFalse(result)

    def test_login_required_blocks_unauthenticated(self):
        app = Flask(__name__)
        app.config['TESTING'] = True

        @app.route('/test')
        @login_required
        def test_route():
            return jsonify({"ok": True})

        client = app.test_client()
        res = client.get('/test')
        self.assertEqual(res.status_code, 401)

    def test_login_required_allows_valid_token(self):
        app = Flask(__name__)
        app.config['TESTING'] = True
        token = generate_token(42, 'competitor')

        @app.route('/test')
        @login_required
        def test_route():
            return jsonify({"user_id": request.user['user_id']})

        client = app.test_client()
        res = client.get('/test', headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['user_id'], 42)

    def test_role_required_blocks_wrong_role(self):
        app = Flask(__name__)
        app.config['TESTING'] = True
        token = generate_token(42, 'competitor')

        @app.route('/admin-only')
        @role_required(['admin'])
        def admin_route():
            return jsonify({"ok": True})

        client = app.test_client()
        res = client.get('/admin-only', headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(res.status_code, 403)

    def test_role_required_allows_correct_role(self):
        app = Flask(__name__)
        app.config['TESTING'] = True
        token = generate_token(42, 'admin')

        @app.route('/admin-only')
        @role_required(['admin'])
        def admin_route():
            return jsonify({"ok": True})

        client = app.test_client()
        res = client.get('/admin-only', headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(res.status_code, 200)


class TestAuthTokenURLQuery(unittest.TestCase):
    def test_login_required_accepts_url_query_param_for_sse(self):
        """Query param tokens are supported for SSE EventSource compatibility."""
        app = Flask(__name__)
        app.config['TESTING'] = True
        token = generate_token(42, 'competitor')

        @app.route('/test')
        @login_required
        def test_route():
            return jsonify({"user_id": request.user['user_id']})

        client = app.test_client()
        res = client.get(f'/test?token={token}')
        self.assertEqual(res.status_code, 200,
                         "Token in URL query params should be accepted for SSE compatibility")
        data = res.get_json()
        self.assertEqual(data['user_id'], 42)

    def test_role_required_accepts_url_query_param_for_sse(self):
        """Query param tokens are supported for SSE EventSource compatibility."""
        app = Flask(__name__)
        app.config['TESTING'] = True
        token = generate_token(42, 'admin')

        @app.route('/test')
        @role_required(['admin'])
        def test_route():
            return jsonify({"user_id": request.user['user_id'], "role": request.user['role']})

        client = app.test_client()
        res = client.get(f'/test?token={token}')
        self.assertEqual(res.status_code, 200,
                         "Token in URL query params should be accepted for SSE compatibility")
        data = res.get_json()
        self.assertEqual(data['user_id'], 42)


class TestRateLimit(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.call_count = 0
        # Clear any stale rate limit keys
        try:
            from cache_utils import get_redis_client
            r = get_redis_client()
            if r:
                for key in r.scan_iter("rate:*"):
                    r.delete(key)
        except Exception:
            pass

    def test_allows_under_limit(self):
        @self.app.route('/test-rl1')
        @rate_limit(max_requests=5, window_seconds=60, per_user=False)
        def test_route():
            self.call_count += 1
            return jsonify({"ok": self.call_count})

        for _ in range(3):
            res = self.client.get('/test-rl1')
            self.assertEqual(res.status_code, 200)
        self.assertEqual(self.call_count, 3)

    def test_rejects_over_limit(self):
        @self.app.route('/test-rl2')
        @rate_limit(max_requests=2, window_seconds=60, per_user=False)
        def test_route():
            self.call_count += 1
            return jsonify({"ok": self.call_count})

        for _ in range(2):
            res = self.client.get('/test-rl2')
            self.assertEqual(res.status_code, 200)
        res = self.client.get('/test-rl2')
        self.assertEqual(res.status_code, 429)

    def test_per_user_keying(self):
        user1_calls = []
        user2_calls = []

        @self.app.route('/test-rl3')
        @login_required
        @rate_limit(max_requests=2, window_seconds=60, per_user=True)
        def test_route():
            uid = getattr(request, 'user', {}).get('user_id', 0)
            if uid == 1:
                user1_calls.append(1)
            else:
                user2_calls.append(1)
            return jsonify({"ok": True})

        # User 1 uses 2 slots
        token1 = generate_token(1, 'competitor')
        for _ in range(2):
            res = self.client.get('/test-rl3', headers={'Authorization': f'Bearer {token1}'})
            self.assertEqual(res.status_code, 200)
        res = self.client.get('/test-rl3', headers={'Authorization': f'Bearer {token1}'})
        self.assertEqual(res.status_code, 429)

        token2 = generate_token(2, 'competitor')
        res = self.client.get('/test-rl3', headers={'Authorization': f'Bearer {token2}'})
        self.assertEqual(res.status_code, 200)


class TestTokenRevocation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["CELERY_BROKER_URL"] = "redis://localhost:6379/0"

    def test_revoke_then_reject(self):
        token = generate_token(42, 'competitor')
        result = verify_token(token)
        self.assertIsNotNone(result)

        revoke_token(token)
        result = verify_token(token)
        self.assertIsNone(result)

    def test_non_revoked_still_accepted(self):
        token = generate_token(99, 'admin')
        result = verify_token(token)
        self.assertIsNotNone(result)

    def test_is_token_revoked_true(self):
        token = generate_token(50, 'competitor')
        self.assertFalse(is_token_revoked(token))
        revoke_token(token)
        self.assertTrue(is_token_revoked(token))


class TestFetchCurrentRole(unittest.TestCase):
    def setUp(self):
        from app import create_app
        from models import db, User
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.user = User(username='roletest', password_hash='x', role='jury')
        db.session.add(self.user)
        db.session.commit()

    def tearDown(self):
        from models import db
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_returns_current_role_from_db(self):
        from auth_utils import _fetch_current_role
        role = _fetch_current_role(self.user.id)
        self.assertEqual(role, 'jury')

    def test_returns_none_for_missing_user(self):
        from auth_utils import _fetch_current_role
        role = _fetch_current_role(99999)
        self.assertIsNone(role)

    def test_role_update_reflected(self):
        from auth_utils import _fetch_current_role
        from models import db
        self.user.role = 'admin'
        db.session.commit()
        role = _fetch_current_role(self.user.id)
        self.assertEqual(role, 'admin')


class TestHealthEndpoint(unittest.TestCase):
    def setUp(self):
        from app import create_app
        from models import db
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

    def tearDown(self):
        from models import db
        db.drop_all()
        self.ctx.pop()

    def test_health_returns_200(self):
        res = self.client.get('/api/health')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['database'], 'connected')


if __name__ == '__main__':
    unittest.main()
