"""Worker runtime utilities — Docker sandbox execution, status reporting."""

import os
import subprocess
import time
import threading
import logging
import requests

logger = logging.getLogger(__name__)


def _sign_worker_token(submission_id):
    """Create an Ed25519-signed token for authenticating to the main server.

    The worker reads WORKER_PRIVATE_KEY from its environment, signs a nonce
    containing the submission_id and current timestamp, and returns the token
    as ``nonce.base64_signature`` for use in the X-Worker-Token header.
    """
    import base64 as _b64

    priv_key_b64 = os.environ.get("WORKER_PRIVATE_KEY", "")
    if not priv_key_b64:
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


def run_command_streaming(cmd, logs_list, time_limit=None):
    """
    Runs a command and streams stdout/stderr lines to logs_list in real-time.
    Returns (returncode, stdout_str, stderr_str, is_timeout).
    """
    stdout_lines = []
    stderr_lines = []
    process_timeout = False

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        def read_pipe(pipe, collector, is_err=False):
            try:
                for line in iter(pipe.readline, ""):
                    if not isinstance(line, str):
                        break
                    collector.append(line)
                    clean_line = line.rstrip("\r\n")
                    if is_err:
                        logs_list.append(f"[stderr] {clean_line}")
                    else:
                        logs_list.append(clean_line)
            except Exception:
                logger.exception("Error reading pipe")
            finally:
                try:
                    pipe.close()
                except Exception:
                    pass

        t_out = threading.Thread(target=read_pipe, args=(proc.stdout, stdout_lines, False))
        t_err = threading.Thread(target=read_pipe, args=(proc.stderr, stderr_lines, True))

        t_out.start()
        t_err.start()

        start_wait = time.time()
        while True:
            ret = proc.poll()
            if ret is not None:
                break
            if time_limit and (time.time() - start_wait > time_limit):
                proc.kill()
                process_timeout = True
                break
            time.sleep(0.1)

        t_out.join(timeout=30.0)
        t_err.join(timeout=30.0)

        # Drain any remaining pipe data after join
        try:
            remaining = proc.stdout.read()
            if remaining:
                stdout_lines.append(remaining)
                logs_list.append(remaining.rstrip("\r\n"))
        except Exception:
            pass
        try:
            remaining = proc.stderr.read()
            if remaining:
                stderr_lines.append(remaining)
                logs_list.append("[stderr] " + remaining.rstrip("\r\n"))
        except Exception:
            pass

        stdout_str = "".join(stdout_lines)
        stderr_str = "".join(stderr_lines)
        return proc.returncode, stdout_str, stderr_str, process_timeout
    except Exception as exc:
        logs_list.append(f"Failed to execute command: {exc}")
        return -1, "", str(exc), False


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
        except Exception as e:
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
            logger.warning(
                "Server returned status %s for report attempt %s", res.status_code, attempt + 1
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
                logs.append(f"Downloaded task file '{filename}' successfully.")
            else:
                logs.append(
                    f"Failed to download task file '{filename}': Status code {res.status_code}"
                )
        except Exception as e:
            logs.append(f"Error downloading task file '{filename}': {str(e)}")


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
                logs.append(f"Error downloading labels.parquet: {str(e)}")
    return None
