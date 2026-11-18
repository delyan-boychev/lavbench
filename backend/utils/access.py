"""Competitor registration, access and password-reset permission helpers."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from models import Challenge, User, db
from utils.auth_utils import check_competitor_access as _check
from utils.auth_utils import jury_challenge_ids


def ensure_registered(user_id: str, challenge_id: str) -> User | None:

    user = db.session.get(User, user_id)
    if not user or not _check(user, challenge_id):
        return None
    return user


def competitor_submissions_locked(challenge: Challenge | None) -> bool:
    """Whether a competitor may no longer view their own submissions.

    One rule for every list, the detail and the live logs: they stay viewable until
    the challenge is finalised, so a submission made in the grace period after the
    deadline can still be followed to its result (M8).
    """
    return bool(challenge and challenge.scores_finalized)


def password_reset_refusal(
    viewer: dict[str, Any],
    target: User,
    challenge: Challenge | None,
    assigned_ids: Collection[Any] | None = None,
) -> str | None:
    """The error code that refuses this password reset, or None when the viewer may do it.

    The admin resets any account but their own; a jury member resets only competitors of
    a competition they judge, before it starts. ``assigned_ids`` spares a lookup per row.
    """
    role, viewer_id = viewer["role"], viewer["user_id"]
    if role == "admin":
        return "ERR_CANNOT_RESET_OWN_PASSWORD" if str(target.id) == str(viewer_id) else None
    if role != "jury":
        return "ERR_ACCESS_DENIED"
    if target.role != "competitor":
        return "ERR_JURY_CANNOT_EDIT_ADMIN"
    if assigned_ids is None:
        assigned_ids = jury_challenge_ids(viewer_id)
    if target.challenge_id is None or target.challenge_id not in assigned_ids:
        return "ERR_ACCESS_DENIED"
    if challenge is not None and challenge.is_started:
        return "ERR_CANNOT_RESET_STARTED"
    return None
