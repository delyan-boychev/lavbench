"""Tests for the comment-style checker's capital-letter rule (W1)."""

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_comments.py"


@pytest.fixture
def checker():
    spec = importlib.util.spec_from_file_location("check_comments", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _w1_lines(checker, tmp_path, source):
    path = tmp_path / "sample.py"
    path.write_text(source, encoding="utf-8")
    checker.check_comment_tokens(path)
    return [line for _, line, msg in checker.WARNINGS if "capital letter" in msg]


def test_continuation_lines_may_start_lower_case(checker, tmp_path):
    source = "# The first line starts the sentence and\n# the second line continues it\nx = 1\n"
    assert _w1_lines(checker, tmp_path, source) == []


def test_first_line_of_a_block_must_be_capitalised(checker, tmp_path):
    source = "x = 1\n# lower-case start\n# continued here\n"
    assert _w1_lines(checker, tmp_path, source) == [2]


def test_a_trailing_comment_does_not_start_a_block(checker, tmp_path):
    source = "x = 1  # Trailing note\n# lower-case start of a new block\n"
    assert _w1_lines(checker, tmp_path, source) == [2]


def test_a_gap_or_a_new_indent_starts_a_new_block(checker, tmp_path):
    source = "# First block\n\n# after a blank line\ndef f():\n    # indented start\n    return 1\n"
    assert _w1_lines(checker, tmp_path, source) == [3, 5]
