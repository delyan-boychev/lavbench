"""Text helpers: Bulgarian transliteration and task folder names."""

from __future__ import annotations

import re
import unicodedata

_BULGARIAN_TO_LATIN = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sht",
    "ъ": "a",
    "ь": "y",
    "ю": "yu",
    "я": "ya",
}

FOLDER_NAME_MAX_LENGTH = 40
FOLDER_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# The workspace root also holds the shared Hugging Face folders
RESERVED_FOLDER_NAMES = frozenset({"models", "datasets"})
DEFAULT_FOLDER_NAME = "task"


def transliterate_bulgarian(text: str) -> str:
    """Lower-case the text and spell Bulgarian letters in Latin."""
    if not text:
        return ""
    return "".join(_BULGARIAN_TO_LATIN.get(c, c) for c in text.lower())


def task_folder_name(title: str) -> str:
    """Derive a workspace folder name such as ``image-classification`` from a task title."""
    slug = re.sub(r"[^a-z0-9]+", "-", transliterate_bulgarian(title)).strip("-")
    slug = slug[:FOLDER_NAME_MAX_LENGTH].strip("-")
    if not slug or slug in RESERVED_FOLDER_NAMES:
        return DEFAULT_FOLDER_NAME
    return slug


def numbered_folder_name(name: str, number: int) -> str:
    """``name-<number>``, trimming the name so the result stays within the length limit."""
    suffix = f"-{number}"
    return f"{name[: FOLDER_NAME_MAX_LENGTH - len(suffix)].rstrip('-')}{suffix}"


def is_valid_folder_name(name: str) -> bool:
    return (
        len(name) <= FOLDER_NAME_MAX_LENGTH
        and bool(FOLDER_NAME_RE.fullmatch(name))
        and name not in RESERVED_FOLDER_NAMES
    )


_RESERVED_PART = re.compile(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?")


def is_safe_path(path: str) -> bool:
    """The path rules nanoColab applies to every package entry (``asset_zip.safe_path``)."""
    if (
        not path
        or len(path) > 512
        or unicodedata.normalize("NFC", path) != path
        or "\\" in path
        or ":" in path
        or any(ord(c) < 32 or ord(c) == 127 for c in path)
    ):
        return False
    return all(
        part
        and not part.startswith(".")
        and not part.endswith((".", " "))
        and not _RESERVED_PART.fullmatch(part)
        for part in path.split("/")
    )
