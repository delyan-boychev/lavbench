"""Service-layer functions for submission creation, validation, and status management."""

from __future__ import annotations

import ast
import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from flask import Response

from config import Config
from models import Challenge, Stage, Submission, Task, db
from utils.dates import utcnow
from utils.error_utils import err


def validate_submission_allowed(
    user_id: str, user_role: str, task: Task, challenge: Challenge
) -> tuple[Response, int] | None:
    """Shared gate for both submit endpoints (challenge-scoped and task-scoped).

    Enforces, in order: active, not archived, not frozen, not finalized
    (competitors), and stage/challenge deadlines with grace period. Returns an
    ``err()`` response when blocked, otherwise ``None``. Registration and quota
    checks stay in the endpoints (they differ in locking and ordering).
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

    return None


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
    """Return whether automatic selection may use a task's private score."""
    if challenge.scores_finalized:
        return bool(challenge.reveal_results)

    stage: Stage | None = getattr(task, "stage", None) if task.stage_id else None
    return bool(stage and stage.is_finalized and stage.reveal_results)


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
        ),
        reverse=True,
    )

    if subs_sorted:
        return subs_sorted[0]
    return None
