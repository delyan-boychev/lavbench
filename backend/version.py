import os
import tomllib


def _get_version():
    base = os.path.dirname(os.path.abspath(__file__))
    pyproject_path = os.path.join(base, "pyproject.toml")
    try:
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        return data["project"]["version"]
    except Exception:
        return "0.0.0"


__version__ = _get_version()
