from __future__ import annotations

import gzip
import logging
import os
import sys
import time as _time
from contextlib import suppress
from queue import Queue

import requests
from concurrent_log_handler import ConcurrentRotatingFileHandler


def setup_logging(
    service_name: str, log_dir: str | None = None, level: int = logging.INFO
) -> logging.Logger:
    log_dir = log_dir or os.environ.get("LOG_DIR", "/app/logs")

    root = logging.getLogger()
    root.setLevel(level)

    os.makedirs(log_dir, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    if not any(
        isinstance(h, logging.StreamHandler) and h.stream is sys.stdout for h in root.handlers
    ):
        stdout = logging.StreamHandler(sys.stdout)
        stdout.setLevel(logging.INFO)
        stdout.setFormatter(fmt)
        root.addHandler(stdout)

    if not any(
        isinstance(h, logging.StreamHandler) and h.stream is sys.stderr for h in root.handlers
    ):
        stderr = logging.StreamHandler(sys.stderr)
        stderr.setLevel(logging.WARNING)
        stderr.setFormatter(fmt)
        root.addHandler(stderr)

    log_path = os.path.join(log_dir, f"{service_name}.log")
    if not any(
        isinstance(h, ConcurrentRotatingFileHandler) and h.baseFilename == log_path
        for h in root.handlers
    ):
        fh = ConcurrentRotatingFileHandler(
            log_path,
            maxBytes=100 * 1024 * 1024,
            backupCount=6,
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        root.addHandler(fh)

    return root


class RemoteShipHandler(logging.Handler):
    """Buffers log records and ships them to the server via gzipped POST."""

    def __init__(
        self, ship_url: str, token: str, max_lines: int = 5000, ship_interval_days: int = 6
    ):
        super().__init__(level=logging.INFO)
        self.ship_url = ship_url
        self.token = token
        self.max_lines = max_lines
        self.ship_interval = ship_interval_days * 86400
        self.queue: Queue[str] = Queue()
        self._buffer_count: int = 0
        self._last_ship: float = _time.time()

        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        self.setFormatter(fmt)

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        if self.queue.qsize() >= self.max_lines:
            with suppress(Exception):
                self.queue.get_nowait()
        self.queue.put_nowait(msg)
        self._buffer_count += 1
        elapsed = _time.time() - self._last_ship
        if self._buffer_count >= self.max_lines or elapsed >= self.ship_interval:
            self.flush()

    def flush(self) -> None:
        if self.queue.empty():
            return
        lines = []
        while not self.queue.empty():
            try:
                lines.append(self.queue.get_nowait())
            except Exception:
                break
        if not lines:
            return
        with suppress(Exception):
            body = gzip.compress("\n".join(lines).encode())
            resp = requests.post(
                self.ship_url,
                data=body,
                headers={
                    "Content-Type": "application/octet-stream",
                    "Content-Encoding": "gzip",
                    "X-Worker-Token": self.token,
                    "X-Worker-Service": os.environ.get("HOSTNAME", "unknown-worker"),
                },
                timeout=10,
            )
            if resp.ok:
                self._last_ship = _time.time()
                self._buffer_count = 0
