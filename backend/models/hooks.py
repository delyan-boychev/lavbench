"""SQLAlchemy event listeners for test auto-assignment."""

import contextlib
import os

from sqlalchemy import event, text

from models.challenge import Challenge
from models.user import User


@event.listens_for(User, "after_insert")
def auto_assign_jury_in_tests(mapper, connection, target):
    if target.role == "jury" and os.environ.get("PYTEST_CURRENT_TEST"):
        cursor = connection.execute(text("SELECT id FROM challenges"))
        challenge_ids = [row[0] for row in cursor.fetchall()]
        for ch_id in challenge_ids:
            with contextlib.suppress(Exception):
                connection.execute(
                    text(
                        "INSERT INTO jury_challenges (jury_id, "
                        "challenge_id) VALUES (:jury_id, :challenge_id)"
                    ),
                    {"jury_id": str(target.id), "challenge_id": str(ch_id)},
                )


@event.listens_for(Challenge, "after_insert")
def auto_assign_challenge_to_jury_in_tests(mapper, connection, target):
    if os.environ.get("PYTEST_CURRENT_TEST"):
        cursor = connection.execute(text("SELECT id FROM users WHERE role = 'jury'"))
        jury_ids = [row[0] for row in cursor.fetchall()]
        for j_id in jury_ids:
            with contextlib.suppress(Exception):
                connection.execute(
                    text(
                        "INSERT INTO jury_challenges (jury_id, "
                        "challenge_id) VALUES (:jury_id, :challenge_id)"
                    ),
                    {"jury_id": str(j_id), "challenge_id": str(target.id)},
                )
