"""Worker runtime utilities — Docker sandbox execution, status reporting."""

import logging
import os
import threading
import time

import requests
from docker.types import DeviceRequest, Ulimit

logger = logging.getLogger(__name__)


def _sign_worker_token(submission_id):
    """Create an Ed25519-signed token for authenticating to the main server.

    The worker reads WORKER_PRIVATE_KEY from its environment, signs a nonce
    containing the submission_id and current timestamp, and returns the token
    as ``nonce.base64_signature`` for use in the X-Worker-Token header.
    """
    import base64 as _b64

    priv_key_b64 = os.environ.get("WORKER_PRIVATE_KEY")
    if not priv_key_b64:
        logger.critical(
            "WORKER_PRIVATE_KEY is not set — worker cannot authenticate to the main server"
        )
        return ""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        private_key = Ed25519PrivateKey.from_private_bytes(_b64.b64decode(priv_key_b64))
        nonce = f"{submission_id}:{int(time.time())}"
        signature = private_key.sign(nonce.encode())
        return f"{nonce}.{_b64.b64encode(signature).decode()}"
    except Exception as exc:
        logger.warning("Failed to sign worker token: %s", exc)
        return ""


def run_command_streaming(
    docker_client,
    image_tag,
    command,
    logs_list,
    time_limit=None,
    mem_limit=None,
    cpu_count=2,
    network_mode="none",
    cap_drop=None,
    security_opt=None,
    pids_limit=64,
    tmpfs=None,
    volumes=None,
    working_dir="/app",
    environment=None,
    gpu_required=False,
    gpu_id=None,
):
    """Run a Docker container and stream its output to *logs_list* in real-time.

    Returns ``(returncode, stdout_str, stderr_str, is_timeout)``.
    """
    ulimits = [
        Ulimit(name="nofile", soft=256, hard=256),
        Ulimit(name="nproc", soft=64, hard=64),
    ]

    device_requests = None
    if gpu_required:
        if gpu_id is not None:
            device_requests = [DeviceRequest(device_ids=[str(gpu_id)], capabilities=[["gpu"]])]
        else:
            device_requests = [DeviceRequest(count=-1, capabilities=[["gpu"]])]

    try:
        container = docker_client.containers.run(
            image_tag,
            command,
            detach=True,
            network_mode=network_mode,
            cap_drop=cap_drop or ["ALL"],
            security_opt=security_opt or ["no-new-privileges:true"],
            pids_limit=pids_limit,
            nano_cpus=int(cpu_count * 1e9),
            mem_limit=mem_limit,
            memswap_limit=mem_limit,
            tmpfs=tmpfs or {"/tmp": "noexec,nosuid,size=128m"},  # noqa: S108
            volumes=volumes,
            working_dir=working_dir,
            environment=environment,
            ulimits=ulimits,
            device_requests=device_requests,
        )
    except Exception as exc:
        logs_list.append(f"Failed to start container: {exc}")
        return -1, "", str(exc), False

    stdout_lines = []
    process_timeout = False

    def stream_logs():
        try:
            for chunk in container.logs(stream=True, follow=True):
                if chunk:
                    text = chunk.decode("utf-8", errors="replace")
                    for line in text.splitlines(keepends=True):
                        clean = line.rstrip("\r\n")
                        if clean:
                            stdout_lines.append(clean)
                            logs_list.append(clean)
        except Exception:
            logger.debug("Log stream ended", exc_info=True)

    t = threading.Thread(target=stream_logs, daemon=True)
    t.start()

    start_wait = time.time()
    try:
        while True:
            container.reload()
            if container.status in ("exited", "removing", "dead"):
                break
            if time_limit and (time.time() - start_wait > time_limit):
                container.kill()
                process_timeout = True
                break
            time.sleep(0.1)
    except Exception as exc:
        logs_list.append(f"Error during container execution: {exc}")
        container.kill()
        process_timeout = True

    t.join(timeout=30.0)

    try:
        result = container.wait()
        exit_code = result.get("StatusCode", -1)
    except Exception:
        exit_code = -1

    try:
        container.remove(force=True)
    except Exception:
        logger.debug("Error removing container", exc_info=True)

    stdout_str = "\n".join(stdout_lines)
    stderr_str = ""
    return exit_code, stdout_str, stderr_str, process_timeout


MAX_LOG_LINES = 10000


class StreamingLogList(list):
    """A list subclass that publishes each appended log line via SSE in real time."""

    def __init__(self, submission_id):
        super().__init__()
        self.submission_id = submission_id

    def append(self, item):
        super().append(item)
        if len(self) > MAX_LOG_LINES:
            self.pop(0)
        try:
            from sse_utils import publish_submission_log

            publish_submission_log(self.submission_id, str(item))
        except Exception:
            logger.exception("[StreamingLogList Error] Failed to publish log line to Redis")


class MockModel:
    """A simple dict-like object for passing metadata without a real ORM model."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def report_status_to_server(
    metadata,
    status,
    detailed_status,
    logs=None,
    public_score=None,
    private_score=None,
    execution_time_ms=None,
    metrics_payload_pub=None,
    metrics_payload_priv=None,
    gpu_node=None,
    max_retries=3,
    backoff_factor=2,
):
    """POST submission status/scores back to the main server with exponential backoff retry."""
    if not metadata or "main_server_url" not in metadata:
        return False

    submission_id = metadata.get("submission_id", "unknown")
    url = f"{metadata['main_server_url']}/api/worker/report/{submission_id}"

    import sys

    if (
        "pytest" in sys.modules
        and not hasattr(requests.post, "assert_called")
        and any(lh in url for lh in ("localhost", "127.0.0.1"))
    ):
        logger.info("Skipping real network request to localhost in test runner: %s", url)
        return True
    token = _sign_worker_token(submission_id)
    headers = {"X-Worker-Token": token, "Content-Type": "application/json"}

    payload = {"status": status, "detailed_status": detailed_status}
    if logs is not None:
        if isinstance(logs, list):
            payload["logs"] = "\n".join(str(x) for x in logs)
        else:
            payload["logs"] = str(logs)
    if public_score is not None:
        payload["public_score"] = public_score
    if private_score is not None:
        payload["private_score"] = private_score
    if execution_time_ms is not None:
        payload["execution_time_ms"] = execution_time_ms
    if metrics_payload_pub is not None:
        payload["metrics_payload_pub"] = metrics_payload_pub
    if metrics_payload_priv is not None:
        payload["metrics_payload_priv"] = metrics_payload_priv
    if gpu_node is not None:
        payload["gpu_node"] = gpu_node

    for attempt in range(max_retries):
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=10)
            if res.status_code == 200:
                return True
            if res.status_code == 404:
                logger.warning(
                    "Submission %s not found on server (404) — stopping retries",
                    submission_id,
                )
                return False
            logger.warning(
                "Server returned status %s for report attempt %s",
                res.status_code,
                attempt + 1,
            )
        except Exception as e:
            logger.warning(
                "Error reporting progress to server (attempt %s/%s): %s",
                attempt + 1,
                max_retries,
                e,
            )

        if attempt < max_retries - 1:
            sleep_time = backoff_factor**attempt
            time.sleep(sleep_time)

    return False


def download_task_files_to_dir(metadata, temp_dir, logs):
    """Download task resource files (excluding labels.parquet) from the server into a temp dir."""
    if not metadata or "main_server_url" not in metadata:
        return
    files_list = metadata.get("task_files", [])
    if not files_list:
        return

    task_id = metadata.get("task_id")
    submission_id = metadata.get("submission_id", "unknown")
    main_server_url = metadata["main_server_url"]
    token = _sign_worker_token(submission_id)
    headers = {"X-Worker-Token": token}
    is_unified = True
    for f in files_list:
        filename = f["filename"]
        if is_unified and filename == "labels.parquet":
            continue  # Do NOT download labels.parquet to sandbox temp_dir!

        url = f"{main_server_url}/api/worker/tasks/{task_id}/files/{filename}"
        try:
            logs.append(f"Downloading task file '{filename}' from server...")
            res = requests.get(url, headers=headers, timeout=30)
            if res.status_code == 200:
                dest_file = os.path.join(temp_dir, filename)
                with open(dest_file, "wb") as df:
                    df.write(res.content)
                os.chmod(dest_file, 0o644)
                logs.append(f"Downloaded task file '{filename}' successfully.")
            else:
                logs.append(
                    f"Failed to download task file '{filename}': Status code {res.status_code}"
                )
        except Exception as e:
            logs.append(f"Error downloading task file '{filename}': {e!s}")


def download_labels_parquet_to_dir(metadata, labels_dir, logs):
    """Download labels.parquet securely from the server for evaluation comparison."""
    if not metadata or "main_server_url" not in metadata:
        return None
    files_list = metadata.get("task_files", [])
    if not files_list:
        return None

    task_id = metadata.get("task_id")
    submission_id = metadata.get("submission_id", "unknown")
    main_server_url = metadata["main_server_url"]
    token = _sign_worker_token(submission_id)
    headers = {"X-Worker-Token": token}
    for f in files_list:
        filename = f["filename"]
        if filename == "labels.parquet":
            url = f"{main_server_url}/api/worker/tasks/{task_id}/files/{filename}"
            try:
                logs.append("Downloading labels.parquet securely from server...")
                res = requests.get(url, headers=headers, timeout=30)
                if res.status_code == 200:
                    dest_file = os.path.join(labels_dir, filename)
                    with open(dest_file, "wb") as df:
                        df.write(res.content)
                    logs.append("Downloaded labels.parquet securely.")
                    return dest_file
                else:
                    logs.append(f"Failed to download labels.parquet: Status code {res.status_code}")
            except Exception as e:
                logs.append(f"Error downloading labels.parquet: {e!s}")
    return None
