"""Timezone-aware datetime parsing and formatting helpers."""

from __future__ import annotations

import logging
import zoneinfo
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


def to_utc(dt: datetime, timezone_str: str = "UTC") -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(zoneinfo.ZoneInfo("UTC")).replace(tzinfo=None)
    tz = zoneinfo.ZoneInfo(timezone_str)
    return dt.replace(tzinfo=tz).astimezone(zoneinfo.ZoneInfo("UTC")).replace(tzinfo=None)


def to_tz_iso(dt: datetime, timezone_str: str = "UTC") -> str:
    """Convert a naive UTC datetime to the given timezone and return ISO string with offset."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=zoneinfo.ZoneInfo("UTC"))
    try:
        timezone = zoneinfo.ZoneInfo(timezone_str)
    except zoneinfo.ZoneInfoNotFoundError:
        logger.warning("Invalid stored timezone %r; serializing in UTC", timezone_str)
        timezone = zoneinfo.ZoneInfo("UTC")
    return dt.astimezone(timezone).isoformat()


def is_valid_timezone(timezone_str: str) -> bool:
    """Return whether a string identifies an installed IANA timezone."""
    try:
        zoneinfo.ZoneInfo(timezone_str)
    except (TypeError, ValueError, zoneinfo.ZoneInfoNotFoundError):
        return False
    return True


def utcnow() -> datetime:
    """Return a naive datetime representing the current UTC time."""
    return datetime.now(UTC).replace(tzinfo=None)


def local_day_start_utc(timezone_str: str | None, now: datetime | None = None) -> datetime:
    """Return the latest local midnight in ``timezone_str`` as a naive UTC datetime.

    Daily quotas reset at midnight in the challenge's timezone, not at UTC midnight.
    An unknown timezone falls back to UTC.
    """
    try:
        tz = zoneinfo.ZoneInfo(timezone_str or "UTC")
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        tz = zoneinfo.ZoneInfo("UTC")
    current = (now or utcnow()).replace(tzinfo=UTC).astimezone(tz)
    midnight = current.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(UTC).replace(tzinfo=None)
