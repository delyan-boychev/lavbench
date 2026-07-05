"""Service-layer audit logging for admin actions."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from flask import request

from models import AuditLog, db

logger = logging.getLogger(__name__)


def get_client_ip() -> str:
    if request.headers.getlist("X-Forwarded-For"):
        return request.headers.getlist("X-Forwarded-For")[0].split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"


def _clean_details(val: Any) -> Any:
    if isinstance(val, dict):
        return {k: _clean_details(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [_clean_details(v) for v in val]
    elif isinstance(val, uuid.UUID):
        return str(val)
    return val


def log_action(
    admin_id: uuid.UUID,
    action_type: str,
    target_type: str,
    target_id: uuid.UUID | str | None = None,
    details: dict[str, Any] | None = None,
    target_user_id: uuid.UUID | str | None = None,
    task_id: uuid.UUID | str | None = None,
    old_score: float | None = None,
    new_score: float | None = None,
    reason: str | None = None,
) -> None:
    """Log an admin action to the audit_logs table.

    Args:
        admin_id: ID of the admin performing the action
        action_type: create, update, delete, finalize, archive, import, reset_password
        target_type: user, challenge, task, stage, submission
        target_id: ID of the affected entity
        details: dict with relevant context (e.g. changed fields)
        target_user_id: for user-targeted actions (legacy compat)
        task_id: for task-targeted actions (legacy compat)
        old_score: previous score value (legacy compat)
        new_score: new score value (legacy compat)
        reason: justification (legacy compat)
    """
    try:
        cleaned_details = _clean_details(details) if details else {}
        entry = AuditLog(
            admin_id=admin_id,
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            details=cleaned_details,
            ip_address=get_client_ip(),
            target_user_id=target_user_id,
            task_id=task_id,
            old_score=old_score,
            new_score=new_score,
            reason=reason,
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        logger.exception(
            "Failed to write audit log for action_type=%s target_type=%s target_id=%s",
            action_type,
            target_type,
            target_id,
        )
