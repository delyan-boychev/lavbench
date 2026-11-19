"""Submission metadata builders."""

from __future__ import annotations

import json
import math
import os
from typing import Any

from config import Config
from utils.split_key import derive_task_split_key

# Syncing the labels, reading the predictions and the built-in metrics, in either mode
SCORING_BASE_SECONDS = 120
# Fetching and extracting a Hugging Face ZIP: a base plus two passes at a pessimistic rate
HF_PREP_BASE_SECONDS = 60
HF_PREP_BYTES_PER_SECOND = 20 * 1024 * 1024


def hf_prep_seconds(zip_size: int | None) -> int:
    """Extra seconds a run may spend on its HF ZIP: 60 + 2 * size / (20 MiB/s)."""
    if not zip_size:
        return 0
    return HF_PREP_BASE_SECONDS + math.ceil(2 * int(zip_size) / HF_PREP_BYTES_PER_SECOND)


def run_hf_zip(task: Any) -> str | None:
    """The HF ZIP a run of *task* mounts: notebook runs only."""
    if task.is_file_mode:
        return None
    sha256: str | None = task.hf_zip_sha256
    return sha256


def scoring_time_budget(task: Any) -> int:
    """Seconds the scoring step may take: a base plus one evaluator run per option set."""
    from services.evaluation import AVAILABLE_METRICS

    runs: set[str] = set()
    metrics = task.metrics_config
    if isinstance(metrics, str):
        metrics = json.loads(metrics or "{}")
    if task.custom_eval_code and isinstance(metrics, dict):
        for name, cfg in metrics.items():
            if name.startswith("_") or name.lower().strip() in AVAILABLE_METRICS:
                continue
            options = cfg.get("options", {}) if isinstance(cfg, dict) else {}
            runs.add(json.dumps(options, sort_keys=True, default=str))
    return SCORING_BASE_SECONDS + len(runs) * Config.CUSTOM_EVALUATOR_TIME_LIMIT_SECONDS


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
    # enforce the same limit even if the task config changes mid-run
    submission.time_limit_snapshot = time_limit
    hf_sha256 = run_hf_zip(task)
    submission.hf_zip_sha256 = hf_sha256
    return {
        "submission_id": submission.id,
        "attempt_id": submission.celery_task_id,
        "task_id": task.id,
        "challenge_id": challenge.id,
        "evaluation_mode": task.evaluation_mode,
        "artifact_sha256": submission.artifact_sha256,
        "artifact_size": submission.artifact_size,
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
        # worker fetches them on demand via a signed request right before
        # execution, keeping Celery messages small
        "metrics_config": task.metrics_config,
        "hf_zip_sha256": hf_sha256,
        "hf_zip_size": task.hf_zip_size if hf_sha256 else None,
        "hf_unpacked_bytes": task.hf_unpacked_bytes if hf_sha256 else None,
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
