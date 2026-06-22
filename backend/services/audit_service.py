"""Service-layer audit logging for admin actions."""

import logging
from flask import request
from models import db, AuditLog

logger = logging.getLogger(__name__)


def get_client_ip():
    if request.headers.getlist("X-Forwarded-For"):
        return request.headers.getlist("X-Forwarded-For")[0].split(',')[0].strip()
    return request.remote_addr or "127.0.0.1"


def log_action(admin_id, action_type, target_type, target_id=None, details=None, target_user_id=None, task_id=None, old_score=None, new_score=None, reason=None):
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
        entry = AuditLog(
            admin_id=admin_id,
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            details=details or {},
            ip_address=get_client_ip(),
            target_user_id=target_user_id,
            task_id=task_id,
            old_score=old_score,
            new_score=new_score,
            reason=reason
        )
        db.session.add(entry)
        db.session.flush()
    except Exception:
        logger.exception("Failed to write audit log for action_type=%s target_type=%s target_id=%s", action_type, target_type, target_id)
