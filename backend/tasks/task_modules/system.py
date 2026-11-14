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


def run_backup(app: Flask, auto: bool = True, db_only: bool = False) -> str:
    """
    Unified backup: pg_dump via .pgpass + tar.gz of DB dump + uploads.
    - auto=True  → saves to /backups/auto_*.tar.gz (auto_db_*.tar.gz when db_only)
      and keeps the newest BACKUP_RETENTION_COUNT of each kind
    - auto=False → saves to /backups/manual_*.tar.gz, never auto-deleted
    - db_only → if True, only backs up the database (no uploads folder)
    """
    prefix = "manual"
    if auto:
        prefix = "auto_db" if db_only else "auto"
    ts = utcnow().strftime("%Y%m%d_%H%M%S")

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
        tar_args = [
            "tar",
            "--exclude=backups",
            "--exclude=*.tar.gz",
            # Never include plaintext-adjacent credential exports in backups
            "--exclude=*/credentials",
            "-czf",
            target,
            "-C",
            tmp,
            "db_dump.sql",
            "audit_logs.json",
        ]
        if os.path.isdir(logs_dest):
            tar_args.extend(["-C", tmp, "logs"])
        if not db_only and uploads_path and os.path.isdir(uploads_path):
            tar_args.extend(["-C", os.path.dirname(uploads_path), os.path.basename(uploads_path)])

        if auto:
            tar_args = ["nice", "-n", "19", *tar_args]

        result = subprocess.run(  # noqa: S603 — args from trusted config
            tar_args, env=env, capture_output=True, text=True, timeout=Config.BACKUP_TIMEOUT
        )
        if result.returncode != 0:
            raise RuntimeError(f"tar failed: {result.stderr.strip()}")

    file_size = os.path.getsize(target)

    # Rotation: keep the newest BACKUP_RETENTION_COUNT automatic backups of this kind
    if auto:
        keep_count = max(1, Config.BACKUP_RETENTION_COUNT)
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
