"""Submission status groups shared by web, worker and scheduler code."""

from __future__ import annotations

# Dependency-free on purpose: beat and eval workers import these without the app,
# The database or the PII encryption key. A terminal status never changes again;
# A running one means a worker took the submission; an active one is queued or running
TERMINAL_STATUSES: tuple[str, ...] = ("completed", "failed")
RUNNING_STATUSES: tuple[str, ...] = ("running", "building_env", "running_inference", "evaluating")
ACTIVE_STATUSES: tuple[str, ...] = ("queued", *RUNNING_STATUSES)
# Detailed status of a failure caused by the platform, not the competitor's code
# (enqueue failure, never picked up, lost worker, file sync, GPU, Docker or image
# build failure). Such submissions never count toward a quota (R16, R60, Q22)
INFRA_FAILURE = "failed_infra"
