"""Tests for the worker spec."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tasks.task_modules import submission_runner as sr
from tasks.task_modules.submission_runner import (
    _preload_dataset,
    _preload_model,
    _refresh_worker_spec,
    preload_submission_datasets,
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


class TestPreloadDatasetModel:
    def test_preload_dataset_success_appends_log(self):
        load_fn = MagicMock()
        logs = []
        _preload_dataset(load_fn, "ds1", "/cache", "tok", logs)
        load_fn.assert_called_once_with("ds1", cache_dir="/cache", token="tok")
        assert any("Successfully preloaded dataset 'ds1'" in log for log in logs)

    def test_preload_dataset_failure_appends_warning(self):
        load_fn = MagicMock(side_effect=Exception("network down"))
        logs = []
        _preload_dataset(load_fn, "ds1", "/cache", None, logs)
        assert any("Warning: Failed to preload dataset 'ds1'" in log for log in logs)

    def test_preload_model_success_appends_log(self):
        download_fn = MagicMock()
        logs = []
        _preload_model(download_fn, "model1", "/cache", "tok", logs)
        download_fn.assert_called_once_with(repo_id="model1", cache_dir="/cache", token="tok")
        assert any("Successfully preloaded model 'model1'" in log for log in logs)

    def test_preload_model_failure_appends_warning(self):
        download_fn = MagicMock(side_effect=Exception("network down"))
        logs = []
        _preload_model(download_fn, "model1", "/cache", None, logs)
        assert any("Warning: Failed to preload model 'model1'" in log for log in logs)


class TestPreloadSubmissionDatasetsDispatch:
    def _make_task(self, datasets=None, models=None, hf_token=None):
        from utils.worker_utils import MockModel

        kwargs = {"hf_datasets": datasets, "hf_models": models}
        if hf_token is not None:
            kwargs["get_hf_api_key"] = lambda: hf_token
        return MockModel(**kwargs)

    def test_dispatches_with_correct_args_and_dedupes(self, mocker, tmp_path):
        mock_ds = MagicMock()
        mock_hub = MagicMock()
        mocker.patch.dict("sys.modules", {"datasets": mock_ds, "huggingface_hub": mock_hub})
        mock_preload_ds = mocker.patch.object(sr, "_preload_dataset")
        mock_preload_model = mocker.patch.object(sr, "_preload_model")
        task = self._make_task(datasets='["ds1", "ds1", "ds2"]', models='["m1"]', hf_token="tok")
        logs = []
        preload_submission_datasets(task, None, str(tmp_path), "/cache", logs)
        assert mock_preload_ds.call_count == 2
        first_args = mock_preload_ds.call_args_list[0][0]
        assert first_args[1] == "ds1"
        assert first_args[2] == "/cache"
        assert first_args[3] == "tok"
        assert mock_preload_model.call_count == 1
        assert mock_preload_model.call_args[0][1] == "m1"
        assert any("Preloading datasets" in log for log in logs)
        assert any("Preloading HF models" in log for log in logs)

    def test_empty_metadata_is_noop(self, mocker):
        mock_preload_ds = mocker.patch.object(sr, "_preload_dataset")
        mock_preload_model = mocker.patch.object(sr, "_preload_model")
        logs = []
        preload_submission_datasets(None, None, "/tmp", "/cache", logs)
        mock_preload_ds.assert_not_called()
        mock_preload_model.assert_not_called()
        assert logs == []
