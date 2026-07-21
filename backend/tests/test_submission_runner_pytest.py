import math
from unittest.mock import patch

import pytest

from config import Config
from evaluation_engine import (
    AVAILABLE_METRICS,
    evaluate_predictions,
    validate_parquet_schema,
)
from task_modules.submission_runner import calculate_weighted_score


class TestSubmissionRunnerMetrics:
    def test_calculate_weighted_score_no_cfg_higher_better(self):
        payload = {"accuracy": 0.85}
        score = calculate_weighted_score(payload, None)
        assert score == 0.85

    def test_calculate_weighted_score_no_cfg_lower_better(self):
        payload = {"mse": 0.25}
        score = calculate_weighted_score(payload, None)
        assert score == 1.0 / (1.0 + 0.25)

    def test_calculate_weighted_score_no_cfg_brier(self):
        payload = {"brier_score": 0.1}
        score = calculate_weighted_score(payload, None)
        assert score == 0.9

    def test_calculate_weighted_score_with_cfg_higher_better(self):
        payload = {"accuracy": 0.9, "f1": 0.8}
        cfg = {"accuracy": {"weight": 2.0}, "f1": {"weight": 1.0}}
        score = calculate_weighted_score(payload, cfg)
        assert round(score, 10) == round(0.8666666666666667, 10)

    def test_calculate_weighted_score_with_cfg_lower_better(self):
        payload = {"mse": 0.5, "accuracy": 0.8}
        cfg = {"mse": {"weight": 1.0}, "accuracy": {"weight": 1.0}}
        score = calculate_weighted_score(payload, cfg)
        assert round(score, 10) == round(0.7333333333333333, 10)

    def test_calculate_weighted_score_nan_inf(self):
        payload = {"accuracy": math.nan, "f1": math.inf}
        cfg = {"accuracy": {"weight": 1.0}, "f1": {"weight": 1.0}}
        score = calculate_weighted_score(payload, cfg)
        assert score == 0.0

    def test_calculate_weighted_score_negative_one(self):
        payload = {"mse": -1.0}
        cfg = {"mse": {"weight": 1.0}}
        score = calculate_weighted_score(payload, cfg)
        assert score == 0.0

    def test_weighted_score_mse_lower_better(self):
        payload = {"mse": 5.0, "mae": 3.0}
        cfg = {"mse": {"weight": 1.0}, "mae": {"weight": 1.0}}
        score = calculate_weighted_score(payload, cfg)
        expected = (1.0 / 6.0 + 1.0 / 4.0) / 2.0
        assert abs(score - expected) < 1e-6

    def test_weighted_score_default_higher_better(self):
        payload = {"accuracy": 0.95, "f1_score": 0.85}
        cfg = {"accuracy": {"weight": 1.0}, "f1_score": {"weight": 1.0}}
        score = calculate_weighted_score(payload, cfg)
        assert abs(score - (0.95 + 0.85) / 2.0) < 1e-6


captured_run_kwargs = {}


class CommandInterruptedError(Exception):
    pass


class TestSubmissionRunnerDocker:
    @pytest.fixture(autouse=True)
    def setup_mocks(self, mocker):
        captured_run_kwargs.clear()

        mock_docker_client = mocker.MagicMock()

        mocker.patch(
            "task_modules.submission_runner.check_docker_available",
            return_value=True,
        )
        mocker.patch(
            "task_modules.submission_runner._get_client",
            return_value=mock_docker_client,
        )
        mocker.patch(
            "task_modules.submission_runner._image_exists_docker",
            return_value=True,
        )
        mocker.patch(
            "task_modules.submission_runner.report_status_to_server",
            return_value=True,
        )
        mocker.patch(
            "task_modules.submission_runner.get_redis_client",
            return_value=mocker.MagicMock(),
        )

        def mock_stream(docker_client, image_tag, command, logs_list, **kwargs):
            captured_run_kwargs.update(kwargs)
            captured_run_kwargs["image_tag"] = image_tag
            captured_run_kwargs["command"] = command
            raise CommandInterruptedError("docker run")

        mocker.patch(
            "task_modules.submission_runner.run_command_streaming",
            side_effect=mock_stream,
        )

    def test_unconditional_sandbox_args(self):
        from task_modules.submission_runner import run_eval_submission

        metadata = {
            "task_id": 456,
            "time_limit": 30,
            "ram_limit": 4096,
            "gpu_required": False,
            "base_docker_image": "python:3.10-slim",
            "apt_packages": "",
            "pip_requirements": "",
            "metrics_config": {},
            "public_eval_percentage": 100,
            "hf_datasets": "[]",
            "hf_models": "[]",
            "custom_eval_code": "print('hello')",
            "challenge_id": 789,
            "metric_name": "accuracy",
            "hf_dataset_split": "test",
            "user_code": "print('user code')",
            "submission_id": "sub_123",
            "main_server_url": "http://localhost:5000",
        }

        with pytest.raises(CommandInterruptedError):
            run_eval_submission(
                self_task=None,
                submission_id="sub_123",
                metadata=metadata,
                app=None,
                db=None,
                submission_cls=None,
                challenge_cls=None,
            )

        assert captured_run_kwargs.get("network_mode") == "none"
        assert captured_run_kwargs.get("cap_drop") == ["ALL"]
        assert captured_run_kwargs.get("security_opt") == ["no-new-privileges:true"]
        assert captured_run_kwargs.get("pids_limit") == 64
        assert captured_run_kwargs.get("mem_limit") == "4096m"
        assert captured_run_kwargs.get("working_dir") == "/app"
        assert captured_run_kwargs.get("gpu_required") is False
        assert captured_run_kwargs.get("gpu_id") is None

    def test_ram_limit_2048(self):
        from task_modules.submission_runner import run_eval_submission

        metadata = {
            "task_id": 456,
            "time_limit": 30,
            "ram_limit": 2048,
            "gpu_required": False,
            "base_docker_image": "python:3.10-slim",
            "apt_packages": "",
            "pip_requirements": "",
            "metrics_config": {},
            "public_eval_percentage": 100,
            "hf_datasets": "[]",
            "hf_models": "[]",
            "custom_eval_code": "print('hello')",
            "challenge_id": 789,
            "metric_name": "accuracy",
            "hf_dataset_split": "test",
            "user_code": "print('user code')",
            "submission_id": "sub_123",
            "main_server_url": "http://localhost:5000",
        }

        with pytest.raises(CommandInterruptedError):
            run_eval_submission(
                self_task=None,
                submission_id="sub_123",
                metadata=metadata,
                app=None,
                db=None,
                submission_cls=None,
                challenge_cls=None,
            )

        assert captured_run_kwargs.get("mem_limit") == "2048m"

    def test_gpu_routing_all(self):
        from task_modules.submission_runner import run_eval_submission

        # Config.WORKER_GPU_ID defaults to "" (falsy), so gpu_id = None

        metadata = {
            "task_id": 456,
            "time_limit": 30,
            "ram_limit": 4096,
            "gpu_required": True,
            "base_docker_image": "python:3.10-slim",
            "apt_packages": "",
            "pip_requirements": "",
            "metrics_config": {},
            "public_eval_percentage": 100,
            "hf_datasets": "[]",
            "hf_models": "[]",
            "custom_eval_code": "print('hello')",
            "challenge_id": 789,
            "metric_name": "accuracy",
            "hf_dataset_split": "test",
            "user_code": "print('user code')",
            "submission_id": "sub_123",
            "main_server_url": "http://localhost:5000",
        }

        with pytest.raises(CommandInterruptedError):
            run_eval_submission(
                self_task=None,
                submission_id="sub_123",
                metadata=metadata,
                app=None,
                db=None,
                submission_cls=None,
                challenge_cls=None,
            )

        assert captured_run_kwargs.get("gpu_required") is True
        assert captured_run_kwargs.get("gpu_id") is None
        assert "CUDA_VISIBLE_DEVICES" not in captured_run_kwargs.get("environment", {})

    def test_gpu_routing_specific_device(self):
        from task_modules.submission_runner import run_eval_submission

        metadata = {
            "task_id": 456,
            "time_limit": 30,
            "ram_limit": 4096,
            "gpu_required": True,
            "base_docker_image": "python:3.10-slim",
            "apt_packages": "",
            "pip_requirements": "",
            "metrics_config": {},
            "public_eval_percentage": 100,
            "hf_datasets": "[]",
            "hf_models": "[]",
            "custom_eval_code": "print('hello')",
            "challenge_id": 789,
            "metric_name": "accuracy",
            "hf_dataset_split": "test",
            "user_code": "print('user code')",
            "submission_id": "sub_123",
            "main_server_url": "http://localhost:5000",
        }

        with patch.object(Config, "WORKER_GPU_ID", "2"), pytest.raises(CommandInterruptedError):
            run_eval_submission(
                self_task=None,
                submission_id="sub_123",
                metadata=metadata,
                app=None,
                db=None,
                submission_cls=None,
                challenge_cls=None,
            )

        assert captured_run_kwargs.get("gpu_required") is True
        assert captured_run_kwargs.get("gpu_id") == "2"
        assert "CUDA_VISIBLE_DEVICES" not in captured_run_kwargs.get("environment", {})

    def test_gpu_routing_none(self):
        from task_modules.submission_runner import run_eval_submission

        metadata = {
            "task_id": 456,
            "time_limit": 30,
            "ram_limit": 4096,
            "gpu_required": False,
            "base_docker_image": "python:3.10-slim",
            "apt_packages": "",
            "pip_requirements": "",
            "metrics_config": {},
            "public_eval_percentage": 100,
            "hf_datasets": "[]",
            "hf_models": "[]",
            "custom_eval_code": "print('hello')",
            "challenge_id": 789,
            "metric_name": "accuracy",
            "hf_dataset_split": "test",
            "user_code": "print('user code')",
            "submission_id": "sub_123",
            "main_server_url": "http://localhost:5000",
        }

        with pytest.raises(CommandInterruptedError):
            run_eval_submission(
                self_task=None,
                submission_id="sub_123",
                metadata=metadata,
                app=None,
                db=None,
                submission_cls=None,
                challenge_cls=None,
            )

        assert captured_run_kwargs.get("gpu_required") is False
        assert captured_run_kwargs.get("gpu_id") is None
        assert "CUDA_VISIBLE_DEVICES" not in captured_run_kwargs.get("environment", {})


class TestCalculateWeightedScoreEdgeCases:
    """Edge cases for calculate_weighted_score — no-cfg nan/inf + weighted special paths."""

    def test_no_cfg_nan_payload_returns_zero(self):
        """No config with NaN payload (lines 150-151) → 0.0."""
        score = calculate_weighted_score({"accuracy": math.nan}, None)
        assert score == 0.0

    def test_no_cfg_inf_payload_returns_zero(self):
        score = calculate_weighted_score({"accuracy": math.inf}, None)
        assert score == 0.0

    def test_no_cfg_empty_payload_returns_zero(self):
        score = calculate_weighted_score({}, None)
        assert score == 0.0

    def test_no_cfg_brier_score_inverted(self):
        """brier_score is lower-better → 1 - val normalization."""
        score = calculate_weighted_score({"brier_score": 0.3}, None)
        assert score == pytest.approx(0.7)

    def test_cfg_zero_total_weight_returns_zero(self):
        """All weights zero → total_weight 0 → return 0.0 immediately."""
        score = calculate_weighted_score({"accuracy": 0.9}, {"accuracy": {"weight": 0.0}})
        assert score == 0.0

    def test_cfg_weighted_brier_score(self):
        """In the weighted path, brier_score → 1 - val normalization."""
        score = calculate_weighted_score({"brier_score": 0.2}, {"brier_score": {"weight": 1.0}})
        assert score == pytest.approx(0.8)

    def test_cfg_lower_better_val_negative_one_returns_zero(self):
        """val=-1.0 for lower-better metric triggers the special-case guard."""
        score = calculate_weighted_score({"mse": -1.0}, {"mse": {"weight": 1.0}})
        assert score == pytest.approx(0.0)

    def test_cfg_nan_norm_val_clamped_to_zero(self):
        """NaN/inf higher-is-better metric values → guard returns 0.0 contribution."""
        score = calculate_weighted_score({"accuracy": math.inf}, {"accuracy": {"weight": 1.0}})
        assert score == pytest.approx(0.0)


class TestFetchHFKeyFromServer:
    """Unit tests for _fetch_hf_key_from_server."""

    def test_missing_task_id_returns_empty(self):
        from task_modules.submission_runner import _fetch_hf_key_from_server

        assert _fetch_hf_key_from_server(None, "http://server", "token") == ""

    def test_missing_server_url_returns_empty(self):
        from task_modules.submission_runner import _fetch_hf_key_from_server

        assert _fetch_hf_key_from_server("task_1", None, "token") == ""

    def test_missing_token_returns_empty(self):
        from task_modules.submission_runner import _fetch_hf_key_from_server

        assert _fetch_hf_key_from_server("task_1", "http://server", None) == ""

    def test_all_params_missing_returns_empty(self):
        from task_modules.submission_runner import _fetch_hf_key_from_server

        assert _fetch_hf_key_from_server(None, None, None) == ""

    def test_successful_200_response(self, mocker):
        from task_modules.submission_runner import _fetch_hf_key_from_server

        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"hf_key": "hf_secret_token"}
        mocker.patch("task_modules.submission_runner.requests.get", return_value=mock_resp)

        result = _fetch_hf_key_from_server("task_1", "http://server:5000", "worker_token")
        assert result == "hf_secret_token"

    def test_http_403_returns_empty(self, mocker):
        from task_modules.submission_runner import _fetch_hf_key_from_server

        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 403
        mocker.patch("task_modules.submission_runner.requests.get", return_value=mock_resp)

        result = _fetch_hf_key_from_server("task_1", "http://server:5000", "bad_token")
        assert result == ""

    def test_http_404_returns_empty(self, mocker):
        from task_modules.submission_runner import _fetch_hf_key_from_server

        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 404
        mocker.patch("task_modules.submission_runner.requests.get", return_value=mock_resp)

        result = _fetch_hf_key_from_server("task_999", "http://server:5000", "token")
        assert result == ""

    def test_connection_error_returns_empty(self, mocker):
        import requests as req

        from task_modules.submission_runner import _fetch_hf_key_from_server

        mocker.patch(
            "task_modules.submission_runner.requests.get",
            side_effect=req.exceptions.ConnectionError("refused"),
        )
        result = _fetch_hf_key_from_server("task_1", "http://badhost:9999", "token")
        assert result == ""

    def test_timeout_exception_returns_empty(self, mocker):
        import requests as req

        from task_modules.submission_runner import _fetch_hf_key_from_server

        mocker.patch(
            "task_modules.submission_runner.requests.get",
            side_effect=req.exceptions.Timeout("timeout"),
        )
        result = _fetch_hf_key_from_server("task_1", "http://server:5000", "token")
        assert result == ""

    def test_200_but_missing_hf_key_field_returns_empty_string(self, mocker):
        from task_modules.submission_runner import _fetch_hf_key_from_server

        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}  # No "hf_key" field
        mocker.patch("task_modules.submission_runner.requests.get", return_value=mock_resp)

        result = _fetch_hf_key_from_server("task_1", "http://server:5000", "token")
        assert result == ""


class TestImageExists:
    """Unit tests for docker_utils.image_exists."""

    def test_image_found_returns_true(self, mocker):
        mock_client = mocker.MagicMock()
        mock_client.images.get.return_value = "image_obj"
        mocker.patch("task_modules.docker_utils._get_client", return_value=mock_client)
        from task_modules.docker_utils import image_exists

        assert image_exists("lavbench_task_42") is True

    def test_image_not_found_returns_false(self, mocker):
        from docker.errors import ImageNotFound

        mock_client = mocker.MagicMock()
        mock_client.images.get.side_effect = ImageNotFound("not found")
        mocker.patch("task_modules.docker_utils._get_client", return_value=mock_client)
        from task_modules.docker_utils import image_exists

        assert image_exists("nonexistent_image:v1") is False

    def test_image_exception_returns_false(self, mocker):
        mock_client = mocker.MagicMock()
        mock_client.images.get.side_effect = Exception("connection error")
        mocker.patch("task_modules.docker_utils._get_client", return_value=mock_client)
        from task_modules.docker_utils import image_exists

        assert image_exists("any_image") is False


class TestPreloadSubmissionDatasets:
    """Unit tests for preload_submission_datasets."""

    def _make_task(self, datasets=None, models=None):
        from worker_utils import MockModel

        return MockModel(
            hf_datasets=datasets,
            hf_models=models,
        )

    def test_no_hf_datasets_no_hf_models_noop(self):
        from task_modules.submission_runner import preload_submission_datasets

        task = self._make_task(datasets=None, models=None)
        logs = []
        preload_submission_datasets(task, None, "/tmp", None, logs)
        assert not any("Preloading" in log for log in logs)

    def test_malformed_datasets_json_is_ignored(self):
        from task_modules.submission_runner import preload_submission_datasets

        task = self._make_task(datasets="{malformed", models=None)
        logs = []
        preload_submission_datasets(task, None, "/tmp", None, logs)
        assert not any("Preloading datasets" in log for log in logs)

    def test_malformed_models_json_is_ignored(self):
        from task_modules.submission_runner import preload_submission_datasets

        task = self._make_task(datasets=None, models="[not valid json")
        logs = []
        preload_submission_datasets(task, None, "/tmp", None, logs)
        assert not any("Preloading" in log for log in logs)

    def test_datasets_list_without_cache_dir_skips(self):
        from task_modules.submission_runner import preload_submission_datasets

        task = self._make_task(datasets='["dataset1"]', models=None)
        logs = []
        # No cache_dir → should not try to load datasets
        preload_submission_datasets(task, None, "/tmp", None, logs)
        assert not any("Preloading datasets" in log for log in logs)

    def test_models_list_without_cache_dir_skips(self):
        from task_modules.submission_runner import preload_submission_datasets

        task = self._make_task(datasets=None, models='["bert-base-uncased"]')
        logs = []
        preload_submission_datasets(task, None, "/tmp", None, logs)
        assert not any("Preloading HF models" in log for log in logs)

    def test_datasets_with_cache_dir_attempts_preload(self, mocker, tmp_path):
        """When cache_dir and datasets are set, preload is attempted."""
        from task_modules.submission_runner import preload_submission_datasets

        task = self._make_task(datasets='["stanfordnlp/imdb"]', models=None)
        logs = []
        cache_dir = str(tmp_path)

        mock_ds_module = mocker.MagicMock()
        mock_ds_module.load_dataset = mocker.MagicMock()
        mocker.patch.dict("sys.modules", {"datasets": mock_ds_module})

        preload_submission_datasets(task, None, str(tmp_path), cache_dir, logs)
        assert any("Preloading datasets" in log for log in logs)

    def test_datasets_preload_failure_is_logged_as_warning(self, mocker, tmp_path):
        """Even if preload fails, it should log a warning and continue without crashing."""
        from task_modules.submission_runner import preload_submission_datasets

        task = self._make_task(datasets='["failing/dataset"]', models=None)
        logs = []
        cache_dir = str(tmp_path)

        mock_ds_module = mocker.MagicMock()
        mock_ds_module.load_dataset.side_effect = Exception("Dataset not found on Hub")
        mocker.patch.dict("sys.modules", {"datasets": mock_ds_module})

        preload_submission_datasets(task, None, str(tmp_path), cache_dir, logs)
        assert any("Warning" in log for log in logs)

    def test_models_with_cache_dir_attempts_preload(self, mocker, tmp_path):
        from task_modules.submission_runner import preload_submission_datasets

        task = self._make_task(datasets=None, models='["bert-base-uncased"]')
        logs = []
        cache_dir = str(tmp_path)

        mock_hub_module = mocker.MagicMock()
        mock_hub_module.snapshot_download = mocker.MagicMock()
        mocker.patch.dict("sys.modules", {"huggingface_hub": mock_hub_module})

        preload_submission_datasets(task, None, str(tmp_path), cache_dir, logs)
        assert any("Preloading HF models" in log for log in logs)

    def test_model_preload_failure_is_logged_as_warning(self, mocker, tmp_path):
        from task_modules.submission_runner import preload_submission_datasets

        task = self._make_task(datasets=None, models='["failing/model"]')
        logs = []
        cache_dir = str(tmp_path)

        mock_hub_module = mocker.MagicMock()
        mock_hub_module.snapshot_download.side_effect = Exception("Model not found")
        mocker.patch.dict("sys.modules", {"huggingface_hub": mock_hub_module})

        preload_submission_datasets(task, None, str(tmp_path), cache_dir, logs)
        assert any("Warning" in log for log in logs)

    def test_empty_dataset_names_are_filtered(self):
        """Empty strings in the dataset list should not be added to datasets_to_load."""
        from task_modules.submission_runner import preload_submission_datasets

        task = self._make_task(datasets='["", ""]', models=None)
        logs = []
        preload_submission_datasets(task, None, "/tmp", "/tmp/cache", logs)
        assert not any("Preloading datasets" in log for log in logs)

    def test_task_is_none_handled_gracefully(self):
        from task_modules.submission_runner import preload_submission_datasets

        logs = []
        preload_submission_datasets(None, None, "/tmp", None, logs)
        assert not any("Preloading" in log for log in logs)

    def test_list_datasets_directly_set(self, mocker, tmp_path):
        """Task with hf_datasets already as a Python list (not JSON string)."""
        from task_modules.submission_runner import preload_submission_datasets

        task = self._make_task(datasets=["my_dataset"], models=None)
        logs = []
        cache_dir = str(tmp_path)

        mock_ds_module = mocker.MagicMock()
        mock_ds_module.load_dataset = mocker.MagicMock()
        mocker.patch.dict("sys.modules", {"datasets": mock_ds_module})

        preload_submission_datasets(task, None, str(tmp_path), cache_dir, logs)
        assert any("Preloading datasets" in log for log in logs)


class TestDockerNotAvailable:
    """Test that run_eval_submission fails gracefully when Docker is unavailable."""

    def _metadata(self):
        return {
            "task_id": 1,
            "time_limit": 30,
            "ram_limit": 4096,
            "gpu_required": False,
            "base_docker_image": "python:3.10-slim",
            "apt_packages": "",
            "pip_requirements": "",
            "metrics_config": {},
            "public_eval_percentage": 50,
            "hf_datasets": "[]",
            "hf_models": "[]",
            "custom_eval_code": None,
            "challenge_id": 1,
            "metric_name": "accuracy",
            "hf_dataset_split": "test",
            "user_code": "print('hi')",
            "submission_id": "sub_docker_test",
            "main_server_url": "http://localhost:5000",
        }

    def _setup_mocks(self, mocker, docker_available=True):
        mock_docker_client = mocker.MagicMock()

        mocker.patch(
            "task_modules.submission_runner.check_docker_available",
            return_value=docker_available,
        )
        mocker.patch(
            "task_modules.submission_runner._get_client",
            return_value=mock_docker_client,
        )
        mocker.patch(
            "task_modules.submission_runner._image_exists_docker",
            return_value=True,
        )
        mocker.patch(
            "task_modules.submission_runner.report_status_to_server",
            return_value=True,
        )
        mocker.patch(
            "task_modules.submission_runner.get_redis_client",
            return_value=mocker.MagicMock(),
        )
        mocker.patch(
            "task_modules.submission_runner.download_task_files_to_dir",
            return_value=None,
        )

    def test_docker_not_available_returns_early(self, mocker):
        from task_modules.submission_runner import run_eval_submission

        self._setup_mocks(mocker, docker_available=False)
        result = run_eval_submission(
            self_task=None,
            submission_id="sub_docker_test",
            metadata=self._metadata(),
            app=None,
            db=None,
            submission_cls=None,
            challenge_cls=None,
        )
        assert result is None


class TestCodeCellsParseError:
    """Test that malformed code_cells JSON causes graceful failure."""

    def test_malformed_code_cells_json_returns_none(self, mocker):
        import json as _json

        from task_modules.submission_runner import run_eval_submission

        mock_docker_client = mocker.MagicMock()

        mocker.patch(
            "task_modules.submission_runner.check_docker_available",
            return_value=True,
        )
        mocker.patch(
            "task_modules.submission_runner._get_client",
            return_value=mock_docker_client,
        )
        mocker.patch(
            "task_modules.submission_runner._image_exists_docker",
            return_value=True,
        )
        mocker.patch(
            "task_modules.submission_runner.report_status_to_server",
            return_value=True,
        )
        mocker.patch(
            "task_modules.submission_runner.get_redis_client",
            return_value=mocker.MagicMock(),
        )
        mocker.patch(
            "task_modules.submission_runner.download_task_files_to_dir",
            return_value=None,
        )

        # Patch json.loads so the first call (code_cells parse) raises
        original_loads = _json.loads
        call_count = [0]

        def patched_loads(s, *a, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("Simulated malformed code_cells JSON")
            return original_loads(s, *a, **kw)

        mocker.patch("task_modules.submission_runner.json.loads", side_effect=patched_loads)

        metadata = {
            "task_id": 1,
            "time_limit": 30,
            "ram_limit": 4096,
            "gpu_required": False,
            "base_docker_image": "python:3.10-slim",
            "apt_packages": "",
            "pip_requirements": "",
            "metrics_config": {},
            "public_eval_percentage": 50,
            "hf_datasets": "[]",
            "hf_models": "[]",
            "custom_eval_code": None,
            "challenge_id": 1,
            "metric_name": "accuracy",
            "hf_dataset_split": "test",
            "user_code": "print('hi')",
            "submission_id": "sub_json_err",
            "main_server_url": "http://localhost:5000",
        }

        result = run_eval_submission(
            self_task=None,
            submission_id="sub_json_err",
            metadata=metadata,
            app=None,
            db=None,
            submission_cls=None,
            challenge_cls=None,
        )
        assert result is None


class TestEvaluationEngineImport:
    def test_import_evaluate_predictions_exists(self):
        assert callable(evaluate_predictions)

    def test_import_validate_parquet_schema_exists(self):
        assert callable(validate_parquet_schema)

    def test_available_metrics_has_expected_keys(self):
        assert "accuracy" in AVAILABLE_METRICS
        assert "f1" in AVAILABLE_METRICS
        assert "rmse" in AVAILABLE_METRICS
