"""Tests for the /api/health endpoint probes (database, redis, disk)."""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestHealthEndpoint:
    @staticmethod
    def _healthy_redis():
        client = MagicMock()
        client.ping.return_value = True
        client.info.side_effect = lambda section: {
            "persistence": {
                "loading": 0,
                "aof_enabled": 1,
                "aof_last_write_status": "ok",
            },
            "memory": {"used_memory": 50, "maxmemory": 100},
        }[section]
        return client

    def test_health_ok_when_all_probes_pass(self, client, db_session):
        fake_redis = self._healthy_redis()
        with (
            patch("utils.cache_utils.get_redis_client", return_value=fake_redis),
            patch("utils.cache_utils.get_coordination_client", return_value=fake_redis),
        ):
            resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"
        assert body["checks"]["database"] == "ok"
        assert body["checks"]["redis_cache"] == "ok"
        assert body["checks"]["redis_broker"] == "ok"
        assert body["checks"]["disk"] == "ok"

    def test_health_degraded_when_cache_redis_down(self, client, db_session):
        with (
            patch("utils.cache_utils.get_redis_client", return_value=None),
            patch("utils.cache_utils.get_coordination_client", return_value=self._healthy_redis()),
        ):
            resp = client.get("/api/health")
        assert resp.status_code == 503
        body = resp.get_json()
        assert body["status"] == "degraded"
        assert body["checks"]["database"] == "ok"
        assert body["checks"]["redis_cache"] == "degraded"
        assert body["checks"]["redis_broker"] == "ok"

    def test_health_degraded_when_broker_redis_down(self, client, db_session):
        with (
            patch("utils.cache_utils.get_redis_client", return_value=self._healthy_redis()),
            patch("utils.cache_utils.get_coordination_client", return_value=None),
        ):
            resp = client.get("/api/health")
        assert resp.status_code == 503
        body = resp.get_json()
        assert body["checks"]["redis_cache"] == "ok"
        assert body["checks"]["redis_broker"] == "degraded"

    def test_health_degraded_when_redis_memory_is_nearly_full(self, client, db_session):
        full_redis = self._healthy_redis()
        full_redis.info.side_effect = lambda section: {
            "persistence": {
                "loading": 0,
                "aof_enabled": 1,
                "aof_last_write_status": "ok",
            },
            "memory": {"used_memory": 95, "maxmemory": 100},
        }[section]
        with (
            patch("utils.cache_utils.get_redis_client", return_value=full_redis),
            patch("utils.cache_utils.get_coordination_client", return_value=self._healthy_redis()),
        ):
            resp = client.get("/api/health")
        assert resp.status_code == 503
        assert resp.get_json()["checks"]["redis_cache"] == "degraded"

    def test_health_degraded_when_database_down(self, client, db_session):
        fake_redis = self._healthy_redis()
        with (
            patch("utils.cache_utils.get_redis_client", return_value=fake_redis),
            patch("utils.cache_utils.get_coordination_client", return_value=fake_redis),
            patch("app.db.session.execute", side_effect=Exception("db unavailable")),
        ):
            resp = client.get("/api/health")
        assert resp.status_code == 503
        body = resp.get_json()
        assert body["checks"]["database"] == "degraded"
