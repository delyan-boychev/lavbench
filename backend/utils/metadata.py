"""Submission metadata builders."""

from __future__ import annotations

import json
import os
from typing import Any

from config import Config
from services.evaluation import derive_task_split_key


def _hf_value(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    return json.dumps(value) if value else None


def build_submission_metadata(
    task: Any,
    challenge: Any,
    submission: Any,
    task_files_list: list[dict[str, Any]],
    gpu_required: bool,
    main_server_url: str | None = None,
) -> dict[str, Any]:
    time_limit = task.time_limit_sec or challenge.time_limit_sec or Config.DEFAULT_TIME_LIMIT_SEC
    # Persist the dispatch-time limit so the server watchdog and the runner
    # Enforce the same limit even if the task config changes mid-run
    submission.time_limit_snapshot = time_limit
    return {
        "submission_id": submission.id,
        "attempt_id": submission.celery_task_id,
        "task_id": task.id,
        "challenge_id": challenge.id,
        "time_limit": time_limit,
        "ram_limit": task.ram_limit_mb or challenge.ram_limit_mb or Config.DEFAULT_RAM_LIMIT_MB,
        "gpu_required": gpu_required,
        "base_docker_image": task.base_docker_image,
        "apt_packages": task.apt_packages,
        "pip_requirements": task.pip_requirements,
        "is_custom_eval": bool(
            task.custom_eval_code
            or (task.evaluator_script_path and os.path.exists(task.evaluator_script_path))
        ),
        # User_code and custom_eval_code are NOT embedded here — the
        # Worker fetches them on demand via a signed request right before
        # Execution, keeping Celery messages small
        "metrics_config": task.metrics_config,
        "hf_datasets": _hf_value(task.hf_datasets),
        "hf_models": _hf_value(task.hf_models),
        "public_eval_percentage": (
            task.public_eval_percentage
            if task.public_eval_percentage is not None
            else Config.DEFAULT_PUBLIC_EVAL_PERCENTAGE
        ),
        "evaluation_split_key": derive_task_split_key(Config.EVALUATION_SPLIT_SECRET, task.id),
        "task_files": task_files_list,
        "is_unified_parquet": any(
            isinstance(f, dict) and f.get("filename") == "labels.parquet" for f in task_files_list
        ),
        "main_server_url": (main_server_url or Config.MAIN_SERVER_URL),
        "celery_broker_url": Config.CELERY_BROKER_URL,
    }
