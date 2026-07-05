from __future__ import annotations

from typing import Any

from flask import Response, jsonify

# ruff: noqa: E501

DEFAULT_ERROR_MESSAGES = {
    # auth_utils.py
    "ERR_TOKEN_INVALID": "Unauthorized access. Token is missing, expired, or invalid.",
    "ERR_CSRF_FAILED": "CSRF token missing or invalid.",
    "ERR_RATE_LIMITED": "Too many requests. Please slow down.",
    "ERR_ACCESS_DENIED": "Access denied.",
    "ERR_VALIDATION": "Request validation failed.",
    # TODO: planned feature — not yet wired
    "ERR_ROLE_REQUIRED": "Unauthorized. Requires role: {roles}",
    # auth.py
    "ERR_RATE_LIMIT_EXCEEDED": "Too many failed login attempts. Please try again later.",
    "ERR_INVALID_CREDENTIALS": "Invalid credentials.",
    # TODO: planned feature — not yet wired
    "ERR_COMPETITION_ARCHIVED": "This competition has been archived. Registered competitors are not allowed to log in.",
    "ERR_USER_NOT_FOUND": "User not found.",
    # admin.py — competitor registration
    "ERR_CHALLENGE_ID_REQUIRED": "challenge_id is required for competitor registration.",
    "ERR_MISSING_DEMOGRAPHICS": "Name, Surname, Middle Name, Birth Date, Grade, School and City are required.",
    "ERR_INVALID_CHALLENGE_ID": "Invalid challenge_id.",
    "ERR_JURY_REGISTRATION_STARTED": "Jury members cannot register competitors once the competition has started.",
    # TODO: planned feature — not yet wired
    "ERR_COMPETITOR_ALREADY_REGISTERED": "A competitor with these demographic details is already registered for this competition.",
    # admin.py — user CRUD
    "ERR_CANNOT_DELETE_SELF": "You cannot delete your own admin account.",
    "ERR_USERNAME_REQUIRED": "Username is required.",
    "ERR_USERNAME_TAKEN": "User with this username already exists.",
    "ERR_JURY_ONLY_COMPETITOR": "Jury members can only register competitor accounts.",
    "ERR_ADMIN_CLI_ONLY": "Administrator accounts can only be generated directly on the server command line (CLI).",
    "ERR_FILE_REQUIRED": "No file uploaded.",
    "ERR_FILE_INVALID": "Failed to read uploaded file.",
    "ERR_CSV_PARSE_FAILED": "Failed to parse CSV file.",
    # TODO: planned feature — not yet wired
    "ERR_CSV_MISSING_COLUMN": "CSV missing required column: {column}",
    # admin.py — backups
    "ERR_INVALID_PATH": "Invalid path",
    "ERR_NO_AUTO_BACKUP_DELETE": "Auto-backups cannot be deleted manually.",
    # admin.py — user edit
    "ERR_JURY_CANNOT_EDIT_ADMIN": "Jury members cannot edit administrator or other jury accounts.",
    "ERR_CANNOT_EDIT_STARTED": "Cannot edit user: The assigned competition has already started.",
    "ERR_CANNOT_CHANGE_ROLE_ADMIN": "Cannot change user role to Administrator.",
    "ERR_CANNOT_ASSIGN_STARTED": "Cannot assign user to a competition that has already started.",
    "ERR_CANNOT_RESET_STARTED": "Cannot reset password: The assigned competition has already started.",
    "ERR_CANNOT_RESET_BULK_STARTED": "Cannot reset passwords: The competition has already started.",
    # admin.py — ZIP download
    "ERR_SCORES_NOT_FINALIZED": "Scores must be finalized before downloading.",
    "ERR_STAGE_MISMATCH": "Stage does not belong to this challenge.",
    "ERR_STAGE_NOT_FINISHED": "Submissions cannot be downloaded until this stage has finished.",
    "ERR_COMPETITION_NOT_FINISHED": "Submissions cannot be downloaded until the competition has finished.",
    # admin.py — general
    "ERR_NOT_FOUND": "Not found.",
    # challenges.py — CRUD
    "ERR_NOT_REGISTERED": "Access denied. You are not registered for this competition.",
    "ERR_CHALLENGE_NOT_FOUND": "Challenge not found.",
    "ERR_DATETIME_REQUIRED": "Competition start time and end time are required.",
    "ERR_ALREADY_FINALIZED": "Competition is already finalized.",
    # TODO: planned feature — not yet wired
    "ERR_COMPETITION_NOT_ENDED": "Cannot finalize the competition before its end time.",
    # TODO: planned feature — not yet wired
    "ERR_NO_COMPETITORS": "Cannot finalize a competition with no competitors.",
    # challenges.py — stages
    # TODO: planned feature — not yet wired
    "ERR_NOT_FINALIZED": "Stage must be finalized before toggling reveal.",
    # TODO: planned feature — not yet wired
    "ERR_STAGE_NOT_ENDED": "Cannot finalize the stage before its end time.",
    "ERR_INVALID_DATE_FORMAT": "Invalid date format.",
    "ERR_INVALID_DATE_RANGE": "End time must be after start time.",
    "ERR_INVALID_DATE": "Invalid date.",
    # TODO: planned feature — not yet wired
    "ERR_STAGE_OUT_OF_COMPETITION_BOUNDS": "Stage time must be within the competition timeframe.",
    # TODO: planned feature — not yet wired
    "ERR_COMPETITION_STARTED": "Cannot create a test stage after the competition has started.",
    # TODO: planned feature — not yet wired
    "ERR_TEST_STAGE_AFTER_COMP_START": "Test stage must end before the competition starts.",
    # TODO: planned feature — not yet wired
    "ERR_TEST_STAGE_EXISTS": "A test stage already exists for this competition.",
    "ERR_MISSING_DATES": "start_time and end_time are required.",
    # challenges.py — import/upload
    "ERR_INVALID_UPLOAD_FORMAT": "Only ZIP files uploaded as multipart/form-data are supported.",
    "ERR_NO_DATA_PROVIDED": "No data provided.",
    # TODO: planned feature — not yet wired
    "ERR_INVALID_ARCHIVE": "Invalid or corrupt ZIP archive.",
    "ERR_INVALID_IMPORT_DATA": "Import data must be a JSON object.",
    # challenges.py — manual points (shared with leaderboard.py)
    "ERR_MISSING_MANUAL_POINTS": "Cannot finalize. A competitor is missing manual points for a task.",
    # TODO: planned feature — not yet wired
    "ERR_EDITING_BLOCKED": "Cannot modify manual points.",
    # TODO: planned feature — not yet wired
    "ERR_REASON_REQUIRED": "A justification reason is mandatory.",
    # TODO: planned feature — not yet wired
    "ERR_TASK_NOT_IN_CHALLENGE": "Task does not belong to this challenge.",
    # TODO: planned feature — not yet wired
    # TODO: planned feature — not yet wired
    "ERR_NO_SUBMISSIONS": "Only competitors with submissions can be assigned manual points.",
    # submissions.py
    "ERR_NO_FILE_UPLOADED": "No file uploaded.",
    "ERR_INVALID_FILE_TYPE": "Invalid file type.",
    "ERR_FILE_TOO_LARGE": "File size exceeds the 5MB limit.",
    "ERR_PARSING_FAILED": "Invalid notebook file.",
    "ERR_CHALLENGE_INACTIVE": "This challenge is currently inactive.",
    "ERR_CHALLENGE_ARCHIVED": "This competition has been archived and no longer accepts submissions.",
    "ERR_COMPETITION_FROZEN": "This competition is currently frozen. Submissions are temporarily blocked.",
    "ERR_COMPETITION_FINALIZED": "Submissions are disabled for finalized competitions.",
    # TODO: planned feature — not yet wired
    "ERR_STAGE_NOT_STARTED": "The stage has not started yet.",
    # TODO: planned feature — not yet wired
    "ERR_STAGE_DEADLINE_PASSED": "The deadline for the stage has passed.",
    "ERR_COMPETITION_NOT_STARTED": "This competition has not started yet.",
    "ERR_COMPETITION_ENDED": "This competition has ended and no longer accepts submissions.",
    "ERR_INVALID_TASK_ID": "Invalid task_id for this challenge.",
    "ERR_AST_RULE_FAILED": "Notebook execution rules violated.",
    "ERR_SUBMIT_LOCKED": "Another submission is being processed. Please wait.",
    # TODO: planned feature — not yet wired
    "ERR_DAILY_LIMIT_REACHED": "Daily limit reached.",
    "ERR_QUEUE_UNAVAILABLE": "Submission queue is temporarily unavailable. Please try again.",
    "ERR_SUBMISSIONS_LOCKED": "Access denied. Submissions are locked.",
    "ERR_SELECTION_WINDOW_CLOSED": "The final selection window for this stage has closed.",
    "ERR_SUBMISSION_LATE": "Cannot select a submission created after the stage deadline.",
    "ERR_NO_COMPLETED_SUBMISSIONS": "No completed submissions found for this user/task.",
    # tasks.py — create / update task
    "ERR_BASELINE_REQUIRED": "Baseline notebook is required.",
    "ERR_INVALID_METRIC_NAME": "Invalid metric name.",
    "ERR_INVALID_METRIC_CONFIG": "Invalid metrics configuration.",
    "ERR_INVALID_DOCKER_IMAGE": "Invalid Docker image format.",
    "ERR_INVALID_APT_PACKAGE": "Invalid APT package name.",
    "ERR_INVALID_PIP_REQUIREMENT": "Invalid pip requirement.",
    "ERR_INVALID_HF_DATASETS": "Invalid Hugging Face datasets configuration.",
    "ERR_INVALID_HF_MODELS": "Invalid Hugging Face models configuration.",
    "ERR_INVALID_SELECTED_CELLS": "Each selected cell must be an object with id, type, and source.",
    "ERR_POINTS_MUST_BE_INT": "Points must be integers.",
    "ERR_POINTS_OUT_OF_BOUNDS": "Points must be between 0 and 100.",
    "ERR_INVALID_STAGE_ID": "Invalid stage_id for this challenge.",
    # TODO: planned feature — not yet wired
    "ERR_STAGE_REQUIRED": "Task must be assigned to a stage when the competition has stages.",
    "ERR_TOO_MANY_FILES": "You can upload a maximum of 5 files per task.",
    # TODO: planned feature — not yet wired
    "ERR_FILE_TOO_LARGE_25MB": "File exceeds the maximum allowed size of 25MB.",
    # TODO: planned feature — not yet wired
    "ERR_INVALID_LABELS_SCHEMA": "Invalid labels.parquet schema.",
    # TODO: planned feature — not yet wired
    "ERR_LABELS_PARSE_FAILED": "Failed to parse labels.parquet.",
    # tasks.py — move
    "ERR_CANNOT_MOVE_FINALIZED": "Cannot move task -- source stage is finalized",
    "ERR_CANNOT_MOVE_ENDED": "Cannot move task -- source stage has ended",
    "ERR_CANNOT_MOVE_HAS_MANUAL_POINTS": "Cannot move task -- submissions have manual points assigned",
    # tasks.py — worker routes
    "ERR_EVALUATOR_LOAD_FAILED": "Failed to load evaluator script.",
    "ERR_UNAUTHORIZED": "Unauthorized",
    "ERR_INVALID_REQUEST_BODY": "Request must be JSON",
    "ERR_INVALID_STATUS": "Invalid status value.",
    "ERR_INVALID_PUBLIC_SCORE": "public_score must be numeric or null",
    "ERR_INVALID_PRIVATE_SCORE": "private_score must be numeric or null",
    "ERR_INVALID_FILENAME": "Invalid filename",
    # tasks.py — misc
    "ERR_FILE_NOT_FOUND": "File not found in task metadata.",
    "ERR_NOT_AVAILABLE": "Access denied or task not available yet.",
    "ERR_FORBIDDEN": "Only administrators are allowed to configure custom environments.",
    "ERR_TASK_NOT_FOUND": "Task not found.",
    # TODO: planned feature — not yet wired
    "ERR_TASK_LIMIT_REACHED": "Task limit reached.",
    # app.py
    "ERR_INTERNAL": "Internal server error.",
    "ERR_INTERNAL_SERVER_ERROR": "An internal server error occurred. Please try again later.",
}


def err(
    code: str, status: int = 400, message: str | None = None, **extra: Any
) -> tuple[Response, int]:
    if message is None:
        message = DEFAULT_ERROR_MESSAGES.get(code, "An error occurred.")
    response: dict[str, Any] = {"error": message, "code": code}
    response.update(extra)
    return jsonify(response), status
