"""File-mode submissions: check a Parquet before queueing and keep it with its notebook."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Any

from flask import Response

from config import Config
from models import Submission, Task
from models.submission import SUBMISSION_FILES_DIR, submission_files_dir
from services.environment_package import SOLUTION_NOTEBOOK, SUBMISSION_PARQUET
from services.evaluator_script import evaluator_submission_columns
from utils.error_utils import err
from utils.files import (
    BASELINE_SUBMISSION_FILE,
    LABELS_FILE,
    file_sha256,
    upload_root,
)
from utils.json_utils import safe_json_loads
from utils.threadpool import run_blocking

ErrorResult = tuple[Response, int]

ORIGIN_WORKSPACE = "workspace"
ORIGIN_UPLOAD = "upload"
ORIGIN_EMERGENCY_UPLOAD = "emergency_upload"
_ID_COLUMNS = ("id", "query_id", "doc_id")


@dataclass
class SubmissionFiles:
    """A checked Parquet (and its notebook) waiting to become part of a submission."""

    artifact_path: str
    artifact_sha256: str
    artifact_size: int
    notebook_path: str | None = None
    notebook_sha256: str | None = None
    origin: str | None = None
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
        submission.origin = self.origin
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
    return ParquetRules(
        labels_path=task_file_path(task, LABELS_FILE),
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


def _id_counts(sub: Any, labels: Any, column: str) -> dict[str, int]:
    submitted = set(sub[column].tolist())
    expected = set(labels[column].tolist())
    return {
        "expected_ids": len(expected),
        "missing_ids": len(expected - submitted),
        "unexpected_ids": len(submitted - expected),
    }


def check_parquet(path: str, rules: ParquetRules) -> tuple[str, dict[str, int]] | None:
    """Why *path* cannot be scored, with id counts only; None when it can."""
    from services.evaluation import EvaluationError, validate_evaluation_frames

    if rules.labels_path is None:
        return "The task has no labels.parquet to check it against.", {}
    try:
        labels_file, label_columns = _open_parquet(rules.labels_path)
        parquet, columns = _open_parquet(path)
    except EvaluationError as exc:
        return str(exc), {}
    id_columns = ["query_id", "doc_id"] if "query_id" in label_columns else ["id"]
    missing = [c for c in (*id_columns, *rules.required_columns) if c not in columns]
    if missing:
        return f"The column(s) {', '.join(missing)} are missing.", {}
    if not rules.required_columns and not any(c not in _ID_COLUMNS for c in columns):
        return "There is no prediction column next to the ids.", {}
    try:
        sub = parquet.read(columns=id_columns).to_pandas()
        labels = labels_file.read(columns=id_columns).to_pandas()
    except Exception:
        return "The id columns cannot be read.", {}
    try:
        validate_evaluation_frames(sub, labels)
    except EvaluationError as exc:
        if exc.code in ("EVALUATION_ID_SET_MISMATCH", "EVALUATION_QUERY_SET_MISMATCH"):
            counts = _id_counts(sub, labels, id_columns[0])
            return (
                f"{counts['missing_ids']} of the {counts['expected_ids']} expected ids are "
                f"missing and {counts['unexpected_ids']} ids are not in the task.",
                counts,
            )
        return str(exc), {}
    return None


def check_submission_parquet(path: str, task: Task) -> ErrorResult | None:
    """Refuse a Parquet that would fail scoring; runs in the threadpool, before any row exists."""
    problem = run_blocking(check_parquet, path, parquet_rules(task))
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
    """A file task needs a hidden baseline_submission.parquet that passes the same check."""
    path = task_file_path(task, BASELINE_SUBMISSION_FILE)
    problem: tuple[str, dict[str, int]] | None
    if path is None:
        problem = ("The task has no baseline_submission.parquet.", {})
    else:
        problem = run_blocking(check_parquet, path, parquet_rules(task))
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


def notebook_problem(path: str) -> str | None:
    """Why the file at *path* is not a Jupyter notebook, or None."""
    from services.file_validation import validate_notebook_content

    with open(path, "rb") as handle:
        content = handle.read()
    valid, problem, _notebook = validate_notebook_content(content)
    return None if valid else problem


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
