"""Every machine reason a refusal sends has its own English and Bulgarian text."""

import ast
import json
import os

import pytest

from services.environment_package import MAX_ENTRIES, PackageError, check_caps

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCALES = os.path.join(BACKEND, "..", "frontend", "public", "locales")
SOURCES = (
    "services/hf_zip.py",
    "services/parquet_check_child.py",
    "services/file_submission.py",
    "services/environment_package.py",
)


def _text(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _reasons():
    found = set()
    for source in SOURCES:
        with open(os.path.join(BACKEND, source), encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", getattr(node.func, "attr", ""))
                if name in ("HfZipError", "RefusedError") and len(node.args) > 1:
                    found.add(_text(node.args[1]))
                found.update(_text(k.value) for k in node.keywords if k.arg == "reason")
            if isinstance(node, ast.Dict):
                found.update(
                    _text(value)
                    for key, value in zip(node.keys, node.values, strict=True)
                    if key is not None and _text(key) == "reason"
                )
    found.discard(None)
    return found


def test_the_sources_send_reasons():
    assert {
        "outside_folders",
        "ids_mismatch",
        "package_files",
        "no_labels",
    } <= _reasons()


@pytest.mark.parametrize("language", ["en", "bg"])
def test_every_reason_has_a_text(language):
    with open(os.path.join(LOCALES, language, "translation.json"), encoding="utf-8") as handle:
        texts = json.load(handle)["api_reasons"]
    assert _reasons() <= set(texts)
    assert all(texts[reason].strip() for reason in _reasons())


def test_the_file_cap_sends_numbers_and_its_reason():
    with pytest.raises(PackageError) as raised:
        check_caps(MAX_ENTRIES + 1, 0)
    assert raised.value.fields == {
        "limit": str(MAX_ENTRIES),
        "detail": str(MAX_ENTRIES + 1),
        "reason": "package_files",
    }
