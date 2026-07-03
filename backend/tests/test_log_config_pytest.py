"""Tests for log_config.py — setup_logging, RemoteShipHandler, POST /api/workers/logs."""

import base64
import gzip
import json
import logging
import os
import sys
import tempfile
import time as _time
from unittest.mock import patch

import pytest
from concurrent_log_handler import ConcurrentRotatingFileHandler

# ── helpers ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _save_root_handlers():
    """Save/restore root logger handlers so setup_logging tests don't conflict."""
    root = logging.getLogger()
    saved = root.handlers[:]
    yield
    root.handlers = saved


# ── setup_logging ─────────────────────────────────────────────────────────


class TestSetupLogging:
    def test_creates_log_dir(self):
        root = logging.getLogger()
        root.handlers.clear()
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = os.path.join(tmp, "subdir")
            assert not os.path.isdir(log_dir)
            from log_config import setup_logging

            setup_logging("test", log_dir=log_dir)
            assert os.path.isdir(log_dir)

    def test_idempotent(self):
        root = logging.getLogger()
        root.handlers.clear()
        with tempfile.TemporaryDirectory() as tmp:
            from log_config import setup_logging

            root1 = setup_logging("test", log_dir=tmp)
            n_handlers = len(root1.handlers)
            root2 = setup_logging("test", log_dir=tmp)
            assert root2 is root1
            assert len(root2.handlers) == n_handlers

    def test_handlers_present(self):
        root = logging.getLogger()
        root.handlers.clear()
        with tempfile.TemporaryDirectory() as tmp:
            from log_config import setup_logging

            root = setup_logging("test", log_dir=tmp)
            handler_types = [type(h).__name__ for h in root.handlers]
            assert "StreamHandler" in handler_types
            assert "ConcurrentRotatingFileHandler" in handler_types

    def test_stdout_info_stderr_warning(self):
        root = logging.getLogger()
        root.handlers.clear()
        with tempfile.TemporaryDirectory() as tmp:
            from log_config import setup_logging

            root = setup_logging("test", log_dir=tmp)
            for h in root.handlers:
                if isinstance(h, logging.StreamHandler) and h.stream is sys.stdout:
                    assert h.level == logging.INFO
                elif isinstance(h, logging.StreamHandler) and h.stream is sys.stderr:
                    assert h.level == logging.WARNING

    def test_file_handler_debug_level(self):
        root = logging.getLogger()
        root.handlers.clear()
        with tempfile.TemporaryDirectory() as tmp:
            from log_config import setup_logging

            root = setup_logging("test", log_dir=tmp)
            fh = next(h for h in root.handlers if isinstance(h, ConcurrentRotatingFileHandler))
            assert fh.level == logging.DEBUG

    def test_file_handler_params(self):
        root = logging.getLogger()
        root.handlers.clear()
        with tempfile.TemporaryDirectory() as tmp:
            from log_config import setup_logging

            root = setup_logging("test", log_dir=tmp)
            fh = next(h for h in root.handlers if isinstance(h, ConcurrentRotatingFileHandler))
            assert fh.backupCount == 6
            assert fh.maxBytes == 100 * 1024 * 1024

    def test_respects_log_dir_env(self):
        root = logging.getLogger()
        root.handlers.clear()
        with tempfile.TemporaryDirectory() as tmp:
            expected = os.path.join(tmp, "from_env")
            with patch.dict(os.environ, {"LOG_DIR": expected}, clear=False):
                from log_config import setup_logging

                setup_logging("test")
                assert os.path.isdir(expected)


# ── RemoteShipHandler ─────────────────────────────────────────────────────


class TestRemoteShipHandler:
    @pytest.fixture(autouse=True)
    def _handler(self):
        self.ship_url = "http://server:5000/api/workers/logs"
        self.token = "test-token"
        with patch("log_config.requests.post") as self.mock_post:
            self.mock_post.return_value.ok = True
            from log_config import RemoteShipHandler

            self.handler = RemoteShipHandler(
                self.ship_url, self.token, max_lines=10, ship_interval_days=365
            )
            yield

    def test_constructor(self):
        assert self.handler.ship_url == self.ship_url
        assert self.handler.token == self.token
        assert self.handler.max_lines == 10
        assert self.handler.ship_interval == 365 * 86400

    def test_emit_buffers_message(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "hello", (), None)
        self.handler.emit(record)
        assert self.handler.queue.qsize() == 1
        assert self.handler._buffer_count == 1

    def test_emit_drops_oldest_when_full(self):
        """Emit more than max_lines; oldest should be dropped, NOT flushed."""
        from log_config import RemoteShipHandler

        h = RemoteShipHandler(self.ship_url, self.token, max_lines=10, ship_interval_days=36500)
        # Reset _buffer_count after each emit to prevent auto-flush
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        for _ in range(15):
            h.emit(record)
            h._buffer_count = 0
        assert h.queue.qsize() == 10

    def test_flush_sends_gzip_post(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "hello", (), None)
        self.handler.emit(record)
        self.handler.flush()
        self.mock_post.assert_called_once()
        call_args = self.mock_post.call_args
        assert call_args[0][0] == self.ship_url
        body = call_args[1]["data"]
        assert call_args[1]["headers"]["Content-Encoding"] == "gzip"
        decompressed = gzip.decompress(body).decode()
        assert "hello" in decompressed

    def test_flush_headers(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        self.handler.emit(record)
        self.handler.flush()
        headers = self.mock_post.call_args[1]["headers"]
        assert headers["X-Worker-Token"] == self.token
        assert headers["Content-Encoding"] == "gzip"
        assert headers["Content-Type"] == "application/octet-stream"
        assert "X-Worker-Service" in headers

    def test_flush_resets_buffer_on_success(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        self.handler.emit(record)
        self.handler.flush()
        assert self.handler._buffer_count == 0
        assert self.handler.queue.empty()

    def test_flush_no_op_when_empty(self):
        self.handler.flush()
        self.mock_post.assert_not_called()

    def test_auto_flush_on_max_lines(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        for _ in range(9):
            self.handler.emit(record)
        self.mock_post.assert_not_called()
        self.handler.emit(record)
        self.mock_post.assert_called_once()

    def test_flush_failure_suppressed(self):
        self.mock_post.side_effect = Exception("connection error")
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        self.handler.emit(record)
        # Should not raise
        self.handler.flush()

    def test_rate_limiting_via_ship_interval(self):
        from log_config import RemoteShipHandler

        with patch("log_config.requests.post") as mock_post:
            mock_post.return_value.ok = True
            h = RemoteShipHandler(self.ship_url, self.token, max_lines=5, ship_interval_days=0)
            h._last_ship = _time.time() - 1
            record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
            h.emit(record)
            mock_post.assert_called()


# ── POST /api/workers/logs integration ────────────────────────────────────


class TestReceiveWorkerLogs:
    @pytest.fixture(autouse=True)
    def setup(self, app, db_session, redis_flush):
        self.client = app.test_client()
        self.log_dir = tempfile.mkdtemp()
        os.environ["LOG_DIR"] = self.log_dir

        # Clear rate-limit counters left by other xdist workers
        from contextlib import suppress

        with suppress(Exception):
            from cache_utils import get_redis_client

            r = get_redis_client()
            if r:
                for key in r.scan_iter("rate:*"):
                    r.delete(key)

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        self._worker_key = Ed25519PrivateKey.generate()
        os.environ["WORKER_PUBLIC_KEY"] = base64.b64encode(
            self._worker_key.public_key().public_bytes_raw()
        ).decode()

    def _worker_token(self, submission_id="1"):
        nonce = f"{submission_id}:{int(_time.time())}"
        sig = base64.b64encode(self._worker_key.sign(nonce.encode())).decode()
        return f"{nonce}.{sig}"

    def _post_logs(self, lines, token=None):
        token = token or self._worker_token()
        body = gzip.compress("\n".join(lines).encode())
        return self.client.post(
            "/api/workers/logs",
            data=body,
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Encoding": "gzip",
                "X-Worker-Token": token,
            },
        )

    def test_no_token_returns_401(self):
        resp = self.client.post(
            "/api/workers/logs", data=b"", content_type="application/octet-stream"
        )
        assert resp.status_code == 401

    def test_empty_body_returns_400(self):
        token = self._worker_token()
        resp = self.client.post(
            "/api/workers/logs",
            data=b"",
            headers={"X-Worker-Token": token},
            content_type="application/octet-stream",
        )
        assert resp.status_code == 400

    def test_invalid_gzip_returns_400(self):
        token = self._worker_token()
        resp = self.client.post(
            "/api/workers/logs",
            data=b"not-gzip-data",
            headers={
                "X-Worker-Token": token,
                "Content-Type": "application/octet-stream",
                "Content-Encoding": "gzip",
            },
        )
        assert resp.status_code == 400

    def test_success_returns_200(self):
        resp = self._post_logs(["line1", "line2"])
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "ok"

    def test_writes_to_worker_remote_log(self):
        self._post_logs(["test log line"])
        log_path = os.path.join(self.log_dir, "worker_remote.log")
        with open(log_path) as f:
            content = f.read()
        assert "test log line" in content

    def test_appends_multiple_requests(self):
        self._post_logs(["first"])
        self._post_logs(["second"])
        log_path = os.path.join(self.log_dir, "worker_remote.log")
        with open(log_path) as f:
            content = f.read()
        assert "first" in content
        assert "second" in content

    def test_invalid_token_returns_401(self):
        resp = self._post_logs(["msg"], token="bad.token.here")
        assert resp.status_code == 401

    def test_expired_token_returns_401(self):
        nonce = "1:0"
        sig = base64.b64encode(self._worker_key.sign(nonce.encode())).decode()
        token = f"{nonce}.{sig}"
        resp = self._post_logs(["msg"], token=token)
        assert resp.status_code == 401

    def test_rate_limited(self):
        for _ in range(12):
            resp = self._post_logs(["ok"])
            assert resp.status_code == 200
        resp = self._post_logs(["too many"])
        assert resp.status_code == 429


# ── Backup includes logs ──────────────────────────────────────────────────


class TestBackupIncludesLogs:
    @pytest.fixture(autouse=True)
    def setup(self, app, db_session):
        self.app = app
        self.app.config["TESTING"] = True

    @patch("models.AuditLog.query")
    @patch("task_modules.system.subprocess.run")
    @patch("task_modules.system.os.path.getsize")
    def test_copytree_called_when_log_dir_exists(self, mock_getsize, mock_run, mock_audit):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = ""
        mock_getsize.return_value = 1024
        mock_audit.return_value.order_by.return_value.yield_per.return_value = []

        log_dir = tempfile.mkdtemp()
        with open(os.path.join(log_dir, "backend.log"), "w") as f:
            f.write("test log")

        from task_modules.system import run_backup

        with (
            self.app.app_context(),
            patch("task_modules.system.Config.LOG_DIR", log_dir),
            patch("task_modules.system.shutil.copytree") as mock_copytree,
        ):
            run_backup(self.app, auto=True)
            mock_copytree.assert_called_once()
            args, kwargs = mock_copytree.call_args
            assert args[0] == log_dir
            assert kwargs.get("dirs_exist_ok") is True

    @patch("models.AuditLog.query")
    @patch("task_modules.system.subprocess.run")
    @patch("task_modules.system.os.path.getsize")
    def test_copytree_not_called_when_log_dir_missing(self, mock_getsize, mock_run, mock_audit):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = ""
        mock_getsize.return_value = 1024
        mock_audit.return_value.order_by.return_value.yield_per.return_value = []

        from task_modules.system import run_backup

        with (
            self.app.app_context(),
            patch("task_modules.system.Config.LOG_DIR", "/tmp/nonexistent-test-log-dir-12345"),
            patch("task_modules.system.shutil.copytree") as mock_copytree,
        ):
            run_backup(self.app, auto=True)
            mock_copytree.assert_not_called()
