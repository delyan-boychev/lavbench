"""Application version, read once from backend/pyproject.toml."""

from __future__ import annotations

import tomllib
from pathlib import Path

# The single source of the version: /api/health and the OpenAPI document both report it
PYPROJECT_PATH = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _get_version() -> str:
    with PYPROJECT_PATH.open("rb") as f:
        return str(tomllib.load(f)["project"]["version"])


__version__ = _get_version()
