"""nanoColab environment of a stage or competition, and the students' workspaces in it."""

from models.base import GUID, db, uuid7
from utils.dates import utcnow


class Environment(db.Model):  # type: ignore[misc, name-defined]
    __tablename__ = "environments"
    __table_args__ = (
        db.CheckConstraint(
            "(stage_id IS NULL) != (challenge_id IS NULL)", name="ck_environment_one_owner"
        ),
    )

    id = db.Column(GUID, primary_key=True, default=uuid7)
    stage_id = db.Column(
        GUID, db.ForeignKey("stages.id", ondelete="CASCADE"), nullable=True, unique=True
    )
    challenge_id = db.Column(
        GUID, db.ForeignKey("challenges.id", ondelete="CASCADE"), nullable=True, unique=True
    )
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    auto_publish = db.Column(db.Boolean, nullable=False, default=False)
    published_at = db.Column(db.DateTime, nullable=True)

    compute_kind = db.Column(db.String(8), nullable=False, default="CPU")
    cpu_cores = db.Column(db.Integer, nullable=False, default=2)
    memory_gib = db.Column(db.Integer, nullable=False, default=8)
    disk_gib = db.Column(db.Integer, nullable=False, default=10)
    gpu_type = db.Column(db.String(100), nullable=True)
    image_id = db.Column(db.String(63), nullable=False, default="")
    image_digest = db.Column(db.String(500), nullable=True)
    archive_until = db.Column(db.DateTime, nullable=True)
    max_attendance = db.Column(db.Integer, nullable=True)
    retention_days = db.Column(db.Integer, nullable=True)

    asset_version = db.Column(db.String(100), nullable=True)
    package_state = db.Column(db.String(16), nullable=False, default="NONE")
    package_progress = db.Column(db.Integer, nullable=False, default=0)
    package_fingerprint = db.Column(db.String(64), nullable=True)
    package_error_code = db.Column(db.String(64), nullable=True)
    package_error = db.Column(db.String(500), nullable=True)
    package_error_limit = db.Column(db.String(32), nullable=True)

    event_id = db.Column(db.String(64), nullable=True)
    sync_error = db.Column(db.String(500), nullable=True)
    synced_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: utcnow())
    updated_at = db.Column(
        db.DateTime, nullable=False, default=lambda: utcnow(), onupdate=lambda: utcnow()
    )

    stage = db.relationship(
        "Stage", backref=db.backref("environment", uselist=False, cascade="all, delete-orphan")
    )
    challenge = db.relationship(
        "Challenge",
        backref=db.backref("environment", uselist=False, cascade="all, delete-orphan"),
    )
    workspaces = db.relationship(
        "Workspace", backref="environment", lazy=True, cascade="all, delete-orphan"
    )

    @property
    def is_published(self) -> bool:
        return self.published_at is not None


class Workspace(db.Model):  # type: ignore[misc, name-defined]
    __tablename__ = "workspaces"
    __table_args__ = (
        db.UniqueConstraint("environment_id", "user_id", name="uq_workspace_environment_user"),
    )

    id = db.Column(GUID, primary_key=True, default=uuid7)
    environment_id = db.Column(
        GUID, db.ForeignKey("environments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = db.Column(
        GUID, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: utcnow())
    last_launched_at = db.Column(db.DateTime, nullable=True)
