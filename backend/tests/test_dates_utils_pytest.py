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


class TestLocalDayStartUtc:
    def test_sofia_after_local_midnight(self):
        from datetime import datetime

        from utils.dates import local_day_start_utc

        # 01:30 UTC on 15 Nov is 03:30 in Sofia (UTC+2); its midnight is 22:00 UTC on 14 Nov
        start = local_day_start_utc("Europe/Sofia", now=datetime(2026, 11, 15, 1, 30))
        assert start == datetime(2026, 11, 14, 22, 0)

    def test_sofia_before_local_midnight(self):
        from datetime import datetime

        from utils.dates import local_day_start_utc

        # 21:30 UTC on 14 Nov is 23:30 in Sofia, still 14 Nov there
        start = local_day_start_utc("Europe/Sofia", now=datetime(2026, 11, 14, 21, 30))
        assert start == datetime(2026, 11, 13, 22, 0)

    def test_summer_time_offset(self):
        from datetime import datetime

        from utils.dates import local_day_start_utc

        # Sofia is UTC+3 in July
        start = local_day_start_utc("Europe/Sofia", now=datetime(2026, 7, 1, 12, 0))
        assert start == datetime(2026, 6, 30, 21, 0)

    def test_utc_and_unknown_timezones_use_utc_midnight(self):
        from datetime import datetime

        from utils.dates import local_day_start_utc

        now = datetime(2026, 11, 15, 1, 30)
        assert local_day_start_utc("UTC", now=now) == datetime(2026, 11, 15, 0, 0)
        assert local_day_start_utc(None, now=now) == datetime(2026, 11, 15, 0, 0)
        assert local_day_start_utc("Not/AZone", now=now) == datetime(2026, 11, 15, 0, 0)
