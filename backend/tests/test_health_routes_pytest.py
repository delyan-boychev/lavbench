"""Tests for the /api/health endpoint probes (database, redis, disk)."""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestHealthEndpoint:
    def test_health_ok_when_all_probes_pass(self, client, db_session):
        fake_redis = MagicMock()
        fake_redis.ping.return_value = True
        with patch("cache_utils.get_redis_client", return_value=fake_redis):
            resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"
        assert body["checks"]["database"] == "ok"
        assert body["checks"]["redis"] == "ok"
        assert body["checks"]["disk"] == "ok"

    def test_health_degraded_when_redis_down(self, client, db_session):
        with patch("cache_utils.get_redis_client", return_value=None):
            resp = client.get("/api/health")
        assert resp.status_code == 503
        body = resp.get_json()
        assert body["status"] == "degraded"
        assert body["checks"]["database"] == "ok"
        assert body["checks"]["redis"] == "degraded"

    def test_health_degraded_when_database_down(self, client, db_session):
        fake_redis = MagicMock()
        fake_redis.ping.return_value = True
        with (
            patch("cache_utils.get_redis_client", return_value=fake_redis),
            patch("app.db.session.execute", side_effect=Exception("db unavailable")),
        ):
            resp = client.get("/api/health")
        assert resp.status_code == 503
        body = resp.get_json()
        assert body["checks"]["database"] == "degraded"
