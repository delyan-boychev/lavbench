"""Worker runtime utilities — Docker sandbox execution, status reporting."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import logging
import os
import shutil
import tarfile
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from typing import Any

import requests
from docker import DockerClient  # type: ignore[import-untyped]
from docker.types import DeviceRequest, Ulimit  # type: ignore[import-untyped]

from config import Config
from utils.files import file_sha256
from utils.worker_auth import sign_worker_token, worker_request_headers

logger = logging.getLogger(__name__)


def fetch_submission_run_content(metadata: dict[str, Any]) -> tuple[str | None, str | None]:
    """Fetch user code + evaluator script for a submission from the server.

    Messages no longer embed the (potentially large) user code and evaluator
    script; the worker fetches them on demand with a signed token bound to the
    submission just before execution. Returns ``(user_code, custom_eval_code)``.
    """
    submission_id = metadata.get("submission_id", "unknown")
    main_url = metadata.get("main_server_url")
    if not main_url:
        logger.error("No main_server_url in metadata — cannot fetch run content")
        raise RuntimeError("Cannot fetch run content: no main_server_url")
    headers = worker_request_headers(metadata, "submission_run_content")
    if not headers["X-Worker-Token"] or not headers["X-Worker-Capability"]:
        raise RuntimeError("Cannot sign worker token for run-content fetch")

    url = f"{main_url}/api/worker/submission-run-content/{submission_id}"
    resp = requests.get(
        url,
        headers=headers,
        timeout=Config.WORKER_REPORT_TIMEOUT,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Server returned {resp.status_code} for run-content fetch")
    data = resp.json()
    return data.get("user_code"), data.get("custom_eval_code")


def _sign_worker_token(submission_id: Any = None) -> str:
    """Compatibility alias for callers while issuing fresh per-request tokens."""
    return sign_worker_token()


SANDBOX_UID = 65534
SANDBOX_GID = 65534
# Working directories run_sandbox mounts a fresh volume on: /app for submissions,
# /work for the custom evaluator. Task images must own each one (image_builder)
SANDBOX_WORKING_DIRS = ("/app", "/work")


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
        # Read access for the sandbox user regardless of host file modes
        member.mode = 0o644 | (member.mode & 0o111)
    return member


_DOWNLOAD_CHUNK = 1024 * 1024
# Partial downloads; readers of a shared cache skip names with this prefix
DOWNLOAD_TEMP_PREFIX = ".download-"
# Long enough for another job to fetch a 10 GiB file at about 12 MB/s
DOWNLOAD_LOCK_MAX_WAIT = 900
_LOCK_POLL_SECONDS = 0.5
# Manifest updates are a small JSON write, so a long wait means a stuck holder
_MANIFEST_LOCK_MAX_WAIT = 30


class DownloadError(RuntimeError):
    """A worker download failed or did not match its recorded size or sha256."""


def _file_matches(path: str, size_bytes: int | None, sha256: str | None) -> bool:
    """Whether *path* holds exactly the recorded content (needs a recorded sha256)."""
    if not sha256 or not os.path.isfile(path):
        return False
    if size_bytes is not None and os.path.getsize(path) != size_bytes:
        return False
    return file_sha256(path) == sha256


def _lock_path(dest: str) -> str:
    """``<dir>/../.locks/<dir>-<name>.lock``: outside the data dir baked into task images."""
    dest_dir, name = os.path.split(dest)
    parent, dir_name = os.path.split(dest_dir)
    return os.path.join(parent, ".locks", f"{dir_name}-{name}.lock")


@contextlib.contextmanager
def _file_lock(lock_path: str | None, max_wait: float | None = None) -> Iterator[None]:
    """Exclusive flock shared by every worker process on this host's volume.

    Raises ``DownloadError`` when the lock is still held after *max_wait* seconds
    (default ``DOWNLOAD_LOCK_MAX_WAIT``).
    """
    if lock_path is None:
        yield
        return
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        deadline = time.monotonic() + (DOWNLOAD_LOCK_MAX_WAIT if max_wait is None else max_wait)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise DownloadError(
                        f"timed out waiting for {os.path.basename(lock_path)}"
                    ) from None
                time.sleep(_LOCK_POLL_SECONDS)
        yield
    finally:
        os.close(fd)


def _install_verified(
    chunks: Iterable[bytes],
    dest: str,
    size_bytes: int | None,
    sha256: str | None,
    mode: int,
) -> None:
    """Write *chunks* to a temp file next to *dest*, verify, then ``os.replace`` it."""
    fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(dest),
        prefix=f"{DOWNLOAD_TEMP_PREFIX}{os.path.basename(dest)}.",
        suffix=".tmp",
    )
    try:
        digest = hashlib.sha256()
        received = 0
        with os.fdopen(fd, "wb") as out:
            for chunk in chunks:
                out.write(chunk)
                digest.update(chunk)
                received += len(chunk)
        if size_bytes is not None and received != size_bytes:
            raise DownloadError(f"size mismatch: expected {size_bytes} bytes, got {received}")
        if sha256 and digest.hexdigest() != sha256:
            raise DownloadError("sha256 mismatch: the file is corrupted")
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, dest)
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp_path)


def _file_chunks(path: str) -> Iterator[bytes]:
    with open(path, "rb") as fh:
        while chunk := fh.read(_DOWNLOAD_CHUNK):
            yield chunk


def download_file(
    url: str,
    headers: dict[str, str],
    dest: str,
    *,
    size_bytes: int | None = None,
    sha256: str | None = None,
    mode: int = 0o644,
    lock: bool = False,
    reuse: bool = True,
) -> bool:
    """Stream *url* into *dest* atomically, verifying size and sha256 when recorded.

    With *lock*, a concurrent caller for the same *dest* waits and then reuses the
    verified file, unless *reuse* is False (the caller knows *dest* is stale). Returns
    False when the file was reused, True when it was downloaded; raises
    ``DownloadError`` on an HTTP error, a size or sha256 mismatch or a lock timeout.
    """
    with _file_lock(_lock_path(dest) if lock else None):
        if lock and reuse and _file_matches(dest, size_bytes, sha256):
            return False
        if size_bytes is None and not sha256:
            logger.debug("No recorded size or sha256 for %s, skipping verification", url)
        res = requests.get(
            url, headers=headers, timeout=Config.WORKER_DOWNLOAD_TIMEOUT, stream=True
        )
        with contextlib.closing(res):
            if res.status_code != 200:
                raise DownloadError(f"HTTP {res.status_code}")
            _install_verified(
                res.iter_content(chunk_size=_DOWNLOAD_CHUNK), dest, size_bytes, sha256, mode
            )
    return True


def copy_file_verified(
    src: str,
    dest: str,
    *,
    size_bytes: int | None = None,
    sha256: str | None = None,
    mode: int = 0o644,
) -> bool:
    """Copy a local file into a shared cache under the same lock and checks as a download.

    Returns False when *dest* already held the verified content.
    """
    with _file_lock(_lock_path(dest)):
        if _file_matches(dest, size_bytes, sha256):
            return False
        _install_verified(_file_chunks(src), dest, size_bytes, sha256, mode)
    return True


def entry_size(entry: dict[str, Any]) -> int | None:
    """Recorded size of a ``Task.files`` entry, or None when missing or invalid."""
    size = entry.get("size_bytes")
    return size if isinstance(size, int) and not isinstance(size, bool) else None


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
    storage_opt: dict[str, str] | None = None,
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
            logger.warning(
                "gpu_required but no gpu_id (WORKER_GPU_ID unset) — "
                "falling back to count=-1 (requests ALL GPUs)"
            )
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
    if storage_opt:
        run_kwargs["storage_opt"] = storage_opt

    container: Any | None = None
    seed_volume: Any | None = None
    try:
        # Seed the sandbox through a per-run anonymous volume: the daemon
        # Can't put_archive into a tmpfs on a not-yet-started container, so
        # /app is a disposable volume that is removed after the run
        # Tar metadata is normalized to the sandbox user (65534) with
        # World-accessible modes — the seed dir is host-owned (e.g. 0o700
        # Mkdtemp) and the container runs as non-root nobody
        seed_volume = docker_client.volumes.create()
        run_kwargs["volumes"] = {seed_volume.name: {"bind": working_dir, "mode": "rw"}}
        # A sandbox without an enforceable writable-layer quota can exhaust
        # The worker host, so unsupported storage drivers fail closed
        container = docker_client.containers.create(**run_kwargs)
        with tempfile.TemporaryDirectory(prefix="lavbench-seed-") as td:
            tar_path = os.path.join(td, "seed.tar")
            with tarfile.open(tar_path, "w") as tar:
                # Put_archive ignores metadata on the '.' root entry, so
                # /app would keep the daemon's root-owned 0o755 mount point
                # And the non-root sandbox user could not write outputs
                # A leading '/' entry makes older daemons chown/chmod the
                # Volume root (/app) itself before the seed contents. Newer
                # Daemons ignore it; task images own every directory in
                # SANDBOX_WORKING_DIRS, which the empty volume inherits
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

    stdout_lines: deque[str] = deque()
    stdout_chars = 0
    sink_chars = sum(len(str(item)) for item in logs_list)
    process_timeout = False
    exit_code = -1

    def stream_logs() -> None:
        nonlocal sink_chars, stdout_chars
        try:
            for chunk in container.logs(stream=True, follow=True):
                if chunk:
                    text = chunk.decode("utf-8", errors="replace")
                    for line in text.splitlines(keepends=True):
                        clean = line.rstrip("\r\n")
                        if clean:
                            clean = clean[-Config.WORKER_MAX_STDOUT_CHARS :]
                            stdout_lines.append(clean)
                            stdout_chars += len(clean)
                            while stdout_lines and stdout_chars > Config.WORKER_MAX_STDOUT_CHARS:
                                stdout_chars -= len(stdout_lines.popleft())
                            sink_line = clean[-Config.MAX_LOG_CHARS :]
                            logs_list.append(sink_line)
                            sink_chars += len(sink_line)
                            while logs_list and sink_chars > Config.MAX_LOG_CHARS:
                                sink_chars -= len(str(logs_list.pop(0)))
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
                # Poll exit status at 1Hz instead of 10Hz — detecting a
                # Finished container a second late is irrelevant vs. the load
                # This loop placed on the Docker daemon
                time.sleep(1.0)
        except Exception as exc:
            logs_list.append(f"Error during container execution: {exc}")
            container.kill()
            process_timeout = True

        t.join(timeout=30.0)
        if hasattr(logs_list, "flush"):
            logs_list.flush()

        try:
            result = container.wait()
            exit_code = result.get("StatusCode", -1)
        except Exception:
            exit_code = -1

        if collect_files:
            for container_path, host_path in collect_files:
                try:
                    stream, _stat = container.get_archive(container_path)
                    # Spool the bounded archive to disk so a valid large output does
                    # Not require duplicate bytearray/bytes/BytesIO copies in RAM
                    with tempfile.TemporaryFile() as archive:
                        archive_size = 0
                        for chunk in stream:
                            archive_size += len(chunk)
                            if archive_size > Config.MAX_COLLECT_BUFFER_BYTES:
                                raise ValueError(
                                    f"collected archive from {container_path} exceeded "
                                    f"{Config.MAX_COLLECT_BUFFER_BYTES}-byte buffer cap"
                                )
                            archive.write(chunk)
                        archive.seek(0)
                        with tarfile.open(fileobj=archive, mode="r:") as tar:
                            for member in tar:
                                if not member.isfile():
                                    continue
                                # Per-member cap, enforced from the tar header size
                                # Before any extraction
                                if member.size > Config.MAX_EXTRACT_MEMBER_BYTES:
                                    logger.warning(
                                        "Skipping oversized member %s (%d bytes) in %s",
                                        member.name,
                                        member.size,
                                        container_path,
                                    )
                                    continue
                                extracted = tar.extractfile(member)
                                if extracted is not None:
                                    os.makedirs(os.path.dirname(host_path), exist_ok=True)
                                    written = 0
                                    with open(host_path, "wb") as f:
                                        while True:
                                            block = extracted.read(1024 * 1024)
                                            if not block:
                                                break
                                            written += len(block)
                                            if written > Config.MAX_EXTRACT_MEMBER_BYTES:
                                                raise ValueError(
                                                    f"member {member.name} in {container_path} "
                                                    "exceeded "
                                                    f"{Config.MAX_EXTRACT_MEMBER_BYTES}-byte "
                                                    "extract cap"
                                                )
                                            f.write(block)
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
    storage_opt: dict[str, str] | None = None,
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
    if storage_opt is None:
        configured_storage_size = Config.WORKER_SANDBOX_STORAGE_OPT.strip()
        storage_opt = {"size": configured_storage_size} if configured_storage_size else None

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
        storage_opt=storage_opt,
    )


MAX_LOG_LINES = Config.WORKER_MAX_LOG_LINES


class StreamingLogList(list[str]):
    """A list subclass that batches appended log lines and publishes them via SSE.

    Lines are buffered and flushed as a single pipelined batch (>=50 lines or
    100ms since the last flush) instead of one Redis round trip per line.
    """

    _BATCH_LINES = 50
    _FLUSH_INTERVAL_SECONDS = 0.1

    def __init__(self, submission_id: Any) -> None:
        super().__init__()
        self.submission_id = submission_id
        self._pending: list[str] = []
        self._last_flush: float = 0.0

    def append(self, item: str) -> None:
        super().append(item)
        if len(self) > MAX_LOG_LINES:
            self.pop(0)
        self._pending.append(str(item))
        if len(self._pending) >= self._BATCH_LINES or (
            self._pending and time.time() - self._last_flush >= self._FLUSH_INTERVAL_SECONDS
        ):
            self.flush()

    def flush(self) -> None:
        if not self._pending:
            return
        pending = self._pending
        self._pending = []
        try:
            from utils.sse_utils import publish_submission_log_batch

            publish_submission_log_batch(self.submission_id, pending)
        except Exception:
            logger.exception("[StreamingLogList Error] Failed to publish log batch to Redis")
        finally:
            self._last_flush = time.time()


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
            headers = worker_request_headers(metadata, "report_submission")
            headers["Content-Type"] = "application/json"
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


def _update_assets_manifest(task_id: Any, mutate: Callable[[dict[str, Any]], None]) -> bool:
    """Apply *mutate* to the manifest under its lock and write it atomically.

    Returns False when the update failed; the cached files are still verified, so the
    next sync only re-checks them.
    """
    path = _assets_manifest_path(task_id)
    lock_path = os.path.join(os.path.dirname(path), ".locks", "assets-manifest.lock")
    try:
        with _file_lock(lock_path, max_wait=_MANIFEST_LOCK_MAX_WAIT):
            manifest = _read_assets_manifest(task_id)
            mutate(manifest)
            fd, tmp_path = tempfile.mkstemp(
                dir=os.path.dirname(path), prefix=".assets.", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(manifest, f)
                os.replace(tmp_path, path)
            finally:
                with contextlib.suppress(OSError):
                    os.remove(tmp_path)
    except (OSError, DownloadError) as e:
        logger.warning("Could not update the asset manifest of task %s: %s", task_id, e)
        return False
    return True


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

    cached = _read_assets_manifest(task_id).get("files", {})

    # Prune cache entries no longer part of the task (deleted uploads must not
    # Keep being served to students until the image is rebuilt)
    pruned = [fn for fn in cached if fn not in expected_map]
    for fn in pruned:
        with contextlib.suppress(OSError):
            os.remove(os.path.join(cache_dir, os.path.basename(fn)))

    to_download: list[tuple[dict[str, Any], bool]] = []
    for fn, ent in expected_map.items():
        safe_name = os.path.basename(fn)
        path = os.path.join(cache_dir, safe_name)
        meta = cached.get(fn)
        if meta and meta.get("saved_name") == ent.get("saved_name", fn) and os.path.isfile(path):
            continue
        # A different saved_name means the cached copy is stale: no point hashing it
        to_download.append((ent, not meta))

    if to_download:
        logs.append(f"Syncing {len(to_download)} task file(s) into the asset cache...")
        main_server_url = metadata["main_server_url"]
        headers = worker_request_headers(metadata, "task_file")
        all_ok = True
        synced: dict[str, dict[str, Any]] = {}
        for ent, reuse in to_download:
            filename = ent.get("filename", "")
            saved_name = ent.get("saved_name", filename)
            safe_name = os.path.basename(filename)
            url = f"{main_server_url}/api/worker/tasks/{task_id}/files/{filename}"
            dest_file = os.path.join(cache_dir, safe_name)
            try:
                logs.append(f"Downloading task file '{filename}' from server...")
                download_file(
                    url,
                    headers,
                    dest_file,
                    size_bytes=entry_size(ent),
                    sha256=ent.get("sha256"),
                    lock=True,
                    reuse=reuse,
                )
                synced[filename] = {
                    "saved_name": saved_name,
                    "size": os.path.getsize(dest_file),
                }
                logs.append(f"Downloaded task file '{filename}' successfully.")
            except Exception as e:
                logs.append(f"Error downloading task file '{filename}': {e!s}")
                all_ok = False

        def _merge(manifest: dict[str, Any]) -> None:
            files = manifest.setdefault("files", {})
            for fn in pruned:
                files.pop(fn, None)
            files.update(synced)

        _update_assets_manifest(task_id, _merge)
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
    cached_labels = _read_assets_manifest(task_id).get("labels")
    if (
        cached_labels
        and cached_labels.get("saved_name") == saved_name
        and os.path.isfile(dest_file)
    ):
        logs.append("Labels.parquet up-to-date in host-only cache.")
        return dest_file

    main_server_url = metadata["main_server_url"]
    headers = worker_request_headers(metadata, "task_file")
    url = f"{main_server_url}/api/worker/tasks/{task_id}/files/labels.parquet"
    try:
        logs.append("Downloading labels.parquet securely (host-only cache)...")
        download_file(
            url,
            headers,
            dest_file,
            size_bytes=entry_size(label_meta),
            sha256=label_meta.get("sha256"),
            mode=0o600,
            lock=True,
            reuse=not cached_labels,
        )
        os.chmod(labels_dir, 0o700)
        labels_entry = {"saved_name": saved_name, "size": os.path.getsize(dest_file)}
        _update_assets_manifest(task_id, lambda manifest: manifest.update(labels=labels_entry))
        logs.append("Downloaded labels.parquet securely.")
        return dest_file
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
