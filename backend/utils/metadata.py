from __future__ import annotations

import json
import os
from typing import Any

from config import Config


def _hf_value(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    return json.dumps(value) if value else None


def build_submission_metadata(
    task: Any,
    challenge: Any,
    submission: Any,
    user_code: str,
    task_files_list: list[dict[str, Any]],
    gpu_required: bool,
    main_server_url: str | None = None,
) -> dict[str, Any]:
    return {
        "submission_id": submission.id,
        "task_id": task.id,
        "challenge_id": challenge.id,
        "user_code": user_code,
        "time_limit": (
            task.time_limit_sec or challenge.time_limit_sec or Config.DEFAULT_TIME_LIMIT_SEC
        ),
        "ram_limit": task.ram_limit_mb or challenge.ram_limit_mb or Config.DEFAULT_RAM_LIMIT_MB,
        "gpu_required": gpu_required,
        "base_docker_image": task.base_docker_image,
        "apt_packages": task.apt_packages,
        "pip_requirements": task.pip_requirements,
        "is_custom_eval": bool(
            task.custom_eval_code
            or (task.evaluator_script_path and os.path.exists(task.evaluator_script_path))
        ),
        "custom_eval_code": (
            task.custom_eval_code
            if task.custom_eval_code
            else (
                open(task.evaluator_script_path).read()
                if task.evaluator_script_path and os.path.exists(task.evaluator_script_path)
                else None
            )
        ),
        "metrics_config": task.metrics_config,
        "hf_datasets": _hf_value(task.hf_datasets),
        "hf_models": _hf_value(task.hf_models),
        "public_eval_percentage": (
            task.public_eval_percentage
            if task.public_eval_percentage is not None
            else Config.DEFAULT_PUBLIC_EVAL_PERCENTAGE
        ),
        "task_files": task_files_list,
        "main_server_url": (main_server_url or Config.MAIN_SERVER_URL),
        "celery_broker_url": Config.CELERY_BROKER_URL,
    }
