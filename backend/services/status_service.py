"""Service status computed from worker heartbeats, broker queue depths and the database.

One snapshot feeds both ``GET /api/status`` (coarse, public) and
``GET /api/admin/system-status`` (detail). It never calls Celery ``inspect``.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any, get_args

from sqlalchemy import func

from config import Config
from models import Submission, db
from schemas.responses.status import StatusWord
from services.submission_status import ACTIVE_STATUSES, QUEUED, RUNNING, TERMINAL_STATUSES
from utils.cache_utils import (
    EVALUATION_PRIORITY_STEPS,
    cache_lock,
    get_cached,
    get_coordination_client,
    get_queue_depths,
    redis_time,
    set_cached,
)
from utils.dates import utcnow

logger = logging.getLogger(__name__)

CPU_QUEUE = "cpu_queue"
# Always listed, even without consumers; every CPU submission goes to cpu_queue
EVALUATION_QUEUES = (CPU_QUEUE, "gpu_queue")
STATUS_ORDER: tuple[str, ...] = get_args(StatusWord)
STATUS_CACHE_KEY = "status:system"
# The previous snapshot, kept for _STATUS_LAST_PERIODS cache periods, answers requests
# that miss the cache while another process holds the compute lock
STATUS_LAST_KEY = "status:system:last"
_STATUS_LAST_PERIODS = 10
_STATUS_LOCK_KEY = "lock:status:system"
_STATUS_LOCK_SECONDS = 30

_WORKER_SPEC_PATTERN = "worker_spec:*"
_RECENT_WINDOW = timedelta(minutes=15)

# First-level cache: the last snapshot this process saw, kept for what remains of its
# STATUS_CACHE_SECONDS, so requests do not recompute while the cache Redis is down
_local_lock = threading.Lock()
_local_snapshot: dict[str, Any] | None = None
_local_expires_at = 0.0


def _rfc3339(moment: datetime) -> str:
    """Format a naive UTC datetime as RFC 3339 with a ``Z`` suffix."""
    return moment.replace(microsecond=0).isoformat() + "Z"


def _epoch_rfc3339(epoch_seconds: float) -> str:
    return _rfc3339(datetime.fromtimestamp(epoch_seconds, UTC).replace(tzinfo=None))


def worst_status(*statuses: str) -> str:
    """Return the worst status word, ordered as in ``StatusWord``."""
    return max(statuses, key=STATUS_ORDER.index)


def _number(value: Any, cast: type[int] | type[float]) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return cast(value)


def _database_ok() -> bool:
    try:
        db.session.execute(db.text("SELECT 1"))
        return True
    except Exception as e:
        logger.warning("Status check: database unreachable: %s", e)
        db.session.rollback()
        return False


def _broker_client() -> Any | None:
    """Return the broker client when it answers PING, otherwise None."""
    client = get_coordination_client()
    if client is None:
        return None
    try:
        client.ping()
    except Exception as e:
        logger.warning("Status check: broker Redis unreachable: %s", e)
        return None
    return client


def _read_worker_specs(client: Any) -> list[tuple[str, dict[str, Any]]]:
    specs: list[tuple[str, dict[str, Any]]] = []
    try:
        for key in client.scan_iter(match=_WORKER_SPEC_PATTERN, count=200):
            raw = client.get(key)
            if not raw:
                continue
            try:
                spec = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if isinstance(spec, dict):
                key_name = key.decode("utf-8") if isinstance(key, bytes) else str(key)
                specs.append((key_name.removeprefix("worker_spec:"), spec))
    except Exception as e:
        logger.warning("Status check: reading worker heartbeats failed: %s", e)
    return specs


def _worker_entry(key_name: str, spec: dict[str, Any], now_epoch: float) -> dict[str, Any]:
    last_seen = _number(spec.get("last_seen"), float)
    online = last_seen is not None and now_epoch - last_seen < Config.WORKER_HEARTBEAT_STALE_SECONDS
    gpu_type = spec.get("gpu_type")
    return {
        "name": str(spec.get("name") or key_name),
        "type": "gpu" if str(spec.get("type", "")).upper() == "GPU" else "cpu",
        "queues": sorted(q for q in spec.get("queues") or [] if isinstance(q, str)),
        "online": online,
        "last_seen": _epoch_rfc3339(last_seen) if last_seen is not None else None,
        "concurrency": _number(spec.get("concurrency"), int),
        "cpu_cores": _number(spec.get("cpu_cores"), int),
        "ram_gb": _number(spec.get("ram_gb"), float),
        "gpu_type": gpu_type if isinstance(gpu_type, str) and gpu_type != "N/A" else None,
        "vram_gb": _number(spec.get("vram_gb"), float),
        # A worker on another version (or one too old to report it) misses priority lists
        "priority_steps_match": spec.get("priority_steps") == list(EVALUATION_PRIORITY_STEPS),
    }


def _queue_entries(client: Any | None, workers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """List the evaluation queues plus any queue a live worker reports."""
    live_queues = {q for w in workers if w["online"] for q in w["queues"]}
    names = list(EVALUATION_QUEUES) + sorted(live_queues - set(EVALUATION_QUEUES))
    depths = get_queue_depths(names) if client is not None else {}
    return [
        {
            "name": name,
            "consumers": sum(1 for w in workers if w["online"] and name in w["queues"]),
            "queued": depths.get(name, 0),
        }
        for name in names
    ]


def _submission_counts(now: datetime) -> dict[str, Any]:
    active = dict(
        db.session.query(Submission.status, func.count())
        .filter(Submission.status.in_(ACTIVE_STATUSES))
        .group_by(Submission.status)
        .all()
    )
    oldest_queued = (
        db.session.query(func.min(Submission.created_at))
        .filter(Submission.status == QUEUED)
        .scalar()
    )
    # A row stored without a finish time counts from its creation
    finished_since = func.coalesce(Submission.finished_at, Submission.created_at)
    recent = dict(
        db.session.query(Submission.status, func.count())
        .filter(
            Submission.status.in_(TERMINAL_STATUSES),
            finished_since >= now - _RECENT_WINDOW,
        )
        .group_by(Submission.status)
        .all()
    )
    return {
        "queued": int(active.get(QUEUED, 0)),
        "running": int(active.get(RUNNING, 0)),
        "oldest_queued_seconds": (
            max(0, int((now - oldest_queued).total_seconds())) if oldest_queued else None
        ),
        "completed_last_15m": int(recent.get("completed", 0)),
        "failed_last_15m": int(recent.get("failed", 0)),
    }


def _empty_submission_counts() -> dict[str, Any]:
    return {
        "queued": 0,
        "running": 0,
        "oldest_queued_seconds": None,
        "completed_last_15m": 0,
        "failed_last_15m": 0,
    }


def scoring_status(queues: list[dict[str, Any]], oldest_queued_seconds: int | None) -> str:
    """Apply the scoring component rules to the queue and submission figures."""
    by_name = {q["name"]: q for q in queues}
    if by_name.get(CPU_QUEUE, {}).get("consumers", 0) == 0:
        return "major_outage"
    for name in EVALUATION_QUEUES:
        queue = by_name.get(name)
        if name != CPU_QUEUE and queue and queue["queued"] > 0 and queue["consumers"] == 0:
            return "partial_outage"
    if (
        oldest_queued_seconds is not None
        and oldest_queued_seconds > Config.STATUS_QUEUE_DEGRADED_SECONDS
    ):
        return "degraded_performance"
    return "operational"


def compute_system_status() -> dict[str, Any]:
    """Compute a fresh snapshot shaped like ``SystemStatusResponse``."""
    now = utcnow()
    database_ok = _database_ok()
    client = _broker_client()
    # Heartbeats carry the broker's clock, so liveness is judged against the same clock
    now_epoch = redis_time(client) if client is not None else time.time()

    specs = _read_worker_specs(client) if client is not None else []
    workers = sorted(
        (_worker_entry(name, spec, now_epoch) for name, spec in specs),
        key=lambda w: w["name"],
    )
    for worker in workers:
        if worker["online"] and not worker["priority_steps_match"]:
            logger.warning(
                "Worker %s runs other queue priorities than this server; update it", worker["name"]
            )
    queues = _queue_entries(client, workers)
    submissions = _submission_counts(now) if database_ok else _empty_submission_counts()

    components = {
        "api": "operational" if database_ok and client is not None else "major_outage",
        "scoring": scoring_status(queues, submissions["oldest_queued_seconds"]),
    }
    return {
        "status": worst_status(*components.values()),
        "components": components,
        "queues": queues,
        "workers": workers,
        "submissions": submissions,
        "updated_at": _rfc3339(now),
    }


def _snapshot_age_seconds(snapshot: dict[str, Any]) -> float:
    """Seconds since the snapshot was computed, from its ``updated_at``; inf if unreadable."""
    try:
        updated = datetime.fromisoformat(str(snapshot["updated_at"]).removesuffix("Z"))
    except (KeyError, ValueError):
        return float("inf")
    return (utcnow() - updated).total_seconds()


def _local_get() -> dict[str, Any] | None:
    with _local_lock:
        if _local_snapshot is not None and time.monotonic() < _local_expires_at:
            return _local_snapshot
    return None


def _local_put(snapshot: dict[str, Any]) -> None:
    """Keep the snapshot in this process for the rest of its STATUS_CACHE_SECONDS."""
    global _local_snapshot, _local_expires_at
    remaining = Config.STATUS_CACHE_SECONDS - _snapshot_age_seconds(snapshot)
    if remaining <= 0:
        return
    with _local_lock:
        _local_snapshot = snapshot
        _local_expires_at = time.monotonic() + remaining


def system_status() -> dict[str, Any]:
    """Return the snapshot, cached for STATUS_CACHE_SECONDS and computed by one process at a time.

    ``GET /api/status`` needs no login, so a cache miss must not let every request run
    the database aggregates and broker reads at once. The process-local copy answers
    first, also while the cache Redis is down; the shared Redis cache and its lock
    are the second level.
    """
    snapshot = _local_get()
    if snapshot is None:
        snapshot = _shared_status()
        _local_put(snapshot)
    return snapshot


def _shared_status() -> dict[str, Any]:
    """Read the shared snapshot, or compute it under the broker lock.

    A request that misses while another process computes gets the previous snapshot;
    only when there is none does it compute as well, so the endpoint always answers.
    """
    cached: dict[str, Any] | None = get_cached(STATUS_CACHE_KEY)
    if cached is not None:
        return cached
    with cache_lock(_STATUS_LOCK_KEY, ttl=_STATUS_LOCK_SECONDS) as got:
        # The lock holder re-checks, as another process may have stored a snapshot since
        # the miss; a request without the lock falls back to the previous snapshot
        cached = get_cached(STATUS_CACHE_KEY if got else STATUS_LAST_KEY)
        if cached is not None:
            return cached
        snapshot = compute_system_status()
        set_cached(STATUS_CACHE_KEY, snapshot, timeout=Config.STATUS_CACHE_SECONDS)
        set_cached(
            STATUS_LAST_KEY, snapshot, timeout=_STATUS_LAST_PERIODS * Config.STATUS_CACHE_SECONDS
        )
        return snapshot


def public_status() -> dict[str, Any]:
    """Return the public projection: overall word, components and time only."""
    snapshot = system_status()
    return {
        "status": snapshot["status"],
        "components": snapshot["components"],
        "updated_at": snapshot["updated_at"],
    }
