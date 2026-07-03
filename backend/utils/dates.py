import logging
import zoneinfo
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


def parse_datetime(val):
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    try:
        if val.endswith("Z"):
            val = val[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(val)
        except ValueError:
            if "T" in val:
                val = val.split(".")[0]
            return datetime.strptime(val, "%Y-%m-%dT%H:%M:%S")
    except Exception as e:
        logger.warning("Failed to parse datetime string: %s", e)
    return None


def to_utc(dt, timezone_str="UTC"):
    if dt.tzinfo is not None:
        return dt.astimezone(zoneinfo.ZoneInfo("UTC")).replace(tzinfo=None)
    tz = zoneinfo.ZoneInfo(timezone_str)
    return dt.replace(tzinfo=tz).astimezone(zoneinfo.ZoneInfo("UTC")).replace(tzinfo=None)


def utcnow():
    """Return a naive datetime representing the current UTC time."""
    return datetime.now(UTC).replace(tzinfo=None)


def now_local_for_timezone(timezone_str):
    try:
        tz = zoneinfo.ZoneInfo(timezone_str or "UTC")
        return datetime.now(tz).replace(tzinfo=None)
    except Exception:
        return utcnow()
