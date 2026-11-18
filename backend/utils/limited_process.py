"""Run a trusted Python script as a short-lived child with resource limits and a clean env."""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
from dataclasses import dataclass

_OUTPUT_TAIL_BYTES = 4000

# Applies the limits before the script's own code runs, then runs the script as __main__
_LAUNCHER = '''\
"""Trusted launcher: limit this process, then run the script named in argv."""
import json
import resource
import runpy
import sys

for name, (soft, hard) in json.loads(sys.argv[1]).items():
    kind = getattr(resource, name)
    current_hard = resource.getrlimit(kind)[1]
    if current_hard != resource.RLIM_INFINITY:
        hard = min(hard, current_hard)
        soft = min(soft, hard)
    resource.setrlimit(kind, (soft, hard))
sys.argv = sys.argv[2:]
runpy.run_path(sys.argv[0], run_name="__main__")
'''


@dataclass(frozen=True)
class LimitedResult:
    returncode: int
    timed_out: bool
    output_tail: str


def child_env(workdir: str) -> dict[str, str]:
    """Build the child environment from scratch so no secret of the parent is inherited."""
    return {
        "PATH": f"{os.path.dirname(sys.executable)}:/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "HOME": workdir,
        "TMPDIR": workdir,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        # Arrow's default allocator and glibc arenas reserve address space that RLIMIT_AS counts
        "ARROW_DEFAULT_MEMORY_POOL": "system",
        "MALLOC_ARENA_MAX": "2",
    }


def limits(memory_mb: int, seconds: int, max_file_bytes: int) -> dict[str, tuple[int, int]]:
    """The resource limits the launcher applies to the child."""
    memory = memory_mb * 1024 * 1024
    result = {
        "RLIMIT_AS": (memory, memory),
        "RLIMIT_CPU": (seconds, seconds + 1),
        "RLIMIT_CORE": (0, 0),
        "RLIMIT_FSIZE": (max_file_bytes, max_file_bytes),
    }
    # No RLIMIT_NPROC: it counts every thread of the user and so aborted honest children
    return result


def _kill_group(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, signal.SIGKILL)


def _read_tail(path: str) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(max(0, os.path.getsize(path) - _OUTPUT_TAIL_BYTES))
            return f.read().decode("utf-8", errors="replace").strip()
    except OSError:
        return ""


def run_limited(
    script: str,
    args: list[str],
    workdir: str,
    *,
    memory_mb: int,
    time_limit: int,
    max_file_bytes: int,
) -> LimitedResult:
    """Run *script* in *workdir* under the limits; its whole process group dies at the end.

    Raises ``OSError`` when the child cannot start.
    """
    launcher = os.path.join(workdir, "launcher.py")
    target = os.path.join(workdir, "script.py")
    output = os.path.join(workdir, "output.log")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(_LAUNCHER)
    with open(target, "w", encoding="utf-8") as f:
        f.write(script)
    command = [
        sys.executable,
        "-I",
        "-B",
        launcher,
        json.dumps(limits(memory_mb, time_limit, max_file_bytes)),
        target,
        *args,
    ]
    timed_out = False
    with open(output, "wb") as log_file:
        proc = subprocess.Popen(  # noqa: S603 - fixed interpreter and trusted script
            command,
            cwd=workdir,
            env=child_env(workdir),
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
        try:
            returncode = proc.wait(timeout=time_limit)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_group(proc.pid)
            returncode = proc.wait()
        finally:
            _kill_group(proc.pid)
    timed_out = timed_out or returncode == -signal.SIGXCPU
    return LimitedResult(returncode, timed_out, _read_tail(output))
