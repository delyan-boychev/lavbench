"""Pydantic schemas for the competition workspace setting and nanoColab environments."""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from config import Config
from schemas.common import _parse_datetime_strict
from schemas.exceptions import SchemaError

IMAGE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{0,62}$")
PROFILE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
GIB = 1024**3
# The CPU disk range nanoColab accepts; the disk is the work space plus the task data
MIN_DISK_GIB = 10
MAX_DISK_GIB = 100
WORKSPACE_DEFAULT_GIB = 10
WORKSPACE_MIN_GIB = MIN_DISK_GIB
WORKSPACE_MAX_GIB = max(
    WORKSPACE_MIN_GIB, MAX_DISK_GIB - math.ceil(Config.NANOCOLAB_PACKAGE_MAX_BYTES / GIB)
)


# Used when nanoColab's image listing has no profiles yet
DEFAULT_PROFILES: tuple[dict[str, Any], ...] = (
    {"id": "cpu-compact", "name": "CPU Compact", "cpu_cores": 2, "memory_gib": 8},
    {"id": "cpu-standard", "name": "CPU Standard", "cpu_cores": 2, "memory_gib": 12},
)


def workspace_size_error() -> SchemaError:
    return SchemaError(
        "ERR_INVALID_WORKSPACE_SIZE",
        f"Storage per student must be between {WORKSPACE_MIN_GIB} and {WORKSPACE_MAX_GIB} GiB.",
        min=WORKSPACE_MIN_GIB,
        max=WORKSPACE_MAX_GIB,
    )


class WorkspaceSettingSchema(BaseModel):
    """The competition's student workspaces; every stage derives its environment from it."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    image_id: str = ""
    profile_id: str = ""
    workspace_gib: int = WORKSPACE_DEFAULT_GIB
    auto_publish: bool = False
    archive_until: datetime | None = None

    @field_validator("image_id", mode="after")
    @classmethod
    def _check_image(cls, v: str) -> str:
        if v and not IMAGE_ID_PATTERN.fullmatch(v):
            raise SchemaError("ERR_INVALID_WORKSPACE_IMAGE", "Choose an image from the list.")
        return v

    @field_validator("profile_id", mode="after")
    @classmethod
    def _check_profile(cls, v: str) -> str:
        if v and not PROFILE_ID_PATTERN.fullmatch(v):
            names = ", ".join(profile["name"] for profile in DEFAULT_PROFILES)
            raise SchemaError(
                "ERR_INVALID_WORKSPACE_PROFILE",
                f"Machine must be one of: {names}.",
                allowed=names,
            )
        return v

    @field_validator("workspace_gib", mode="before")
    @classmethod
    def _check_size(cls, v: Any) -> int:
        if isinstance(v, bool) or not isinstance(v, int):
            raise workspace_size_error()
        if not WORKSPACE_MIN_GIB <= v <= WORKSPACE_MAX_GIB:
            raise workspace_size_error()
        return v

    @field_validator("archive_until", mode="before")
    @classmethod
    def _parse_archive_until(cls, v: Any) -> datetime | None:
        return _parse_datetime_strict(v)


class ExtendEnvironmentSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    end_time: datetime
    reason: str = ""

    @field_validator("end_time", mode="before")
    @classmethod
    def _parse_end(cls, v: Any) -> datetime | None:
        return _parse_datetime_strict(v)

    @field_validator("reason", mode="after")
    @classmethod
    def _check_reason(cls, v: str) -> str:
        v = v.strip()
        # The reason goes to nanoColab, which needs 8 to 2000 characters
        if not 8 <= len(v) <= 2000:
            raise SchemaError("ERR_REASON_REQUIRED", "Give a reason of 8 to 2000 characters.")
        return v
