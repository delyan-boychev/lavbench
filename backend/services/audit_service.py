"""Service-layer audit logging for admin actions."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from flask import has_request_context
from sqlalchemy import or_, select

from models import AuditLog, Environment, User, db
from utils.client_ip import get_client_ip

logger = logging.getLogger(__name__)


def _clean_details(val: Any) -> Any:
    if isinstance(val, dict):
        return {k: _clean_details(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [_clean_details(v) for v in val]
    elif isinstance(val, uuid.UUID):
        return str(val)
    return val


def log_action(
    admin_id: uuid.UUID | None,
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
            ip_address=get_client_ip() if has_request_context() else None,
            target_user_id=target_user_id,
            task_id=task_id,
            old_score=old_score,
            new_score=new_score,
            reason=reason,
        )
        db.session.add(entry)
        # Deliberately NO commit here: committing mid-request would flush the
        # Caller's pending transaction (H-C3). The audit row is committed by
        # The caller alongside the action it describes, so the audit log can
        # Never claim an action that was rolled back
    except Exception:
        logger.exception(
            "Failed to write audit log for action_type=%s target_type=%s target_id=%s",
            action_type,
            target_type,
            target_id,
        )


def challenge_audit_conditions(challenge: Any) -> list[Any]:
    """SQL conditions selecting every audit row about a challenge and what belongs to it."""
    stage_ids = [s.id for s in challenge.stages]
    task_ids = [t.id for t in challenge.tasks]
    competitors = (
        select(User.id)
        .where(User.role == "competitor", User.challenge_id == challenge.id)
        .scalar_subquery()
    )
    environments = (
        select(Environment.id)
        .where(or_(Environment.challenge_id == challenge.id, Environment.stage_id.in_(stage_ids)))
        .scalar_subquery()
    )
    conditions = [
        (AuditLog.target_type == "challenge") & (AuditLog.target_id == challenge.id),
        (AuditLog.target_type == "environment") & (AuditLog.target_id.in_(environments)),
        (AuditLog.target_type == "user") & (AuditLog.target_id.in_(competitors)),
        AuditLog.target_user_id.in_(competitors),
    ]
    if stage_ids:
        conditions.append((AuditLog.target_type == "stage") & (AuditLog.target_id.in_(stage_ids)))
    if task_ids:
        conditions.append((AuditLog.target_type == "task") & (AuditLog.target_id.in_(task_ids)))
        conditions.append(AuditLog.task_id.in_(task_ids))
    return conditions
