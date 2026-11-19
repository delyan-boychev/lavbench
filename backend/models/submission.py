"""Submission model and after-delete file cleanup."""

import contextlib
import json
import logging
import os
import shutil
import uuid
from typing import Any

from models.base import GUID, db, uuid7
from utils.dates import utcnow
from utils.score_visibility import can_view_private_scores

logger = logging.getLogger(__name__)

SUBMISSION_FILES_DIR = "submission_files"
# How a submission arrived; every caller of create_submission states one
ORIGIN_CELLS = "cells"
ORIGIN_WORKSPACE = "workspace"
ORIGIN_EMERGENCY_UPLOAD = "emergency_upload"
ORIGIN_BASELINE = "baseline"
ORIGINS = frozenset({ORIGIN_CELLS, ORIGIN_WORKSPACE, ORIGIN_EMERGENCY_UPLOAD, ORIGIN_BASELINE})


def submission_files_dir(submission_id: Any) -> str:
    """Folder holding a submission's own Parquet and notebook."""
    from utils.files import upload_root

    return os.path.join(upload_root(), SUBMISSION_FILES_DIR, str(submission_id))


def remove_submission_files(submission_id: Any) -> None:
    shutil.rmtree(submission_files_dir(submission_id), ignore_errors=True)


class Submission(db.Model):  # type: ignore[misc, name-defined]
    __tablename__ = "submissions"

    __table_args__ = (
        db.Index("idx_sub_user_task", "user_id", "task_id", "challenge_id"),
        db.Index("idx_sub_task_id", "task_id"),
        db.Index("idx_sub_user_challenge_created", "user_id", "challenge_id", "created_at"),
        db.Index("idx_sub_challenge_status_baseline", "challenge_id", "status", "is_baseline"),
        db.Index("idx_sub_challenge_created", "challenge_id", db.text("created_at DESC")),
        db.Index("idx_sub_task_created", "task_id", db.text("created_at DESC")),
        db.Index(
            "idx_sub_task_user_created",
            "task_id",
            "user_id",
            db.text("created_at DESC"),
        ),
    )

    id = db.Column(GUID, primary_key=True, default=uuid7)
    user_id = db.Column(GUID, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    challenge_id = db.Column(
        GUID, db.ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False
    )
    task_id = db.Column(GUID, db.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True)

    status = db.Column(db.String(50), default="queued", index=True)
    is_baseline = db.Column(db.Boolean, default=False)
    # How many failed_infra baseline runs this run retries (MAX_BASELINE_INFRA_RETRIES caps it)
    infra_retry_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    detailed_status = db.Column(db.String(100), default="queued")
    # One of ORIGINS; NULL only on rows created before origins were recorded
    origin = db.Column(db.String(16), nullable=True)
    # File mode: the scored Parquet and the notebook that produced it
    artifact_path = db.Column(db.String(512), nullable=True)
    artifact_sha256 = db.Column(db.String(64), nullable=True)
    artifact_size = db.Column(db.BigInteger, nullable=True)
    notebook_path = db.Column(db.String(512), nullable=True)
    notebook_sha256 = db.Column(db.String(64), nullable=True)
    # The workspace export: source (LIVE or ARCHIVE), sizes and exported_at
    workspace_meta = db.Column(db.JSON, nullable=True)
    time_limit_snapshot = db.Column(db.Integer, nullable=True)
    # The task's Hugging Face ZIP at dispatch; a run fetches this one even after a replace
    hf_zip_sha256 = db.Column(db.String(64), nullable=True)

    code_storage_path = db.Column(db.String(512), nullable=True)
    log_storage_path = db.Column(db.String(512), nullable=True)

    public_score = db.Column(db.Float, nullable=True)
    private_score = db.Column(db.Float, nullable=True)
    gpu_node = db.Column(db.String(255), nullable=True)
    execution_time_ms = db.Column(db.Integer, nullable=True)
    # The scoring step only (metrics or custom evaluator); shown to staff, never ranked
    evaluation_time_ms = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: utcnow(), index=True)
    executed_at = db.Column(db.DateTime, nullable=True)
    # When the run reached a terminal status, set only by services.submission_status
    finished_at = db.Column(db.DateTime, nullable=True)

    metrics_payload_public = db.Column(db.JSON, nullable=True)
    metrics_payload_private = db.Column(db.JSON, nullable=True)
    final_weighted_score_public = db.Column(db.Float, nullable=True)
    final_weighted_score_private = db.Column(db.Float, nullable=True)

    is_final_selection = db.Column(db.Boolean, default=False)
    celery_task_id = db.Column(db.String(255), nullable=True)

    @property
    def code_cells(self) -> str:
        cached = getattr(self, "_cached_code_cells", None)
        if isinstance(cached, str):
            return cached
        if self.code_storage_path and os.path.exists(self.code_storage_path):
            try:
                size = os.path.getsize(self.code_storage_path)
                from config import Config

                if size > Config.MAX_CODE_CELLS_CHARS:
                    logger.warning(
                        "Reading large code_cells file for submission %s: %d bytes (limit: %d)",
                        self.id,
                        size,
                        Config.MAX_CODE_CELLS_CHARS,
                    )
                with open(self.code_storage_path, encoding="utf-8") as f:
                    self._cached_code_cells = f.read()
                    return self._cached_code_cells
            except Exception as e:
                logger.warning("Failed to read code_cells file for submission %s: %s", self.id, e)
        return "[]"

    @code_cells.setter
    def code_cells(self, value: str) -> None:
        from config import Config

        encoded_size = len(value.encode("utf-8"))
        if encoded_size > Config.MAX_CODE_CELLS_CHARS:
            msg = (
                f"Submission code is {encoded_size} bytes; maximum is {Config.MAX_CODE_CELLS_CHARS}"
            )
            raise ValueError(msg)
        self._cached_code_cells = value
        try:
            from flask import current_app

            if current_app:
                upload_folder = current_app.config.get("UPLOAD_FOLDER")
            else:
                upload_folder = Config.UPLOAD_FOLDER

            submissions_dir = os.path.join(upload_folder, "submissions")  # type: ignore[arg-type]
            os.makedirs(submissions_dir, exist_ok=True)
            if not self.code_storage_path:
                filename = f"submission_{uuid.uuid4().hex}.json"
                self.code_storage_path = os.path.join(submissions_dir, filename)
            with open(self.code_storage_path, "w", encoding="utf-8") as f:
                f.write(value)
        except Exception:
            logger.exception("Error saving code_cells to file")

    @property
    def logs(self) -> str:
        if self.log_storage_path and os.path.exists(self.log_storage_path):
            try:
                size = os.path.getsize(self.log_storage_path)
                from config import Config

                if size > Config.MAX_LOG_CHARS:
                    logger.warning(
                        "Log file %s is %d bytes, reading last %d bytes",
                        self.log_storage_path,
                        size,
                        Config.MAX_LOG_CHARS,
                    )
                    with open(self.log_storage_path, "rb") as f:
                        f.seek(-Config.MAX_LOG_CHARS, os.SEEK_END)
                        val = f.read().decode("utf-8", errors="replace")
                        return val + f"\n--- LOG TRUNCATED at {Config.MAX_LOG_CHARS} bytes ---"
                with open(self.log_storage_path, encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                logger.warning("Failed to read logs file for submission %s: %s", self.id, e)
        return ""

    @logs.setter
    def logs(self, value: str) -> None:
        try:
            from config import Config

            if value and len(value) > Config.MAX_LOG_CHARS:
                value = value[: Config.MAX_LOG_CHARS]
                logger.warning(
                    "Truncated logs for submission %s to %d chars",
                    self.id,
                    Config.MAX_LOG_CHARS,
                )

            from flask import current_app

            if current_app:
                upload_folder = current_app.config.get("UPLOAD_FOLDER")
            else:
                upload_folder = Config.UPLOAD_FOLDER

            logs_dir = os.path.join(upload_folder, "logs")  # type: ignore[arg-type]
            os.makedirs(logs_dir, exist_ok=True)
            if not self.log_storage_path:
                filename = f"log_{uuid.uuid4().hex}.txt"
                self.log_storage_path = os.path.join(logs_dir, filename)
            with open(self.log_storage_path, "w", encoding="utf-8") as f:
                f.write(value or "")
        except Exception:
            logger.exception("Error saving logs to file")

    def to_dict(
        self,
        view_role: str = "competitor",
        current_user_id: Any = None,
        include_large_fields: bool = True,
    ) -> dict[str, Any]:
        finalized = self.challenge.scores_finalized if self.challenge else False
        double_blind = self.challenge.double_blind if self.challenge else True

        show_owner = (
            (not double_blind)
            or (view_role == "admin")
            or finalized
            or (current_user_id == self.user_id)
        )
        owner_info = (
            self.user.to_dict(
                view_role=view_role,
                scores_finalized=finalized,
                current_user_id=current_user_id,
            )
            if self.user
            else None
        )

        if not show_owner and owner_info:
            owner_info = {
                "id": owner_info.get("id"),
                "alias_id": owner_info.get("alias_id"),
                "role": owner_info.get("role"),
            }

        staff = view_role in ("admin", "jury")
        stage = self.task.stage if self.task is not None and self.task.stage_id else None
        show_private_score = can_view_private_scores(view_role, self.challenge, stage)

        try:
            m_public = (
                json.loads(self.metrics_payload_public)
                if isinstance(self.metrics_payload_public, str)
                else self.metrics_payload_public
            )
        except Exception as e:
            logger.warning(
                ("Failed to parse metrics_payload_public for submission %s: %s"), self.id, e
            )
            m_public = {}

        try:
            m_private = (
                json.loads(self.metrics_payload_private)
                if isinstance(self.metrics_payload_private, str)
                else self.metrics_payload_private
            )
        except Exception as e:
            logger.warning(
                "Failed to parse metrics_payload_private for submission %s: %s", self.id, e
            )
            m_private = {}

        return {
            "id": self.id,
            "challenge_id": self.challenge_id,
            "task_id": self.task_id,
            "task_title": self.task.title if self.task else None,
            "status": self.status,
            "detailed_status": self.detailed_status,
            "origin": self.origin,
            "artifact_size": self.artifact_size,
            "has_notebook": bool(self.notebook_path),
            "artifact_sha256": self.artifact_sha256 if staff else None,
            "notebook_sha256": self.notebook_sha256 if staff else None,
            "workspace_meta": self.workspace_meta if staff else None,
            "evaluation_time_ms": self.evaluation_time_ms if staff else None,
            "code_cells": self.code_cells if include_large_fields else "[]",
            "public_score": self.public_score,
            "private_score": self.private_score if show_private_score else None,
            "logs": self.logs if include_large_fields else None,
            "gpu_node": self.gpu_node,
            "execution_time_ms": self.execution_time_ms,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "executed_at": self.executed_at.isoformat() + "Z" if self.executed_at else None,
            "user": owner_info,
            "metrics_payload_public": m_public,
            "metrics_payload_private": m_private if show_private_score else None,
            "final_weighted_score_public": self.final_weighted_score_public,
            "final_weighted_score_private": (
                self.final_weighted_score_private if show_private_score else None
            ),
            "is_final_selection": self.is_final_selection,
            "is_baseline": self.is_baseline,
            "celery_task_id": self.celery_task_id,
        }

    def to_dict_light(
        self, view_role: str = "competitor", current_user_id: Any = None
    ) -> dict[str, Any]:
        res = self.to_dict(
            view_role=view_role,
            current_user_id=current_user_id,
            include_large_fields=False,
        )
        res.pop("code_cells", None)
        res.pop("logs", None)
        return res


@db.event.listens_for(Submission, "after_delete")  # type: ignore[untyped-decorator]
def _delete_submission_files(mapper: Any, connection: Any, target: Submission) -> None:
    if target.code_storage_path and os.path.exists(target.code_storage_path):
        with contextlib.suppress(OSError):
            os.remove(target.code_storage_path)
    if target.log_storage_path and os.path.exists(target.log_storage_path):
        with contextlib.suppress(OSError):
            os.remove(target.log_storage_path)
    remove_submission_files(target.id)
