from __future__ import annotations

from auth_utils import check_competitor_access as _check
from models import User, db


def ensure_registered(user_id: str, challenge_id: str) -> User | None:

    user = db.session.get(User, user_id)
    if not user or not _check(user, challenge_id):
        return None
    return user
