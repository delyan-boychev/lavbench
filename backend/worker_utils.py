import os
import subprocess
import time
import threading
import requests

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
                for line in iter(pipe.readline, ''):
                    if not isinstance(line, str):
                        break
                    collector.append(line)
                    clean_line = line.rstrip('\r\n')
                    if is_err:
                        logs_list.append(f"[stderr] {clean_line}")
                    else:
                        logs_list.append(clean_line)
            except Exception:
                pass
            finally:
                try:
                    pipe.close()
                except:
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
            
        t_out.join(timeout=2.0)
        t_err.join(timeout=2.0)
        
        stdout_str = "".join(stdout_lines)
        stderr_str = "".join(stderr_lines)
        return proc.returncode, stdout_str, stderr_str, process_timeout
    except Exception as exc:
        logs_list.append(f"Failed to execute command: {exc}")
        return -1, "", str(exc), False

class StreamingLogList(list):
    def __init__(self, submission_id):
        super().__init__()
        self.submission_id = submission_id
        
    def append(self, item):
        super().append(item)
        try:
            from sse_utils import publish_submission_log
            publish_submission_log(self.submission_id, str(item))
        except Exception as e:
            print(f"[StreamingLogList Error] Failed to publish log line to Redis: {e}")

class MockModel:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

def report_status_to_server(metadata, status, detailed_status, logs=None, public_score=None, private_score=None, execution_time_ms=None, metrics_payload_pub=None, metrics_payload_priv=None, gpu_node=None, max_retries=3, backoff_factor=2):
    if not metadata or "main_server_url" not in metadata or "worker_secret_key" not in metadata:
        return False
    url = f"{metadata['main_server_url']}/api/worker/report/{metadata['submission_id']}"
    headers = {
        "X-Worker-Token": metadata["worker_secret_key"],
        "Content-Type": "application/json"
    }
    payload = {
        "status": status,
        "detailed_status": detailed_status
    }
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
            print(f"Server returned status {res.status_code} for report attempt {attempt + 1}")
        except Exception as e:
            print(f"Error reporting progress to server (attempt {attempt + 1}/{max_retries}): {e}")
        
        if attempt < max_retries - 1:
            sleep_time = backoff_factor ** attempt
            time.sleep(sleep_time)
            
    return False

def download_task_files_to_dir(metadata, temp_dir, logs):
    if not metadata or "main_server_url" not in metadata or "worker_secret_key" not in metadata:
        return
    files_list = metadata.get("task_files", [])
    if not files_list:
        return
        
    task_id = metadata.get("task_id")
    is_unified = True
    for f in files_list:
        filename = f["filename"]
        if is_unified and filename == "labels.parquet":
            continue # Do NOT download labels.parquet to sandbox temp_dir!
            
        url = f"{metadata['main_server_url']}/api/worker/tasks/{task_id}/files/{filename}"
        headers = {
            "X-Worker-Token": metadata["worker_secret_key"]
        }
        try:
            logs.append(f"Downloading task file '{filename}' from server...")
            res = requests.get(url, headers=headers, timeout=30)
            if res.status_code == 200:
                dest_file = os.path.join(temp_dir, filename)
                with open(dest_file, "wb") as df:
                    df.write(res.content)
                logs.append(f"Downloaded task file '{filename}' successfully.")
            else:
                logs.append(f"Failed to download task file '{filename}': Status code {res.status_code}")
        except Exception as e:
            logs.append(f"Error downloading task file '{filename}': {str(e)}")

def download_labels_parquet_to_dir(metadata, labels_dir, logs):
    if not metadata or "main_server_url" not in metadata or "worker_secret_key" not in metadata:
        return None
    files_list = metadata.get("task_files", [])
    if not files_list:
        return None
        
    task_id = metadata.get("task_id")
    for f in files_list:
        filename = f["filename"]
        if filename == "labels.parquet":
            url = f"{metadata['main_server_url']}/api/worker/tasks/{task_id}/files/{filename}"
            headers = {
                "X-Worker-Token": metadata["worker_secret_key"]
            }
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
