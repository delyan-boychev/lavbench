"""Models package — re-exports everything from the models/ package for backward compatibility."""

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
    metric_direction_from_config,
    to_base36,
)
from models.stage import Stage
from models.submission import Submission, _delete_submission_files
from models.task import Task
from models.user import JuryChallenge, User

# Re-exported so route modules can import them with the models
from utils.submission_status import ACTIVE_STATUSES, RUNNING_STATUSES, TERMINAL_STATUSES

__all__ = [
    "ACTIVE_STATUSES",
    "ADJECTIVES",
    "GUID",
    "METRIC_LOWER_IS_BETTER",
    "NOUNS",
    "RUNNING_STATUSES",
    "TERMINAL_STATUSES",
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
    "metric_direction_from_config",
    "to_base36",
    "uuid7",
]
