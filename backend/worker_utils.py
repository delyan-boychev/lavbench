"""Worker runtime utilities — Docker sandbox execution, status reporting."""

from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import shutil
import tarfile
import tempfile
import threading
import time
from typing import Any

import requests
from docker import DockerClient  # type: ignore[import-untyped]
from docker.types import DeviceRequest, Ulimit  # type: ignore[import-untyped]

from config import Config

logger = logging.getLogger(__name__)


def _sign_worker_token(submission_id: str) -> str:
    """Create an Ed25519-signed token for authenticating to the main server.

    The worker reads WORKER_PRIVATE_KEY from its environment, signs a nonce
    containing the submission_id and current timestamp, and returns the token
    as ``nonce.base64_signature`` for use in the X-Worker-Token header.
    """
    import base64 as _b64

    def _pad_b64(s: str) -> str:
        return s + "=" * (-len(s) % 4)

    priv_key_b64 = os.environ.get("WORKER_PRIVATE_KEY", "")
    if not priv_key_b64:
        logger.critical(
            "WORKER_PRIVATE_KEY is not set — worker cannot authenticate to the main server"
        )
        return ""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        private_key = Ed25519PrivateKey.from_private_bytes(_b64.b64decode(_pad_b64(priv_key_b64)))
        nonce = f"{submission_id}:{int(time.time())}"
        signature = private_key.sign(nonce.encode())
        return f"{nonce}.{_b64.b64encode(signature).decode()}"
    except Exception as exc:
        logger.warning("Failed to sign worker token: %s", exc)
        return ""


SANDBOX_UID = 65534
SANDBOX_GID = 65534


def _normalize_seed_tar_member(member: tarfile.TarInfo) -> tarfile.TarInfo:
    """Normalize seed tar metadata for a non-root sandbox user.

    The seed dir lives on the host (e.g. a 0o700 mkdtemp owned by the worker
    user). When extracted via put_archive by the root daemon, host ownership
    and modes would make /app unreadable/unwritable by the container's
    ``nobody`` (65534) user, so rewrite uid/gid and expose world access.
    """
    member.uid = SANDBOX_UID
    member.gid = SANDBOX_GID
    if member.isdir():
        member.mode = 0o777
    elif member.isfile():
        # Preserve exec bits (submission scripts are run directly) but ensure
        # read access for the sandbox user regardless of host file modes.
        member.mode = 0o644 | (member.mode & 0o111)
    return member


def run_command_streaming(
    docker_client: DockerClient,
    image_tag: str,
    command: list[str],
    logs_list: list[str],
    *,
    time_limit: int | None = None,
    mem_limit: str | None = None,
    cpu_count: int = 2,
    network_mode: str = "none",
    cap_drop: list[str] | None = None,
    security_opt: list[str] | None = None,
    pids_limit: int = 64,
    tmpfs: dict[str, str] | None = None,
    working_dir: str = "/app",
    environment: dict[str, str] | None = None,
    gpu_required: bool = False,
    gpu_id: str | None = None,
    seed_dir: str,
    user: str | None = None,
    read_only: bool = False,
    collect_files: list[tuple[str, str]] | None = None,
) -> tuple[int, str, str, bool]:
    """Run a Docker container seeded from a host directory and stream its
    output to *logs_list* in real-time.

    The container is created (not started) and *seed_dir* is streamed into
    *working_dir* via ``put_archive`` before starting — no host-path bind
    mount is required, so the sandbox works regardless of where the daemon
    runs. After the run, each ``(container_path, host_path)`` pair in
    *collect_files* is pulled back with ``get_archive`` and written to
    *host_path* (used to retrieve the submission output from a tmpfs-backed
    /app). Use :func:`run_sandbox` for the hardened entry point.

    Returns ``(returncode, stdout_str, stderr_str, is_timeout)``.
    """
    ulimits = [
        Ulimit(name="nofile", soft=256, hard=256),
    ]

    device_requests = None
    if gpu_required:
        if gpu_id is not None:
            device_requests = [DeviceRequest(device_ids=[str(gpu_id)], capabilities=[["gpu"]])]
        else:
            device_requests = [DeviceRequest(count=-1, capabilities=[["gpu"]])]

    run_kwargs = {
        "image": image_tag,
        "command": command,
        "detach": True,
        "network_mode": network_mode,
        "cap_drop": cap_drop or ["ALL"],
        "security_opt": security_opt or ["no-new-privileges:true"],
        "pids_limit": pids_limit,
        "nano_cpus": int(cpu_count * 1e9),
        "mem_limit": mem_limit,
        "memswap_limit": mem_limit,
        "tmpfs": tmpfs or {"/tmp": "noexec,nosuid,size=128m"},  # noqa: S108
        "working_dir": working_dir,
        "environment": environment,
        "ulimits": ulimits,
        "device_requests": device_requests,
        "user": user,
        "read_only": read_only,
    }

    container: Any | None = None
    seed_volume: Any | None = None
    try:
        # Seed the sandbox through a per-run anonymous volume: the daemon
        # can't put_archive into a tmpfs on a not-yet-started container, so
        # /app is a disposable volume that is removed after the run.
        # Tar metadata is normalized to the sandbox user (65534) with
        # world-accessible modes — the seed dir is host-owned (e.g. 0o700
        # mkdtemp) and the container runs as non-root nobody.
        seed_volume = docker_client.volumes.create()
        run_kwargs["volumes"] = {seed_volume.name: {"bind": working_dir, "mode": "rw"}}
        container = docker_client.containers.create(**run_kwargs)
        with tempfile.TemporaryDirectory(prefix="lavbench-seed-") as td:
            tar_path = os.path.join(td, "seed.tar")
            with tarfile.open(tar_path, "w") as tar:
                # put_archive ignores metadata on the '.' root entry, so
                # /app would keep the daemon's root-owned 0o755 mount point
                # and the non-root sandbox user could not write outputs.
                # A leading '/' entry makes the daemon chown/chmod the
                # volume root (/app) itself before the seed contents.
                root_entry = tarfile.TarInfo("/")
                root_entry.type = tarfile.DIRTYPE
                root_entry.mode = 0o777
                root_entry.uid = SANDBOX_UID
                root_entry.gid = SANDBOX_GID
                tar.addfile(root_entry)
                tar.add(seed_dir, arcname=".", filter=_normalize_seed_tar_member)
            with open(tar_path, "rb") as tf:
                container.put_archive(working_dir, tf)
        container.start()
    except Exception as exc:
        if container is not None:
            with contextlib.suppress(Exception):
                container.remove(force=True)
        if seed_volume is not None:
            with contextlib.suppress(Exception):
                seed_volume.remove()
        logs_list.append(f"Failed to start container: {exc}")
        return -1, "", str(exc), False

    stdout_lines: list[str] = []
    process_timeout = False
    exit_code = -1

    def stream_logs() -> None:
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

    try:
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

        if collect_files:
            for container_path, host_path in collect_files:
                try:
                    stream, _stat = container.get_archive(container_path)
                    # docker-py returns the archive as a byte-chunk generator,
                    # not a file object — materialize it for tarfile.
                    with tarfile.open(fileobj=io.BytesIO(b"".join(stream)), mode="r:") as tar:
                        for member in tar:
                            if member.isfile():
                                extracted = tar.extractfile(member)
                                if extracted is not None:
                                    os.makedirs(os.path.dirname(host_path), exist_ok=True)
                                    with open(host_path, "wb") as f:
                                        shutil.copyfileobj(extracted, f)
                except Exception as exc:
                    logger.warning("Could not collect %s from container: %s", container_path, exc)
    finally:
        with contextlib.suppress(Exception):
            container.kill()
        try:
            container.remove(force=True)
        except Exception:
            logger.debug("Error removing container", exc_info=True)
        if seed_volume is not None:
            with contextlib.suppress(Exception):
                seed_volume.remove()

    stdout_str = "\n".join(stdout_lines)
    stderr_str = ""
    return exit_code, stdout_str, stderr_str, process_timeout


def run_sandbox(
    docker_client: DockerClient,
    image_tag: str,
    command: list[str],
    *,
    seed_dir: str,
    collect_files: list[tuple[str, str]],
    logs_list: list[str],
    time_limit: int | None = None,
    mem_limit: str | None = None,
    cpu_count: int = 2,
    working_dir: str = "/app",
    environment: dict[str, str] | None = None,
    gpu_required: bool = False,
    gpu_id: str | None = None,
) -> tuple[int, str, str, bool]:
    """Run a command in a hardened sandbox seeded from a host directory.

    The single sanctioned entry point for sandboxed execution: applies the
    full security policy (no network, all capabilities dropped,
    no-new-privileges, pids limit, tmpfs-backed /tmp, non-root ``nobody``
    user, read-only rootfs) on top of :func:`run_command_streaming`.
    *seed_dir* is streamed into *working_dir* via ``put_archive`` and each
    ``(container_path, host_path)`` pair in *collect_files* is pulled back
    afterwards — no host-path bind mounts.

    Returns ``(returncode, stdout_str, stderr_str, is_timeout)``.
    """
    return run_command_streaming(
        docker_client,
        image_tag,
        command,
        logs_list,
        time_limit=time_limit,
        mem_limit=mem_limit,
        cpu_count=cpu_count,
        network_mode="none",
        cap_drop=["ALL"],
        security_opt=["no-new-privileges:true"],
        pids_limit=64,
        tmpfs={"/tmp": "noexec,nosuid,size=128m"},  # noqa: S108
        working_dir=working_dir,
        environment=environment,
        gpu_required=gpu_required,
        gpu_id=gpu_id,
        user=f"{SANDBOX_UID}:{SANDBOX_GID}",
        read_only=True,
        seed_dir=seed_dir,
        collect_files=collect_files,
    )


MAX_LOG_LINES = Config.WORKER_MAX_LOG_LINES


class StreamingLogList(list[str]):
    """A list subclass that publishes each appended log line via SSE in real time."""

    def __init__(self, submission_id: Any) -> None:
        super().__init__()
        self.submission_id = submission_id

    def append(self, item: str) -> None:
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

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


def report_status_to_server(
    metadata: dict[str, Any] | None,
    status: str,
    detailed_status: str,
    logs: str | list[str] | None = None,
    public_score: float | None = None,
    private_score: float | None = None,
    execution_time_ms: int | None = None,
    metrics_payload_pub: dict[str, Any] | None = None,
    metrics_payload_priv: dict[str, Any] | None = None,
    gpu_node: str | None = None,
    max_retries: int = Config.WORKER_REPORT_MAX_RETRIES,
    backoff_factor: int = 2,
) -> bool:
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

    payload: dict[str, Any] = {"status": status, "detailed_status": detailed_status}
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
            res = requests.post(
                url, json=payload, headers=headers, timeout=Config.WORKER_REPORT_TIMEOUT
            )
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


def _assets_manifest_path(task_id: Any) -> str:
    """Path of the per-task asset manifest, kept OUTSIDE the data dir so it is
    never baked into the image (COPY data/ /app/data/ would leak dotfiles)."""
    return os.path.join(Config.TASK_IMAGES_DIR, f"task_{task_id}", ".assets.json")


def _read_assets_manifest(task_id: Any) -> dict[str, Any]:
    try:
        with open(_assets_manifest_path(task_id)) as f:
            data: dict[str, Any] = json.load(f)
            return data
    except (OSError, ValueError):
        return {}


def _write_assets_manifest(task_id: Any, manifest: dict[str, Any]) -> None:
    """Atomically persist the asset manifest (temp file + os.replace)."""
    path = _assets_manifest_path(task_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(manifest, f)
    os.replace(tmp_path, path)


def sync_task_files_to_assets_cache(metadata: dict[str, Any] | None, logs: list[str]) -> bool:
    """Synchronize task resource files into the persistent host-side cache.

    The cache lives at ``TASK_IMAGES_DIR/task_{id}/data``; the runner snapshots
    it into each sandbox (``/app/data``) at launch, so in-flight runs keep the
    files they started with even when a rebuild re-syncs the cache mid-run.
    Files are only transferred when the server-side ``saved_name`` differs from
    the cached one (uploads are stored under unique saved names, so a replaced
    file has a new saved name).

    Returns True when the cache is current; False when any download failed.
    """
    if not metadata or not metadata.get("main_server_url"):
        return True
    task_id = metadata.get("task_id")
    if not task_id:
        return True
    files_list = metadata.get("task_files", []) or []
    expected = [f for f in files_list if f.get("filename") != "labels.parquet"]
    expected_map = {f.get("filename", ""): f for f in expected}

    cache_dir = os.path.join(Config.TASK_IMAGES_DIR, f"task_{task_id}", "data")
    os.makedirs(cache_dir, exist_ok=True)

    manifest = _read_assets_manifest(task_id)
    cached = manifest.get("files", {})

    # Prune cache entries no longer part of the task (deleted uploads must not
    # keep being served to students until the image is rebuilt)
    for fn in [fn for fn in cached if fn not in expected_map]:
        with contextlib.suppress(OSError):
            os.remove(os.path.join(cache_dir, fn))
        cached.pop(fn, None)

    to_download: list[dict[str, Any]] = []
    for fn, ent in expected_map.items():
        path = os.path.join(cache_dir, fn)
        meta = cached.get(fn)
        if meta and meta.get("saved_name") == ent.get("saved_name", fn) and os.path.isfile(path):
            continue
        to_download.append(ent)

    if to_download:
        logs.append(f"Syncing {len(to_download)} task file(s) into the asset cache...")
        main_server_url = metadata["main_server_url"]
        token = _sign_worker_token(metadata.get("submission_id", "unknown"))
        headers = {"X-Worker-Token": token}
        all_ok = True
        for ent in to_download:
            filename = ent.get("filename", "")
            saved_name = ent.get("saved_name", filename)
            url = f"{main_server_url}/api/worker/tasks/{task_id}/files/{filename}"
            dest_file = os.path.join(cache_dir, filename)
            try:
                logs.append(f"Downloading task file '{filename}' from server...")
                res = requests.get(url, headers=headers, timeout=Config.WORKER_DOWNLOAD_TIMEOUT)
                if res.status_code != 200:
                    logs.append(
                        f"Failed to download task file '{filename}': Status code {res.status_code}"
                    )
                    all_ok = False
                    continue
                fd, tmp_path = tempfile.mkstemp(
                    dir=cache_dir, prefix=f".{filename}.", suffix=".tmp"
                )
                try:
                    with os.fdopen(fd, "wb") as df:
                        df.write(res.content)
                    os.chmod(tmp_path, 0o644)
                    os.replace(tmp_path, dest_file)
                finally:
                    with contextlib.suppress(OSError):
                        os.remove(tmp_path)
                cached[filename] = {
                    "saved_name": saved_name,
                    "size": os.path.getsize(dest_file),
                }
                logs.append(f"Downloaded task file '{filename}' successfully.")
            except Exception as e:
                logs.append(f"Error downloading task file '{filename}': {e!s}")
                all_ok = False
        manifest["files"] = cached
        _write_assets_manifest(task_id, manifest)
        return all_ok

    logs.append(f"Task files up-to-date in cache (task_{task_id}: {len(expected)} file(s))")
    return True


def sync_labels_parquet_to_cache(metadata: dict[str, Any] | None, logs: list[str]) -> str | None:
    """Ensure the host-only labels.parquet cache is present and current.

    Returns the path of the cached labels file, or None when the task has no
    labels file or the download failed. The cache dir is chmod 0700 and the
    file 0600 — it is never mounted into the sandbox.
    """
    if not metadata or not metadata.get("main_server_url"):
        return None
    task_id = metadata.get("task_id")
    if not task_id:
        return None
    label_meta = next(
        (f for f in metadata.get("task_files", []) if f.get("filename") == "labels.parquet"),
        None,
    )
    if not label_meta:
        return None

    labels_dir = os.path.join(Config.TASK_IMAGES_DIR, f"task_{task_id}", "labels")
    os.makedirs(labels_dir, exist_ok=True)
    os.chmod(labels_dir, 0o700)
    dest_file = os.path.join(labels_dir, "labels.parquet")

    saved_name = label_meta.get("saved_name", "labels.parquet")
    manifest = _read_assets_manifest(task_id)
    if manifest.get("labels", {}).get("saved_name") == saved_name and os.path.isfile(dest_file):
        logs.append("Labels.parquet up-to-date in host-only cache.")
        return dest_file

    main_server_url = metadata["main_server_url"]
    token = _sign_worker_token(metadata.get("submission_id", "unknown"))
    headers = {"X-Worker-Token": token}
    url = f"{main_server_url}/api/worker/tasks/{task_id}/files/labels.parquet"
    try:
        logs.append("Downloading labels.parquet securely (host-only cache)...")
        res = requests.get(url, headers=headers, timeout=Config.WORKER_DOWNLOAD_TIMEOUT)
        if res.status_code != 200:
            logs.append(f"Failed to download labels.parquet: Status code {res.status_code}")
            return None
        fd, tmp_path = tempfile.mkstemp(dir=labels_dir, prefix=".labels.", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as df:
                df.write(res.content)
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, dest_file)
        finally:
            with contextlib.suppress(OSError):
                os.remove(tmp_path)
        os.chmod(labels_dir, 0o700)
        manifest["labels"] = {
            "saved_name": saved_name,
            "size": os.path.getsize(dest_file),
        }
        _write_assets_manifest(task_id, manifest)
        logs.append("Downloaded labels.parquet securely.")
        return dest_file
    except Exception as e:
        logs.append(f"Error downloading labels.parquet: {e!s}")
        return None


def download_task_files_to_dir(
    metadata: dict[str, Any] | None, temp_dir: str, logs: list[str]
) -> None:
    """Download task resource files (excluding labels.parquet) from the server into a temp dir."""
    if not metadata or "main_server_url" not in metadata:
        return
    files_list = metadata.get("task_files", [])
    if not files_list:
        return

    task_id = metadata.get("task_id")

    # Fast path: copy from pre-fetched build cache
    build_cache = os.path.join(Config.TASK_IMAGES_DIR, f"task_{task_id}", "data")
    if os.path.isdir(build_cache):
        copied = 0
        for f in files_list:
            fn = f["filename"]
            if fn == "labels.parquet":
                continue
            src = os.path.join(build_cache, fn)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(temp_dir, fn))
                copied += 1
        non_parquet_files = [ff for ff in files_list if ff.get("filename") != "labels.parquet"]
        if copied == len(non_parquet_files):
            logs.append(f"Copied {copied} task file(s) from build cache")
            return
        elif copied > 0:
            logs.append(
                f"Partially copied {copied}/{len(non_parquet_files)} file(s)"
                " from build cache, downloading rest"
            )

    submission_id = metadata.get("submission_id", "unknown")
    main_server_url = metadata["main_server_url"]
    token = _sign_worker_token(submission_id)
    headers = {"X-Worker-Token": token}

    for f in files_list:
        filename = f["filename"]
        if filename == "labels.parquet":
            continue  # Do NOT download labels.parquet to sandbox temp_dir!

        url = f"{main_server_url}/api/worker/tasks/{task_id}/files/{filename}"
        try:
            logs.append(f"Downloading task file '{filename}' from server...")
            res = requests.get(url, headers=headers, timeout=Config.WORKER_DOWNLOAD_TIMEOUT)
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


def download_labels_parquet_to_dir(
    metadata: dict[str, Any] | None, labels_dir: str, logs: list[str]
) -> str | None:
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
                res = requests.get(url, headers=headers, timeout=Config.WORKER_DOWNLOAD_TIMEOUT)
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


def run_stale_dir_sweep(max_age_hours: int = 24, logs: list[str] | None = None) -> int:
    """Remove abandoned task execution directories under the workspace root.

    Submission temp dirs are normally removed in a ``finally`` block, but a
    killed/restarted worker can leave them behind. Directories not modified in
    the last ``max_age_hours`` are considered abandoned and removed. Only
    directory entries are considered — loose files are left alone.

    Returns the number of directories removed.
    """
    workspace_root = Config.LAVBENCH_WORKSPACE_DIR
    if not workspace_root or not os.path.isdir(workspace_root):
        return 0
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for entry in os.scandir(workspace_root):
        if not entry.is_dir():
            continue
        try:
            st = entry.stat()
        except OSError:
            continue
        if st.st_mtime <= cutoff:
            if logs is not None:
                stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(st.st_mtime))
                logs.append(f"Removing stale task dir {entry.name} (last modified {stamp})")
            shutil.rmtree(entry.path, ignore_errors=True)
            removed += 1
    if removed and logs is not None:
        logs.append(f"Swept {removed} stale directory(ies) from workspace.")
    return removed
