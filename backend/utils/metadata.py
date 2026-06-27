import json
import os


def _hf_value(value):
    if isinstance(value, str):
        return value
    return json.dumps(value) if value else None


def build_submission_metadata(
    task,
    challenge,
    submission,
    user_code,
    task_files_list,
    gpu_required,
    main_server_url=None,
):
    return {
        "submission_id": submission.id,
        "task_id": task.id,
        "challenge_id": challenge.id,
        "user_code": user_code,
        "time_limit": task.time_limit_sec or challenge.time_limit_sec or 300,
        "ram_limit": task.ram_limit_mb or challenge.ram_limit_mb or 8192,
        "gpu_required": gpu_required,
        "base_docker_image": task.base_docker_image,
        "apt_packages": task.apt_packages,
        "pip_requirements": task.pip_requirements,
        "is_custom_eval": bool(
            task.custom_eval_code
            or task.evaluator_script_path
            and os.path.exists(task.evaluator_script_path)
        ),
        "metrics_config": task.metrics_config,
        "hf_datasets": _hf_value(task.hf_datasets),
        "hf_models": _hf_value(task.hf_models),
        "public_eval_percentage": (
            task.public_eval_percentage if task.public_eval_percentage is not None else 30
        ),
        "task_files": task_files_list,
        "main_server_url": (
            main_server_url or os.environ.get("MAIN_SERVER_URL", "http://localhost:5001")
        ),
        "celery_broker_url": os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    }
