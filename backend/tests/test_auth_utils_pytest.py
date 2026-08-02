from datetime import datetime
from unittest.mock import patch

import pytest
from flask import Flask, jsonify, request

from auth_utils import (
    SECRET_KEY,
    check_worker_auth,
    generate_token,
    login_required,
    rate_limit,
    role_required,
    verify_token,
)


class TestAuthUtils:
    def test_generate_token_returns_valid_jwt(self):
        token = generate_token(42, "competitor")
        assert token is not None
        assert len(token) > 20

    def test_verify_token_returns_user_data(self):
        token = generate_token(42, "competitor")
        result = verify_token(token)
        assert result is not None
        assert result["user_id"] == "42"
        assert result["role"] == "competitor"

    def test_verify_token_returns_none_for_empty_token(self):
        assert verify_token("") is None
        assert verify_token(None) is None

    def test_verify_token_handles_bearer_prefix(self):
        token = generate_token(42, "admin")
        result = verify_token(f"Bearer {token}")
        assert result is not None
        assert result["user_id"] == "42"
        assert result["role"] == "admin"

    def test_verify_token_returns_none_for_expired_token(self):
        with (
            patch("auth_utils.SECRET_KEY", SECRET_KEY),
            patch("auth_utils.utcnow") as mock_utcnow,
        ):
            mock_utcnow.return_value = datetime(2020, 1, 1, 12, 0, 0)
            token = generate_token(1, "competitor")
            mock_utcnow.return_value = datetime(2020, 1, 3, 12, 0, 0)
            result = verify_token(token)
            assert result is None

    def test_verify_token_returns_none_for_malformed_token(self):
        assert verify_token("not-a-valid-token!!!") is None

    def test_verify_token_returns_none_for_tampered_token(self):
        token = generate_token(42, "competitor")
        tampered = token[: len(token) // 2] + "AAAA" + token[len(token) // 2 + 4 :]
        assert verify_token(tampered) is None

    def test_check_worker_auth_valid_signature(self, monkeypatch):
        import base64
        import time

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        k = Ed25519PrivateKey.generate()
        monkeypatch.setenv(
            "WORKER_PUBLIC_KEY",
            base64.b64encode(k.public_key().public_bytes_raw()).decode(),
        )
        nonce = f"100:{int(time.time())}"
        sig = base64.b64encode(k.sign(nonce.encode())).decode()
        token = f"{nonce}.{sig}"
        result = check_worker_auth(token)
        assert result is not None
        assert result["submission_id"] == "100"

    def test_check_worker_auth_wrong_signature(self, monkeypatch):
        import base64
        import time

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        k = Ed25519PrivateKey.generate()
        monkeypatch.setenv(
            "WORKER_PUBLIC_KEY",
            base64.b64encode(k.public_key().public_bytes_raw()).decode(),
        )
        nonce = f"100:{int(time.time())}"
        sig = base64.b64encode(b"wrong" * 8).decode()
        token = f"{nonce}.{sig}"
        assert check_worker_auth(token) is None

    def test_check_worker_auth_expired_nonce(self, monkeypatch):
        import base64
        import time

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        k = Ed25519PrivateKey.generate()
        monkeypatch.setenv(
            "WORKER_PUBLIC_KEY",
            base64.b64encode(k.public_key().public_bytes_raw()).decode(),
        )
        old_ts = int(time.time()) - 600
        nonce = f"100:{old_ts}"
        sig = base64.b64encode(k.sign(nonce.encode())).decode()
        token = f"{nonce}.{sig}"
        assert check_worker_auth(token) is None

    def test_check_worker_auth_missing_public_key(self):
        assert check_worker_auth("anything") is None

    def test_check_worker_auth_empty_token(self):
        assert check_worker_auth("") is None
        assert check_worker_auth(None) is None

    def test_login_required_blocks_unauthenticated(self):
        app = Flask(__name__)
        app.config["TESTING"] = True

        @app.route("/test")
        @login_required
        def test_route():
            return jsonify({"ok": True})

        client = app.test_client()
        res = client.get("/test")
        assert res.status_code == 401

    def test_login_required_allows_valid_token(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        token = generate_token(42, "competitor")

        @app.route("/test")
        @login_required
        def test_route():
            return jsonify({"user_id": request.user["user_id"]})

        client = app.test_client()
        res = client.get("/test", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["user_id"] == "42"

    def test_role_required_blocks_wrong_role(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        token = generate_token(42, "competitor")

        @app.route("/admin-only")
        @role_required(["admin"])
        def admin_route():
            return jsonify({"ok": True})

        client = app.test_client()
        res = client.get("/admin-only", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 403

    def test_role_required_allows_correct_role(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        token = generate_token(42, "admin")

        @app.route("/admin-only")
        @role_required(["admin"])
        def admin_route():
            return jsonify({"ok": True})

        client = app.test_client()
        res = client.get("/admin-only", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200


class TestAuthTokenURLQuery:
    def test_login_required_rejects_url_query_param(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        token = generate_token(42, "competitor")

        @app.route("/test")
        @login_required
        def test_route():
            return jsonify({"user_id": request.user["user_id"]})

        client = app.test_client()
        res = client.get(f"/test?token={token}")
        assert res.status_code == 401

    def test_role_required_rejects_url_query_param(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        token = generate_token(42, "admin")

        @app.route("/test")
        @role_required(["admin"])
        def test_route():
            return jsonify({"user_id": request.user["user_id"], "role": request.user["role"]})

        client = app.test_client()
        res = client.get(f"/test?token={token}")
        assert res.status_code in (401, 403)


# Create a simple container object to share tracking state cleanly across closures
class MockCallTracker:
    def __init__(self):
        self.rl1_calls = []
        self.rl2_calls = []
        self.user1_calls = []
        self.user2_calls = []
        self.identity_calls = []


mock_tracker = MockCallTracker()


@pytest.mark.xdist_group(name="rate_limiting")
class TestRateLimit:
    @pytest.fixture
    def unique_ip(self):
        import uuid

        return f"10.99.{uuid.uuid4().hex[:8]}"

    @pytest.fixture(scope="function")
    def rate_limit_client(self):
        """Create a fresh Flask app with rate-limited routes for each test."""
        from flask import Flask, jsonify, request

        from auth_utils import login_required

        app = Flask(__name__)
        app.config["TESTING"] = True

        @app.route("/test-rl1")
        @rate_limit(max_requests=5, window_seconds=60, per_user=False)
        def test_route_1():
            mock_tracker.rl1_calls.append(1)
            return jsonify({"ok": len(mock_tracker.rl1_calls)})

        @app.route("/test-rl2")
        @rate_limit(max_requests=2, window_seconds=60, per_user=False)
        def test_route_2():
            mock_tracker.rl2_calls.append(1)
            return jsonify({"ok": len(mock_tracker.rl2_calls)})

        @app.route("/test-rl3")
        @login_required
        @rate_limit(max_requests=2, window_seconds=60, per_user=True)
        def test_route_3():
            uid = getattr(request, "user", {}).get("user_id", 0)
            if uid == 1:
                mock_tracker.user1_calls.append(1)
            else:
                mock_tracker.user2_calls.append(1)
            return jsonify({"ok": True})

        def _header_identity():
            return request.headers.get("X-Test-Identity", "default")

        @app.route("/test-rl-identity")
        @rate_limit(max_requests=2, window_seconds=60, per_user=False, identity=_header_identity)
        def test_route_identity():
            mock_tracker.identity_calls.append(1)
            return jsonify({"ok": len(mock_tracker.identity_calls)})

        return app.test_client()

    # Added db_session here so SQLAlchemy creates the tables for the @login_required check
    # Keys are unique per test, so no global rate:* flush is needed (avoids races
    # between xdist workers sharing the same Redis).
    @pytest.fixture(autouse=True)
    def setup_method_state(self, db_session):
        # Reset the static tracker attributes before every test
        mock_tracker.rl1_calls = []
        mock_tracker.rl2_calls = []
        mock_tracker.user1_calls = []
        mock_tracker.user2_calls = []
        mock_tracker.identity_calls = []

    def test_allows_under_limit(self, rate_limit_client, unique_ip):
        for _ in range(3):
            res = rate_limit_client.get("/test-rl1", environ_base={"REMOTE_ADDR": unique_ip})
            assert res.status_code == 200
        assert len(mock_tracker.rl1_calls) == 3

    def test_rejects_over_limit(self, rate_limit_client, unique_ip):
        for _ in range(2):
            res = rate_limit_client.get("/test-rl2", environ_base={"REMOTE_ADDR": unique_ip})
            assert res.status_code == 200
        res = rate_limit_client.get("/test-rl2", environ_base={"REMOTE_ADDR": unique_ip})
        assert res.status_code == 429

    def test_per_user_keying(self, rate_limit_client):
        import uuid

        token1 = generate_token(uuid.uuid4().hex, "competitor")
        for _ in range(2):
            res = rate_limit_client.get("/test-rl3", headers={"Authorization": f"Bearer {token1}"})
            assert res.status_code == 200
        res = rate_limit_client.get("/test-rl3", headers={"Authorization": f"Bearer {token1}"})
        assert res.status_code == 429

        token2 = generate_token(uuid.uuid4().hex, "competitor")
        res = rate_limit_client.get("/test-rl3", headers={"Authorization": f"Bearer {token2}"})
        assert res.status_code == 200

    def test_identity_keyed_limiting(self, rate_limit_client):
        import uuid

        headers = {"X-Test-Identity": f"ident-{uuid.uuid4().hex[:8]}"}
        for _ in range(2):
            res = rate_limit_client.get("/test-rl-identity", headers=headers)
            assert res.status_code == 200
        res = rate_limit_client.get("/test-rl-identity", headers=headers)
        assert res.status_code == 429

    def test_identity_different_values_independent(self, rate_limit_client):
        import uuid

        ident_a = f"ident-a-{uuid.uuid4().hex[:8]}"
        ident_b = f"ident-b-{uuid.uuid4().hex[:8]}"
        for _ in range(2):
            res = rate_limit_client.get("/test-rl-identity", headers={"X-Test-Identity": ident_a})
            assert res.status_code == 200
        for _ in range(2):
            res = rate_limit_client.get("/test-rl-identity", headers={"X-Test-Identity": ident_b})
            assert res.status_code == 200

    def test_identity_key_format_in_redis(self, rate_limit_client):
        import uuid

        ident = f"ident-key-check-{uuid.uuid4().hex[:8]}"
        res = rate_limit_client.get("/test-rl-identity", headers={"X-Test-Identity": ident})
        assert res.status_code == 200

        from cache_utils import get_redis_client

        r = get_redis_client()
        if not r:
            pytest.skip("Redis unavailable")
        keys = [k.decode() if isinstance(k, bytes) else k for k in r.scan_iter("rate:*")]
        assert any(f"rate:{ident}:test_route_identity" in k for k in keys)
