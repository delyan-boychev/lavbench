"""Competitor registration and access helpers."""

from __future__ import annotations

from models import Challenge, User, db
from utils.auth_utils import check_competitor_access as _check


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
