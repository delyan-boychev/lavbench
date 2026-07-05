from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

from schemas.exceptions import SchemaError


def _coerce_bool(v: Any) -> bool:
    if isinstance(v, str):
        return v.lower() in ("true", "1", "yes", "on")
    return bool(v) if v is not None else False


def _coerce_int(v: Any, default: int | None = None) -> int | None:
    if v is None or str(v).strip() == "":
        return default
    return int(v)


APT_PACKAGE_RE = re.compile(r"^[a-zA-Z0-9.+-]+$")
PIP_REQUIREMENT_RE = re.compile(
    r"^[a-zA-Z0-9_.-]+(?:\s*(?:>=|<=|==|!=|~=|>|<)\s*[a-zA-Z0-9_.-]+"
    r"(?:\s*,\s*(?:>=|<=|==|!=|~=|>|<)\s*[a-zA-Z0-9_.-]+)*)?$"
)
DOCKER_IMAGE_RE = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*/?[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[a-zA-Z0-9_.-]+)?$"
)


def _validate_hf_json_list(
    v: Any, max_items: int = 5, err_code: str = "ERR_INVALID_HF_DATASETS"
) -> list[str] | None:
    if v is None or str(v).strip() == "":
        return None
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
        except json.JSONDecodeError:
            raise SchemaError(err_code, "Must be valid JSON.") from None
    else:
        parsed = v
    if not isinstance(parsed, list):
        raise SchemaError(err_code, "Must be a JSON array.")
    if len(parsed) > max_items:
        raise SchemaError(err_code, f"Maximum {max_items} items allowed.")
    for item in parsed:
        if not isinstance(item, str) or not item.strip():
            raise SchemaError(err_code, "Each item must be a non-empty string.")
    return parsed


def _validate_metrics_config_json(v: Any) -> dict[str, Any] | None:
    if v is None or str(v).strip() == "":
        return None
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
        except json.JSONDecodeError:
            raise SchemaError("ERR_INVALID_METRIC_CONFIG", "Must be valid JSON.") from None
    else:
        parsed = v
    if not isinstance(parsed, dict):
        raise SchemaError("ERR_INVALID_METRIC_CONFIG", "Must be a JSON object (dict).")
    if not parsed:
        raise SchemaError("ERR_INVALID_METRIC_CONFIG", "Must not be empty.")
    for metric_name, cfg in parsed.items():
        if not isinstance(metric_name, str) or not metric_name.strip():
            raise SchemaError(
                "ERR_INVALID_METRIC_CONFIG", "Each metric key must be a non-empty string."
            )
        if metric_name == "_columns":
            continue

        if not isinstance(cfg, dict) or "weight" not in cfg:
            raise SchemaError(
                "ERR_INVALID_METRIC_CONFIG",
                f"Metric '{metric_name}' config must be a dict with a 'weight' field.",
            )
        try:
            w = float(cfg["weight"])
        except (ValueError, TypeError):
            raise SchemaError(
                "ERR_INVALID_METRIC_CONFIG", f"Weight for metric '{metric_name}' must be numeric."
            ) from None
        if w < 0 or w > 1:
            raise SchemaError(
                "ERR_INVALID_METRIC_CONFIG",
                f"Weight for metric '{metric_name}' must be between 0 and 1.",
            )
        if "options" in cfg and not isinstance(cfg["options"], dict):
            raise SchemaError(
                "ERR_INVALID_METRIC_CONFIG", f"Options for metric '{metric_name}' must be a dict."
            )
    return parsed


class _TaskMetaValidators:
    @field_validator("gpu_required", "ban_magic_commands", mode="before")
    @classmethod
    def _coerce_bools(cls, v: Any) -> bool | None:
        if v is None:
            return None
        return _coerce_bool(v)

    @field_validator("public_eval_percentage", mode="before")
    @classmethod
    def _coerce_pct(cls, v: Any) -> int | None:
        if v is None or str(v).strip() == "":
            return None
        return _coerce_int(v)

    @field_validator(
        "ram_limit_mb",
        "time_limit_sec",
        "max_submissions_per_period",
        "submission_period_hours",
        mode="before",
    )
    @classmethod
    def _coerce_ints(cls, v: Any) -> int | None:
        if v is None or str(v).strip() == "":
            return None
        return _coerce_int(v)

    @field_validator("base_docker_image", mode="before")
    @classmethod
    def _validate_docker_image(cls, v: Any) -> str | None:
        if v is None or str(v).strip() == "":
            return None
        if not isinstance(v, str):
            raise SchemaError("ERR_INVALID_DOCKER_IMAGE", "Docker image must be a string.")
        if not DOCKER_IMAGE_RE.match(v):
            raise SchemaError("ERR_INVALID_DOCKER_IMAGE", f"Invalid Docker image format: '{v}'.")
        return v

    @field_validator("apt_packages", mode="before")
    @classmethod
    def _validate_apt_packages(cls, v: Any) -> str | None:
        if v is None or str(v).strip() == "":
            return None
        if not isinstance(v, str):
            raise SchemaError("ERR_INVALID_APT_PACKAGE", "APT packages must be a string.")
        for pkg in v.replace(",", " ").split():
            pkg = pkg.strip()
            if pkg and not APT_PACKAGE_RE.match(pkg):
                raise SchemaError("ERR_INVALID_APT_PACKAGE", f"Invalid APT package name: '{pkg}'.")
        return v

    @field_validator("pip_requirements", mode="before")
    @classmethod
    def _validate_pip_requirements(cls, v: Any) -> str | None:
        if v is None or str(v).strip() == "":
            return None
        if not isinstance(v, str):
            raise SchemaError("ERR_INVALID_PIP_REQUIREMENT", "Pip requirements must be a string.")
        for line in v.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not PIP_REQUIREMENT_RE.match(line):
                raise SchemaError(
                    "ERR_INVALID_PIP_REQUIREMENT", f"Invalid pip requirement: '{line}'."
                )
        return v

    @field_validator("hf_datasets", mode="before")
    @classmethod
    def _validate_hf_datasets(cls, v: Any) -> list[str] | None:
        return _validate_hf_json_list(v, max_items=5, err_code="ERR_INVALID_HF_DATASETS")

    @field_validator("hf_models", mode="before")
    @classmethod
    def _validate_hf_models(cls, v: Any) -> list[str] | None:
        return _validate_hf_json_list(v, max_items=5, err_code="ERR_INVALID_HF_MODELS")

    @field_validator("metrics_config", mode="before")
    @classmethod
    def _validate_metrics_config(cls, v: Any) -> dict[str, Any] | None:
        return _validate_metrics_config_json(v)


class _TaskMetaDeleteValidators:
    @field_validator("delete_evaluator", "delete_baseline", mode="before")
    @classmethod
    def _coerce_delete_bools(cls, v: Any) -> bool | None:
        if v is None:
            return None
        return _coerce_bool(v)


class _TaskMetaBase(_TaskMetaValidators, BaseModel):
    title: str = Field(..., min_length=1)
    description: str | None = Field(default=None)
    ram_limit_mb: int | None = Field(default=None, ge=128, le=8192)
    time_limit_sec: int | None = Field(default=None, ge=1)
    gpu_required: bool = False
    base_docker_image: str | None = Field(default=None)
    apt_packages: str | None = Field(default=None)
    pip_requirements: str | None = Field(default=None)
    ban_magic_commands: bool = False
    banned_imports: str | None = Field(default=None)
    whitelisted_imports: str | None = Field(default=None)
    hf_datasets: list[str] | None = Field(default=None)
    hf_models: list[str] | None = Field(default=None)
    metrics_config: dict[str, Any] | None = Field(default=None)
    public_eval_percentage: int | None = Field(default=None, ge=0, le=100)
    max_submissions_per_period: int | None = Field(default=None, ge=1)
    submission_period_hours: int | None = Field(default=None, ge=1)
    stage_id: str | None = Field(default=None)


class _TaskMetaUpdate(_TaskMetaValidators, _TaskMetaDeleteValidators, BaseModel):
    title: str | None = Field(default=None, min_length=1)
    description: str | None = Field(default=None)
    ram_limit_mb: int | None = Field(default=None, ge=128, le=8192)
    time_limit_sec: int | None = Field(default=None, ge=1)
    gpu_required: bool | None = Field(default=None)
    base_docker_image: str | None = Field(default=None)
    apt_packages: str | None = Field(default=None)
    pip_requirements: str | None = Field(default=None)
    ban_magic_commands: bool | None = Field(default=None)
    banned_imports: str | None = Field(default=None)
    whitelisted_imports: str | None = Field(default=None)
    hf_datasets: list[str] | None = Field(default=None)
    hf_models: list[str] | None = Field(default=None)
    metrics_config: dict[str, Any] | None = Field(default=None)
    public_eval_percentage: int | None = Field(default=None, ge=0, le=100)
    max_submissions_per_period: int | None = Field(default=None, ge=1)
    submission_period_hours: int | None = Field(default=None, ge=1)
    stage_id: str | None = Field(default=None)
    deleted_files: str | None = Field(default=None)
    delete_evaluator: bool | None = Field(default=None)
    delete_baseline: bool | None = Field(default=None)


class CreateTaskMetaSchema(_TaskMetaBase):
    pass


class UpdateTaskMetaSchema(_TaskMetaUpdate):
    pass
