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

import requests
from flask import Flask

from config import Config
from utils.dates import utcnow

logger = logging.getLogger(__name__)


def run_register_worker_specs(celery_app: Any) -> None:
    from config import Config

    gpu_id = Config.WORKER_GPU_ID or None
    machine_id = os.environ.get("HOSTNAME", "local-worker")
    if gpu_id is not None:
        machine_id = f"gpu-worker-device-{gpu_id}"

    try:
        import psutil  # type: ignore[import-untyped]

        ram_gb = round(psutil.virtual_memory().total / (1024**3), 2)
    except ImportError:
        ram_gb = 16.0

    api_base = Config.API_BASE

    gpu_count = 0
    if gpu_id:
        gpu_count = len([g for g in gpu_id.split(",") if g.strip()])

    try:
        requests.post(
            f"{api_base}/admin/workers/register",
            json={
                "worker_id": machine_id,
                "ram_gb": ram_gb,
                "gpu_count": gpu_count,
                "status": "idle",
            },
            timeout=5,
        )
    except Exception as e:
        logger.warning("Worker registration failed for ID %s: %s", machine_id, str(e))


def run_backup(app: Flask, auto: bool = True, db_only: bool = False) -> str:
    """
    Unified backup: pg_dump via .pgpass + tar.gz of DB dump + uploads.
    - auto=True  → saves to /backups/auto_*.tar.gz, rotates dynamically
    - auto=False → saves to /backups/manual_*.tar.gz, never auto-deleted
    - db_only → if True, only backs up the database (no uploads folder)
    """
    prefix = "auto" if auto else "manual"
    ts = utcnow().strftime("%Y%m%d_%H%M%S")

    backup_dir = Config.BACKUPS_DIR
    os.makedirs(backup_dir, exist_ok=True)

    filename = f"{prefix}_{ts}.tar.gz"
    target = os.path.join(backup_dir, filename)

    # Pre-flight disk space check
    try:
        disk_usage = shutil.disk_usage(backup_dir)
        free_gb = disk_usage.free / (1024**3)
        if free_gb < 1.0:
            raise RuntimeError(
                f"Insufficient disk space for backup: {free_gb:.1f}GB free "
                f"in {backup_dir} (min 1GB required)"
            )
    except FileNotFoundError:
        os.makedirs(backup_dir, exist_ok=True)

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
            timeout=600,
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
                ignore=shutil.ignore_patterns("*.gz"),
                dirs_exist_ok=True,
            )

        uploads_path = app.config.get("UPLOAD_FOLDER", "")
        tar_args = [
            "tar",
            "--exclude=backups",
            "--exclude=*.tar.gz",
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

        result = subprocess.run(tar_args, env=env, capture_output=True, text=True, timeout=600)  # noqa: S603 — args from trusted config
        if result.returncode != 0:
            raise RuntimeError(f"tar failed: {result.stderr.strip()}")

    file_size = os.path.getsize(target)

    # Rotation: keep last N auto backups in root directory only
    if auto:
        pattern = os.path.join(backup_dir, "auto_*.tar.gz")
        auto_files = sorted(glob.glob(pattern), key=os.path.getctime)

        # Cap kept auto-backups based on active competition status
        keep_count = 3
        try:
            from models import Challenge

            now = utcnow()
            active_comp = Challenge.query.filter(
                Challenge.is_active,
                not Challenge.is_archived,
                Challenge.start_time <= now,
                (Challenge.end_time.is_(None)) | (Challenge.end_time >= now),
            ).first()
            if active_comp is not None:
                keep_count = 6
        except Exception as e:
            logger.warning("Failed to publish backup event: %s", e)

        for old in auto_files[:-keep_count]:
            with contextlib.suppress(OSError):
                os.remove(old)

    # SSE notification
    _publish_backup_event(filename, file_size, None, None)

    return filename


def _publish_backup_event(filename: str, size_bytes: int, challenge_id: Any, state: Any) -> None:
    try:
        from cache_utils import get_redis_client

        r = get_redis_client()
        if r:
            payload = {
                "filename": filename,
                "size_bytes": size_bytes,
                "created_at": utcnow().isoformat(),
                "challenge_id": challenge_id,
                "state": state,
            }
            r.publish("backup_status", json.dumps(payload))
    except Exception as e:
        logger.warning("Failed to publish backup event: %s", e)


def run_docker_prune() -> dict[str, str]:
    """Prune unused docker layers on worker nodes to prevent disk space leaks."""
    from task_modules.docker_utils import prune_images

    return prune_images()
