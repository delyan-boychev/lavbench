"""Service-layer functions for submission creation, validation, and status management."""

import ast
import json
from datetime import datetime

from models import Submission


def extract_code_from_cells(cells_list):
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


def extract_code_from_notebook(filepath):
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


def check_execution_rules(task, cells_list):
    (
        """Validate student code against task rules: """
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

    def get_violation_message(name):
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
            elif isinstance(node, ast.Str) and node.s in banned_constants:
                return False, get_violation_message(node.s)
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
        # the banned names appear as whole words not preceded by a dot

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
                        for name in node.names:
                            root_import = name.name.split(".")[0].lower()
                            if root_import in banned:
                                return (
                                    False,
                                    f"Rule Violation: Import of library '{name.name}' is banned.",
                                )
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        root_import = node.module.split(".")[0].lower()
                        if root_import in banned:
                            return (
                                False,
                                (f"Rule Violation: Import from library '{node.module}' is banned."),
                            )
            except SyntaxError:
                pass

    if task.whitelisted_imports:
        whitelisted = [
            lib.strip().lower() for lib in task.whitelisted_imports.split(",") if lib.strip()
        ]
        if whitelisted:
            try:
                tree = ast.parse(combined_code)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for name in node.names:
                            root_import = name.name.split(".")[0].lower()
                            if root_import not in whitelisted:
                                return (
                                    False,
                                    (
                                        f"Rule Violation: Import of library "
                                        f"'{name.name}' is not allowed by whitelist."
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
                pass

    return True, None


def calculate_submission_priority(user_id, role):
    (
        """Return a priority integer: 9 for admin/jury, """
        """decaying from 6 for competitors per daily count."""
    )
    if role in ["admin", "jury"]:
        return 9
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    submission_count = Submission.query.filter(
        Submission.user_id == user_id, Submission.created_at >= today_start
    ).count()
    if submission_count == 0:
        return 6
    priority = max(1, 6 - submission_count)
    return priority


def get_best_submission(task, user_subs, challenge, is_lower_better=None):
    """
    Given a task, a list of completed submissions for a single user, and the challenge,
    resolves the best submission according to final selection, deadline, metrics, and tie-breakers.
    """
    if not user_subs:
        return None

    # Check for late submissions if the challenge has ended
    has_late_sub = False
    if challenge.end_time:
        has_late_sub = any(s.executed_at and s.executed_at > challenge.end_time for s in user_subs)

    # 1. Final selection logic
    final_sub = next((s for s in user_subs if s.is_final_selection), None)
    if final_sub and not has_late_sub:
        return final_sub

    # 2. Tie-breaking sorting logic
    # Since all database scores (public_score, private_score) are normalized to higher-is-better,
    # we always sort descending by score and ascending by execution time (faster is better).
    subs_sorted = sorted(
        user_subs,
        key=lambda x: (
            (
                x.private_score
                if x.private_score is not None
                else (x.public_score if x.public_score is not None else -999999)
            ),
            -(x.execution_time_ms if x.execution_time_ms is not None else 999999),
        ),
        reverse=True,
    )

    if subs_sorted:
        return subs_sorted[0]
    return None
