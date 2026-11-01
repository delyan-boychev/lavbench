"""Stage compute binding, per-user workspaces and exported workspace evidence."""

from typing import Any

from models.base import GUID, db, uuid7
from utils.dates import to_tz_iso, utcnow


class StageCompute(db.Model):  # type: ignore[misc, name-defined]
    __tablename__ = "stage_compute"

    stage_id = db.Column(GUID, db.ForeignKey("stages.id", ondelete="CASCADE"), primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    published = db.Column(db.Boolean, nullable=False, default=False)
    compute_kind = db.Column(db.String(8), nullable=False, default="CPU")
    cpu_cores = db.Column(db.Integer, nullable=False, default=2)
    memory_gib = db.Column(db.Integer, nullable=False, default=8)
    disk_gib = db.Column(db.Integer, nullable=False, default=10)
    gpu_type = db.Column(db.String(100), nullable=True)
    image_id = db.Column(db.String(63), nullable=False, default="")
    image_digest = db.Column(db.String(500), nullable=False, default="")
    asset_version = db.Column(db.String(100), nullable=False, default="")
    package_state = db.Column(db.String(16), nullable=False, default="NONE")
    package_error = db.Column(db.String(255), nullable=True)
    package_fingerprint = db.Column(db.String(64), nullable=True)
    max_attendance = db.Column(db.Integer, nullable=False, default=1)
    retention_days = db.Column(db.Integer, nullable=False, default=30)
    nanocolab_event_id = db.Column(db.String(64), nullable=True)
    sync_state = db.Column(db.String(16), nullable=False, default="PENDING")
    last_synced_at = db.Column(db.DateTime, nullable=True)
    last_sync_error = db.Column(db.String(64), nullable=True)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=lambda: utcnow(), onupdate=lambda: utcnow()
    )

    stage = db.relationship(
        "Stage", backref=db.backref("compute", uselist=False, cascade="all, delete-orphan")
    )

    def to_dict(self, timezone: str = "UTC") -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "enabled": self.enabled,
            "published": self.published,
            "compute_kind": self.compute_kind,
            "cpu_cores": self.cpu_cores,
            "memory_gib": self.memory_gib,
            "disk_gib": self.disk_gib,
            "gpu_type": self.gpu_type,
            "image_id": self.image_id,
            "image_digest": self.image_digest,
            "asset_version": self.asset_version,
            "package_state": self.package_state,
            "package_error": self.package_error,
            "max_attendance": self.max_attendance,
            "retention_days": self.retention_days,
            "nanocolab_event_id": self.nanocolab_event_id,
            "sync_state": self.sync_state,
            "last_synced_at": to_tz_iso(self.last_synced_at, timezone)
            if self.last_synced_at
            else None,
            "last_sync_error": self.last_sync_error,
        }


class StageWorkspace(db.Model):  # type: ignore[misc, name-defined]
    __tablename__ = "stage_workspaces"
    __table_args__ = (db.UniqueConstraint("stage_id", "user_id", name="uq_stage_workspace_user"),)

    id = db.Column(GUID, primary_key=True, default=uuid7)
    stage_id = db.Column(
        GUID, db.ForeignKey("stages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = db.Column(
        GUID, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: utcnow())


class WorkspaceExport(db.Model):  # type: ignore[misc, name-defined]
    __tablename__ = "workspace_exports"

    id = db.Column(GUID, primary_key=True, default=uuid7)
    user_id = db.Column(
        GUID, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id = db.Column(
        GUID, db.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage_id = db.Column(GUID, db.ForeignKey("stages.id", ondelete="CASCADE"), nullable=False)
    submission_id = db.Column(
        GUID, db.ForeignKey("submissions.id", ondelete="SET NULL"), nullable=True
    )
    workspace_id = db.Column(db.String(64), nullable=False)
    source = db.Column(db.String(16), nullable=False)
    exported_at = db.Column(db.DateTime, nullable=False)
    csv_path = db.Column(db.String(512), nullable=False)
    csv_sha256 = db.Column(db.String(64), nullable=False)
    csv_size = db.Column(db.Integer, nullable=False)
    notebook_path = db.Column(db.String(512), nullable=True)
    notebook_sha256 = db.Column(db.String(64), nullable=True)
    notebook_size = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: utcnow())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "submission_id": self.submission_id,
            "source": self.source,
            "exported_at": to_tz_iso(self.exported_at, "UTC"),
            "csv_sha256": self.csv_sha256,
            "csv_size": self.csv_size,
            "notebook_sha256": self.notebook_sha256,
            "notebook_size": self.notebook_size,
        }
