"""Celery task for system maintenance — cleanup, watchdog, diagnostics."""

import contextlib
import glob
import json
import logging
import os
import subprocess
import tempfile
import urllib.parse
from datetime import datetime

import requests

logger = logging.getLogger(__name__)


def run_register_worker_specs(celery_app):
    gpu_id = os.environ.get("WORKER_GPU_ID", None)
    machine_id = os.environ.get("HOSTNAME", "local-worker")
    if gpu_id is not None:
        machine_id = f"gpu-worker-device-{gpu_id}"

    try:
        import psutil

        ram_gb = round(psutil.virtual_memory().total / (1024**3), 2)
    except ImportError:
        ram_gb = 16.0

    api_base = os.environ.get("API_BASE", "http://localhost:5001/api")

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


def run_backup(app, auto=True, db_only=False):
    """
    Unified backup: pg_dump via .pgpass + tar.gz of DB dump + uploads.
    - auto=True  → saves to /backups/auto_*.tar.gz, rotates dynamically
    - auto=False → saves to /backups/manual_*.tar.gz, never auto-deleted
    - db_only → if True, only backs up the database (no uploads folder)
    """
    prefix = "auto" if auto else "manual"
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    backup_dir = os.environ.get("BACKUPS_DIR", "/backups")
    os.makedirs(backup_dir, exist_ok=True)

    filename = f"{prefix}_{ts}.tar.gz"
    target = os.path.join(backup_dir, filename)

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
        )
        if result.returncode != 0:
            raise RuntimeError(f"pg_dump failed: {result.stderr.strip()}")

        # Dump audit logs to audit_logs.json in temp directory
        audit_logs_path = os.path.join(tmp, "audit_logs.json")
        try:
            from models import AuditLog

            with app.app_context():
                logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).all()

                def serialize_audit(log):
                    return {
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

                serialized_logs = [serialize_audit(log) for log in logs]
            with open(audit_logs_path, "w") as f:
                json.dump(serialized_logs, f, indent=2)
        except Exception as e:
            logger.error("Failed to dump audit logs during backup: %s", str(e))
            raise RuntimeError(f"Failed to dump audit logs: {e!s}") from e

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
        if not db_only and uploads_path and os.path.isdir(uploads_path):
            tar_args.extend(["-C", os.path.dirname(uploads_path), os.path.basename(uploads_path)])

        if auto:
            tar_args = ["nice", "-n", "19", *tar_args]

        result = subprocess.run(tar_args, env=env, capture_output=True, text=True)  # noqa: S603 — args from trusted config
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

            now = datetime.utcnow()
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


def _publish_backup_event(filename, size_bytes, challenge_id, state):
    try:
        from cache_utils import get_redis_client

        r = get_redis_client()
        if r:
            payload = {
                "filename": filename,
                "size_bytes": size_bytes,
                "created_at": datetime.utcnow().isoformat(),
                "challenge_id": challenge_id,
                "state": state,
            }
            r.publish("backup_status", json.dumps(payload))
    except Exception as e:
        logger.warning("Failed to publish backup event: %s", e)


def run_docker_prune():
    """Prune unused docker layers on worker nodes to prevent disk space leaks."""
    from task_modules.docker_utils import prune_images

    return prune_images()
