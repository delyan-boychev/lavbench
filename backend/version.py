from __future__ import annotations

import os
import tomllib
from typing import Any


def _get_version() -> str:
    base = os.path.dirname(os.path.abspath(__file__))
    pyproject_path = os.path.join(base, "pyproject.toml")
    try:
        with open(pyproject_path, "rb") as f:
            data: dict[str, Any] = tomllib.load(f)
        return str(data["project"]["version"])
    except Exception:
        return "0.0.0"


__version__ = _get_version()
