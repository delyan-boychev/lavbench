"""Tests for utils/sse.py: session release, retry/idle jitter and signal-only streams."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import utils.sse as sse
from config import Config
from models import Submission, db
from tests.helpers.sse_test_utils import fake_redis


def _events(chunks: list[str]) -> list[dict]:
    return [json.loads(c[len("data: ") :]) for c in chunks if c.startswith("data: ")]


@pytest.fixture
def fredis():
    client = fake_redis()
    with (
        patch("utils.sse_utils.get_coordination_client", return_value=client),
        patch("utils.sse_utils.get_redis_client", return_value=client),
        patch("utils.sse.get_sse_client", return_value=client),
    ):
        yield client


class TestJitter:
    def test_retry_field_is_jittered_within_30_percent(self):
        values = set()
        for _ in range(50):
            field = sse.sse_retry_field()
            assert field.startswith("retry: ") and field.endswith("\n\n")
            value = int(field.split()[1])
            assert 0.7 * Config.SSE_RETRY_MS <= value <= 1.3 * Config.SSE_RETRY_MS
            values.add(value)
        assert len(values) > 1

    def test_idle_timeout_is_jittered_within_30_percent(self):
        values = {sse.jittered_idle_timeout() for _ in range(50)}
        assert all(
            0.7 * Config.SSE_IDLE_TIMEOUT <= v <= 1.3 * Config.SSE_IDLE_TIMEOUT for v in values
        )
        assert len(values) > 1


class TestSseResponse:
    def test_releases_the_db_session_before_streaming(self, app):
        started = []

        def generator():
            started.append(True)
            yield "data: {}\n\n"

        with app.test_request_context(), patch.object(db.session, "remove") as remove:
            _body, status, headers = sse.sse_response(generator)
        remove.assert_called_once_with()
        assert status == 200
        assert headers["Content-Type"] == "text/event-stream"
        assert headers["X-Accel-Buffering"] == "no"
        assert not started, "the generator must not run before the response is returned"


class TestSignalStream:
    def test_forwards_only_update_signals_and_folds_bursts(self, fredis, app_ctx):
        payload = json.dumps({"leaderboard": [{"user": "secret"}]}).encode()
        fredis.pending_messages = [{"data": payload}, {"data": payload}, {"data": payload}]
        with patch.object(sse, "jittered_idle_timeout", return_value=0.05):
            chunks = list(sse.signal_stream("leaderboard_1", user_id="u1")())

        assert chunks[0].startswith("retry: ")
        events = _events(chunks)
        assert events[0] == {"info": "connected"}
        assert events.count({"event": "update"}) == 1
        assert events[-1] == {"event": "timeout"}
        assert all(set(e) <= {"info", "event"} for e in events)
        assert "secret" not in "".join(chunks)
        assert ": keep-alive\n\n" in chunks
        assert fredis.subscriptions == ["leaderboard_1"]

    def test_never_touches_the_database(self, fredis, app_ctx):
        fredis.pending_messages = [{"data": b"x"}]
        with (
            patch.object(sse, "jittered_idle_timeout", return_value=0.05),
            patch.object(db.session, "execute", side_effect=AssertionError("DB used")),
            patch.object(db.session, "get", side_effect=AssertionError("DB used")),
        ):
            chunks = list(sse.signal_stream("queue_updates", user_id="u1")())
        assert {"event": "update"} in _events(chunks)

    def test_without_broker_degrades_to_periodic_signals(self, app_ctx):
        with (
            patch("utils.sse_utils.get_coordination_client", return_value=None),
            patch("utils.sse.get_sse_client", return_value=None),
            patch.object(sse, "SSE_KEEPALIVE_SECONDS", 0.01),
            patch.object(sse, "jittered_idle_timeout", return_value=0.1),
        ):
            chunks = list(sse.signal_stream("backup_status", user_id="u1")())
        events = _events(chunks)
        assert {"event": "update"} in events
        assert events[-1] == {"event": "timeout"}


class TestSignalOnlyRoutes:
    def _first_chunks(self, client, path, headers, count=2):
        res = client.get(path, headers=headers, buffered=False)
        try:
            assert res.status_code == 200
            assert res.mimetype == "text/event-stream"
            it = iter(res.response)
            return [next(it).decode() for _ in range(count)]
        finally:
            res.close()

    @pytest.mark.parametrize(
        "path",
        ["/api/admin/backups/live", "/api/admin/submissions/queue/live"],
    )
    def test_admin_streams_start_with_retry_and_connected(
        self, client, fredis, tokens, auth_headers, path
    ):
        chunks = self._first_chunks(client, path, auth_headers(tokens.admin))
        assert chunks[0].startswith("retry: ")
        assert json.loads(chunks[1][len("data: ") :]) == {"info": "connected"}

    def test_leaderboard_stream_releases_session_and_sends_no_payload(
        self, client, fredis, tokens, auth_headers, sample_challenge
    ):
        with patch.object(db.session, "remove", wraps=db.session.remove) as remove:
            chunks = self._first_chunks(
                client,
                f"/api/challenges/{sample_challenge.id}/leaderboard/live",
                auth_headers(tokens.competitor),
            )
        assert remove.called
        assert json.loads(chunks[1][len("data: ") :]) == {"info": "connected"}


class TestSubmissionLogStream:
    def _running_submission(self, db_session, sample_challenge, sample_task, sample_competitor):
        sub = Submission(
            user_id=sample_competitor.id,
            challenge_id=sample_challenge.id,
            task_id=sample_task.id,
            status="running",
        )
        db_session.add(sub)
        db_session.commit()
        return sub

    def test_streams_logs_and_final_status_without_db_queries(
        self,
        client,
        fredis,
        tokens,
        auth_headers,
        db_session,
        sample_challenge,
        sample_task,
        sample_competitor,
    ):
        sub = self._running_submission(db_session, sample_challenge, sample_task, sample_competitor)
        fredis.rpush(f"submission:{sub.id}:logs", "replayed line")
        fredis.pending_messages = [
            {"data": json.dumps({"logs": ["live 1", "live 2"]}).encode()},
            {"data": json.dumps({"status": "completed"}).encode()},
        ]
        with patch("routes.submissions.get_redis_client", return_value=fredis):
            res = client.get(
                f"/api/submissions/{sub.id}/logs/live",
                headers=auth_headers(tokens.competitor),
                buffered=False,
            )
        try:
            assert res.status_code == 200
            with (
                patch.object(db.session, "get", side_effect=AssertionError("DB used")),
                patch.object(db.session, "execute", side_effect=AssertionError("DB used")),
            ):
                chunks = [c.decode() for c in res.response]
        finally:
            res.close()

        assert chunks[0].startswith("retry: ")
        events = _events(chunks)
        assert events[0] == {"info": "connected"}
        logs = [e["log"] for e in events if "log" in e]
        assert logs == ["replayed line", "live 1", "live 2"]
        assert events[-1] == {"status": "completed"}

    def test_stored_final_status_ends_a_stream_that_missed_the_publish(
        self,
        client,
        fredis,
        tokens,
        auth_headers,
        db_session,
        sample_challenge,
        sample_task,
        sample_competitor,
    ):
        sub = self._running_submission(db_session, sample_challenge, sample_task, sample_competitor)
        fredis.set(f"submission:{sub.id}:status", "failed")
        with patch("routes.submissions.get_redis_client", return_value=fredis):
            res = client.get(
                f"/api/submissions/{sub.id}/logs/live",
                headers=auth_headers(tokens.competitor),
                buffered=False,
            )
        try:
            chunks = [c.decode() for c in res.response]
        finally:
            res.close()
        assert _events(chunks)[-1] == {"status": "failed"}
