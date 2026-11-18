"""Service-layer functions for submission creation, validation, and status management."""

from __future__ import annotations

import ast
import contextlib
import json
import logging
from bisect import bisect_right
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from flask import Response
from sqlalchemy import case, func, or_

from config import Config
from models import Challenge, Stage, Submission, Task, db
from models.base import uuid7
from models.submission import ORIGINS
from services.contest_rules import submission_deadline
from services.task_data import problem_fields, readiness_problems
from utils.access import ensure_registered
from utils.dates import local_day_start_utc, utcnow
from utils.error_utils import (
    DEFAULT_ERROR_MESSAGES,
    SERVICE_BUSY_RETRY_SECONDS,
    err,
    service_busy,
    with_retry_after,
)
from utils.submission_status import ACTIVE_STATUSES, INFRA_FAILURE

logger = logging.getLogger(__name__)

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
        deadline = submission_deadline(task, challenge) if task else None
        if task and task.stage_id:
            stage = db.session.get(Stage, task.stage_id)
            if stage:
                if now < stage.start_time:
                    return err(
                        "ERR_STAGE_NOT_STARTED",
                        400,
                        message=f"The stage '{stage.title}' has not started yet.",
                    )
                if deadline is not None and now > deadline:
                    return err(
                        "ERR_STAGE_DEADLINE_PASSED",
                        400,
                        message=f"The deadline for the stage '{stage.title}' has passed.",
                    )
        else:
            if challenge.start_time and now < challenge.start_time:
                return err("ERR_COMPETITION_NOT_STARTED", 400)
            if deadline is not None and now > deadline:
                return err("ERR_COMPETITION_ENDED", 400)

    codes = readiness_problems(task) if task else []
    if codes:
        # Strict readiness gate: any build, labels, data or baseline problem blocks
        # Submissions and reports every root cause (translated client-side)
        fields = problem_fields(task, codes)
        problems = [_problem_entry(code, fields.get(code, {})) for code in codes]
        return err("ERR_TASK_NOT_READY", 403, problems=problems)

    return None


def _problem_entry(code: str, fields: dict[str, Any]) -> dict[str, Any]:
    message = DEFAULT_ERROR_MESSAGES.get(code, "Task unavailable.")
    if fields:
        with contextlib.suppress(KeyError, IndexError, ValueError):
            message = message.format(**fields)
    return {**fields, "code": code, "message": message}


def submission_gate(
    task: Task, challenge: Challenge, user_id: Any, user_role: str
) -> tuple[Response, int] | None:
    """Registration, window and readiness: checked again before a workspace export starts."""
    if user_role == "competitor" and ensure_registered(user_id, challenge.id) is None:
        return err("ERR_NOT_REGISTERED", 403)
    return validate_submission_allowed(user_id, user_role, task, challenge)


def file_precheck(
    task: Task, challenge: Challenge, user_id: Any, user_role: str, sha256: str
) -> tuple[Response, int] | None:
    """Quota, active-run and duplicate checks from a file's hash, before it is fetched.

    ``create_submission`` repeats them under the submit lock and stays the final authority.
    """
    from services.file_submission import is_duplicate

    if is_duplicate(user_id, task, sha256):
        return err("ERR_SUBMISSION_DUPLICATE", 409)
    return _check_quotas(user_id, task, challenge) or _check_active_runs(user_id, user_role)


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


# Lower runs first: staff and baselines, then competitors by runs used today (0, 1-2, 3-5, 6+)
STAFF_PRIORITY = 0
_RUNS_TODAY_GROUP_STARTS = (1, 3, 6)


def submission_priority(user_role: str, runs_today: int) -> int:
    """Return the broker priority of a staff or competitor run (baselines use STAFF_PRIORITY)."""
    if user_role in ("admin", "jury"):
        return STAFF_PRIORITY
    return 1 + bisect_right(_RUNS_TODAY_GROUP_STARTS, runs_today)


def _today_counts(user_id: Any, task: Task, challenge: Challenge) -> tuple[int, int]:
    """Runs counting toward the quota sent today (the quota's local day): all, and on the task."""
    on_task = func.count(case((Submission.task_id == task.id, 1)))
    daily, task_today = quota_counted(
        db.session.query(func.count(Submission.id), on_task).filter(
            Submission.user_id == user_id,
            Submission.challenge_id == challenge.id,
            Submission.created_at >= local_day_start_utc(challenge.timezone),
        )
    ).one()
    return int(daily), int(task_today)


def _killed_runs_still_running(user_id: Any) -> int:
    """Killed runs whose sandbox has not been removed yet still hold an active-run slot."""
    from utils.cache_utils import get_coordination_client, sandbox_live_key

    attempts = [
        attempt
        for (attempt,) in db.session.query(Submission.celery_task_id).filter(
            Submission.user_id == user_id,
            Submission.is_baseline.is_(False),
            Submission.detailed_status == "killed",
            Submission.celery_task_id.isnot(None),
            Submission.created_at >= utcnow() - timedelta(days=1),
        )
    ]
    r = get_coordination_client()
    if not attempts or r is None:
        return 0
    try:
        pipe = r.pipeline(transaction=False)
        for attempt in attempts:
            pipe.exists(sandbox_live_key(attempt))
        return sum(1 for hit in pipe.execute() if hit)
    except Exception as e:
        logger.warning("Could not read live sandboxes of user %s: %s", user_id, e)
        return 0


def _check_active_runs(user_id: Any, user_role: str) -> tuple[Response, int] | None:
    """Each competitor has at most ``MAX_ACTIVE_RUNS_PER_USER`` runs queued or running."""
    if user_role != "competitor":
        return None
    active = Submission.query.filter(
        Submission.user_id == user_id,
        Submission.is_baseline.is_(False),
        Submission.status.in_(ACTIVE_STATUSES),
    ).count() + _killed_runs_still_running(user_id)
    limit = Config.MAX_ACTIVE_RUNS_PER_USER
    if active >= limit:
        return err(
            "ERR_TOO_MANY_ACTIVE_RUNS",
            429,
            message=f"You already have {limit} runs waiting or running. "
            "Submit again when one of them finishes.",
            limit=limit,
        )
    return None


def _check_quotas(
    user_id: Any, task: Task, challenge: Challenge, daily: int | None = None
) -> tuple[Response, int] | None:
    if daily is None:
        daily = _today_counts(user_id, task, challenge)[0]
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


def _checks_under_lock(
    task: Task,
    challenge: Challenge,
    user_id: Any,
    user_role: str,
    files: SubmissionFiles | None,
    queue_name: str,
    daily: int,
) -> tuple[Response, int] | None:
    """Duplicate, quota, active-run and ceiling checks, run under the submit lock."""
    from utils.cache_utils import get_queue_depth

    if files is not None:
        from services.file_submission import is_duplicate

        if is_duplicate(user_id, task, files.artifact_sha256):
            return err("ERR_SUBMISSION_DUPLICATE", 409)
    limited = _check_quotas(user_id, task, challenge, daily) or _check_active_runs(
        user_id, user_role
    )
    if limited:
        return limited
    if get_queue_depth(queue_name) >= Config.EVALUATION_QUEUE_CEILING:
        return with_retry_after(err("ERR_QUEUE_FULL", 503), SERVICE_BUSY_RETRY_SECONDS)
    return None


def create_submission(
    task: Task,
    challenge: Challenge,
    user_id: Any,
    user_role: str,
    cells: list[dict[str, Any]],
    *,
    origin: str,
    is_baseline: bool = False,
    infra_retry_count: int = 0,
    files: SubmissionFiles | None = None,
) -> Submission | tuple[Response, int]:
    """Create and dispatch a submission; the single creation path for every route.

    Returns the queued submission, or an ``err()`` response. A rejection happens
    before any row exists; an enqueue failure keeps the row, marks it
    ``failed_infra`` and returns 503 with its ``submission_id``. Competitor submissions pass
    registration, the window and readiness gates, the AST rules, the quotas and the
    limit of active runs per competitor; a rejection creates no row and uses no quota
    (Q21); only the broker's safety ceiling refuses for load. Baselines skip those checks
    and the ceiling: they are the system's own run that settles the task's readiness, so
    dropping one would leave the task blocked with no signal. ``infra_retry_count``
    numbers a baseline rerun after a platform failure. File tasks take checked ``files``
    instead of cells; a Parquet the user already submitted to the task is refused.
    ``origin`` (one of ``models.submission.ORIGINS``) records which route sent it.
    """
    if origin not in ORIGINS:
        raise ValueError(f"Unknown submission origin {origin!r}")
    from utils.cache_utils import (
        LockUnavailableError,
        cache_lock,
        clear_attempt_pending,
        mark_attempt_pending,
    )
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
    priority = STAFF_PRIORITY
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
        try:
            # One lock per user: the active-run limit spans every competition
            with cache_lock(f"submit_lock:user_{user_id}", ttl=10, strict=True) as got:
                if not got:
                    return err("ERR_SUBMIT_LOCKED", 429)
                daily, task_today = _today_counts(user_id, task, challenge)
                refused = _checks_under_lock(
                    task, challenge, user_id, user_role, files, queue_name, daily
                )
                if refused:
                    return refused
                priority = submission_priority(user_role, task_today)
                from services.task_locks import mode_locked

                # The first competitor submission locks the mode, so cached task views go stale
                locks_mode = user_role == "competitor" and not mode_locked(task)
                submission = _add_queued_submission(
                    task, challenge, user_id, cells, files=files, origin=origin
                )
                if locks_mode:
                    from utils.cache_utils import invalidate_challenge_cache

                    invalidate_challenge_cache(challenge.id)
        except LockUnavailableError:
            return service_busy()

    # A queued submission cannot change the leaderboard, which counts completed
    # Submissions only; the results path invalidates it when the score arrives
    publish_queue_update()

    attempt_id = f"submission_{int(utcnow().timestamp() * 1000):016d}_{submission.id}"
    submission.celery_task_id = attempt_id
    db.session.commit()
    from tasks import evaluate_submission
    from utils.metadata import hf_prep_seconds

    try:
        metadata = build_submission_metadata(
            task,
            challenge,
            submission,
            task_files_list=safe_json_loads(task.files, []),
            gpu_required=gpu_required,
        )
        # The dispatch-time limit and HF ZIP are read back by the watchdog and the worker routes
        db.session.commit()
        # Fetching and extracting HF data happens before the sandbox's own time limit starts
        hf_extra = hf_prep_seconds(metadata.get("hf_zip_size"))
        # Marked before sending, so a worker's claim can never come before it
        mark_attempt_pending(attempt_id)
        evaluate_submission.apply_async(
            args=[submission.id, metadata],
            soft_time_limit=Config.CELERY_TASK_SOFT_TIME_LIMIT + hf_extra,
            time_limit=Config.CELERY_TASK_TIME_LIMIT + hf_extra,
            priority=priority,
            queue=queue_name,
            task_id=attempt_id,
        )
    except Exception as e:
        clear_attempt_pending(attempt_id)
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
