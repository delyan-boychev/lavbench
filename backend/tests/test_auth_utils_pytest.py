import os
from datetime import datetime
from unittest.mock import patch

import pytest
from flask import Flask, request, jsonify

from auth_utils import (
    generate_token,
    verify_token,
    login_required,
    role_required,
    check_worker_auth,
    SECRET_KEY,
    rate_limit,
    revoke_token,
)
from models import db, User


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
            patch("auth_utils.datetime") as mock_dt,
        ):
            mock_dt.utcnow.return_value = datetime(2020, 1, 1, 12, 0, 0)
            token = generate_token(1, "competitor")
            mock_dt.utcnow.return_value = datetime(2020, 1, 3, 12, 0, 0)
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
        assert check_worker_auth(token) is True

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
        assert check_worker_auth(token) is False

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
        assert check_worker_auth(token) is False

    def test_check_worker_auth_missing_public_key(self):
        assert check_worker_auth("anything") is False

    def test_check_worker_auth_empty_token(self):
        assert check_worker_auth("") is False
        assert check_worker_auth(None) is False

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


class TestRateLimit:
    @pytest.fixture(autouse=True)
    def setup(self, redis_flush):
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.call_count = 0

    def test_allows_under_limit(self):
        @self.app.route("/test-rl1")
        @rate_limit(max_requests=5, window_seconds=60, per_user=False)
        def test_route():
            self.call_count += 1
            return jsonify({"ok": self.call_count})

        for _ in range(3):
            res = self.client.get("/test-rl1")
            assert res.status_code == 200
        assert self.call_count == 3

    def test_rejects_over_limit(self):
        @self.app.route("/test-rl2")
        @rate_limit(max_requests=2, window_seconds=60, per_user=False)
        def test_route():
            self.call_count += 1
            return jsonify({"ok": self.call_count})

        for _ in range(2):
            res = self.client.get("/test-rl2")
            assert res.status_code == 200
        res = self.client.get("/test-rl2")
        assert res.status_code == 429

    def test_per_user_keying(self):
        user1_calls = []
        user2_calls = []

        @self.app.route("/test-rl3")
        @login_required
        @rate_limit(max_requests=2, window_seconds=60, per_user=True)
        def test_route():
            uid = getattr(request, "user", {}).get("user_id", 0)
            if uid == 1:
                user1_calls.append(1)
            else:
                user2_calls.append(1)
            return jsonify({"ok": True})

        token1 = generate_token(1, "competitor")
        for _ in range(2):
            res = self.client.get("/test-rl3", headers={"Authorization": f"Bearer {token1}"})
            assert res.status_code == 200
        res = self.client.get("/test-rl3", headers={"Authorization": f"Bearer {token1}"})
        assert res.status_code == 429

        token2 = generate_token(2, "competitor")
        res = self.client.get("/test-rl3", headers={"Authorization": f"Bearer {token2}"})
        assert res.status_code == 200


class TestTokenRevocation:
    @pytest.fixture(autouse=True)
    def setup_env(self):
        os.environ["CELERY_BROKER_URL"] = "redis://localhost:6379/0"

    def test_revoke_then_reject(self):
        token = generate_token(42, "competitor")
        result = verify_token(token)
        assert result is not None

        revoke_token(token)
        result = verify_token(token)
        assert result is None

    def test_non_revoked_still_accepted(self):
        token = generate_token(99, "admin")
        result = verify_token(token)
        assert result is not None


class TestFetchCurrentRole:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, app_ctx):
        self.user = User(username="roletest", password_hash="x", role="jury")
        db.session.add(self.user)
        db.session.commit()

    def test_returns_current_role_from_db(self, client):
        from auth_utils import _fetch_current_role

        role = _fetch_current_role(self.user.id)
        assert role == "jury"

    def test_returns_none_for_missing_user(self, client):
        from auth_utils import _fetch_current_role

        role = _fetch_current_role(99999)
        assert role is None

    def test_role_update_reflected(self, client):
        from auth_utils import _fetch_current_role

        self.user.role = "admin"
        db.session.commit()
        role = _fetch_current_role(self.user.id)
        assert role == "admin"


class TestHealthEndpoint:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, app_ctx):
        pass

    def test_health_returns_200(self, client):
        res = client.get("/api/health")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "ok"
        assert data["checks"]["database"] == "connected"
