"""Tests for the worker spec."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tasks.task_modules import submission_runner as sr
from tasks.task_modules.submission_runner import (
    _refresh_worker_spec,
    register_worker_specs,
)


class TestRegisterWorkerSpecs:
    @staticmethod
    def _fake_check_output(cmd, *args, **kwargs):
        if cmd == ["sysctl", "-n", "hw.memsize"]:
            return b"8589934592\n"
        raise FileNotFoundError("nvidia-smi not found")

    def _setup(self, mocker, hostname="worker-1", concurrency=4):
        mock_r = mocker.MagicMock()
        mocker.patch.object(sr, "get_coordination_client", return_value=mock_r)
        mocker.patch.object(sr.os, "cpu_count", return_value=8)
        mocker.patch("platform.system", return_value="Darwin")
        mocker.patch.object(sr.subprocess, "check_output", side_effect=self._fake_check_output)
        self.start_heartbeat = mocker.patch.object(sr, "_start_heartbeat")
        task_consumer = SimpleNamespace(
            queues=[SimpleNamespace(name="cpu_queue"), SimpleNamespace(name="celery")]
        )
        sender = SimpleNamespace(
            hostname=hostname,
            pool=SimpleNamespace(limit=concurrency),
            task_consumer=task_consumer,
        )
        return mock_r, sender

    def test_registers_cpu_spec(self, mocker):
        mock_r, sender = self._setup(mocker)
        register_worker_specs(sender)
        mock_r.set.assert_called_once()
        key = mock_r.set.call_args.args[0]
        payload = mock_r.set.call_args.args[1]
        assert key == "worker_spec:worker-1"
        spec = json.loads(payload)
        assert spec["name"] == "worker-1"
        assert spec["type"] == "CPU"
        assert spec["concurrency"] == 4
        assert spec["cpu_cores"] == 8
        assert spec["ram_gb"] == 8.0
        assert spec["gpu_type"] == "N/A"
        assert "last_seen" in spec
        assert spec["queues"] == ["celery", "cpu_queue"]
        assert mock_r.set.call_args.kwargs["ex"] == 86400
        self.start_heartbeat.assert_called_once_with(sender)

    def test_registers_gpu_spec_by_worker_name(self, mocker):
        mock_r, sender = self._setup(mocker, hostname="gpu-worker-2", concurrency=2)
        register_worker_specs(sender)
        spec = json.loads(mock_r.set.call_args.args[1])
        assert spec["type"] == "GPU"
        assert spec["gpu_type"] == "NVIDIA GPU"
        assert spec["vram_gb"] == 8.0

    def test_no_client_returns_early(self, mocker):
        mocker.patch.object(sr, "get_coordination_client", return_value=None)
        register_worker_specs(MagicMock(hostname="worker-3"))

    def test_failed_first_write_still_starts_the_heartbeat(self, mocker):
        mock_r, sender = self._setup(mocker, hostname="worker-4")
        mocker.patch.object(sr, "_cached_worker_spec", None)
        mocker.patch.object(sr, "_cached_worker_name", None)
        mock_r.set.side_effect = Exception("redis restarting")
        register_worker_specs(sender)
        # The heartbeat retries the write from the cached spec on its next beat
        self.start_heartbeat.assert_called_once_with(sender)
        assert sr._cached_worker_name == "worker-4"
        assert sr._cached_worker_spec["name"] == "worker-4"


class TestRefreshWorkerSpec:
    """The heartbeat rewrites the cached spec with a fresh last_seen and live queues."""

    def _consumer(self, *names):
        return SimpleNamespace(
            task_consumer=SimpleNamespace(queues=[SimpleNamespace(name=n) for n in names])
        )

    def test_writes_last_seen_and_current_queues(self, mocker):
        mock_r = mocker.MagicMock()
        # The broker's clock, not the worker's, stamps the heartbeat
        mock_r.time.return_value = (1234, 500000)
        mocker.patch.object(sr, "get_coordination_client", return_value=mock_r)
        mocker.patch.object(sr, "_cached_worker_spec", {"name": "w1", "last_seen": 1.0})
        mocker.patch.object(sr, "_cached_worker_name", "w1")
        mocker.patch.object(sr, "_heartbeat_consumer", self._consumer("gpu_queue", "cpu_queue"))
        mocker.patch.object(sr.time, "time", return_value=999.0)

        _refresh_worker_spec()

        mock_r.set.assert_called_once()
        key, payload = mock_r.set.call_args.args
        assert key == "worker_spec:w1"
        spec = json.loads(payload)
        assert spec["last_seen"] == 1234.5
        assert spec["queues"] == ["cpu_queue", "gpu_queue"]
        assert mock_r.set.call_args.kwargs["ex"] == 86400
        assert sr._cached_worker_spec["queues"] == ["cpu_queue", "gpu_queue"]

    def test_keeps_registered_queues_when_consumer_reports_none(self, mocker):
        mock_r = mocker.MagicMock()
        mocker.patch.object(sr, "get_coordination_client", return_value=mock_r)
        mocker.patch.object(sr, "_cached_worker_spec", {"name": "w1", "queues": ["cpu_queue"]})
        mocker.patch.object(sr, "_cached_worker_name", "w1")
        mocker.patch.object(sr, "_heartbeat_consumer", SimpleNamespace())

        _refresh_worker_spec()

        assert json.loads(mock_r.set.call_args.args[1])["queues"] == ["cpu_queue"]

    def test_no_cached_spec_is_noop(self, mocker):
        mock_r = mocker.MagicMock()
        mocker.patch.object(sr, "get_coordination_client", return_value=mock_r)
        mocker.patch.object(sr, "_cached_worker_spec", None)
        mocker.patch.object(sr, "_cached_worker_name", None)
        _refresh_worker_spec()
        mock_r.set.assert_not_called()

    def test_no_client_is_noop(self, mocker):
        mocker.patch.object(sr, "get_coordination_client", return_value=None)
        mocker.patch.object(sr, "_cached_worker_spec", {"name": "w1"})
        mocker.patch.object(sr, "_cached_worker_name", "w1")
        _refresh_worker_spec()


class TestHeartbeatThread:
    def test_starts_one_daemon_thread(self, mocker):
        started = []

        class FakeThread:
            def __init__(self, target, args, name, daemon):
                self.target, self.args, self.name, self.daemon = target, args, name, daemon

            def start(self):
                started.append(self)

            def is_alive(self):
                return True

        mocker.patch.object(sr.threading, "Thread", FakeThread)
        mocker.patch.object(sr, "_heartbeat_thread", None)
        consumer = SimpleNamespace(hostname="w1")

        sr._start_heartbeat(consumer)
        sr._start_heartbeat(consumer)

        assert len(started) == 1
        assert started[0].daemon is True
        assert started[0].args == (sr.Config.WORKER_HEARTBEAT_SECONDS,)
        assert sr._heartbeat_consumer is consumer

    def test_loop_refreshes_every_interval_and_survives_errors(self, mocker):
        sleeps = []

        def fake_sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) > 2:
                raise SystemExit

        mocker.patch.object(sr.time, "sleep", side_effect=fake_sleep)
        refresh = mocker.patch.object(
            sr, "_refresh_worker_spec", side_effect=[RuntimeError("redis blip"), None]
        )
        with pytest.raises(SystemExit):
            sr._heartbeat_loop(30)
        assert sleeps == [30, 30, 30]
        assert refresh.call_count == 2
