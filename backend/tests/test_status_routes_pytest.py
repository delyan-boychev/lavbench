"""Tests for GET /api/status and GET /api/admin/system-status (heartbeat-based status)."""

from __future__ import annotations

import json
import time
from datetime import timedelta
from unittest.mock import patch

import pytest

from config import Config
from models import Submission
from services import status_service
from services.status_service import (
    STATUS_CACHE_KEY,
    STATUS_LAST_KEY,
    scoring_status,
    worst_status,
)
from utils.auth_utils import generate_token
from utils.cache_utils import delete_cached, get_coordination_client, get_redis_client
from utils.dates import utcnow


class FakeBroker:
    """Broker Redis double holding ``worker_spec:*`` heartbeats."""

    def __init__(self, specs: dict[str, dict] | None = None, healthy: bool = True) -> None:
        self.specs = {name: {**spec, "name": name} for name, spec in (specs or {}).items()}
        self.healthy = healthy

    def ping(self) -> bool:
        if not self.healthy:
            raise ConnectionError("broker down")
        return True

    def scan_iter(self, match: str | None = None, count: int | None = None):
        return [f"worker_spec:{name}".encode() for name in self.specs]

    def get(self, key):
        name = key.decode().removeprefix("worker_spec:")
        spec = self.specs.get(name)
        return json.dumps(spec) if spec is not None else None


def _spec(queues: list[str], age_seconds: float = 0, kind: str = "CPU") -> dict:
    return {
        "type": kind,
        "queues": queues,
        "last_seen": time.time() - age_seconds,
        "concurrency": 2,
        "cpu_cores": 8,
        "ram_gb": 16.0,
        "gpu_type": "N/A",
        "vram_gb": "N/A",
    }


@pytest.fixture
def status_env(db_session, redis_flush):
    """Patch the broker and queue depths; returns a mutable environment."""
    env = {"broker": FakeBroker(), "depths": {}}

    def _broker():
        return env["broker"]

    def _depths(names) -> dict[str, int]:
        return {name: env["depths"].get(name, 0) for name in names}

    delete_cached(STATUS_CACHE_KEY)
    delete_cached(STATUS_LAST_KEY)
    with (
        patch.object(status_service, "get_coordination_client", _broker),
        patch.object(status_service, "get_queue_depths", _depths),
    ):
        yield env
    delete_cached(STATUS_CACHE_KEY)
    delete_cached(STATUS_LAST_KEY)
    broker = get_coordination_client()
    if broker is not None:
        broker.delete("lock:status:system")


def _cache_redis():
    r = get_redis_client()
    if r is None:
        pytest.skip("Redis unavailable")
    return r


def _hold_status_lock() -> None:
    """Hold the compute lock as another process would."""
    r = get_coordination_client()
    if r is None:
        pytest.skip("Redis unavailable")
    r.set("lock:status:system", "another-process", ex=30)


def _queued_submission(db_session, sample_challenge, sample_task, sample_competitor, age):
    sub = Submission(
        user_id=sample_competitor.id,
        challenge_id=sample_challenge.id,
        task_id=sample_task.id,
        status="queued",
        created_at=utcnow() - age,
    )
    db_session.add(sub)
    db_session.commit()
    return sub


class TestScoringRules:
    def test_no_cpu_consumer_is_major_outage(self):
        queues = [
            {"name": "cpu_queue", "consumers": 0, "queued": 0},
            {"name": "gpu_queue", "consumers": 1, "queued": 0},
        ]
        assert scoring_status(queues, None) == "major_outage"

    def test_other_queue_with_backlog_and_no_consumer_is_partial_outage(self):
        queues = [
            {"name": "cpu_queue", "consumers": 1, "queued": 0},
            {"name": "gpu_queue", "consumers": 0, "queued": 3},
        ]
        assert scoring_status(queues, None) == "partial_outage"

    def test_other_queue_without_backlog_is_fine(self):
        queues = [
            {"name": "cpu_queue", "consumers": 1, "queued": 0},
            {"name": "gpu_queue", "consumers": 0, "queued": 0},
        ]
        assert scoring_status(queues, None) == "operational"

    def test_old_queued_submission_is_degraded(self):
        queues = [
            {"name": "cpu_queue", "consumers": 1, "queued": 4},
            {"name": "gpu_queue", "consumers": 0, "queued": 0},
        ]
        too_old = Config.STATUS_QUEUE_DEGRADED_SECONDS + 1
        assert scoring_status(queues, too_old) == "degraded_performance"
        assert scoring_status(queues, Config.STATUS_QUEUE_DEGRADED_SECONDS) == "operational"

    def test_worst_status_follows_statusword_order(self):
        assert worst_status("operational", "degraded_performance") == "degraded_performance"
        assert worst_status("partial_outage", "major_outage") == "major_outage"
        assert worst_status("operational", "operational") == "operational"


class TestPublicStatus:
    def test_needs_no_auth_and_reports_operational(self, client, status_env):
        status_env["broker"] = FakeBroker({"cpu@w1": _spec(["cpu_queue"])})
        res = client.get("/api/status")
        assert res.status_code == 200
        body = res.get_json()
        assert body["status"] == "operational"
        assert body["components"] == {"api": "operational", "scoring": "operational"}
        assert body["updated_at"].endswith("Z")
        assert set(body) == {"status", "components", "updated_at"}

    def test_stale_heartbeat_means_no_consumer(self, client, status_env):
        stale = Config.WORKER_HEARTBEAT_STALE_SECONDS + 5
        status_env["broker"] = FakeBroker({"cpu@w1": _spec(["cpu_queue"], age_seconds=stale)})
        body = client.get("/api/status").get_json()
        assert body["components"]["scoring"] == "major_outage"
        assert body["status"] == "major_outage"

    def test_broker_down_is_major_outage_for_api_and_scoring(self, client, status_env):
        status_env["broker"] = FakeBroker({"cpu@w1": _spec(["cpu_queue"])}, healthy=False)
        body = client.get("/api/status").get_json()
        assert body["components"] == {"api": "major_outage", "scoring": "major_outage"}

    def test_database_down_is_api_major_outage(self, client, status_env):
        status_env["broker"] = FakeBroker({"cpu@w1": _spec(["cpu_queue"])})
        with patch.object(status_service, "_database_ok", return_value=False):
            body = client.get("/api/status").get_json()
        assert body["components"]["api"] == "major_outage"
        assert body["components"]["scoring"] == "operational"
        assert body["status"] == "major_outage"

    def test_gpu_backlog_without_consumer_is_partial_outage(self, client, status_env):
        status_env["broker"] = FakeBroker({"cpu@w1": _spec(["cpu_queue"])})
        status_env["depths"] = {"gpu_queue": 2}
        body = client.get("/api/status").get_json()
        assert body["components"]["scoring"] == "partial_outage"
        assert body["status"] == "partial_outage"

    def test_old_queued_submission_is_degraded(
        self, client, status_env, db_session, sample_challenge, sample_task, sample_competitor
    ):
        status_env["broker"] = FakeBroker({"cpu@w1": _spec(["cpu_queue"])})
        age = timedelta(seconds=Config.STATUS_QUEUE_DEGRADED_SECONDS + 60)
        _queued_submission(db_session, sample_challenge, sample_task, sample_competitor, age)
        body = client.get("/api/status").get_json()
        assert body["components"]["scoring"] == "degraded_performance"
        assert body["status"] == "degraded_performance"

    def test_result_is_cached_for_status_cache_seconds(self, client, status_env):
        status_env["broker"] = FakeBroker({"cpu@w1": _spec(["cpu_queue"])})
        first = client.get("/api/status").get_json()
        assert first["status"] == "operational"

        status_env["broker"] = FakeBroker({})
        assert client.get("/api/status").get_json() == first

        delete_cached(STATUS_CACHE_KEY)
        assert client.get("/api/status").get_json()["status"] == "major_outage"

    def test_cache_uses_status_cache_seconds(self, status_env):
        r = _cache_redis()
        status_service.system_status()
        assert 0 < r.ttl(STATUS_CACHE_KEY) <= Config.STATUS_CACHE_SECONDS
        # The previous snapshot outlives the fresh one, so lock losers can still answer
        assert r.ttl(STATUS_LAST_KEY) > Config.STATUS_CACHE_SECONDS


class TestStatusSingleFlight:
    """Only one process computes a snapshot; the others never stampede the database."""

    def test_lock_miss_serves_the_previous_snapshot(self, client, status_env):
        status_env["broker"] = FakeBroker({"cpu@w1": _spec(["cpu_queue"])})
        previous = client.get("/api/status").get_json()
        assert previous["status"] == "operational"

        # The fresh snapshot expired and another process is computing the next one
        delete_cached(STATUS_CACHE_KEY)
        _hold_status_lock()
        status_env["broker"] = FakeBroker({})
        with patch.object(
            status_service, "compute_system_status", side_effect=AssertionError("computed")
        ):
            assert client.get("/api/status").get_json() == previous

    def test_lock_miss_without_a_previous_snapshot_computes_anyway(self, client, status_env):
        status_env["broker"] = FakeBroker({"cpu@w1": _spec(["cpu_queue"])})
        _hold_status_lock()
        res = client.get("/api/status")
        assert res.status_code == 200
        assert res.get_json()["status"] == "operational"

    def test_lock_holder_uses_a_snapshot_stored_after_its_miss(self, status_env):
        stored = {"status": "operational", "stored": True}
        reads = iter([None, stored])
        with (
            patch.object(status_service, "get_cached", side_effect=lambda _key: next(reads)),
            patch.object(
                status_service, "compute_system_status", side_effect=AssertionError("computed")
            ),
        ):
            assert status_service.system_status() == stored

    def test_admin_system_status_shares_the_single_flight(
        self, client, status_env, tokens, auth_headers
    ):
        status_env["broker"] = FakeBroker({"cpu@w1": _spec(["cpu_queue"])})
        first = client.get("/api/admin/system-status", headers=auth_headers(tokens.admin))
        delete_cached(STATUS_CACHE_KEY)
        _hold_status_lock()
        with patch.object(
            status_service, "compute_system_status", side_effect=AssertionError("computed")
        ):
            again = client.get("/api/admin/system-status", headers=auth_headers(tokens.admin))
        assert again.get_json() == first.get_json()


class TestSystemStatus:
    def test_requires_login(self, client, status_env):
        assert client.get("/api/admin/system-status").status_code == 401

    def test_competitor_is_forbidden(self, client, status_env, tokens, auth_headers):
        res = client.get("/api/admin/system-status", headers=auth_headers(tokens.competitor))
        assert res.status_code == 403

    def test_jury_is_allowed(self, client, status_env, create_user, auth_headers):
        jury = create_user(username="status_jury", role="jury")
        token = generate_token(jury.id, "jury")
        res = client.get("/api/admin/system-status", headers=auth_headers(token))
        assert res.status_code == 200

    def test_admin_gets_queues_workers_and_counts(
        self,
        client,
        status_env,
        tokens,
        auth_headers,
        db_session,
        sample_challenge,
        sample_task,
        sample_competitor,
    ):
        stale = Config.WORKER_HEARTBEAT_STALE_SECONDS + 30
        status_env["broker"] = FakeBroker(
            {
                "cpu@w1": _spec(["cpu_queue"]),
                "cpu@w2": _spec(["cpu_queue"], age_seconds=stale),
                "internal@srv": _spec(["celery", "internal"]),
            }
        )
        status_env["depths"] = {"cpu_queue": 5}
        _queued_submission(
            db_session, sample_challenge, sample_task, sample_competitor, timedelta(seconds=90)
        )
        for status in ("running", "completed", "failed", "failed"):
            db_session.add(
                Submission(
                    user_id=sample_competitor.id,
                    challenge_id=sample_challenge.id,
                    task_id=sample_task.id,
                    status=status,
                    created_at=utcnow() - timedelta(minutes=2),
                )
            )
        db_session.add(
            Submission(
                user_id=sample_competitor.id,
                challenge_id=sample_challenge.id,
                task_id=sample_task.id,
                status="completed",
                created_at=utcnow() - timedelta(hours=2),
            )
        )
        db_session.commit()

        res = client.get("/api/admin/system-status", headers=auth_headers(tokens.admin))
        assert res.status_code == 200
        body = res.get_json()

        assert body["status"] == "operational"
        queues = {q["name"]: q for q in body["queues"]}
        assert [q["name"] for q in body["queues"]][:2] == ["cpu_queue", "gpu_queue"]
        assert queues["cpu_queue"] == {"name": "cpu_queue", "consumers": 1, "queued": 5}
        assert queues["gpu_queue"]["consumers"] == 0
        assert {"celery", "internal"} <= set(queues)

        workers = {w["name"]: w for w in body["workers"]}
        assert set(workers) == {"cpu@w1", "cpu@w2", "internal@srv"}
        assert workers["cpu@w1"]["online"] is True
        assert workers["cpu@w2"]["online"] is False
        assert workers["cpu@w1"]["type"] == "cpu"
        assert workers["cpu@w1"]["last_seen"].endswith("Z")
        assert workers["cpu@w1"]["gpu_type"] is None
        assert workers["cpu@w1"]["vram_gb"] is None

        counts = body["submissions"]
        assert counts["queued"] == 1
        assert counts["running"] == 1
        assert 80 <= counts["oldest_queued_seconds"] <= 200
        assert counts["completed_last_15m"] == 1
        assert counts["failed_last_15m"] == 2
        assert body["updated_at"].endswith("Z")

    def test_never_calls_celery_inspect(self, client, status_env, tokens, auth_headers):
        with patch("tasks.celery.control.inspect") as inspect:
            client.get("/api/admin/system-status", headers=auth_headers(tokens.admin))
        inspect.assert_not_called()
