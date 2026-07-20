from __future__ import annotations

import json
import os
import shutil
import tempfile
from typing import Any

from unidecode import unidecode


def sanitize_filename_part(text: str, replacement: str = "_") -> str:
    text = unidecode(text)
    text = "".join(
        c if c.isascii() and (c.isalnum() or c in (" ", "_", "-")) else replacement for c in text
    )
    text = "_".join(text.split())
    safe = text.strip("_") or "unnamed"
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe


def wrap_raw_code_cells(code_storage_path: str | None) -> bytes | None:
    """Wrap a raw code_cells JSON array file into notebook format without parsing.

    Streams the file 64KB at a time to avoid loading the entire cells file
    into memory (prevents OOM for large submissions).

    Returns notebook bytes, or None if the file is missing or not a valid array.
    """
    if not code_storage_path or not os.path.exists(code_storage_path):
        return None

    with open(code_storage_path, "rb") as f:
        start = f.read(1)
        f.seek(-1, os.SEEK_END)
        end = f.read(1)
        if start != b"[" or end != b"]":
            return None

    try:
        with (
            tempfile.NamedTemporaryFile(delete=True, suffix=".ipynb") as tmp,
            open(code_storage_path, "rb") as cf,
        ):
            tmp.write(b'{"cells":')
            shutil.copyfileobj(cf, tmp)
            tmp.write(
                b',"metadata":{"language_info":{"name":"python"}},"nbformat":4,"nbformat_minor":2}'
            )
            tmp.flush()
            tmp.seek(0)
            return tmp.read()
    except Exception:
        return None


def cells_to_ipynb_json(cells_data: list[Any], indent: int | None = None) -> str:
    ipynb_cells = []
    for c in cells_data:
        if isinstance(c, dict):
            source_lines = c.get("source", "")
            cell_type = c.get("type", "code") or c.get("cell_type", "code")
        else:
            source_lines = str(c)
            cell_type = "code"

        if isinstance(source_lines, str):
            source_lines = [line + "\n" for line in source_lines.splitlines()]
        ipynb_cells.append(
            {
                "cell_type": cell_type,
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": source_lines,
            }
        )

    notebook_json = {
        "cells": ipynb_cells,
        "metadata": {"language_info": {"name": "python"}},
        "nbformat": 4,
        "nbformat_minor": 2,
    }
    return json.dumps(notebook_json, indent=indent)
