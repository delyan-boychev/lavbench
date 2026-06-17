"""Service-layer functions for submission creation, validation, and status management."""

import os
import json
import ast
from datetime import datetime
from models import db, Submission, is_metric_lower_better

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
        with open(filepath, "r") as f:
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
    """Validate student code against task rules: banned magic commands, banned/whitelisted imports."""
    extracted_cells = extract_code_from_cells(cells_list)
    combined_code = "\n".join(extracted_cells)
    
    if task.ban_magic_commands:
        for line in combined_code.splitlines():
            stripped = line.strip()
            if stripped.startswith("!") or stripped.startswith("%"):
                return False, "Rule Violation: Jupyter magic commands ('!' or '%') are banned."
                
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
                                return False, f"Rule Violation: Import of library '{name.name}' is banned."
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            root_import = node.module.split(".")[0].lower()
                            if root_import in banned:
                                return False, f"Rule Violation: Import from library '{node.module}' is banned."
            except SyntaxError:
                pass

    if task.whitelisted_imports:
        whitelisted = [lib.strip().lower() for lib in task.whitelisted_imports.split(",") if lib.strip()]
        if whitelisted:
            try:
                tree = ast.parse(combined_code)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for name in node.names:
                            root_import = name.name.split(".")[0].lower()
                            if root_import not in whitelisted:
                                return False, f"Rule Violation: Import of library '{name.name}' is not allowed by whitelist."
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            root_import = node.module.split(".")[0].lower()
                            if root_import not in whitelisted:
                                return False, f"Rule Violation: Import from library '{node.module}' is not allowed by whitelist."
            except SyntaxError:
                pass
                
    return True, None

def calculate_submission_priority(user_id, role):
    """Return a priority integer: 9 for admin/jury, decaying from 6 for competitors per daily count."""
    if role in ['admin', 'jury']:
        return 9
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    submission_count = Submission.query.filter(
        Submission.user_id == user_id,
        Submission.created_at >= today_start
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
    if is_lower_better is None:
        is_lower_better = False
        if task.metrics_config:
            try:
                m_config = json.loads(task.metrics_config) if isinstance(task.metrics_config, str) else task.metrics_config
                for m_name, m_info in m_config.items():
                    if m_info.get("higher_is_better") is False or is_metric_lower_better(m_name):
                        is_lower_better = True
                    break
            except Exception:
                pass

    if is_lower_better:
        subs_sorted = sorted(user_subs, key=lambda x: (
            x.private_score if x.private_score is not None else (x.public_score if x.public_score is not None else 999999),
            x.execution_time_ms if x.execution_time_ms is not None else 999999
        ))
    else:
        subs_sorted = sorted(user_subs, key=lambda x: (
            x.private_score if x.private_score is not None else (x.public_score if x.public_score is not None else -999999),
            -(x.execution_time_ms if x.execution_time_ms is not None else 999999)
        ), reverse=True)

    if subs_sorted:
        return subs_sorted[0]
    return None
