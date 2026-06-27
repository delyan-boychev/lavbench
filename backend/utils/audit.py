from services.audit_service import log_action as _log_action


def log_audit(user_id, action_type, target_type, target_id=None, details=None):

    _log_action(
        admin_id=user_id,
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
        details=details,
    )
