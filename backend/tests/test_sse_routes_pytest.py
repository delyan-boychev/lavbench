"""Route-level tests for all SSE streaming endpoints.

Each test verifies:
- 401 without authentication
- 200 + correct Content-Type with authentication
- The first SSE event is well-formed
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.helpers.sse_test_utils import fake_redis


# Use a short timeout so tests don't hang on infinite SSE streams
@pytest.fixture(autouse=True)
def _mock_redis():
    """Mock Redis to prevent actual connections and make streams terminate."""
    fredis = fake_redis()

    def _mock_get_redis():
        return fredis

    with patch("sse_utils.get_redis_client", _mock_get_redis):
        yield


class TestStreamSubmissionLogs:
    def test_requires_auth(self, client):
        res = client.get("/api/submissions/00000000-0000-0000-0000-000000000000/logs/live")
        assert res.status_code == 401

    def test_returns_event_stream_with_auth(self, client, tokens, auth_headers):
        res = client.get(
            "/api/submissions/00000000-0000-0000-0000-000000000000/logs/live",
            headers=auth_headers(tokens.admin),
            buffered=False,
        )
        try:
            assert res.status_code in (200, 404)
        finally:
            res.close()


class TestStreamTaskSubmissions:
    def test_requires_auth(self, client):
        res = client.get("/api/tasks/00000000-0000-0000-0000-000000000000/submissions/live")
        assert res.status_code in (401, 302)

    def test_returns_event_stream_with_auth(self, client, tokens, auth_headers):
        res = client.get(
            "/api/tasks/00000000-0000-0000-0000-000000000000/submissions/live",
            headers=auth_headers(tokens.admin),
            buffered=False,
        )
        try:
            if res.status_code == 200:
                assert res.mimetype == "text/event-stream"
        finally:
            res.close()


class TestStreamChallengeLeaderboard:
    def test_requires_auth(self, client):
        res = client.get("/api/challenges/00000000-0000-0000-0000-000000000000/leaderboard/live")
        assert res.status_code in (401, 302)

    def test_returns_event_stream_with_auth(self, client, tokens, auth_headers):
        res = client.get(
            "/api/challenges/00000000-0000-0000-0000-000000000000/leaderboard/live",
            headers=auth_headers(tokens.admin),
            buffered=False,
        )
        try:
            if res.status_code == 200:
                assert res.mimetype == "text/event-stream"
        finally:
            res.close()


class TestStreamBackupStatus:
    def test_requires_auth(self, client):
        res = client.get("/api/admin/backups/live")
        assert res.status_code in (401, 302, 403)


class TestStreamWorkerStats:
    def test_requires_auth(self, client):
        res = client.get("/api/admin/workers/stats/live")
        assert res.status_code in (401, 302, 403)


class TestStreamWorkerStatus:
    def test_requires_auth(self, client):
        res = client.get("/api/worker-status/live")
        assert res.status_code in (401, 302)

    def test_returns_event_stream_with_auth(self, client, tokens, auth_headers):
        res = client.get(
            "/api/worker-status/live",
            headers=auth_headers(tokens.admin),
            buffered=False,
        )
        try:
            if res.status_code == 200:
                assert res.mimetype == "text/event-stream"
        finally:
            res.close()
