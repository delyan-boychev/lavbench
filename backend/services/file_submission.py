"""File-mode submissions: check a Parquet before queueing and keep it with its notebook."""

from __future__ import annotations

import json
import logging
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

_ID_COLUMNS = ("id", "query_id", "doc_id")


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


def _open_parquet(path: str) -> tuple[Any, list[str]]:
    """Read only the footer and refuse files over the evaluation limits."""
    import pyarrow.parquet as pq  # type: ignore[import-untyped]

    from services.evaluation import EvaluationError

    try:
        parquet = pq.ParquetFile(path)
        metadata = parquet.metadata
    except Exception as exc:
        raise EvaluationError("EVALUATION_INVALID_PARQUET", "It is not a Parquet file.") from exc
    uncompressed = sum(
        metadata.row_group(group).column(column).total_uncompressed_size
        for group in range(metadata.num_row_groups)
        for column in range(metadata.row_group(group).num_columns)
    )
    if (
        os.path.getsize(path) > Config.MAX_PARQUET_FILE_BYTES
        or metadata.num_rows > Config.MAX_PARQUET_ROWS
        or metadata.num_columns > Config.MAX_PARQUET_COLUMNS
        or uncompressed > Config.MAX_PARQUET_UNCOMPRESSED_BYTES
    ):
        raise EvaluationError("EVALUATION_PARQUET_LIMIT_EXCEEDED", "It exceeds the size limits.")
    return parquet, list(parquet.schema_arrow.names)


# An honest file holds the labels' ids; 4x their bytes plus 64 KiB covers another writer's encoding
_ID_BYTES_FACTOR = 4
_ID_BYTES_SLACK = 64 * 1024


def _id_bytes(parquet: Any, columns: list[str]) -> int:
    metadata = parquet.metadata
    names = parquet.schema_arrow.names
    wanted = {names.index(name) for name in columns}
    return sum(
        metadata.row_group(group).column(index).total_uncompressed_size
        for group in range(metadata.num_row_groups)
        for index in wanted
    )


def _longest(column: Any) -> int:
    """Byte length of the longest string id, read from the dictionary when there is one."""
    import pyarrow as pa
    import pyarrow.compute as pc  # type: ignore[import-untyped]

    chunks = [
        chunk.dictionary if pa.types.is_dictionary(chunk.type) else chunk for chunk in column.chunks
    ]
    lengths = [pc.max(pc.binary_length(chunk)).as_py() or 0 for chunk in chunks if len(chunk)]
    return max(lengths, default=0)


def _is_text(arrow_type: Any) -> bool:
    import pyarrow as pa

    value = arrow_type.value_type if pa.types.is_dictionary(arrow_type) else arrow_type
    return bool(pa.types.is_string(value) or pa.types.is_large_string(value))


def label_stats(rules: ParquetRules, columns: list[str]) -> dict[str, Any]:
    """Distinct ids, id bytes and longest ids of the labels, cached by the labels' sha256."""
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    path = os.path.splitext(label_cache_path(rules))[0] + ".json"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cached: dict[str, Any] = json.load(f)
        return cached
    labels = pq.ParquetFile(str(rules.labels_path))
    table = labels.read(columns=columns)
    stats = {
        "ids": len(pc.unique(table.column(columns[0]).combine_chunks())),
        "id_bytes": _id_bytes(labels, columns),
        "longest": {
            name: _longest(table.column(name))
            for name in columns
            if _is_text(table.column(name).type)
        },
    }
    temporary = f"{path}.{os.getpid()}.tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(stats, f)
    os.replace(temporary, path)
    return stats


def _bounded_ids(path: str, parquet: Any, columns: list[str], stats: dict[str, Any]) -> str | None:
    """Rows, id bytes, id lengths and duplicates, without letting repeated values expand."""
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    retrieval = len(columns) > 1
    rows = parquet.metadata.num_rows
    if not retrieval and rows != stats["ids"]:
        return f"The file has {rows} rows; the task has {stats['ids']} ids."
    if _id_bytes(parquet, columns) > stats["id_bytes"] * _ID_BYTES_FACTOR + _ID_BYTES_SLACK:
        return "The id columns are far larger than the task's ids."
    text = [name for name in columns if _is_text(parquet.schema_arrow.field(name).type)]
    table = pq.read_table(path, columns=columns, read_dictionary=text)
    for name in text:
        longest = stats["longest"].get(name)
        if longest is not None and _longest(table.column(name)) > longest:
            return f"The column {name} has ids longer than any id of the task."
    if not retrieval:
        key = table.column(columns[0]).combine_chunks()
        values = key.dictionary_decode() if hasattr(key, "dictionary_decode") else key
        duplicates = rows - len(pc.unique(values))
        if duplicates:
            return f"{duplicates} ids appear more than once."
    return None


def sniff_parquet(path: str, rules: ParquetRules) -> str | list[str]:
    """Cheap checks for the web process, bounded by the labels: a problem, or the id columns."""
    from services.evaluation import EvaluationError

    if rules.labels_path is None:
        return "The task has no labels.parquet to check it against."
    try:
        _labels, label_columns = _open_parquet(rules.labels_path)
        parquet, columns = _open_parquet(path)
    except EvaluationError as exc:
        return str(exc)
    id_columns = ["query_id", "doc_id"] if "query_id" in label_columns else ["id"]
    missing = [c for c in (*id_columns, *rules.required_columns) if c not in columns]
    if missing:
        return f"The column(s) {', '.join(missing)} are missing."
    if not rules.required_columns and not any(c not in _ID_COLUMNS for c in columns):
        return "There is no prediction column next to the ids."
    try:
        problem = _bounded_ids(path, parquet, id_columns, label_stats(rules, id_columns))
    except Exception:
        return "The id columns cannot be read."
    return problem or id_columns


# Trusted id check, run under utils.limited_process so a hostile file cannot exhaust the web host
_ID_CHECK = '''\
"""Trusted check: compare a submission's ids with the task's label ids using Arrow."""
import json
import os
import sys

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.ipc as ipc
import pyarrow.parquet as pq


class TooLarge(Exception):
    pass


def kind(arrow_type):
    if pa.types.is_integer(arrow_type) or pa.types.is_floating(arrow_type):
        return "number"
    if pa.types.is_string(arrow_type) or pa.types.is_large_string(arrow_type):
        return "string"
    if pa.types.is_boolean(arrow_type):
        return "bool"
    if pa.types.is_timestamp(arrow_type) or pa.types.is_date(arrow_type):
        return "time"
    return None


def comparable(array):
    found = kind(array.type)
    if found == "number":
        return pc.cast(array, pa.float64())
    if found == "string":
        return pc.cast(array, pa.large_string())
    return array


def read_ids(path, columns, cap):
    parquet = pq.ParquetFile(path)
    schema = pa.schema([parquet.schema_arrow.field(name) for name in columns])
    batches, total = [], 0
    for batch in parquet.iter_batches(batch_size=65536, columns=columns):
        total += batch.nbytes
        if total > cap:
            raise TooLarge
        batches.append(batch)
    return pa.Table.from_batches(batches, schema=schema)


def label_ids(labels_path, cache_path, key):
    if os.path.exists(cache_path):
        with pa.memory_map(cache_path) as source:
            return ipc.open_file(source).read_all().column(0).combine_chunks()
    column = pq.read_table(labels_path, columns=[key]).column(key).combine_chunks()
    ids = pc.unique(column).sort()
    temporary = f"{cache_path}.{os.getpid()}.tmp"
    table = pa.table({key: ids})
    with pa.OSFile(temporary, "wb") as sink, ipc.new_file(sink, table.schema) as writer:
        writer.write_table(table)
    os.replace(temporary, cache_path)
    return ids


def check(sub_path, labels_path, cache_path, columns, cap):
    try:
        table = read_ids(sub_path, columns, cap)
    except TooLarge:
        return "The id columns decode to more than the size limit.", {}
    for name in columns:
        column = table.column(name)
        if kind(column.type) is None:
            return f"The column {name} holds values that are not plain ids.", {}
        empty = pc.sum(pc.is_null(column, nan_is_null=True)).as_py() or 0
        if empty:
            return f"The column {name} has {empty} empty values.", {}
    key = columns[0]
    labels = label_ids(labels_path, cache_path, key)
    if kind(table.column(key).type) != kind(labels.type):
        return "The ids have another type than the task's ids.", {}
    rows = table.num_rows
    distinct = table.group_by(columns).aggregate([]).num_rows
    if distinct != rows:
        return f"{rows - distinct} ids appear more than once.", {}
    submitted = comparable(pc.unique(table.column(key).combine_chunks()))
    expected = comparable(labels)
    missing = len(expected) - (pc.sum(pc.is_in(expected, value_set=submitted)).as_py() or 0)
    unexpected = len(submitted) - (pc.sum(pc.is_in(submitted, value_set=expected)).as_py() or 0)
    if missing or unexpected:
        counts = {
            "expected_ids": len(expected),
            "missing_ids": missing,
            "unexpected_ids": unexpected,
        }
        return (
            f"{missing} of the {len(expected)} expected ids are missing "
            f"and {unexpected} ids are not in the task.",
            counts,
        )
    return None, {}


def main():
    sub_path, labels_path, cache_path, columns, cap, result_path = sys.argv[1:]
    problem, counts = check(sub_path, labels_path, cache_path, json.loads(columns), int(cap))
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump({"problem": problem, "counts": counts}, f)
    return 0


sys.exit(main())
'''

_CHECK_SLOTS = threading.BoundedSemaphore(Config.SUBMISSION_CHECK_CONCURRENCY)
_CHECK_FILE_BYTES = 64 * 1024 * 1024
CHECK_BUSY_RETRY_SECONDS = 5
Problem = tuple[str, dict[str, int]]


class CheckBusyError(Exception):
    """Every slot for the id check is taken on this web worker."""


def label_cache_path(rules: ParquetRules) -> str:
    """The cached label ids, keyed by the labels' sha256 so a new labels file gets new ones."""
    directory = os.path.join(upload_root(), "label_ids")
    os.makedirs(directory, mode=0o700, exist_ok=True)
    digest = rules.labels_sha256 or file_sha256(str(rules.labels_path))
    return os.path.join(directory, f"{digest}.arrow")


def check_ids(path: str, rules: ParquetRules, id_columns: list[str]) -> Problem | None:
    """Compare the ids in a child process with memory, CPU, time and decoded-size limits."""
    if not _CHECK_SLOTS.acquire(blocking=False):
        raise CheckBusyError
    workdir = tempfile.mkdtemp(prefix="parquet_check_")
    try:
        result_path = os.path.join(workdir, "result.json")
        run = run_limited(
            _ID_CHECK,
            [
                path,
                str(rules.labels_path),
                label_cache_path(rules),
                json.dumps(id_columns),
                str(Config.MAX_PARQUET_DECODED_BYTES),
                result_path,
            ],
            workdir,
            memory_mb=Config.SUBMISSION_CHECK_MEMORY_MB,
            time_limit=Config.SUBMISSION_CHECK_TIME_LIMIT_SECONDS,
            max_file_bytes=_CHECK_FILE_BYTES,
        )
        if run.timed_out or run.returncode != 0 or not os.path.exists(result_path):
            logger.warning("Parquet id check stopped (rc=%s): %s", run.returncode, run.output_tail)
            return "The file is too large or too complex to check.", {}
        with open(result_path, encoding="utf-8") as f:
            result = json.load(f)
        if result.get("problem"):
            return str(result["problem"]), dict(result.get("counts") or {})
        return None
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        _CHECK_SLOTS.release()


def check_parquet(path: str, rules: ParquetRules) -> Problem | None:
    """Why *path* cannot be scored, with id counts only; None when it can."""
    sniffed = run_blocking(sniff_parquet, path, rules)
    if isinstance(sniffed, str):
        return sniffed, {}
    return check_ids(path, rules, sniffed)


def _busy() -> ErrorResult:
    return with_retry_after(err("ERR_SUBMISSION_CHECK_BUSY", 503), CHECK_BUSY_RETRY_SECONDS)


def check_submission_parquet(path: str, rules: ParquetRules) -> ErrorResult | None:
    """Refuse a Parquet that would fail scoring; call it with no transaction open."""
    try:
        problem = check_parquet(path, rules)
    except CheckBusyError:
        return _busy()
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
    try:
        problem = (
            ("The task has no baseline_submission.parquet.", {})
            if path is None
            else (check_parquet(path, rules))
        )
    except CheckBusyError:
        return _busy()
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
