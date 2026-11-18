"""Tests for the settings that keep the server up under load: pools, fail-closed checks,
worker rate keys, the leaderboard response path and the server and proxy configuration."""

import base64
import json
import os
import re
import subprocess
from unittest.mock import MagicMock, patch

import pytest
import redis
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from flask import Flask, jsonify

from config import Config
from utils import cache_utils

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _read(*parts):
    with open(os.path.join(REPO, *parts)) as handle:
        return handle.read()


class TestRedisPools:
    def test_pools_wait_for_a_free_connection_instead_of_raising(self, monkeypatch):
        monkeypatch.setattr(cache_utils, "_pools", {})
        monkeypatch.setattr(cache_utils, "_pools_pid", None)
        pool = cache_utils._get_pool("redis://localhost:6390/0")
        assert isinstance(pool, redis.BlockingConnectionPool)
        assert pool.max_connections == Config.REDIS_POOL_MAX_CONNECTIONS
        assert pool.timeout == Config.REDIS_POOL_TIMEOUT_SECONDS

    def test_the_sse_pool_waits_too(self, monkeypatch):
        monkeypatch.setattr(cache_utils, "_sse_pools", {})
        monkeypatch.setattr(cache_utils, "_sse_pools_pid", None)
        pool = cache_utils._get_sse_pool("redis://localhost:6390/0")
        assert isinstance(pool, redis.BlockingConnectionPool)
        assert pool.max_connections >= Config.SSE_MAX_GLOBAL

    def test_an_exhausted_pool_waits_then_raises_a_connection_error(self):
        pool = redis.BlockingConnectionPool.from_url(
            "redis://localhost:6390/0", max_connections=1, timeout=0.2
        )
        held = pool.get_connection()
        try:
            with pytest.raises(redis.ConnectionError):
                redis.Redis(connection_pool=pool).ping()
        finally:
            pool.release(held)
            pool.disconnect()

    def test_a_strict_lock_tells_an_error_from_a_held_lock(self, monkeypatch, redis_flush):
        broken = MagicMock()
        broken.set.side_effect = redis.ConnectionError("No connection available.")
        monkeypatch.setattr(cache_utils, "get_coordination_client", lambda: broken)
        with (
            pytest.raises(cache_utils.LockUnavailableError),
            cache_utils.cache_lock("k", strict=True),
        ):
            pass
        with cache_utils.cache_lock("k") as got:
            assert got is False


class TestFailClosedChecks:
    """Revocation and rate limits refuse with 503 instead of letting requests through."""

    def test_a_revocation_redis_cannot_check_answers_503(
        self, client, auth_headers, tokens, monkeypatch
    ):
        broken = MagicMock()
        broken.exists.side_effect = redis.ConnectionError("No connection available.")
        monkeypatch.setattr("utils.cache_utils.get_coordination_client", lambda: broken)
        response = client.get("/api/auth/me", headers=auth_headers(tokens.competitor))
        assert response.status_code == 503
        assert response.get_json()["code"] == "ERR_AUTH_UNAVAILABLE"
        assert response.headers["Retry-After"] == "5"

    def test_a_revocation_without_redis_answers_503(
        self, client, auth_headers, tokens, monkeypatch
    ):
        monkeypatch.setattr("utils.cache_utils.get_coordination_client", lambda: None)
        response = client.get("/api/auth/me", headers=auth_headers(tokens.competitor))
        assert response.status_code == 503

    @pytest.mark.parametrize("broker", [None, "error"])
    def test_a_rate_limit_redis_cannot_count_answers_503(self, monkeypatch, broker):
        from utils.auth_utils import rate_limit

        if broker == "error":
            broker = MagicMock()
            broker.eval.side_effect = redis.ConnectionError("No connection available.")
        monkeypatch.setattr("utils.cache_utils.get_coordination_client", lambda: broker)
        app = Flask(__name__)
        calls = []

        @app.route("/limited")
        @rate_limit(max_requests=5, window_seconds=60, per_user=False)
        def limited():
            calls.append(1)
            return jsonify({"ok": True})

        response = app.test_client().get("/limited")
        assert response.status_code == 503
        assert response.get_json()["code"] == "ERR_SERVICE_BUSY"
        assert response.headers["Retry-After"] == "5"
        assert calls == []


class TestWorkerRateLimitKey:
    @pytest.fixture
    def worker(self, monkeypatch):
        keys = {}
        for worker_id in ("host-a", "host-b"):
            key = Ed25519PrivateKey.generate()
            keys[worker_id] = (
                base64.urlsafe_b64encode(key.private_bytes_raw()).decode(),
                base64.urlsafe_b64encode(key.public_key().public_bytes_raw()).decode(),
            )
        monkeypatch.setenv(
            "WORKER_PUBLIC_KEYS_JSON", json.dumps({wid: pair[1] for wid, pair in keys.items()})
        )

        def token(worker_id):
            from utils.worker_auth import sign_worker_token

            monkeypatch.setenv("WORKER_ID", worker_id)
            monkeypatch.setenv("WORKER_PRIVATE_KEY", keys[worker_id][0])
            return sign_worker_token()

        return token

    def _identity(self, app, headers):
        from routes.tasks import _worker_token_identity

        with app.test_request_context(
            "/api/worker/report/x", headers=headers, environ_base={"REMOTE_ADDR": "10.0.0.7"}
        ):
            return _worker_token_identity()

    def test_workers_behind_one_address_get_separate_limits(self, app, worker):
        assert self._identity(app, {"X-Worker-Token": worker("host-a")}) == "worker:host-a"
        assert self._identity(app, {"X-Worker-Token": worker("host-b")}) == "worker:host-b"

    def test_the_key_never_consumes_the_tokens_nonce(self, app, worker):
        from utils.worker_auth import check_worker_auth

        token = worker("host-a")
        assert self._identity(app, {"X-Worker-Token": token}) == "worker:host-a"
        assert check_worker_auth(token) is not None

    def test_an_unsigned_or_forged_token_falls_back_to_the_address(self, app, worker):
        forged = worker("host-a").rsplit(".", 1)[0] + ".AAAA"
        assert self._identity(app, {"X-Worker-Token": forged}) == "10.0.0.7"
        assert self._identity(app, {}) == "10.0.0.7"


class TestLeaderboardResponse:
    def test_the_route_returns_a_model_so_spectree_skips_its_walk(
        self, client, auth_headers, tokens, sample_task, db_session
    ):
        from spectree.plugins import base

        walked = []
        original = base.is_partial_base_model_instance

        def counting(value):
            walked.append(1)
            return original(value)

        with patch.object(base, "is_partial_base_model_instance", counting):
            response = client.get(
                f"/api/challenges/{sample_task.challenge_id}/leaderboard",
                headers=auth_headers(tokens.admin),
            )
        assert response.status_code == 200
        assert walked == []
        body = response.get_json()
        assert set(body) >= {"challenge_id", "tasks", "leaderboard", "metric_name"}
        assert body["tasks"][0]["id"] == str(sample_task.id)
        assert response.headers["Cache-Control"].startswith("no-store")


class TestServerAndProxySettings:
    @pytest.mark.skipif(os.geteuid() == 0, reason="as root the entrypoint changes /app")
    def test_gunicorn_workers_come_from_the_environment(self, tmp_path):
        env = {**os.environ, "GUNICORN_WORKERS": "6"}
        script = os.path.join(REPO, "backend", "entrypoint.sh")
        out = subprocess.run(  # noqa: S603
            ["sh", script, "echo", "gunicorn"],  # noqa: S607
            env=env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert re.search(r"--workers 6\b", out)

        env["GUNICORN_WORKERS"] = "four"
        refused = subprocess.run(  # noqa: S603
            ["sh", script, "echo", "gunicorn"],  # noqa: S607
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert refused.returncode == 1
        assert "GUNICORN_WORKERS must be a positive integer" in refused.stderr

    def test_the_image_leaves_the_worker_count_to_the_entrypoint(self):
        dockerfile = _read("backend", "Dockerfile")
        assert '"-w"' not in dockerfile
        assert '"--keep-alive", "75"' in dockerfile

    def test_compose_sizes_workers_and_caps_from_settings(self):
        compose = _read("docker-compose.yml")
        assert "GUNICORN_WORKERS=${GUNICORN_WORKERS:-${BACKEND_CPUS:-4}}" in compose
        assert "cpu_quota: ${DB_CPUS:-2}00000" in compose
        assert "mem_limit: ${DB_MEMORY:-2g}" in compose
        assert "cpu_quota: ${FRONTEND_CPUS:-1}00000" in compose
        long_worker = compose.split("celery_worker_long:", 1)[1].split("\n\n", 1)[0]
        assert "-Q internal_long" in long_worker
        assert "<<: *internal-worker" in long_worker
        short_worker = compose.split("  celery_worker:", 1)[1].split("\n\n", 1)[0]
        assert "-Q celery,internal " in short_worker

    def test_nginx_buffers_api_responses_and_keeps_upstream_connections(self):
        site = _read("frontend", "nginx.conf")
        assert re.search(r"upstream backend_api \{[^}]*keepalive 64;", site)
        api = site.split("location /api {", 1)[1]
        assert "proxy_buffering on;" in api
        assert "proxy_buffering off;" not in site
        assert "proxy_max_temp_file_size 0;" in api
        assert "backend:5001;" not in api
        # SSE streams opt out of buffering per response
        sse = _read("backend", "utils", "sse.py")
        assert '"X-Accel-Buffering": "no"' in sse
        assert "proxy_buffering on;" in _read("frontend", "ssl.conf.disabled")

    def test_nginx_raises_its_descriptor_and_connection_limits(self):
        main = _read("frontend", "nginx.main.conf")
        assert "worker_rlimit_nofile 65536;" in main
        assert re.search(r"worker_connections\s+8192;", main)
        assert "COPY nginx.main.conf /etc/nginx/nginx.conf" in _read("frontend", "Dockerfile")
