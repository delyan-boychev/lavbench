"""Placeholder hand-off to the CSV scoring mode until the real one is merged."""

from __future__ import annotations

from typing import Any

from models import Submission, Task, WorkspaceExport, db

PENDING_STATUS = "received"


def accept_workspace_csv(
    *, user_id: Any, task: Task, csv_bytes: bytes, export: WorkspaceExport
) -> Submission:
    submission = Submission(
        user_id=user_id,
        challenge_id=task.challenge_id,
        task_id=task.id,
        status=PENDING_STATUS,
        detailed_status="awaiting_csv_scoring",
        logs=f"Received {len(csv_bytes)} bytes from the workspace (sha256 {export.csv_sha256}). "
        "CSV scoring is not available yet.",
    )
    db.session.add(submission)
    db.session.flush()
    return submission
