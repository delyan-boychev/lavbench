"""Tests for utils.dates timezone helpers."""

from datetime import datetime

import pytest

from utils.dates import is_valid_timezone, to_tz_iso


@pytest.mark.parametrize("name", ["UTC", "Europe/Sofia", "America/New_York", "Asia/Tokyo"])
def test_is_valid_timezone_accepts_iana_names(name):
    assert is_valid_timezone(name) is True


@pytest.mark.parametrize(
    "name",
    ["Not/AZone", "Europe/Atlantis", "UTC+2", "", "  ", "utc/", None, 42],
)
def test_is_valid_timezone_rejects_everything_else(name):
    assert is_valid_timezone(name) is False


def test_to_tz_iso_converts_naive_utc_to_target_zone():
    result = to_tz_iso(datetime(2026, 1, 15, 12, 0, 0), "Europe/Sofia")
    assert result.startswith("2026-01-15T14:00:00")
    assert result.endswith("+02:00")


def test_to_tz_iso_falls_back_to_utc_for_a_corrupt_stored_zone(caplog):
    """A row written before validation existed must still serialize, not raise."""
    result = to_tz_iso(datetime(2026, 1, 15, 12, 0, 0), "Not/AZone")
    assert result == "2026-01-15T12:00:00+00:00"
    assert "Invalid stored timezone" in caplog.text
