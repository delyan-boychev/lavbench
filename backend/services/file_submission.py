"""File-mode submissions: check a Parquet before queueing and keep it with its notebook."""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Any

from flask import Response

from config import Config
from models import Submission, Task, db
from models.submission import SUBMISSION_FILES_DIR, submission_files_dir
from services.environment_package import SOLUTION_NOTEBOOK, SUBMISSION_PARQUET
from services.evaluator_script import evaluator_submission_columns
from utils.error_utils import err, with_retry_after
from utils.files import (
    BASELINE_SUBMISSION_FILE,
    LABELS_FILE,
    file_sha256,
    upload_root,
)
from utils.json_utils import safe_json_loads
from utils.limited_process import run_limited
from utils.threadpool import run_blocking

logger = logging.getLogger(__name__)

ErrorResult = tuple[Response, int]


@dataclass
class SubmissionFiles:
    """A checked Parquet (and its notebook) waiting to become part of a submission."""

    artifact_path: str
    artifact_sha256: str
    artifact_size: int
    notebook_path: str | None = None
    notebook_sha256: str | None = None
    workspace_meta: dict[str, Any] | None = None
    # False for a baseline, whose Parquet is the task's own hidden file
    owned: bool = True
    directory: str | None = field(default=None, repr=False)

    def attach(self, submission: Submission) -> None:
        """Move owned files into the submission's folder and record them on the row."""
        artifact, notebook = self.artifact_path, self.notebook_path
        if self.owned:
            target = submission_files_dir(submission.id)
            os.makedirs(target, exist_ok=True)
            artifact = os.path.join(target, SUBMISSION_PARQUET)
            os.replace(self.artifact_path, artifact)
            if self.notebook_path:
                notebook = os.path.join(target, SOLUTION_NOTEBOOK)
                os.replace(self.notebook_path, notebook)
            self.discard()
        submission.artifact_path = artifact
        submission.artifact_sha256 = self.artifact_sha256
        submission.artifact_size = self.artifact_size
        submission.notebook_path = notebook
        submission.notebook_sha256 = self.notebook_sha256
        submission.workspace_meta = self.workspace_meta

    def discard(self) -> None:
        if self.owned and self.directory:
            shutil.rmtree(self.directory, ignore_errors=True)


def incoming_dir() -> str:
    """A private folder on the upload volume, so files move into place without a copy."""
    parent = os.path.join(upload_root(), SUBMISSION_FILES_DIR, ".incoming")
    os.makedirs(parent, exist_ok=True)
    return tempfile.mkdtemp(dir=parent)


def task_file_path(task: Task, filename: str) -> str | None:
    """The stored path of one of the task's files, when it exists on disk."""
    for entry in safe_json_loads(task.files, []):
        if isinstance(entry, dict) and entry.get("filename") == filename:
            saved = os.path.basename(str(entry.get("saved_name") or ""))
            path = os.path.join(upload_root(), f"task_{task.id}", saved)
            return path if saved and os.path.isfile(path) else None
    return None


def baseline_files(task: Task) -> SubmissionFiles | None:
    """The hidden baseline submission of a file task, scored like a student's Parquet."""
    path = task_file_path(task, BASELINE_SUBMISSION_FILE)
    if path is None:
        return None
    entry = next(
        e for e in safe_json_loads(task.files, []) if e.get("filename") == BASELINE_SUBMISSION_FILE
    )
    sha256 = entry.get("sha256") or file_sha256(path)
    return SubmissionFiles(
        artifact_path=path,
        artifact_sha256=str(sha256),
        artifact_size=os.path.getsize(path),
        owned=False,
    )


@dataclass(frozen=True)
class ParquetRules:
    """What a task's Parquet must hold, read on the request thread before the check runs."""

    labels_path: str | None
    labels_sha256: str | None
    required_columns: tuple[str, ...]


def parquet_rules(task: Task) -> ParquetRules:
    metrics = task.metrics_config
    if isinstance(metrics, str):
        metrics = safe_json_loads(metrics, {})
    columns: list[str] = []
    if isinstance(metrics, dict):
        for name, cfg in metrics.items():
            options = cfg.get("options") if isinstance(cfg, dict) else None
            column = options.get("column") if isinstance(options, dict) else None
            if not name.startswith("_") and isinstance(column, str) and column:
                columns.append(column)
    columns.extend(evaluator_submission_columns(task.custom_eval_code))
    labels_path = task_file_path(task, LABELS_FILE)
    entry: dict[str, Any] = next(
        (e for e in safe_json_loads(task.files, []) if e.get("filename") == LABELS_FILE), {}
    )
    return ParquetRules(
        labels_path=labels_path,
        labels_sha256=str(entry.get("sha256") or "") or None,
        required_columns=tuple(dict.fromkeys(columns)),
    )


_CHECK_SLOTS = threading.BoundedSemaphore(Config.SUBMISSION_CHECK_CONCURRENCY)
_CHILD_SCRIPT = os.path.join(os.path.dirname(__file__), "parquet_check_child.py")
_MIB = 1024 * 1024
_MIN_FILE_BYTES = 64 * _MIB
# Labels ids, the submitted ids, Arrow's hash tables and a margin, per id byte
_ID_MEMORY_FACTOR = 4
_BATCH_ROWS = 1024
CHECK_BUSY_RETRY_SECONDS = 5
TOO_COMPLEX = "The file is too large or too complex to check."
Problem = tuple[str, dict[str, int]]


# Bump when the cached label stats or ids change shape, so old caches are rebuilt
LABEL_CACHE_FORMAT = 2
_STATS_KEYS = frozenset({"format", "retrieval", "ids", "kind", "longest", "id_bytes"})


class CheckBusyError(Exception):
    """Every slot for a Parquet check is taken on this web worker."""


class CheckFailedError(Exception):
    """The check itself failed (a bug or a broken environment), not the file."""


def label_cache_dir() -> str:
    directory = os.path.join(upload_root(), "label_ids", f"v{LABEL_CACHE_FORMAT}")
    os.makedirs(directory, mode=0o700, exist_ok=True)
    return directory


def label_cache_path(rules: ParquetRules) -> str:
    """The cached label ids, keyed by the labels' sha256 so a new labels file gets new ones."""
    digest = rules.labels_sha256 or file_sha256(str(rules.labels_path))
    return os.path.join(label_cache_dir(), f"{digest}.arrow")


def labels_sha256(files: Any) -> str | None:
    """The sha256 recorded for the labels in a ``Task.files`` value."""
    for entry in safe_json_loads(files, []):
        if isinstance(entry, dict) and entry.get("filename") == LABELS_FILE:
            return str(entry.get("sha256") or "") or None
    return None


def prune_label_cache(sha256: str | None) -> None:
    """Drop the cached ids of a labels file no task uses any more."""
    if not sha256 or Task.query.filter(Task.files.contains(sha256)).first() is not None:
        return
    for suffix in (".arrow", ".json"):
        with contextlib.suppress(OSError):
            os.remove(os.path.join(label_cache_dir(), f"{sha256}{suffix}"))


def _read_stats(cache_path: str) -> dict[str, Any] | None:
    """Cached stats in the current format, or None so the labels are read again."""
    try:
        with open(os.path.splitext(cache_path)[0] + ".json", encoding="utf-8") as f:
            stats = json.load(f)
    except (OSError, ValueError):
        return None
    if (
        not isinstance(stats, dict)
        or not stats.keys() >= _STATS_KEYS
        or stats["format"] != LABEL_CACHE_FORMAT
        or not os.path.isfile(cache_path)
    ):
        return None
    return stats


def _ceiling_mb() -> int:
    return Config.SUBMISSION_CHECK_MAX_MEMORY_MB


def required_memory_mb(stats: dict[str, Any]) -> int:
    """Memory a submission check needs for these labels, before the ceiling applies."""
    need = Config.SUBMISSION_CHECK_MEMORY_MB + math.ceil(
        _ID_MEMORY_FACTOR * int(stats["id_bytes"]) / _MIB
    )
    if stats.get("retrieval"):
        # A run's ids are bounded by the decoded cap, not by the labels
        need += math.ceil(Config.MAX_PARQUET_DECODED_BYTES / _MIB)
    return need


def _run_child(config: dict[str, Any], memory_mb: int, max_file_bytes: int) -> dict[str, Any]:
    """Run the Parquet check child: a limit hit refuses the file, any other failure raises."""
    if not _CHECK_SLOTS.acquire(blocking=False):
        raise CheckBusyError
    workdir = None
    try:
        workdir = tempfile.mkdtemp(prefix="parquet_check_")
        result_path = os.path.join(workdir, "result.json")
        config_path = os.path.join(workdir, "config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump({**config, "result_path": result_path, "cache_format": LABEL_CACHE_FORMAT}, f)
        with open(_CHILD_SCRIPT, encoding="utf-8") as f:
            script = f.read()
        run = run_limited(
            script,
            [config_path],
            workdir,
            memory_mb=memory_mb,
            time_limit=Config.SUBMISSION_CHECK_TIME_LIMIT_SECONDS,
            max_file_bytes=max_file_bytes,
        )
        if run.timed_out or run.returncode < 0:
            # Killed by a signal: the memory, CPU-time or wall-clock limit
            logger.warning("Parquet check hit a limit (rc=%s)", run.returncode)
            return {"problem": TOO_COMPLEX, "counts": {}, "crashed": True}
        if run.returncode != 0 or not os.path.exists(result_path):
            logger.error("Parquet check failed (rc=%s): %s", run.returncode, run.output_tail)
            raise CheckFailedError
        with open(result_path, encoding="utf-8") as f:
            result: dict[str, Any] = json.load(f)
        return result
    except OSError as exc:
        logger.error("Parquet check could not run: %s", exc)
        raise CheckFailedError from exc
    finally:
        if workdir:
            shutil.rmtree(workdir, ignore_errors=True)
        _CHECK_SLOTS.release()


def build_label_stats(labels_path: str, cache_path: str) -> dict[str, Any]:
    """Read the labels in the child, at the ceiling: columns, id statistics and cached ids."""
    ceiling = _ceiling_mb()
    return _run_child(
        {"mode": "labels", "labels_path": labels_path, "cache_path": cache_path},
        ceiling,
        max(_MIN_FILE_BYTES, ceiling * _MIB),
    )


def _label_stats(rules: ParquetRules) -> dict[str, Any] | Problem:
    if rules.labels_path is None:
        return "The task has no labels.parquet to check it against.", {}
    cache = label_cache_path(rules)
    stats = _read_stats(cache)
    if stats is not None:
        return stats
    built = build_label_stats(str(rules.labels_path), cache)
    if built.get("problem") or "stats" not in built:
        return str(built.get("problem") or "labels.parquet has no id column."), {}
    return dict(built["stats"])


def check_parquet(path: str, rules: ParquetRules) -> Problem | None:
    """Why *path* cannot be scored, with id counts only; every read happens in the child."""
    stats = _label_stats(rules)
    if isinstance(stats, tuple):
        return stats
    memory = min(_ceiling_mb(), required_memory_mb(stats))
    result = _run_child(
        {
            "mode": "submission",
            "sub_path": path,
            "cache_path": label_cache_path(rules),
            "required_columns": list(rules.required_columns),
            "limits": {
                "max_file_bytes": Config.MAX_PARQUET_FILE_BYTES,
                "max_rows": Config.MAX_PARQUET_ROWS,
                "max_columns": Config.MAX_PARQUET_COLUMNS,
                "max_uncompressed_bytes": Config.MAX_PARQUET_UNCOMPRESSED_BYTES,
                "max_decoded_bytes": Config.MAX_PARQUET_DECODED_BYTES,
                "batch_rows": _BATCH_ROWS,
            },
        },
        memory,
        _MIN_FILE_BYTES,
    )
    if not result.get("problem"):
        return None
    return str(result["problem"]), dict(result.get("counts") or {})


def check_labels(path: str, sha256: str | None) -> ErrorResult | None:
    """Validate an uploaded labels.parquet in the child and refuse one too large to check."""
    rules = ParquetRules(labels_path=path, labels_sha256=sha256, required_columns=())
    try:
        built = build_label_stats(path, label_cache_path(rules))
    except CheckBusyError:
        return _busy()
    except CheckFailedError:
        return _failed()
    ceiling = _ceiling_mb()
    limit = f"{ceiling} MB"
    too_large = err(
        "ERR_LABELS_TOO_LARGE",
        413,
        message=(
            f"labels.parquet holds too many ids to check each submission within {limit} "
            "(SUBMISSION_CHECK_MAX_MEMORY_MB)."
        ),
        limit=limit,
        field="labels.parquet",
    )
    if built.get("crashed"):
        return too_large
    if built.get("problem"):
        return err(
            "ERR_INVALID_LABELS_SCHEMA",
            400,
            message=f"Invalid labels.parquet: {built['problem']}",
        )
    from services.evaluation.validation import validate_parquet_schema_columns

    columns = list(built.get("columns") or [])
    is_valid, schema_err = validate_parquet_schema_columns(columns, is_submission=False)
    if not is_valid:
        return err(
            "ERR_INVALID_LABELS_SCHEMA",
            400,
            message=f"Invalid labels.parquet schema: {schema_err}",
        )
    if required_memory_mb(dict(built.get("stats") or {"id_bytes": 0})) > ceiling:
        return too_large
    return None


def _busy() -> ErrorResult:
    return with_retry_after(err("ERR_SUBMISSION_CHECK_BUSY", 503), CHECK_BUSY_RETRY_SECONDS)


def _failed() -> ErrorResult:
    return with_retry_after(err("ERR_SUBMISSION_CHECK_FAILED", 503), CHECK_BUSY_RETRY_SECONDS)


def check_submission_parquet(path: str, rules: ParquetRules) -> ErrorResult | None:
    """Refuse a Parquet that would fail scoring; call it with no transaction open."""
    try:
        problem = check_parquet(path, rules)
    except CheckBusyError:
        return _busy()
    except CheckFailedError:
        return _failed()
    if problem is None:
        return None
    detail, counts = problem
    return err(
        "ERR_SUBMISSION_FILE_INVALID",
        422,
        message=f"The submission file cannot be scored: {detail}",
        detail=detail,
        **counts,
    )


def check_baseline_parquet(task: Task) -> ErrorResult | None:
    """A file task needs a hidden baseline_submission.parquet that passes the same check.

    Ends the session's transaction first, so the check never holds a database connection.
    """
    path = task_file_path(task, BASELINE_SUBMISSION_FILE)
    rules = parquet_rules(task)
    db.session.commit()
    return check_baseline_file(path, rules)


def baseline_unreadable() -> ErrorResult:
    """The baseline check itself failed; the file is reported as unreadable."""
    detail = "The file could not be read."
    return err(
        "ERR_BASELINE_SUBMISSION_INVALID",
        422,
        message=f"baseline_submission.parquet cannot be scored: {detail}",
        detail=detail,
    )


def check_baseline_file(path: str | None, rules: ParquetRules) -> ErrorResult | None:
    """The scoring check on a baseline submission file, with no transaction open."""
    try:
        problem = (
            ("The task has no baseline_submission.parquet.", {})
            if path is None
            else check_parquet(path, rules)
        )
    except CheckBusyError:
        return _busy()
    except CheckFailedError:
        return _failed()
    if problem is None:
        return None
    detail, counts = problem
    return err(
        "ERR_BASELINE_SUBMISSION_INVALID",
        422,
        message=f"baseline_submission.parquet cannot be scored: {detail}",
        detail=detail,
        **counts,
    )


def read_notebook(path: str) -> tuple[str | None, dict[str, Any] | None]:
    """Parse a notebook off the gevent hub: the problem, or the notebook."""
    from services.file_validation import validate_notebook_content

    def parse() -> tuple[bool, str | None, dict[str, Any] | None]:
        with open(path, "rb") as handle:
            return validate_notebook_content(handle.read())

    valid, problem, notebook = run_blocking(parse)
    return (None, notebook) if valid else (problem or "Invalid notebook.", None)


def notebook_problem(path: str) -> str | None:
    """Why the file at *path* is not a Jupyter notebook, or None."""
    return read_notebook(path)[0]


def is_duplicate(user_id: Any, task: Task, sha256: str) -> bool:
    """Whether the user already sent this Parquet for the task.

    Only a platform failure (failed_infra) lets the same file be sent again; any other
    state, a scoring failure included, blocks it.
    """
    from services.submission_service import quota_counted

    query = quota_counted(
        Submission.query.filter(
            Submission.user_id == user_id,
            Submission.task_id == task.id,
            Submission.artifact_sha256 == sha256,
        )
    )
    return bool(query.first() is not None)
