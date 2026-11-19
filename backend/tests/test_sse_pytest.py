"""Tests for utils/sse.py: session release, retry/idle jitter and signal-only streams."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import utils.sse as sse
from config import Config
from models import Submission, db
from services.submission_status import COMPLETED, RUNNING, transition
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

    def test_on_close_runs_even_when_the_generator_never_started(self, app):
        started, closed = [], []

        def generator():
            started.append(True)
            yield "data: {}\n\n"

        with app.test_request_context():
            body, _status, _headers = sse.sse_response(generator, on_close=lambda: closed.append(1))
        body.close()
        assert not started
        assert closed == [1]


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

    def test_without_broker_sends_only_keep_alives_until_the_idle_timeout(self, app_ctx):
        with (
            patch("utils.sse_utils.get_coordination_client", return_value=None),
            patch("utils.sse.get_sse_client", return_value=None),
            patch.object(sse, "SSE_KEEPALIVE_SECONDS", 0.01),
            patch.object(sse, "jittered_idle_timeout", return_value=0.1),
        ):
            chunks = list(sse.signal_stream("backup_status", user_id="u1")())
        events = _events(chunks)
        # An update signal per interval would make every client refetch in a loop
        assert {"event": "update"} not in events
        assert chunks.count(": keep-alive\n\n") >= 2
        assert events == [{"info": "connected"}, {"event": "timeout"}]


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


class TestSubmissionLogReplayGap:
    """The stream subscribes before reading the replay and always closes its pub/sub."""

    @pytest.fixture
    def running(self, db_session, sample_challenge, sample_task, sample_competitor):
        sub = Submission(
            user_id=sample_competitor.id,
            challenge_id=sample_challenge.id,
            task_id=sample_task.id,
            status="running",
        )
        db_session.add(sub)
        db_session.commit()
        return sub

    @staticmethod
    def _open(client, fredis, sub, headers):
        """Run the view; the test client has pulled only the first chunk (the retry field)."""
        with patch("routes.submissions.get_redis_client", return_value=fredis):
            return client.get(
                f"/api/submissions/{sub.id}/logs/live", headers=headers, buffered=False
            )

    @staticmethod
    def _read(res):
        try:
            return [c.decode() for c in res.response]
        finally:
            res.close()

    def test_line_published_before_the_replay_is_streamed_is_delivered(
        self, client, fredis, tokens, auth_headers, running
    ):
        from utils.sse_utils import publish_submission_log_batch, publish_submission_status

        fredis.rpush(f"submission:{running.id}:logs", "replayed line")
        res = self._open(client, fredis, running, auth_headers(tokens.competitor))
        assert res.status_code == 200
        # The view returned (subscribed, replay read); the worker publishes before the
        # client consumes the replay, which used to subscribe only after it
        publish_submission_log_batch(running.id, ["late line"])
        publish_submission_status(running.id, "completed")
        events = _events(self._read(res))

        assert [e["log"] for e in events if "log" in e] == ["replayed line", "late line"]
        assert events[-1] == {"status": "completed"}
        assert len(fredis.pubsubs) == 1
        assert fredis.pubsubs[0].closed

    def test_pubsub_is_closed_when_the_client_stops_reading(
        self, client, fredis, tokens, auth_headers, running
    ):
        res = self._open(client, fredis, running, auth_headers(tokens.competitor))
        assert len(fredis.pubsubs) == 1
        assert not fredis.pubsubs[0].closed
        res.close()
        assert fredis.pubsubs[0].closed

    def test_finished_submission_never_subscribes(
        self, client, fredis, tokens, auth_headers, running, db_session
    ):
        assert transition(running.id, COMPLETED, from_statuses=(RUNNING,))
        db_session.commit()
        events = _events(
            self._read(self._open(client, fredis, running, auth_headers(tokens.admin)))
        )
        assert events[-1] == {"status": "completed"}
        assert fredis.pubsubs == []

    @pytest.mark.parametrize("ending", ["timeout", "evicted", "error"])
    def test_pubsub_is_closed_on_every_exit_path(
        self, client, fredis, tokens, auth_headers, running, ending
    ):
        patches = {
            "timeout": patch("routes.submissions.jittered_idle_timeout", return_value=0),
            "evicted": patch("routes.submissions.sse_heartbeat", return_value=False),
            "error": patch(
                "tests.helpers.sse_test_utils._FakePubSub.get_message",
                side_effect=ConnectionError("broker gone"),
            ),
        }
        res = self._open(client, fredis, running, auth_headers(tokens.competitor))
        with patches[ending]:
            events = _events(self._read(res))

        expected_last = {
            "timeout": {"event": "timeout"},
            "evicted": {"event": "evicted"},
        }
        if ending in expected_last:
            assert events[-1] == expected_last[ending]
        assert len(fredis.pubsubs) == 1
        assert fredis.pubsubs[0].closed
