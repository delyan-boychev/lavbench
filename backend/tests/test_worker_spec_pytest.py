import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import redis

from tasks.task_modules import submission_runner as sr
from tasks.task_modules.submission_runner import (
    _preload_dataset,
    _preload_model,
    _recreate_spec_on_reconnect,
    _refresh_worker_spec,
    preload_submission_datasets,
    register_worker_specs,
)


class TestRecreateSpecOnReconnect:
    def test_no_cached_spec_is_noop(self, mocker):
        mocker.patch.object(sr, "_cached_worker_spec", None)
        mocker.patch.object(sr, "_cached_worker_name", None)
        mock_r = mocker.MagicMock()
        mocker.patch.object(sr, "get_coordination_client", return_value=mock_r)
        _recreate_spec_on_reconnect()
        mock_r.set.assert_not_called()

    def test_no_client_is_noop(self, mocker):
        mocker.patch.object(sr, "_cached_worker_spec", {"name": "w1"})
        mocker.patch.object(sr, "_cached_worker_name", "w1")
        mocker.patch.object(sr, "get_coordination_client", return_value=None)
        _recreate_spec_on_reconnect()
        assert sr._spec_reconnect_needed is False

    def test_rewrites_spec_key_with_cached_fields(self, mocker):
        mocker.patch.object(sr, "_cached_worker_spec", {"name": "w1", "type": "CPU"})
        mocker.patch.object(sr, "_cached_worker_name", "w1")
        mock_r = mocker.MagicMock()
        mocker.patch.object(sr, "get_coordination_client", return_value=mock_r)
        _recreate_spec_on_reconnect()
        mock_r.set.assert_called_once()
        key = mock_r.set.call_args.args[0]
        payload = mock_r.set.call_args.args[1]
        assert key == "worker_spec:w1"
        assert json.loads(payload)["name"] == "w1"
        assert "last_seen" in json.loads(payload)
        assert mock_r.set.call_args.kwargs["ex"] == 604800

    def test_redis_exception_is_swallowed(self, mocker):
        mocker.patch.object(sr, "_cached_worker_spec", {"name": "w1"})
        mocker.patch.object(sr, "_cached_worker_name", "w1")
        mock_r = mocker.MagicMock()
        mock_r.set.side_effect = Exception("redis down")
        mocker.patch.object(sr, "get_coordination_client", return_value=mock_r)
        _recreate_spec_on_reconnect()


class TestInstallReconnectGuard:
    def _install(self, fake_execute):
        original = redis.client.Redis.execute_command
        redis.client.Redis.execute_command = fake_execute
        sr._install_reconnect_guard()
        return original

    def test_connection_error_sets_flag_then_next_success_registers(self, mocker):
        fail_next = {"value": True}

        def fake_execute(self_, *args, **options):
            if fail_next["value"]:
                fail_next["value"] = False
                raise redis.exceptions.ConnectionError("connection refused")
            return "OK"

        original = self._install(fake_execute)
        try:
            sr._spec_reconnect_needed = False
            mock_recreate = mocker.patch.object(sr, "_recreate_spec_on_reconnect")
            with pytest.raises(redis.exceptions.ConnectionError):
                redis.client.Redis.execute_command(None, "PING")
            assert sr._spec_reconnect_needed is True
            mock_recreate.assert_not_called()
            redis.client.Redis.execute_command(None, "SET", "k", "v")
            mock_recreate.assert_called_once()
        finally:
            redis.client.Redis.execute_command = original
            sr._spec_reconnect_needed = False

    def test_successful_calls_do_not_re_register(self, mocker):
        def fake_execute(self_, *args, **options):
            return "OK"

        original = self._install(fake_execute)
        try:
            sr._spec_reconnect_needed = False
            mock_recreate = mocker.patch.object(sr, "_recreate_spec_on_reconnect")
            redis.client.Redis.execute_command(None, "GET", "k")
            redis.client.Redis.execute_command(None, "SET", "k", "v")
            mock_recreate.assert_not_called()
        finally:
            redis.client.Redis.execute_command = original
            sr._spec_reconnect_needed = False

    def test_unrelated_errors_are_propagated(self, mocker):
        def fake_execute(self_, *args, **options):
            raise redis.exceptions.ResponseError("wrong type")

        original = self._install(fake_execute)
        try:
            sr._spec_reconnect_needed = False
            with pytest.raises(redis.exceptions.ResponseError):
                redis.client.Redis.execute_command(None, "GET", "k")
            assert sr._spec_reconnect_needed is False
        finally:
            redis.client.Redis.execute_command = original
            sr._spec_reconnect_needed = False


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
        mock_build = mocker.patch("tasks.task_modules.image_builder.build_all_active_tasks")
        mock_listener = mocker.patch("tasks.task_modules.image_builder.start_rebuild_listener")
        sender = SimpleNamespace(hostname=hostname, pool=SimpleNamespace(limit=concurrency))
        return mock_r, mock_build, mock_listener, sender

    def test_registers_cpu_spec(self, mocker):
        mock_r, mock_build, mock_listener, sender = self._setup(mocker)
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
        assert mock_r.set.call_args.kwargs["ex"] == 604800
        mock_build.assert_called_once()
        mock_listener.assert_called_once()

    def test_registers_gpu_spec_by_worker_name(self, mocker):
        mock_r, _mock_build, _mock_listener, sender = self._setup(
            mocker, hostname="gpu-worker-2", concurrency=2
        )
        register_worker_specs(sender)
        spec = json.loads(mock_r.set.call_args.args[1])
        assert spec["type"] == "GPU"
        assert spec["gpu_type"] == "NVIDIA GPU"
        assert spec["vram_gb"] == 8.0

    def test_no_client_returns_early(self, mocker):
        mocker.patch.object(sr, "get_coordination_client", return_value=None)
        mock_build = mocker.patch("tasks.task_modules.image_builder.build_all_active_tasks")
        register_worker_specs(MagicMock(hostname="worker-3"))
        mock_build.assert_not_called()

    def test_internal_only_worker_skips_image_prebuilding(self, mocker):
        mock_r, mock_build, mock_listener, sender = self._setup(mocker)
        mocker.patch.object(sr.Config, "RUNS_EVALUATION", False)
        register_worker_specs(sender)
        mock_r.set.assert_called_once()
        mock_build.assert_not_called()
        mock_listener.assert_not_called()

    def test_build_failure_does_not_block_spec_registration(self, mocker):
        mock_r, mock_build, _mock_listener, sender = self._setup(mocker)
        mock_build.side_effect = Exception("build boom")
        register_worker_specs(sender)
        mock_r.set.assert_called_once()


class TestRefreshWorkerSpec:
    def test_updates_spec_ttl(self, mocker):
        mock_r = mocker.MagicMock()
        mock_r.exists.return_value = True
        mock_r.get.return_value = json.dumps({"name": "w1", "last_seen": 1.0})
        mocker.patch.object(sr, "get_coordination_client", return_value=mock_r)
        _refresh_worker_spec(task=SimpleNamespace(hostname="w1"))
        mock_r.set.assert_called_once()
        key = mock_r.set.call_args.args[0]
        payload = mock_r.set.call_args.args[1]
        assert key == "worker_spec:w1"
        spec = json.loads(payload)
        assert spec["name"] == "w1"
        assert "last_seen" in spec
        assert mock_r.set.call_args.kwargs["ex"] == 604800

    def test_no_task_request_is_noop(self, mocker):
        mock_r = mocker.MagicMock()
        mocker.patch.object(sr, "get_coordination_client", return_value=mock_r)
        _refresh_worker_spec(task=None)
        mock_r.set.assert_not_called()

    def test_task_without_hostname_is_noop(self, mocker):
        mock_r = mocker.MagicMock()
        mocker.patch.object(sr, "get_coordination_client", return_value=mock_r)
        _refresh_worker_spec(task=SimpleNamespace(hostname=""))
        mock_r.set.assert_not_called()

    def test_missing_spec_key_is_noop(self, mocker):
        mock_r = mocker.MagicMock()
        mock_r.exists.return_value = False
        mocker.patch.object(sr, "get_coordination_client", return_value=mock_r)
        _refresh_worker_spec(task=SimpleNamespace(hostname="w1"))
        mock_r.set.assert_not_called()

    def test_no_client_is_noop(self, mocker):
        mocker.patch.object(sr, "get_coordination_client", return_value=None)
        _refresh_worker_spec(task=SimpleNamespace(hostname="w1"))


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
        from worker_utils import MockModel

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
