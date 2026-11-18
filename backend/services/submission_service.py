"""Service-layer functions for submission creation, validation, and status management."""

from __future__ import annotations

import ast
import json
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from flask import Response
from sqlalchemy import or_

from config import Config
from models import Challenge, Stage, Submission, Task, db
from models.base import uuid7
from models.submission import ORIGINS
from utils.access import ensure_registered
from utils.dates import local_day_start_utc, utcnow
from utils.error_utils import DEFAULT_ERROR_MESSAGES, err
from utils.score_visibility import private_scores_revealed
from utils.submission_status import INFRA_FAILURE

if TYPE_CHECKING:
    from services.file_submission import SubmissionFiles


def validate_submission_allowed(
    user_id: str, user_role: str, task: Task, challenge: Challenge
) -> tuple[Response, int] | None:
    """Gate every submission before registration-independent work starts.

    Enforces, in order: active, not archived, not frozen, not finalized
    (competitors), stage/challenge deadlines with grace period, and task
    readiness (no recorded problem codes). Returns an ``err()`` response when
    blocked, otherwise ``None``. ``create_submission`` adds the registration check,
    the AST rules and the quotas around it.
    """
    if not challenge.is_active:
        return err("ERR_CHALLENGE_INACTIVE", 400)
    if challenge.is_archived:
        return err("ERR_CHALLENGE_ARCHIVED", 400)
    if challenge.is_frozen:
        return err("ERR_COMPETITION_FROZEN", 403)

    if user_role == "competitor":
        if challenge.scores_finalized:
            return err("ERR_COMPETITION_FINALIZED", 403)

        now = utcnow()
        grace = timedelta(seconds=int(Config.DEADLINE_GRACE_PERIOD_SECONDS))
        if task and task.stage_id:
            stage = db.session.get(Stage, task.stage_id)
            if stage:
                if now < stage.start_time:
                    return err(
                        "ERR_STAGE_NOT_STARTED",
                        400,
                        message=f"The stage '{stage.title}' has not started yet.",
                    )
                if stage.end_time and now > (stage.end_time + grace):
                    return err(
                        "ERR_STAGE_DEADLINE_PASSED",
                        400,
                        message=f"The deadline for the stage '{stage.title}' has passed.",
                    )
        else:
            if challenge.start_time and now < challenge.start_time:
                return err("ERR_COMPETITION_NOT_STARTED", 400)
            if challenge.end_time and now > (challenge.end_time + grace):
                return err("ERR_COMPETITION_ENDED", 400)

    if task and task.problem_codes:
        # Strict readiness gate: any build, labels, data or baseline problem blocks
        # Submissions and reports every root cause (translated client-side)
        codes = {c for c in task.problem_codes if isinstance(c, str)}
        problems = [
            {"code": code, "message": DEFAULT_ERROR_MESSAGES.get(code, "Task unavailable.")}
            for code in sorted(codes)
        ]
        return err("ERR_TASK_NOT_READY", 403, problems=problems)

    return None


def submission_gate(
    task: Task, challenge: Challenge, user_id: Any, user_role: str
) -> tuple[Response, int] | None:
    """Registration, window and readiness: checked again before a workspace export starts."""
    if user_role == "competitor" and ensure_registered(user_id, challenge.id) is None:
        return err("ERR_NOT_REGISTERED", 403)
    return validate_submission_allowed(user_id, user_role, task, challenge)


def file_precheck(
    task: Task, challenge: Challenge, user_id: Any, sha256: str
) -> tuple[Response, int] | None:
    """Quota and duplicate checks from a file's hash, before it is fetched or checked.

    ``create_submission`` repeats both under the submit lock and stays the final authority.
    """
    from services.file_submission import is_duplicate

    if is_duplicate(user_id, task, sha256):
        return err("ERR_SUBMISSION_DUPLICATE", 409)
    return _check_quotas(user_id, task, challenge)


def resolve_gpu_required(task: Task, challenge: Challenge) -> bool:
    """The task's GPU flag wins; the challenge's applies only when the task sets none."""
    # File tasks run no student code, so they never need a GPU
    if task.is_file_mode:
        return False
    if task.gpu_required is not None:
        return bool(task.gpu_required)
    return bool(challenge.gpu_required)


def quota_counted(query: Any) -> Any:
    """Restrict a Submission query to rows that count toward a quota.

    Baselines are system runs, and infrastructure failures are the platform's fault,
    so neither uses a competitor's daily or per-task allowance (Q22).
    """
    return query.filter(
        Submission.is_baseline.is_(False),
        or_(Submission.detailed_status.is_(None), Submission.detailed_status != INFRA_FAILURE),
    )


def _check_quotas(user_id: Any, task: Task, challenge: Challenge) -> tuple[Response, int] | None:
    day_start = local_day_start_utc(challenge.timezone)
    daily = quota_counted(
        Submission.query.filter(
            Submission.user_id == user_id,
            Submission.challenge_id == challenge.id,
            Submission.created_at >= day_start,
        )
    ).count()
    if daily >= challenge.max_eval_requests:
        return err(
            "ERR_DAILY_LIMIT_REACHED",
            429,
            message=f"Daily limit reached. Max {challenge.max_eval_requests} submissions per day.",
        )
    if task.max_submissions_per_period and task.submission_period_hours:
        period_start = utcnow() - timedelta(hours=task.submission_period_hours)
        in_period = quota_counted(
            Submission.query.filter(
                Submission.user_id == user_id,
                Submission.task_id == task.id,
                Submission.created_at >= period_start,
            )
        ).count()
        if in_period >= task.max_submissions_per_period:
            return err(
                "ERR_TASK_LIMIT_REACHED",
                429,
                message=f"Task limit reached. Max {task.max_submissions_per_period} "
                f"submissions per {task.submission_period_hours} hours.",
            )
    return None


def _add_queued_submission(
    task: Task,
    challenge: Challenge,
    user_id: Any,
    cells: list[dict[str, Any]],
    *,
    is_baseline: bool = False,
    infra_retry_count: int = 0,
    files: SubmissionFiles | None = None,
    origin: str,
) -> Submission:
    submission = Submission(
        id=uuid7(),
        origin=origin,
        user_id=user_id,
        challenge_id=challenge.id,
        task_id=task.id,
        status="queued",
        detailed_status="queued",
        is_baseline=is_baseline,
        infra_retry_count=infra_retry_count,
    )
    if files is not None:
        files.attach(submission)
    else:
        submission.code_cells = json.dumps(cells)
    db.session.add(submission)
    db.session.commit()
    return submission


def create_submission(
    task: Task,
    challenge: Challenge,
    user_id: Any,
    user_role: str,
    cells: list[dict[str, Any]],
    *,
    origin: str,
    is_baseline: bool = False,
    priority: int | None = None,
    infra_retry_count: int = 0,
    files: SubmissionFiles | None = None,
) -> Submission | tuple[Response, int]:
    """Create and dispatch a submission; the single creation path for every route.

    Returns the queued submission, or an ``err()`` response. A rejection happens
    before any row exists; an enqueue failure keeps the row, marks it
    ``failed_infra`` and returns 503 with its ``submission_id``. Competitor submissions pass
    registration, the window and readiness gates, the AST rules and the quotas; a
    rejection creates no row and uses no quota (Q21). Baselines skip those checks and
    the queue cap: they are the system's own run that settles the task's readiness, so
    dropping one would leave the task blocked with no signal. ``infra_retry_count``
    numbers a baseline rerun after a platform failure. File tasks take checked ``files``
    instead of cells; a Parquet the user already submitted to the task is refused.
    ``origin`` (one of ``models.submission.ORIGINS``) records which route sent it.
    """
    if origin not in ORIGINS:
        raise ValueError(f"Unknown submission origin {origin!r}")
    from utils.cache_utils import cache_lock, get_queue_depth
    from utils.json_utils import safe_json_loads
    from utils.metadata import build_submission_metadata
    from utils.sse_utils import publish_queue_update

    if task.is_file_mode != (files is not None):
        return err("ERR_TASK_MODE_MISMATCH", 409)
    if not is_baseline:
        blocked = submission_gate(task, challenge, user_id, user_role)
        if blocked:
            return blocked
        if files is None:
            passed, rule_error = check_execution_rules(task, cells)
            if not passed:
                return err("ERR_AST_RULE_FAILED", 400, message=rule_error)

    gpu_required = resolve_gpu_required(task, challenge)
    queue_name = "gpu_queue" if gpu_required else "cpu_queue"
    if is_baseline:
        submission = _add_queued_submission(
            task,
            challenge,
            user_id,
            cells,
            is_baseline=True,
            infra_retry_count=infra_retry_count,
            files=files,
            origin=origin,
        )
    else:
        with cache_lock(f"submit_lock:user_{user_id}:challenge_{challenge.id}", ttl=10) as got:
            if not got:
                return err("ERR_SUBMIT_LOCKED", 429)
            if files is not None:
                from services.file_submission import is_duplicate

                if is_duplicate(user_id, task, files.artifact_sha256):
                    return err("ERR_SUBMISSION_DUPLICATE", 409)
            limited = _check_quotas(user_id, task, challenge)
            if limited:
                return limited
            if get_queue_depth(queue_name) >= Config.MAX_QUEUED_EVALUATIONS:
                return err(
                    "ERR_QUEUE_FULL",
                    429,
                    message=(
                        f"Queue full (max {Config.MAX_QUEUED_EVALUATIONS} pending evaluations). "
                        "Please try again later."
                    ),
                )
            submission = _add_queued_submission(
                task, challenge, user_id, cells, files=files, origin=origin
            )

    # A queued submission cannot change the leaderboard, which counts completed
    # Submissions only; the results path invalidates it when the score arrives
    publish_queue_update()

    attempt_id = f"submission_{int(utcnow().timestamp() * 1000):016d}_{submission.id}"
    submission.celery_task_id = attempt_id
    db.session.commit()
    metadata = build_submission_metadata(
        task,
        challenge,
        submission,
        task_files_list=safe_json_loads(task.files, []),
        gpu_required=gpu_required,
    )
    from tasks import evaluate_submission

    try:
        evaluate_submission.apply_async(
            args=[submission.id, metadata],
            priority=priority
            if priority is not None
            else calculate_submission_priority(user_id, user_role),
            queue=queue_name,
            expires=Config.CELERY_MESSAGE_EXPIRES,
            task_id=attempt_id,
        )
    except Exception as e:
        submission.status = "failed"
        submission.detailed_status = INFRA_FAILURE
        # No message was sent, so the row keeps no attempt id
        submission.celery_task_id = None
        submission.logs = f"{submission.logs or ''}\nSubmission queue unavailable: {e}".strip()
        db.session.commit()
        publish_queue_update()
        return err("ERR_QUEUE_UNAVAILABLE", 503, submission_id=submission.id)
    return submission


def extract_code_from_cells(cells_list: list[Any]) -> list[str]:
    """Extract source code strings from a list of cell dicts (from notebook JSON)."""
    if not cells_list:
        return []
    extracted = []
    for cell in cells_list:
        if isinstance(cell, dict):
            source = cell.get("source", "")
            if isinstance(source, list):
                extracted.append("".join(source))
            else:
                extracted.append(str(source))
        elif isinstance(cell, str):
            extracted.append(cell)
        else:
            extracted.append(str(cell))
    return extracted


def extract_code_from_notebook(filepath: str) -> list[str]:
    """Open a .ipynb file and return all code cell sources as a list of strings."""
    try:
        with open(filepath) as f:
            data = json.load(f)
        code_cells = []
        for cell in data.get("cells", []):
            if cell.get("cell_type") == "code":
                source = cell.get("source", [])
                if isinstance(source, list):
                    code_cells.append("".join(source))
                else:
                    code_cells.append(str(source))
        return code_cells
    except Exception:
        return []


def check_execution_rules(task: Task, cells_list: list[dict[str, Any]]) -> tuple[bool, str | None]:
    (
        """Validate competitor code against task rules: """
        """banned magic commands, banned/whitelisted imports."""
    )
    extracted_cells = extract_code_from_cells(cells_list)
    combined_code = "\n".join(extracted_cells)

    # Always-banned dynamic execution bypasses (unconditional — cannot be opted out)
    banned_names = {
        "exec",
        "eval",
        "compile",
        "__import__",
        "importlib",
        "__builtins__",
        "builtins",
    }
    banned_attributes = {
        "exec",
        "__import__",
        "importlib",
        "__builtins__",
        "__globals__",
        "__subclasses__",
        "__code__",
    }
    banned_constants = {
        "exec",
        "eval",
        "compile",
        "__import__",
        "importlib",
        "__builtins__",
        "builtins",
        "__globals__",
        "__subclasses__",
        "__code__",
    }

    def get_violation_message(name: str) -> str:
        if name == "__import__":
            return "Rule Violation: Dynamic imports via __import__() are not allowed."
        if name == "exec":
            return "Rule Violation: exec() is not allowed."
        if name == "eval":
            return "Rule Violation: eval() is not allowed."
        if name == "compile":
            return "Rule Violation: compile() is not allowed."
        if name in ("__globals__", "__subclasses__", "__code__"):
            return f"Rule Violation: Access to meta-programming attribute '{name}' is banned."
        return f"Rule Violation: Dynamic execution or import via '{name}' is not allowed."

    try:
        tree = ast.parse(combined_code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in banned_names:
                return False, get_violation_message(node.id)
            elif isinstance(node, ast.Attribute) and node.attr in banned_attributes:
                return False, get_violation_message(node.attr)
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value in banned_constants
            ):
                return False, get_violation_message(node.value)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    root_import = alias.name.split(".")[0]
                    if root_import in banned_names:
                        return False, get_violation_message(root_import)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root_import = node.module.split(".")[0]
                    if root_import in banned_names:
                        return False, get_violation_message(root_import)
                for alias in node.names:
                    if alias.name in banned_names:
                        return False, get_violation_message(alias.name)
    except SyntaxError:
        # Fallback for code with syntax errors: check if any of
        # The banned names appear as whole words not preceded by a dot

        import re

        for name in banned_names:
            pattern = re.compile(rf"(?<!\.)\b{name}\b")
            if pattern.search(combined_code):
                return False, get_violation_message(name)

    if task.ban_magic_commands:
        import re

        # Remove triple-quoted strings first
        cleaned = re.sub(r'""".*?"""', "", combined_code, flags=re.DOTALL)
        cleaned = re.sub(r"'''.*?'''", "", cleaned, flags=re.DOTALL)
        # Remove single-line strings
        cleaned = re.sub(r'".*?"', "", cleaned)
        cleaned = re.sub(r"'.*?'", "", cleaned)
        # Remove comments
        cleaned = re.sub(r"#.*", "", cleaned)
        for line in cleaned.splitlines():
            stripped = line.strip()
            if stripped.startswith("!") or stripped.startswith("%"):
                return (
                    False,
                    "Rule Violation: Jupyter magic commands ('!' or '%') are banned.",
                )

    if task.banned_imports:
        banned = [lib.strip().lower() for lib in task.banned_imports.split(",") if lib.strip()]
        if banned:
            try:
                tree = ast.parse(combined_code)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for imp in node.names:
                            root_import = imp.name.split(".")[0].lower()
                            if root_import in banned:
                                return (
                                    False,
                                    f"Rule Violation: Import of library '{imp.name}' is banned.",
                                )
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        root_import = node.module.split(".")[0].lower()
                        if root_import in banned:
                            return (
                                False,
                                (f"Rule Violation: Import from library '{node.module}' is banned."),
                            )
            except SyntaxError:
                return (
                    False,
                    "Rule Violation: Code contains syntax errors "
                    "and could not be validated for banned imports.",
                )

    if task.whitelisted_imports:
        whitelisted = [
            lib.strip().lower() for lib in task.whitelisted_imports.split(",") if lib.strip()
        ]
        if whitelisted:
            try:
                tree = ast.parse(combined_code)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for imp in node.names:
                            root_import = imp.name.split(".")[0].lower()
                            if root_import not in whitelisted:
                                return (
                                    False,
                                    (
                                        f"Rule Violation: Import of library "
                                        f"'{imp.name}' is not allowed by whitelist."
                                    ),
                                )
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        root_import = node.module.split(".")[0].lower()
                        if root_import not in whitelisted:
                            return (
                                False,
                                (
                                    f"Rule Violation: Import from library "
                                    f"'{node.module}' is not allowed by whitelist."
                                ),
                            )
            except SyntaxError:
                return (
                    False,
                    "Rule Violation: Code contains syntax errors "
                    "and could not be validated for whitelisted imports.",
                )

    return True, None


def calculate_submission_priority(user_id: uuid.UUID, role: str) -> int:
    """Return 0 for admin/jury (always first), 1 for all students (FIFO by timestamp)."""
    if role in ["admin", "jury"]:
        return 0
    return 1


def uses_private_score_for_selection(task: Task, challenge: Challenge) -> bool:
    """Return whether automatic selection may use a task's private score.

    Only once competitors may see it, so the visible selection never leaks private results.
    """
    stage: Stage | None = getattr(task, "stage", None) if task.stage_id else None
    return private_scores_revealed(challenge, stage)


def submission_deadline(task: Task, challenge: Challenge) -> datetime | None:
    """Return the deadline that controls a task's leaderboard eligibility.

    Includes ``DEADLINE_GRACE_PERIOD_SECONDS`` so eligibility matches the window
    ``validate_submission_allowed`` accepts and the countdown UI advertises as the
    grace period. Competitors are shown the strict stage/challenge end time as the
    deadline; the grace only exists so a delay does not cost them a submission.
    """
    stage: Stage | None = getattr(task, "stage", None) if task.stage_id else None
    if stage is None and task.stage_id:
        stage = db.session.get(Stage, task.stage_id)
    base: datetime | None
    if stage is not None and stage.end_time is not None:
        base = stage.end_time
    else:
        base = challenge.end_time
    if base is None:
        return None
    deadline: datetime = base + timedelta(seconds=int(Config.DEADLINE_GRACE_PERIOD_SECONDS))
    return deadline


def is_submission_eligible(submission: Submission, task: Task, challenge: Challenge) -> bool:
    """Return whether a submission was created within the task's submission window.

    The window is the official deadline plus the grace period — the same window
    ``validate_submission_allowed`` accepts submissions in.
    """
    deadline = submission_deadline(task, challenge)
    return deadline is None or (
        submission.created_at is not None and submission.created_at <= deadline
    )


def get_best_submission(
    task: Task, user_subs: list[Submission], challenge: Challenge
) -> Submission | None:
    """
    Given a task, a list of completed submissions for a single user, and the challenge,
    resolves the best submission according to final selection, deadline, metrics, and tie-breakers.
    """
    eligible_subs = [s for s in user_subs if is_submission_eligible(s, task, challenge)]
    if not eligible_subs:
        return None

    # 1. Final selection logic
    final_sub = next((s for s in eligible_subs if s.is_final_selection), None)
    if final_sub:
        return final_sub

    # 2. Automatic selection logic
    # Private ordering must not influence the visible selection before private results are revealed
    use_private_score = uses_private_score_for_selection(task, challenge)

    subs_sorted = sorted(
        eligible_subs,
        key=lambda x: (
            (
                x.private_score
                if use_private_score and x.private_score is not None
                else (x.public_score if x.public_score is not None else -999999)
            ),
            -(x.execution_time_ms if x.execution_time_ms is not None else 999999),
            # Equal scores: the earlier submission wins, as in the leaderboard query
            -(x.created_at.timestamp() if x.created_at is not None else float("inf")),
        ),
        reverse=True,
    )

    if subs_sorted:
        return subs_sorted[0]
    return None
