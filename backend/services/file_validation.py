"""Validate uploaded submission files."""

from __future__ import annotations

import json
from typing import Any

KNOWN_DANGEROUS_EXTENSIONS = {
    ".exe",
    ".com",
    ".bat",
    ".cmd",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".vbs",
    ".scr",
    ".jar",
    ".class",
    ".elf",
    ".dll",
    ".so",
    ".dylib",
    ".app",
    ".msi",
    ".bin",
}


def validate_extension(filename: str, allowed_extensions: set[str]) -> tuple[bool, str | None]:
    """Case-insensitive extension check. Returns (is_valid, error_msg)."""
    if not filename or "." not in filename:
        return False, "Filename has no extension."
    ext = filename.rsplit(".", 1)[1].lower()
    dot_ext = "." + ext
    if dot_ext not in allowed_extensions:
        return (
            False,
            f"File extension '.{ext}' is not allowed. Allowed: {', '.join(allowed_extensions)}",
        )
    return True, None


def validate_notebook_content(
    content_bytes: bytes,
) -> tuple[bool, str | None, dict[str, Any] | None]:
    """Validate that content is a valid Jupyter Notebook JSON structure.
    Returns (is_valid, error_msg, parsed_notebook)."""
    try:
        text = content_bytes.decode("utf-8")
        notebook = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return False, f"Invalid JSON: {e}", None

    if not isinstance(notebook, dict):
        return False, "Notebook must be a JSON object.", None
    if "cells" in notebook and not isinstance(notebook["cells"], list):
        return False, "Notebook 'cells' must be an array.", None
    cells = notebook.get("cells", [])
    required_keys = {"cell_type", "source"}
    for i, cell in enumerate(cells):
        if not isinstance(cell, dict):
            return False, f"Cell at index {i} must be an object.", None
        if not required_keys.issubset(cell.keys()):
            missing = required_keys - cell.keys()
            return False, f"Cell at index {i} missing keys: {missing}", None
        if cell.get("cell_type") not in ("code", "markdown", "raw"):
            return (
                False,
                f"Cell at index {i} has invalid cell_type '{cell.get('cell_type')}'",
                None,
            )
    return True, None, notebook


def validate_csv_content(content_bytes: bytes) -> tuple[bool, str | None, str | None]:
    """Validate that content is valid CSV with text content."""
    try:
        text = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return False, "CSV must be a UTF-8 encoded text file.", None
    if not text.strip():
        return False, "CSV file is empty.", None
    return True, None, text


def check_dangerous_extension(filename: str) -> bool:
    """Check if the filename has a known dangerous extension."""
    ext = "." + filename.rsplit(".", 1)[1].lower() if "." in filename else ""
    return ext in KNOWN_DANGEROUS_EXTENSIONS
