from __future__ import annotations

from typing import Any

from services.audit_service import log_action as _log_action


def log_audit(
    user_id: int | str,
    action_type: str,
    target_type: str,
    target_id: int | str | None = None,
    details: dict[str, Any] | None = None,
) -> None:

    _log_action(
        admin_id=user_id,  # type: ignore[arg-type]
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,  # type: ignore[arg-type]
        details=details,
    )
