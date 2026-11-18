"""Run an admin- or jury-provided evaluator as a resource-limited Python subprocess."""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from typing import Any

import pandas as pd

from config import Config
from services.evaluation.exceptions import EvaluationError

logger = logging.getLogger(__name__)

_EXIT_INVALID_SCRIPT = 3
_EXIT_INVALID_OUTPUT = 4
_MAX_FILE_BYTES = 256 * 1024 * 1024
_EXTRA_PROCESSES = 256
_STDERR_LOG_BYTES = 4000

# Trusted harness: applies the limits before any evaluator code runs, then scores the data
_HARNESS = '''\
"""Trusted harness: limits this process, loads the evaluator and writes its metrics."""
import json
import resource
import sys


def main() -> int:
    limits, eval_path, sub_path, labels_path, opts_path, result_path = sys.argv[1:7]
    for name, (soft, hard) in json.loads(limits).items():
        kind = getattr(resource, name)
        current_hard = resource.getrlimit(kind)[1]
        if current_hard != resource.RLIM_INFINITY:
            hard = min(hard, current_hard)
            soft = min(soft, hard)
        resource.setrlimit(kind, (soft, hard))

    with open(eval_path, encoding="utf-8") as f:
        source = f.read()
    try:
        code = compile(source, "evaluator.py", "exec")
    except SyntaxError as exc:
        sys.stderr.write(f"Evaluator does not compile: {exc}\\n")
        return 3
    namespace = {"__name__": "evaluator"}
    exec(code, namespace)
    evaluate = namespace.get("evaluate")
    if not callable(evaluate):
        sys.stderr.write("Evaluator does not define a callable evaluate\\n")
        return 3

    import pandas as pd

    df_sub = pd.read_parquet(sub_path)
    df_labels = pd.read_parquet(labels_path)
    with open(opts_path, encoding="utf-8") as f:
        options = json.load(f)
    result = evaluate(df_sub, df_labels, options)
    if not isinstance(result, dict):
        sys.stderr.write(f"evaluate returned {type(result).__name__}, not a dict\\n")
        return 4
    clean = {}
    for key, value in result.items():
        try:
            clean[str(key)] = float(value)
        except (TypeError, ValueError):
            sys.stderr.write(f"Metric {key!r} is not numeric\\n")
            return 4
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(clean, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def _child_env(workdir: str) -> dict[str, str]:
    """Build the child environment from scratch so no worker secret is inherited."""
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


def _user_task_count() -> int | None:
    """Count the current user's threads, which RLIMIT_NPROC limits as a whole."""
    uid = str(os.getuid())
    total = 0
    try:
        entries = list(os.scandir("/proc"))
    except OSError:
        return None
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            with open(f"/proc/{entry.name}/status", encoding="utf-8") as f:
                fields = dict(line.split(":", 1) for line in f if ":" in line)
        except (OSError, ValueError):
            continue
        if fields.get("Uid", "").split()[:1] == [uid]:
            total += int(fields.get("Threads", "1"))
    return total


def _limits() -> dict[str, tuple[int, int]]:
    """Return the resource limits the harness applies to itself."""
    memory = Config.CUSTOM_EVALUATOR_MEMORY_MB * 1024 * 1024
    seconds = Config.CUSTOM_EVALUATOR_TIME_LIMIT_SECONDS
    limits = {
        "RLIMIT_AS": (memory, memory),
        "RLIMIT_CPU": (seconds, seconds + 1),
        "RLIMIT_CORE": (0, 0),
        "RLIMIT_FSIZE": (_MAX_FILE_BYTES, _MAX_FILE_BYTES),
    }
    tasks = _user_task_count()
    if tasks is not None:
        # A limit below the user's current count would stop the child creating any thread
        limits["RLIMIT_NPROC"] = (tasks + _EXTRA_PROCESSES, tasks + _EXTRA_PROCESSES)
    return limits


def _kill_group(pid: int) -> None:
    """Kill the evaluator's whole process group, including anything it spawned."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, signal.SIGKILL)


def _read_tail(path: str) -> str:
    """Return the end of the evaluator's output for the worker log."""
    try:
        with open(path, "rb") as f:
            f.seek(max(0, os.path.getsize(path) - _STDERR_LOG_BYTES))
            return f.read().decode("utf-8", errors="replace").strip()
    except OSError:
        return ""


def _parse_result(result_path: str) -> dict[str, float]:
    """Read result.json and require a mapping of metric names to finite floats."""
    if os.path.getsize(result_path) > Config.MAX_EVALUATOR_RESULT_BYTES:
        raise EvaluationError(
            "EVALUATOR_INVALID_OUTPUT",
            "Custom evaluator output exceeds the configured size limit.",
        )
    with open(result_path, encoding="utf-8") as f:
        result = json.load(f)
    if not isinstance(result, dict):
        raise EvaluationError(
            "EVALUATOR_INVALID_OUTPUT",
            "Custom evaluator output must be a metric mapping.",
        )
    clean: dict[str, float] = {}
    for key, value in result.items():
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise EvaluationError(
                "EVALUATOR_INVALID_OUTPUT",
                f"Custom evaluator metric {key!r} is not numeric.",
            ) from exc
        if not math.isfinite(numeric):
            raise EvaluationError(
                "EVALUATOR_INVALID_OUTPUT",
                f"Custom evaluator metric {key!r} is not finite.",
            )
        clean[str(key)] = numeric
    return clean


def run_custom_evaluator(
    code: str,
    df_sub: pd.DataFrame,
    df_labels: pd.DataFrame,
    options: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Run ``evaluate(df_sub, df_labels, options)`` from *code* and return its metrics.

    The evaluator runs in the worker's interpreter with a clean environment, a private
    temporary folder and resource limits; it has no network or filesystem isolation, an
    accepted risk because evaluators come only from admins and jury and every upload is audited.
    """
    time_limit = Config.CUSTOM_EVALUATOR_TIME_LIMIT_SECONDS
    workdir = tempfile.mkdtemp(prefix="custom_eval_")
    try:
        paths = {
            name: os.path.join(workdir, name)
            for name in (
                "harness.py",
                "evaluator.py",
                "predictions.parquet",
                "labels.parquet",
                "options.json",
                "result.json",
                "output.log",
            )
        }
        try:
            with open(paths["harness.py"], "w", encoding="utf-8") as f:
                f.write(_HARNESS)
            with open(paths["evaluator.py"], "w", encoding="utf-8") as f:
                f.write(code)
            df_sub.to_parquet(paths["predictions.parquet"], index=False)
            df_labels.to_parquet(paths["labels.parquet"], index=False)
            with open(paths["options.json"], "w", encoding="utf-8") as f:
                json.dump(options or {}, f)
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("Custom evaluator inputs could not be staged: %s", exc)
            raise EvaluationError(
                "EVALUATOR_EXECUTION_FAILED",
                "Custom evaluator did not complete successfully.",
            ) from exc

        command = [
            sys.executable,
            "-I",
            "-B",
            paths["harness.py"],
            json.dumps(_limits()),
            paths["evaluator.py"],
            paths["predictions.parquet"],
            paths["labels.parquet"],
            paths["options.json"],
            paths["result.json"],
        ]
        timed_out = False
        with open(paths["output.log"], "wb") as log_file:
            try:
                proc = subprocess.Popen(  # noqa: S603 - fixed interpreter and harness
                    command,
                    cwd=workdir,
                    env=_child_env(workdir),
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                )
            except OSError as exc:
                logger.warning("Custom evaluator process could not start: %s", exc)
                raise EvaluationError(
                    "EVALUATOR_EXECUTION_FAILED",
                    "Custom evaluator did not complete successfully.",
                ) from exc
            try:
                returncode = proc.wait(timeout=time_limit)
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_group(proc.pid)
                returncode = proc.wait()
            finally:
                _kill_group(proc.pid)

        if timed_out or returncode == -signal.SIGXCPU:
            raise EvaluationError(
                "EVALUATOR_TIMEOUT",
                f"Custom evaluator exceeded the {time_limit} second time limit.",
            )
        if returncode != 0 or not os.path.exists(paths["result.json"]):
            logger.warning(
                "Custom evaluator failed (rc=%s): %s",
                returncode,
                _read_tail(paths["output.log"]),
            )
            if returncode == _EXIT_INVALID_SCRIPT:
                raise EvaluationError(
                    "EVALUATOR_INVALID_SCRIPT",
                    "Custom evaluator does not compile or define a callable evaluate function.",
                )
            if returncode == _EXIT_INVALID_OUTPUT:
                raise EvaluationError(
                    "EVALUATOR_INVALID_OUTPUT",
                    "Custom evaluator output must map metric names to numbers.",
                )
            raise EvaluationError(
                "EVALUATOR_EXECUTION_FAILED",
                "Custom evaluator did not complete successfully.",
            )
        try:
            return _parse_result(paths["result.json"])
        except (OSError, ValueError) as exc:
            raise EvaluationError(
                "EVALUATOR_INVALID_OUTPUT",
                "Custom evaluator output is not valid JSON.",
            ) from exc
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
