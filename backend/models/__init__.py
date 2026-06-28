"""Models package — re-exports everything from backend/models.py for backward compatibility."""

from models.audit_log import AuditLog
from models.base import GUID, db, decrypt_field, encrypt_field, logger, uuid7
from models.challenge import Challenge
from models.hooks import auto_assign_challenge_to_jury_in_tests, auto_assign_jury_in_tests
from models.naming import (
    ADJECTIVES,
    METRIC_LOWER_IS_BETTER,
    NOUNS,
    generate_pseudonym,
    is_metric_lower_better,
    to_base36,
)
from models.stage import Stage
from models.submission import Submission, _delete_submission_files
from models.task import Task
from models.user import JuryChallenge, User

__all__ = [
    "ADJECTIVES",
    "GUID",
    "METRIC_LOWER_IS_BETTER",
    "NOUNS",
    "AuditLog",
    "Challenge",
    "JuryChallenge",
    "Stage",
    "Submission",
    "Task",
    "User",
    "_delete_submission_files",
    "auto_assign_challenge_to_jury_in_tests",
    "auto_assign_jury_in_tests",
    "db",
    "decrypt_field",
    "encrypt_field",
    "generate_pseudonym",
    "is_metric_lower_better",
    "logger",
    "to_base36",
    "uuid7",
]
