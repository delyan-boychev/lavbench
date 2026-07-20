from __future__ import annotations

import json
from typing import Any


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
