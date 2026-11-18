"""Celery task for system maintenance — cleanup, watchdog, diagnostics."""

from __future__ import annotations

import contextlib
import glob
import json
import logging
import os
import shutil
import subprocess
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any

from flask import Flask

from config import Config
from utils.dates import utcnow

logger = logging.getLogger(__name__)


_GIB = 1024**3
# Rotated application logs (``backend.log.1`` ... ``backend.log.6``) stay out of backups
_ROTATED_LOG_PATTERN = "*.log.[0-9]*"

# Start time of the last successful automatic backup (any kind) and of the last full one;
# They live on the broker Redis, which never evicts (the cache instance runs volatile-lru)
LAST_AUTO_BACKUP_KEY = "backup:last_auto"
LAST_FULL_BACKUP_KEY = "backup:last_auto_full"
# Held from dispatch until the automatic backup ends, so the scheduler never queues a
# Duplicate; its value is the backup's scheduled time, which the backup releases it with
BACKUP_DISPATCH_KEY = "backup:auto_dispatched"


def backup_dispatch_ttl() -> int:
    """Lifetime of the dispatch claim: frees the schedule when a backup never finishes.

    pg_dump is bounded by BACKUP_TIMEOUT and tar by BACKUP_UPLOADS_TIMEOUT for a full
    backup; the rest covers the queue wait and the audit log dump.
    """
    return Config.BACKUP_TIMEOUT + _tar_timeout() + 600


def _tar_timeout() -> int:
    """One bound for every archive, so the dispatch claim always outlives it."""
    return max(Config.BACKUP_TIMEOUT, Config.BACKUP_UPLOADS_TIMEOUT)


def release_backup_dispatch(scheduled_at: str) -> None:
    """Release the dispatch claim, unless a later dispatch already holds it."""
    from utils.cache_utils import delete_if_value, get_coordination_client

    r = get_coordination_client()
    if not r:
        return
    try:
        delete_if_value(r, BACKUP_DISPATCH_KEY, scheduled_at)
    except Exception as e:
        logger.warning("Failed to release the backup dispatch claim: %s", e)


def _record_auto_backup(db_only: bool, started_at: str) -> None:
    """Mark an automatic backup as done; only a written archive gets here.

    The marker holds the scheduled start, not the finish time, so the 20 min cadence
    does not drift by the backup's duration.
    """
    from utils.cache_utils import get_coordination_client

    r = get_coordination_client()
    if not r:
        return
    marker_ttl = max(86400, 2 * Config.BACKUP_UPLOADS_INTERVAL_SECONDS)
    try:
        r.set(LAST_AUTO_BACKUP_KEY, started_at, ex=marker_ttl)
        if not db_only:
            r.set(LAST_FULL_BACKUP_KEY, started_at, ex=marker_ttl)
    except Exception as e:
        logger.warning("Failed to record the automatic backup marker: %s", e)


def _auto_backup_pattern(backup_dir: str, db_only: bool) -> str:
    return os.path.join(backup_dir, "auto_db_*.tar.gz" if db_only else "auto_*.tar.gz")


def _auto_backups(backup_dir: str, db_only: bool) -> list[str]:
    """Return the automatic backups of one kind, oldest first.

    Database-only and full backups rotate separately, so the frequent database
    backups never push the last copy of the uploads out of retention.
    """
    paths = glob.glob(_auto_backup_pattern(backup_dir, db_only))
    if not db_only:
        paths = [p for p in paths if not os.path.basename(p).startswith("auto_db_")]
    return sorted(paths, key=os.path.getctime)


def _required_free_bytes(backup_dir: str, db_only: bool) -> int:
    """Free space a new backup needs: twice the last backup of its kind, at least the floor."""
    floor = Config.MIN_BACKUP_DISK_GB * _GIB
    previous = _auto_backups(backup_dir, db_only)
    last_size = 0
    if previous:
        with contextlib.suppress(OSError):
            last_size = os.path.getsize(previous[-1])
    return max(floor, 2 * last_size)


def _check_free_space(backup_dir: str, db_only: bool) -> None:
    try:
        free = shutil.disk_usage(backup_dir).free
    except FileNotFoundError:
        os.makedirs(backup_dir, exist_ok=True)
        return
    required = _required_free_bytes(backup_dir, db_only)
    if free < required:
        raise RuntimeError(
            f"Insufficient disk space for backup: {free / _GIB:.1f}GB free in {backup_dir} "
            f"({required / _GIB:.1f}GB required: twice the last backup, at least "
            f"{Config.MIN_BACKUP_DISK_GB}GB)"
        )


def run_backup(
    app: Flask, auto: bool = True, db_only: bool = False, scheduled_at: str | None = None
) -> str:
    """
    Unified backup: pg_dump via .pgpass + tar.gz of DB dump + uploads.
    - auto=True  → saves to /backups/auto_*.tar.gz (auto_db_*.tar.gz when db_only),
      keeps the newest BACKUP_RETENTION_COUNT full and BACKUP_DB_RETENTION_COUNT
      database-only backups, and records the schedule marker once the archive exists
    - auto=False → saves to /backups/manual_*.tar.gz, never auto-deleted
    - db_only → if True, only backs up the database (no uploads folder)
    - scheduled_at → the scheduler's dispatch time, stored as the marker
    """
    prefix = "manual"
    if auto:
        prefix = "auto_db" if db_only else "auto"
    started_at = utcnow()
    ts = started_at.strftime("%Y%m%d_%H%M%S")

    backup_dir = Config.BACKUPS_DIR
    os.makedirs(backup_dir, exist_ok=True)

    filename = f"{prefix}_{ts}.tar.gz"
    target = os.path.join(backup_dir, filename)

    _check_free_space(backup_dir, db_only)

    db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    parsed = urllib.parse.urlparse(db_uri)
    host = parsed.hostname or "localhost"
    port = str(parsed.port or 5432)
    database = parsed.path.lstrip("/")
    username = parsed.username or "postgres"
    password = parsed.password or ""

    with tempfile.TemporaryDirectory() as tmp:
        # .pgpass file
        pgpass_path = os.path.join(tmp, "pgpass")
        with open(pgpass_path, "w") as f:
            os.chmod(pgpass_path, 0o600)
            f.write(f"{host}:{port}:{database}:{username}:{password}\n")

        env = os.environ.copy()
        env["PGPASSFILE"] = pgpass_path
        env["COPYFILE_DISABLE"] = "1"

        dump_path = os.path.join(tmp, "db_dump.sql")
        pg_dump_cmd = [
            "pg_dump",
            "-h",
            host,
            "-U",
            username,
            "-p",
            port,
            "-d",
            database,
            "-f",
            dump_path,
        ]
        if auto:
            pg_dump_cmd = ["nice", "-n", "19", *pg_dump_cmd]

        result = subprocess.run(  # noqa: S603 — args from trusted config
            pg_dump_cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=Config.BACKUP_TIMEOUT,
        )
        if result.returncode != 0:
            raise RuntimeError(f"pg_dump failed: {result.stderr.strip()}")

        # Dump audit logs to audit_logs.json in temp directory
        audit_logs_path = os.path.join(tmp, "audit_logs.json")
        try:
            from models import AuditLog

            with app.app_context(), open(audit_logs_path, "w") as f:
                f.write("[")
                first = True
                for log in AuditLog.query.order_by(AuditLog.timestamp.desc()).yield_per(500):
                    if not first:
                        f.write(",\n")
                    serialized = {
                        "id": str(log.id),
                        "admin_id": str(log.admin_id) if log.admin_id else None,
                        "action_type": log.action_type,
                        "target_type": log.target_type,
                        "target_id": str(log.target_id) if log.target_id else None,
                        "details": log.details,
                        "ip_address": log.ip_address,
                        "target_user_id": str(log.target_user_id) if log.target_user_id else None,
                        "task_id": str(log.task_id) if log.task_id else None,
                        "old_score": log.old_score,
                        "new_score": log.new_score,
                        "reason": log.reason,
                        "timestamp": log.timestamp.isoformat() + "Z" if log.timestamp else None,
                    }
                    f.write(json.dumps(serialized, indent=2))
                    first = False
                f.write("\n]")
        except Exception as e:
            logger.error("Failed to dump audit logs during backup: %s", str(e))
            raise RuntimeError(f"Failed to dump audit logs: {e!s}") from e

        # Copy application logs into the backup snapshot
        log_dir = Config.LOG_DIR
        logs_dest = os.path.join(tmp, "logs")
        if os.path.isdir(log_dir):
            Path(logs_dest).mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                log_dir,
                logs_dest,
                ignore=shutil.ignore_patterns("*.gz", _ROTATED_LOG_PATTERN),
                dirs_exist_ok=True,
            )

        uploads_path = app.config.get("UPLOAD_FOLDER", "")
        uploads_name = os.path.basename(uploads_path)
        tar_args = [
            "tar",
            "--exclude=backups",
            "--exclude=*.tar.gz",
            # Rebuilt from the task files on the next sync, and deleted after upload
            f"--exclude={uploads_name}/environment_packages",
            # Hugging Face ZIPs are large and re-uploadable; the export records their hashes
            f"--exclude={uploads_name}/hf",
            # Uploads in progress are incomplete by definition
            f"--exclude={uploads_name}/.incoming",
            # Fastest gzip level: task data is mostly compressed binary (parquet, zip, images)
            "--use-compress-program=gzip -1",
            "-cf",
            target,
            "-C",
            tmp,
            "db_dump.sql",
            "audit_logs.json",
        ]
        if os.path.isdir(logs_dest):
            tar_args.extend(["-C", tmp, "logs"])
        if not db_only and uploads_path and os.path.isdir(uploads_path):
            tar_args.extend(["-C", os.path.dirname(uploads_path), uploads_name])

        if auto:
            tar_args = ["nice", "-n", "19", *tar_args]

        result = subprocess.run(  # noqa: S603 — args from trusted config
            tar_args, env=env, capture_output=True, text=True, timeout=_tar_timeout()
        )
        if result.returncode != 0:
            raise RuntimeError(f"tar failed: {result.stderr.strip()}")

    file_size = os.path.getsize(target)

    if auto:
        _record_auto_backup(db_only, scheduled_at or started_at.isoformat())
        # Rotation: database-only and full backups each keep their own count
        retention = Config.BACKUP_DB_RETENTION_COUNT if db_only else Config.BACKUP_RETENTION_COUNT
        keep_count = max(1, retention)
        for old in _auto_backups(backup_dir, db_only)[:-keep_count]:
            with contextlib.suppress(OSError):
                os.remove(old)

    # SSE notification
    _publish_backup_event(filename, file_size, None, None)

    return filename


def _publish_backup_event(filename: str, size_bytes: int, challenge_id: Any, state: Any) -> None:
    try:
        from utils.cache_utils import get_coordination_client
        from utils.sse_utils import CHANNEL_BACKUPS

        r = get_coordination_client()
        if r:
            payload = {
                "filename": filename,
                "size_bytes": size_bytes,
                "created_at": utcnow().isoformat(),
                "challenge_id": challenge_id,
                "state": state,
            }
            r.publish(CHANNEL_BACKUPS, json.dumps(payload))
    except Exception as e:
        logger.warning("Failed to publish backup event: %s", e)


def run_docker_prune() -> dict[str, str]:
    """Prune unused docker layers on worker nodes to prevent disk space leaks."""
    from .docker_utils import prune_images

    return prune_images()
