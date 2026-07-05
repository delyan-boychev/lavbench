import json
import uuid


class TestCsrfEndpoint:
    def test_generate_csrf_token_endpoint(self, client, db_session, redis_flush):
        res = client.get("/api/auth/csrf-token")
        assert res.status_code == 200
        data = res.get_json()
        assert "csrf_token" in data
        assert len(data["csrf_token"]) > 0

    def test_csrf_cookie_set(self, client, db_session, redis_flush):
        res = client.get("/api/auth/csrf-token")
        cookie = res.headers.get("Set-Cookie", "")
        assert "csrf_token=" in cookie
        assert "HttpOnly" not in cookie

    def test_csrf_token_is_uuid_hex(self, client, db_session, redis_flush):
        res = client.get("/api/auth/csrf-token")
        token = res.get_json()["csrf_token"]
        assert len(token) == 32
        int(token, 16)


class TestVerifyCsrfIntegration:
    def test_get_always_allows(
        self, client, db_session, redis_flush, sample_admin, auth_headers, tokens
    ):
        res = client.get("/api/auth/me", headers=auth_headers(tokens.admin))
        assert res.status_code == 200

    def test_bearer_token_bypasses_csrf_on_post(
        self, client, db_session, redis_flush, auth_headers, tokens
    ):
        payload = {
            "title": "CSRF Bypass Test",
            "description": "d",
            "max_eval_requests": 5,
            "start_time": "2026-01-01T00:00:00",
            "end_time": "2026-01-02T00:00:00",
            "timezone": "UTC",
        }
        res = client.post(
            "/api/challenges",
            data=json.dumps(payload),
            content_type="application/json",
            headers=auth_headers(tokens.admin),
        )
        assert res.status_code == 201


class TestCsrfFunctions:
    def test_generate_returns_response(self, app):
        with app.app_context():
            from auth_utils import generate_csrf_token

            resp = generate_csrf_token()
            assert resp.status_code == 200
            data = resp.get_json()
            assert "csrf_token" in data
            assert len(data["csrf_token"]) == 32

    def test_generate_sets_cookie(self, app):
        with app.app_context():
            from auth_utils import generate_csrf_token

            resp = generate_csrf_token()
            cookie = resp.headers.get("Set-Cookie", "")
            assert "csrf_token=" in cookie
            assert "HttpOnly" not in cookie

    def test_verify_get_safe_methods(self, app):
        from auth_utils import verify_csrf_token

        with app.app_context():
            with app.test_request_context(method="GET"):
                assert verify_csrf_token() is True
            with app.test_request_context(method="HEAD"):
                assert verify_csrf_token() is True
            with app.test_request_context(method="OPTIONS"):
                assert verify_csrf_token() is True

    def test_verify_no_token_no_cookie(self, app):
        from auth_utils import verify_csrf_token

        with app.app_context(), app.test_request_context(method="POST"):
            assert verify_csrf_token() is False

    def test_verify_matching_token(self, app):
        from auth_utils import verify_csrf_token

        token = uuid.uuid4().hex
        with (
            app.app_context(),
            app.test_request_context(
                method="POST",
                headers={"X-CSRF-Token": token},
                environ_overrides={"HTTP_COOKIE": f"csrf_token={token}"},
            ),
        ):
            assert verify_csrf_token() is True

    def test_verify_mismatched_token(self, app):
        from auth_utils import verify_csrf_token

        with (
            app.app_context(),
            app.test_request_context(
                method="POST",
                headers={"X-CSRF-Token": "header-token"},
                environ_overrides={"HTTP_COOKIE": "csrf_token=cookie-token"},
            ),
        ):
            assert verify_csrf_token() is False

    def test_verify_empty_header(self, app):
        from auth_utils import verify_csrf_token

        with (
            app.app_context(),
            app.test_request_context(
                method="POST",
                headers={"X-CSRF-Token": ""},
                environ_overrides={"HTTP_COOKIE": "csrf_token=some-token"},
            ),
        ):
            assert verify_csrf_token() is False

    def test_verify_bearer_bypasses(self, app):
        from auth_utils import verify_csrf_token

        with (
            app.app_context(),
            app.test_request_context(
                method="POST",
                headers={"Authorization": "Bearer some-jwt-token"},
            ),
        ):
            assert verify_csrf_token() is True

    def test_verify_worker_token_bypasses(self, app):
        from auth_utils import verify_csrf_token

        with (
            app.app_context(),
            app.test_request_context(
                method="POST",
                headers={"X-Worker-Token": "worker-token"},
            ),
        ):
            assert verify_csrf_token() is True

    def test_verify_no_cookie_only_header(self, app):
        from auth_utils import verify_csrf_token

        with (
            app.app_context(),
            app.test_request_context(
                method="POST",
                headers={"X-CSRF-Token": "some-token"},
            ),
        ):
            assert verify_csrf_token() is False

    def test_verify_no_header_only_cookie(self, app):
        from auth_utils import verify_csrf_token

        with (
            app.app_context(),
            app.test_request_context(
                method="POST",
                headers={},
                environ_overrides={"HTTP_COOKIE": "csrf_token=some-token"},
            ),
        ):
            assert verify_csrf_token() is False


class TestCsrfDecorator:
    def test_csrf_required_decorator_rejects_missing(self, app):
        from flask import jsonify

        from auth_utils import csrf_required

        @csrf_required
        def fake_view():
            return jsonify({"ok" if False else "error": "should not reach"}), 200

        with app.app_context(), app.test_request_context(method="POST"):
            resp = fake_view()
            assert resp[1] == 403
            data = resp[0].get_json()
            assert data.get("code") == "ERR_CSRF_FAILED"

    def test_csrf_required_decorator_allows_valid(self, app):
        from flask import jsonify

        from auth_utils import csrf_required

        @csrf_required
        def fake_view():
            return jsonify({"ok": True})

        token = uuid.uuid4().hex
        with (
            app.app_context(),
            app.test_request_context(
                method="POST",
                headers={"X-CSRF-Token": token},
                environ_overrides={"HTTP_COOKIE": f"csrf_token={token}"},
            ),
        ):
            resp = fake_view()
            assert resp.status_code == 200
            assert resp.get_json()["ok"] is True

    def test_csrf_required_get_always_passes(self, app):
        from flask import jsonify

        from auth_utils import csrf_required

        @csrf_required
        def fake_view():
            return jsonify({"ok": True})

        with app.app_context(), app.test_request_context(method="GET"):
            resp = fake_view()
            assert resp.status_code == 200
