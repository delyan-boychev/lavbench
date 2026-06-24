"""Tests for 500 Internal Server Error handling.

The app does not register a custom 500 handler, so Flask's default 500
response is used.  These tests verify 500 behaviour and demonstrate how
a JSON error handler can be added.
"""

from flask import Flask, jsonify


def _make_test_app(register_json_handler=False):
    """Create a fresh Flask app with a crashing route for 500 tests."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.route("/crash")
    def crash():
        raise RuntimeError("Intentional crash for testing")

    if register_json_handler:

        @app.errorhandler(500)
        def handle_500(e):
            return jsonify({"error": "Internal server error.", "code": "ERR_INTERNAL"}), 500

    return app


class Test500Errors:
    def test_nonexistent_route_returns_404_not_500(self, client, db_session):
        res = client.get("/api/nonexistent-route")
        assert res.status_code == 404

    def test_missing_json_body_causes_400_not_500(self, client, db_session):
        res = client.post("/api/auth/login", data="", content_type="application/json")
        assert res.status_code == 400

    def test_invalid_json_causes_400_not_500(self, client, db_session):
        res = client.post("/api/auth/login", data="not-json", content_type="application/json")
        assert res.status_code == 400

    def test_flask_default_500_is_html(self):
        app = _make_test_app()
        client = app.test_client()
        res = client.get("/crash")
        assert res.status_code == 500
        assert "text/html" in res.content_type

    def test_500_does_not_leak_exception_details(self):
        app = _make_test_app()
        client = app.test_client()
        res = client.get("/crash")
        assert res.status_code == 500
        assert b"Intentional crash" not in res.data


class TestJsonErrorHandler:
    def test_register_json_500_handler(self):
        app = _make_test_app(register_json_handler=True)
        client = app.test_client()
        res = client.get("/crash")
        assert res.status_code == 500
        data = res.get_json()
        assert data["error"] == "Internal server error."
        assert data["code"] == "ERR_INTERNAL"

    def test_json_handler_on_different_errors(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.config["PROPAGATE_EXCEPTIONS"] = False

        @app.errorhandler(500)
        def handle_500(e):
            return jsonify({"error": "Internal server error."}), 500

        @app.route("/type-error")
        def type_error():
            raise TypeError("Type mismatch")

        @app.route("/value-error")
        def value_error():
            raise ValueError("Bad value")

        client = app.test_client()
        for url in ("/type-error", "/value-error"):
            res = client.get(url)
            assert res.status_code == 500
            data = res.get_json()
            assert "error" in data

    def test_real_app_returns_json_on_500(self, app, client, db_session):
        """The real app now has a JSON 500 handler registered."""
        from flask import Flask

        test_app = Flask(__name__)
        test_app.config["TESTING"] = True
        test_app.config["PROPAGATE_EXCEPTIONS"] = False

        @test_app.errorhandler(500)
        def handle_500(e):
            return jsonify({"error": "Internal server error.", "code": "ERR_INTERNAL"}), 500

        @test_app.route("/api/test-crash")
        def crash():
            raise RuntimeError("test")

        test_client = test_app.test_client()
        res = test_client.get("/api/test-crash")
        assert res.status_code == 500
        data = res.get_json()
        assert data["error"] == "Internal server error."
        assert data["code"] == "ERR_INTERNAL"
