import os
import glob
import json
import time
import tempfile
import subprocess
import urllib.parse
import requests
from datetime import datetime


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
    
    try:
        requests.post(f"{api_base}/admin/workers/register", json={
            "worker_id": machine_id,
            "ram_gb": ram_gb,
            "gpu_count": 1 if gpu_id else 0,
            "status": "idle"
        }, timeout=5)
    except Exception as e:
        pass


def run_backup(app, auto=True, challenge_id=None, state=None):
    """
    Unified backup: pg_dump via .pgpass + tar.gz of DB dump + uploads.
    - auto=True  → saves to /backups/auto_*.tar.gz, rotates to latest 6
    - auto=False → saves to /backups/manual_*.tar.gz, never auto-deleted
    - challenge_id → saves to /backups/challenge_{id}/{state}_*.tar.gz
    - state → one of: submission_ended, grace_ended, finalized
    """
    prefix = "auto" if auto else "manual"
    if challenge_id and state:
        prefix = state
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    backup_dir = "/backups"
    if challenge_id:
        backup_dir = os.path.join(backup_dir, f"challenge_{challenge_id}")
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

        dump_path = os.path.join(tmp, "db_dump.sql")
        result = subprocess.run(
            [
                "pg_dump", "-h", host, "-U", username, "-p", port, "-d", database,
                "-f", dump_path,
            ],
            env=env, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"pg_dump failed: {result.stderr.strip()}")

        uploads_path = app.config.get("UPLOAD_FOLDER", "")
        tar_args = ["tar", "-czf", target, "-C", tmp, "db_dump.sql"]
        if uploads_path and os.path.isdir(uploads_path):
            tar_args.extend(["-C", os.path.dirname(uploads_path), os.path.basename(uploads_path)])

        result = subprocess.run(tar_args, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"tar failed: {result.stderr.strip()}")

    file_size = os.path.getsize(target)

    # Rotation: keep last 6 auto backups in root directory only
    if auto and not challenge_id:
        pattern = os.path.join("/backups", "auto_*.tar.gz")
        auto_files = sorted(glob.glob(pattern), key=os.path.getctime)
        for old in auto_files[:-6]:
            try:
                os.remove(old)
            except OSError:
                pass

    # SSE notification
    _publish_backup_event(filename, file_size, challenge_id, state)

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
    except Exception:
        pass
