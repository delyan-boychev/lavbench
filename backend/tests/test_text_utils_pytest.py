"""Tests for Bulgarian transliteration, task folder names and run log tails."""

import pytest

from utils.text import (
    LOG_CUT_MARKER,
    is_valid_folder_name,
    keep_log_tail,
    numbered_folder_name,
    task_folder_name,
    transliterate_bulgarian,
)


def test_transliterates_bulgarian():
    assert transliterate_bulgarian("Щастие Юли") == "shtastie yuli"


@pytest.mark.parametrize(
    ("title", "folder"),
    [
        ("Image Classification", "image-classification"),
        ("Класификация на изображения", "klasifikatsiya-na-izobrazheniya"),
        ("  Task #1: Spam / Ham!  ", "task-1-spam-ham"),
        ("a" * 60, "a" * 40),
        ("!!!", "task"),
        ("Models", "task"),
    ],
)
def test_folder_name_from_title(title, folder):
    assert task_folder_name(title) == folder
    assert is_valid_folder_name(folder)


def test_folder_name_is_trimmed_without_a_trailing_hyphen():
    name = task_folder_name("x" * 39 + " yz")
    assert name == "x" * 39


@pytest.mark.parametrize(
    "name", ["", "Upper", "two--dashes", "-lead", "models", "datasets", "a" * 41]
)
def test_invalid_folder_names(name):
    assert not is_valid_folder_name(name)


def test_numbered_folder_name_stays_within_the_limit():
    assert numbered_folder_name("spam-filter", 2) == "spam-filter-2"
    assert numbered_folder_name("a" * 40, 12) == "a" * 37 + "-12"
    assert numbered_folder_name("a" * 37 + "-bc", 2) == "a" * 37 + "-2"
    assert is_valid_folder_name(numbered_folder_name("x" * 40, 99))


def test_keep_log_tail_keeps_the_end_and_says_so():
    tail = keep_log_tail("a" * 150 + "THE END", 100)
    assert len(tail) == 100
    assert tail.startswith(LOG_CUT_MARKER + "\n")
    assert tail.endswith("THE END")


def test_keep_log_tail_leaves_a_short_log_alone():
    assert keep_log_tail("short", 100) == "short"


def test_keep_log_tail_marks_a_log_whose_lines_were_dropped():
    assert keep_log_tail("last lines", 100, cut=True) == f"{LOG_CUT_MARKER}\nlast lines"


def test_keep_log_tail_is_idempotent():
    once = keep_log_tail("b" * 300, 120)
    assert keep_log_tail(once, 120) == once
    assert keep_log_tail(once, 120, cut=True) == once
