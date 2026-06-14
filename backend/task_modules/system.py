import os
import subprocess
import time
import requests

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

def run_automated_backup(app):
    """
    Periodically dumps the postgres database to S3 or local volume.
    """
    try:
        import datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs("backups", exist_ok=True)
        subprocess.run(["pg_dump", "-U", "postgres", "-h", "db", "-d", "webplatform", "-F", "c", "-f", f"backups/db_{ts}.dump"], capture_output=True)
    except:
        pass
